"""训练入口:交叉熵二分类,Adam(lr=1e-5)+batch128+早停2轮,70/30随机切分."""
import argparse
import os
import random

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
        from .imaging import HEIGHTS
        self.shape = (len(self.y), HEIGHTS[h], 3 * h)
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

        x = torch.from_numpy(np.asarray(self._mm()[i], dtype=np.float32) / 255.0)
        return x.unsqueeze(0), self.y[i]


class ImgDS(Dataset):
    def __init__(self, samples):
        self.s = samples

    def __len__(self):
        return len(self.s)

    def __getitem__(self, i):
        s = self.s[i]
        return torch.from_numpy(s[0]).unsqueeze(0), torch.tensor(s[1], dtype=torch.long)


def train_one(n_days, horizon, parquet, train_end, max_codes, epochs, bs, lr, out,
              stride=5, num_workers=4, img_cache=None, amp=False):
    if img_cache:  # 预生成缓存直读,跳过 parquet 与渲染
        full = CachedImageDataset(img_cache)
        print(f"缓存直读 {len(full)}", flush=True)
        n_tr = len(full)
        g = torch.Generator().manual_seed(0)
        tr_ds, va_ds = random_split(full, [int(0.7 * n_tr), n_tr - int(0.7 * n_tr)], g)
    else:
        df = pd.read_parquet(parquet, columns=["code", "kline_time", "open", "high",
                                                "low", "close", "volume", "is_trading",
                                                "ma_20", "ma_60", "volume_ratio_5d", "macd"])
        # 全量走延迟渲染索引(不预渲染,内存百 MB 级);小样本保持同一切分语义
        tr = build_index(df, n_days, horizon, max_codes, end_date=train_end,
                         seed=0, stride=stride)
        print(f"训练索引 {len(tr['idx'])} codes={len(tr['codes'])} "
              f"正样本率={tr['y'].mean():.3f}", flush=True)
        n_tr = len(tr["idx"])
        g = torch.Generator().manual_seed(0)
        tr_ds, va_ds = random_split(LazyImageDataset(tr),
                                    [int(0.7 * n_tr), n_tr - int(0.7 * n_tr)], g)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = ImageCNN(n_days).to(dev)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    use_amp = amp and dev == "cuda"
    scaler = torch.amp.GradScaler("cuda") if use_amp else None
    pin = dev == "cuda"
    ld_kw = {"batch_size": bs, "num_workers": num_workers, "pin_memory": pin}
    best, bad, best_state = 1e9, 0, None
    for ep in range(epochs):
        model.train()
        tot = 0.0
        for xb, yb in DataLoader(tr_ds, shuffle=True, **ld_kw):
            xb, yb = xb.to(dev, non_blocking=pin), yb.to(dev, non_blocking=pin)
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
        with torch.no_grad():
            for xb, yb in DataLoader(va_ds, **ld_kw):
                with torch.amp.autocast("cuda", enabled=use_amp):
                    vl += loss_fn(model(xb.to(dev)), yb.to(dev)).item() * len(xb)
        vl /= max(1, len(va_ds))
        print(f"ep{ep} train_loss={tot / max(1, len(tr_ds)):.4f} val_loss={vl:.4f}", flush=True)
        if vl < best:
            best, bad = vl, 0
            best_state = {k: v.cpu() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 2:
                break
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"cnn_I{n_days}R{horizon}.pth")
    torch.save(best_state or model.state_dict(), path)
    print(f"保存 {path} 最优val={best:.4f}", flush=True)
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
              amp=a.amp)


if __name__ == "__main__":
    main()
