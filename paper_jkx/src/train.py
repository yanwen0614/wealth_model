"""训练入口:交叉熵二分类,Adam(lr=1e-5)+batch128+早停2轮,70/30随机切分."""
import argparse
import os
import random
import time

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, random_split

from .dataset import LazyImageDataset, build_index
from .models import ImageCNN


class CachedImageDataset(Dataset):
    """uint8 memmap 只读数据集:无渲染开销,GPU 常满.

    Windows spawn 下每个进程第一次 __getitem__ 时才打开自己的文件映射,
    避免跨进程共享存储导致的 shared event 报错.
    """

    def __init__(self, cache_dir):
        import numpy as np

        meta = np.load(os.path.join(cache_dir, "meta.npz"), allow_pickle=False)
        self.y = torch.from_numpy(meta["y"].astype(np.int64))
        h = int(meta["n_days"])
        from .imaging import SHAPES
        H, W, C = SHAPES[h]
        self.channels = C
        self.shape = (len(self.y), H, W) if C == 1 else (len(self.y), H, W, C)
        self.cache_dir = cache_dir
        self._mm_by_pid = {}

    def __getstate__(self):
        st = self.__dict__.copy()
        st["_mm_by_pid"] = {}  # 映射句柄不跨进程传递,worker 内 lazy 重开
        return st

    def __len__(self):
        return len(self.y)

    def _mm(self):
        import os as _os

        import numpy as np

        pid = _os.getpid()
        mm = self._mm_by_pid.get(pid)
        if mm is None:
            mm = np.memmap(_os.path.join(self.cache_dir, "images.mm"), dtype=np.uint8,
                           mode="r", shape=self.shape)
            self._mm_by_pid[pid] = mm
        return mm

    def __getitem__(self, i):
        import numpy as np

        arr = np.asarray(self._mm()[i])
        if self.channels == 3:  # [H,W,C] -> [C,H,W]
            x = torch.from_numpy(np.ascontiguousarray(arr.transpose(2, 0, 1)))
            return x.float() / 255.0, self.y[i]
        x = torch.from_numpy(arr.astype(np.float32) / 255.0)
        return x.unsqueeze(0), self.y[i]


class ShardedImageDataset(Dataset):
    """分片缓存直读: 每片一个小文件, 片内顺序读友好; 片内样本已在构建时随机置换."""

    def __init__(self, cache_dir):
        import numpy as np

        meta = np.load(os.path.join(cache_dir, "meta.npz"), allow_pickle=False)
        self.y = torch.from_numpy(meta["y"].astype(np.int64))
        h = int(meta["n_days"])
        from .imaging import SHAPES
        H, W, C = SHAPES[h]
        self.channels, self.hw = C, (H, W)
        self.sizes = meta["shard_sizes"].astype(np.int64)
        self.offsets = np.concatenate([[0], np.cumsum(self.sizes)]).astype(np.int64)
        self.shard_dir = os.path.join(cache_dir, "shards")
        # 供验证集算 RankIC(排序任务唯一可信的选型指标)
        self.rets = np.asarray(meta["rets"], dtype=np.float64)
        self.dates = np.asarray(meta["dates"])
        self._mm_by_pid = {}

    def __getstate__(self):
        st = self.__dict__.copy()
        st["_mm_by_pid"] = {}  # 映射句柄不跨进程传递
        return st

    def __len__(self):
        return len(self.y)

    def _shard(self, k):
        mm = self._mm_by_pid.get(os.getpid(), {}).get(k)
        if mm is None:
            import numpy as np
            H, W = self.hw
            nk = int(self.sizes[k])
            sk = (nk, H, W) if self.channels == 1 else (nk, H, W, self.channels)
            mm = np.memmap(os.path.join(self.shard_dir, f"part_{k:05d}.bin"),
                           dtype=np.uint8, mode="r", shape=sk)
            self._mm_by_pid.setdefault(os.getpid(), {})[k] = mm
        return mm

    def __getitem__(self, i):
        import numpy as np

        k = int(np.searchsorted(self.offsets, i, side="right") - 1)
        j = int(i) - int(self.offsets[k])
        arr = np.asarray(self._shard(k)[j])
        # 返回 uint8, 归一化在 GPU 上做(half pipeline 下 CPU worker 是瓶颈)
        if self.channels == 3:
            x = torch.from_numpy(np.ascontiguousarray(arr.transpose(2, 0, 1)))
            return x, self.y[i]
        return torch.from_numpy(np.ascontiguousarray(arr)).unsqueeze(0), self.y[i]


class ShardBlockBatchSampler:
    """块随机/片内顺序 batch 采样: 片序按 epoch 打乱, 片内按顺序切 batch.

    片内样本已随机置换, 故片内顺序读取等价于随机采样, 避免 HDD 随机寻道.
    """

    def __init__(self, sizes, mask, batch_size, shuffle=True, seed=0):
        self.sizes = sizes
        self.mask = mask
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0

    def __len__(self):
        # 精确: 每片内被掩码样本各切 floor(n_k/bs) 个批(片内余数丢弃)
        import numpy as np

        off = np.concatenate([[0], np.cumsum(self.sizes)]).astype(np.int64)
        tot = 0
        for k in range(len(self.sizes)):
            lo, hi = int(off[k]), int(off[k + 1])
            tot += int(self.mask[lo:hi].sum()) // self.batch_size
        return tot

    def __iter__(self):
        import numpy as np

        off = np.concatenate([[0], np.cumsum(self.sizes)]).astype(np.int64)
        order = np.arange(len(self.sizes))
        if self.shuffle:
            np.random.RandomState(self.seed + self.epoch).shuffle(order)
        self.epoch += 1
        bs = self.batch_size
        for k in order:
            lo, hi = int(off[k]), int(off[k + 1])
            idxs = np.nonzero(self.mask[lo:hi])[0] + lo
            for p in range(0, len(idxs) - bs + 1, bs):
                yield idxs[p:p + bs].tolist()


class IndexedDataset(Dataset):
    """包一层, __getitem__ 额外返回全局下标(验证集据此对齐日期/收益算 RankIC)."""

    def __init__(self, ds):
        self.ds = ds

    def __len__(self):
        return len(self.ds)

    def __getitem__(self, i):
        x, y = self.ds[i]
        return x, y, i


def xs_rank_ic(pred, idx, dates, rets, min_n=100):
    """逐日截面 Spearman 的均值(RankIC). pred 与 idx 同序, 用 idx 取 dates/rets."""
    import numpy as np

    d = dates[idx]
    order = np.argsort(d, kind="stable")
    sd = d[order]
    _, start = np.unique(sd, return_index=True)
    ics = []
    for ix in np.split(order, start[1:]):
        if len(ix) < min_n:
            continue
        p, r = pred[ix], rets[idx][ix]
        if p.std() == 0 or r.std() == 0:
            continue
        pr = np.argsort(np.argsort(p)).astype(float)
        rr = np.argsort(np.argsort(r)).astype(float)
        pr -= pr.mean()
        rr -= rr.mean()
        ics.append(float((pr * rr).mean() / (pr.std() * rr.std() + 1e-12)))
    return float(np.mean(ics)) if ics else float("nan")


class ImgDS(Dataset):
    def __init__(self, samples):
        self.s = samples

    def __len__(self):
        return len(self.s)

    def __getitem__(self, i):
        s = self.s[i]
        return torch.from_numpy(s[0]).unsqueeze(0), torch.tensor(s[1], dtype=torch.long)


def train_one(n_days, horizon, parquet, train_end, max_codes, epochs, bs, lr, out,
              stride=5, num_workers=4, img_cache=None, amp=False, val_cache=None):
    vfull = None  # 仅分片路径设置; 供验证集 RankIC 取日期/收益
    if img_cache and os.path.isdir(os.path.join(img_cache, "shards")):
        # 分片直读: 块随机/片内顺序. val_cache 给出时训练=全量、验证=独立区间(如2025),
        # 消除同区间随机切分的时间泄漏; 未给出则退回 70/30 随机切分(仅小样本调试).
        full = ShardedImageDataset(img_cache)
        vfull = ShardedImageDataset(val_cache) if val_cache else full
        n_tr = len(full)
        if val_cache:
            tmask = np.ones(n_tr, dtype=bool)
            vmask = np.ones(len(vfull), dtype=bool)
            tag = "训练全量 / 验证独立区间"
        else:
            g = torch.Generator().manual_seed(0)
            perm = torch.randperm(n_tr, generator=g).numpy()
            tmask = np.zeros(n_tr, dtype=bool)
            tmask[perm[:int(0.7 * n_tr)]] = True
            vmask = ~tmask
            tag = "随机70/30"
        tr_bs = ShardBlockBatchSampler(full.sizes, tmask, bs, shuffle=True, seed=0)
        va_bs = ShardBlockBatchSampler(vfull.sizes, vmask, bs, shuffle=False, seed=0)
        print(f"分片直读 {n_tr} ({tag}: 训练 {int(tmask.sum())} / "
              f"验证 {int(vmask.sum())})", flush=True)
        tr_loader = DataLoader(full, batch_sampler=tr_bs,
                               num_workers=num_workers, pin_memory=True)
        va_loader = DataLoader(IndexedDataset(vfull), batch_sampler=va_bs,
                               num_workers=num_workers, pin_memory=True)
        n_train_samples, n_val_samples = len(tr_bs) * bs, len(va_bs) * bs
    elif img_cache:  # 单文件缓存直读,跳过 parquet 与渲染
        full = CachedImageDataset(img_cache)
        print(f"缓存直读 {len(full)}", flush=True)
        n_tr = len(full)
        g = torch.Generator().manual_seed(0)
        tr_ds, va_ds = random_split(full, [int(0.7 * n_tr), n_tr - int(0.7 * n_tr)], g)
        tr_loader = DataLoader(tr_ds, shuffle=True, batch_size=bs,
                               num_workers=num_workers, pin_memory=True)
        va_loader = DataLoader(va_ds, batch_size=bs,
                               num_workers=num_workers, pin_memory=True)
        n_train_samples, n_val_samples = len(tr_ds), len(va_ds)
    else:
        df = pd.read_parquet(parquet, columns=["code", "kline_time", "open", "high",
                                                "low", "close", "volume", "is_trading",
                                                "ma_5", "ma_20", "ma_60",
                                                "volume_ratio_5d", "macd"])
        # 全量走延迟渲染索引(不预渲染,内存百 MB 级);小样本保持同一切分语义
        tr = build_index(df, n_days, horizon, max_codes, end_date=train_end,
                         seed=0, stride=stride)
        print(f"训练索引 {len(tr['idx'])} codes={len(tr['codes'])} "
              f"正样本率={tr['y'].mean():.3f}", flush=True)
        n_tr = len(tr["idx"])
        g = torch.Generator().manual_seed(0)
        tr_ds, va_ds = random_split(LazyImageDataset(tr),
                                    [int(0.7 * n_tr), n_tr - int(0.7 * n_tr)], g)
        tr_loader = DataLoader(tr_ds, shuffle=True, batch_size=bs,
                               num_workers=num_workers, pin_memory=False)
        va_loader = DataLoader(va_ds, batch_size=bs,
                               num_workers=num_workers, pin_memory=False)
        n_train_samples, n_val_samples = len(tr_ds), len(va_ds)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    pin = dev == "cuda"
    model = ImageCNN(n_days).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    use_amp = amp and dev == "cuda"
    scaler = torch.amp.GradScaler("cuda") if use_amp else None
    best_loss, best_ic, bad, best_state = 1e9, -2.0, 0, None
    for ep in range(epochs):
        ep_t0 = time.time()
        model.train()
        tot = 0.0
        for xb, yb in tr_loader:
            xb, yb = xb.to(dev, non_blocking=pin), yb.to(dev, non_blocking=pin)
            if xb.dtype == torch.uint8:  # CPU 只搬 uint8, 归一化在 GPU
                xb = xb.float().div_(255.0)
            opt.zero_grad()
            with torch.amp.autocast("cuda", enabled=use_amp):
                loss = loss_fn(model(xb), yb)
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.step(opt)
                scaler.update()
            else:
                loss.backward()
                opt.step()
            tot += loss.item() * len(xb)
        model.eval()
        vl = 0.0
        vpred, vidx = [], []
        with torch.no_grad():
            for batch in va_loader:
                xb, yb = batch[0], batch[1]
                xb = xb.to(dev, non_blocking=pin)
                if xb.dtype == torch.uint8:
                    xb = xb.float().div_(255.0)
                with torch.amp.autocast("cuda", enabled=use_amp):
                    logits = model(xb)
                    vl += loss_fn(logits, yb.to(dev)).item() * len(xb)
                if len(batch) == 3:  # IndexedDataset: 记录概率与下标算 RankIC
                    vpred.append(torch.softmax(logits.float(), 1)[:, 1].cpu())
                    vidx.append(batch[2])
        vl /= max(1, n_val_samples)
        ric = float("nan")
        if getattr(vfull, "dates", None) is not None and vpred:
            ric = xs_rank_ic(torch.cat(vpred).numpy(),
                             torch.cat(vidx).numpy().astype(np.int64),
                             vfull.dates, vfull.rets)
        if np.isfinite(ric):  # 排序任务: 用 RankIC 选型/早停, CE 仅诊断
            improved = ric > best_ic
            metric = f"val_loss={vl:.4f} xs_rank_ic={ric:.4f}"
        else:
            improved = vl < best_loss
            metric = f"val_loss={vl:.4f}"
        print(f"[{time.strftime('%H:%M:%S')}] ep{ep} "
              f"train_loss={tot / max(1, n_train_samples):.4f} {metric} "
              f"({time.time() - ep_t0:.0f}s)", flush=True)
        if improved:
            bad = 0
            if np.isfinite(ric):
                best_ic = ric
            else:
                best_loss = vl
            best_state = {k: v.cpu() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                break
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"cnn_I{n_days}R{horizon}.pth")
    torch.save(best_state or model.state_dict(), path)
    if best_ic > -2.0:
        print(f"保存 {path} 最优RankIC={best_ic:.4f}", flush=True)
    else:
        print(f"保存 {path} 最优val={best_loss:.4f}", flush=True)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_days", type=int, default=5)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--parquet", type=str, required=True)
    ap.add_argument("--train_end", type=str, default="2018-12-31")
    ap.add_argument("--max_codes", type=int, default=200)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--bs", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--stride", type=int, default=5, help="采样步长,5=周频对齐调仓")
    ap.add_argument("--num_workers", type=int, default=4)
    ap.add_argument("--img_cache", type=str, default=None, help="预生成图片缓存目录,给出则跳过渲染")
    ap.add_argument("--val_cache", type=str, default=None,
                    help="独立验证缓存(如2025),给出则训练用img_cache全量、早停用该区间")
    ap.add_argument("--amp", action="store_true", help="混合精度(大模型提速+省显存)")
    ap.add_argument("--out", type=str, default="paper_jkx/logs")
    a = ap.parse_args()
    if a.max_codes is not None and a.max_codes <= 0:
        a.max_codes = None  # 0=全量5166股
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    train_one(a.n_days, a.horizon, a.parquet, a.train_end,
              a.max_codes, a.epochs, a.bs, a.lr, a.out,
              stride=a.stride, num_workers=a.num_workers, img_cache=a.img_cache,
              amp=a.amp, val_cache=a.val_cache)


if __name__ == "__main__":
    main()
