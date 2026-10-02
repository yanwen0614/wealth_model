"""预生成图片缓存:一次性多进程渲染 → uint8 memmap,训练/推理只读缓存.

解决延迟渲染每轮重复烧 CPU 的问题(I60 单轮渲染 >20min)。
用法:
  python -m paper_jkx.src.build_cache --n_days 60 --horizon 60 --stride 20
      --train_end 2023-12-31 --out paper_jkx/logs/cache_I60R60_train --workers 8
产物: images.mm(uint8 [N,H,W]) + meta.npz(y/rets/dates/codes/n_days/...).
"""
import argparse
import os

import numpy as np
import pandas as pd

PARQUET = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
READ_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume",
             "is_trading", "ma_5", "ma_20", "ma_60", "volume_ratio_5d", "macd"]


def _render_chunk(args):
    import numpy as np

    from paper_jkx.src.imaging import render_i30_rgb, render_plus
    (store_keys, store_vals, jobs, out_path, shape, n_days, rgb,
     shard_dir, shard_offsets, shard_sizes) = args
    store = dict(zip(store_keys, store_vals))
    H, W, C = shape[-3], shape[-2], shape[-1]
    single = shard_dir is None
    mms = {}
    if single:
        mms[None] = np.memmap(out_path, dtype=np.uint8, mode="r+", shape=shape)
    for out_i, code, s, t in jobs:
        arr = store[code][s:t + 1]
        if rgb:  # I30-color: ma_5(10)/ma_20(6)/ma_60(7), vol_ratio(8), macd(9)
            img = render_i30_rgb(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3],
                                 arr[:, 4], arr[:, 10], arr[:, 6], arr[:, 7],
                                 arr[:, 8], arr[:, 9])
            px = img
        else:
            px = (render_plus(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4],
                              [arr[:, 5], arr[:, 6], arr[:, 7]], arr[:, 8], arr[:, 9],
                              n_days=n_days) * 255).astype(np.uint8)
        if single:
            mms[None][out_i] = px
        else:
            k = int(np.searchsorted(shard_offsets, out_i, side="right") - 1)
            mm = mms.get(k)
            if mm is None:
                nk = int(shard_sizes[k])
                sk = (nk, H, W) if C == 1 else (nk, H, W, C)
                mm = np.memmap(os.path.join(shard_dir, f"part_{k:05d}.bin"),
                               dtype=np.uint8, mode="r+", shape=sk)
                mms[k] = mm
            mm[out_i - int(shard_offsets[k])] = px
    for mm in mms.values():
        mm.flush()
    return len(jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_days", type=int, default=60)
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--stride", type=int, default=20)
    ap.add_argument("--train_end", default="2023-12-31")
    ap.add_argument("--start", default=None)
    ap.add_argument("--max_codes", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--parquet", type=str, default=PARQUET,
                    help="覆盖默认本地 parquet(Z 盘含 2026 数据时显式传入)")
    ap.add_argument("--shards", type=int, default=0,
                    help=">0 时按固定种子随机置换后切成 N 片(块随机/片内顺序读友好)")
    a = ap.parse_args()
    from paper_jkx.src.dataset import build_index
    from paper_jkx.src.imaging import SHAPES

    max_codes = None if a.max_codes <= 0 else a.max_codes
    df = pd.read_parquet(a.parquet, columns=READ_COLS)
    index = build_index(df, a.n_days, a.horizon, max_codes, end_date=a.train_end,
                        start_date=a.start, stride=a.stride)
    del df
    H, W, C = SHAPES[a.n_days]
    rgb = C == 3
    N = len(index["idx"])
    # 固定种子随机置换: build_index 按股票分组, 不置换则单 shard 仅含一两只股票,
    # 片内顺序读虽快但 batch 失去横截面多样性. 置换后每片=随机混合, 片内顺序读=随机采样.
    perm = np.random.RandomState(0).permutation(N)
    # 注意: codes 为逐股票(长度=股票数), 不参与逐样本置换; idx/dates/rets/y 逐样本
    y = np.asarray(index["y"])[perm]
    rets = np.asarray(index["rets"])[perm]
    dates = np.asarray(index["dates"])[perm]
    codes = np.asarray(index["codes"])
    idx = np.asarray(index["idx"])[perm]
    os.makedirs(a.out, exist_ok=True)
    codes_src = np.asarray(index["codes"])
    jobs = [(i, codes_src[int(idx[i, 0])], int(idx[i, 1]) - a.n_days + 1, int(idx[i, 1]))
            for i in range(N)]
    if a.shards > 0:
        K = min(a.shards, N)
        base, rem = divmod(N, K)
        sizes = np.full(K, base, dtype=np.int64)
        sizes[:rem] += 1
        offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64)
        shard_dir = os.path.join(a.out, "shards")
        os.makedirs(shard_dir, exist_ok=True)
        for k in range(K):
            sk = (int(sizes[k]), H, W) if C == 1 else (int(sizes[k]), H, W, C)
            _m = np.memmap(os.path.join(shard_dir, f"part_{k:05d}.bin"),
                           dtype=np.uint8, mode="w+", shape=sk)
            del _m
        shape = (N, H, W, C) if rgb else (N, H, W)
        mm_path, sd, so, ss = None, shard_dir, offsets, sizes
        print(f"样本 {N} 分片 {K} 片 {a.workers} 进程渲染", flush=True)
    else:
        shape = (N, H, W, C) if rgb else (N, H, W)
        mm_path = os.path.join(a.out, "images.mm")
        _m = np.memmap(mm_path, dtype=np.uint8, mode="w+", shape=shape)
        del _m  # workers 各自映射写入
        gb = N * H * W * C / 1e9
        sd, so, ss = None, None, None
        print(f"样本 {N} 形状 {list(shape)} {gb:.1f}GB {a.workers} 进程渲染", flush=True)
    import torch.multiprocessing as mp

    keys = list(index["store"].keys())
    vals = [index["store"][k] for k in keys]
    stride = max(1, len(jobs) // a.workers)
    chunks = []
    for w in range(a.workers):
        part = jobs[w * stride:] if w == a.workers - 1 else jobs[w * stride:(w + 1) * stride]
        if part:
            chunks.append((keys, vals, part, mm_path, shape, a.n_days, rgb, sd, so, ss))
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers) as pool:
        done = sum(pool.map(_render_chunk, chunks))
    np.savez(os.path.join(a.out, "meta.npz"), y=y, rets=rets, dates=dates, codes=codes,
             idx=idx, n_days=a.n_days, horizon=a.horizon, stride=a.stride,
             train_end=a.train_end,
             shard_sizes=(np.asarray(ss, dtype=np.int64) if ss is not None
                          else np.zeros(0, dtype=np.int64)))
    print(f"完成 {done}/{N} 已存 {a.out}", flush=True)


if __name__ == "__main__":
    main()
