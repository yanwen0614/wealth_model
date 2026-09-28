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
             "is_trading", "ma_20", "ma_60", "volume_ratio_5d", "macd"]


def _render_chunk(args):
    import numpy as np

    from paper_jkx.src.imaging import render_plus
    store_keys, store_vals, jobs, out_path, shape = args
    mm = np.memmap(out_path, dtype=np.uint8, mode="r+", shape=shape)
    store = dict(zip(store_keys, store_vals))
    n = shape[2] // 3
    for out_i, code, s, t in jobs:
        arr = store[code][s:t + 1]
        img = render_plus(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4],
                          [arr[:, 5], arr[:, 6], arr[:, 7]], arr[:, 8], arr[:, 9],
                          n_days=n)
        mm[out_i] = (img * 255).astype(np.uint8)
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
    a = ap.parse_args()
    from paper_jkx.src.dataset import build_index
    from paper_jkx.src.imaging import HEIGHTS

    max_codes = None if a.max_codes <= 0 else a.max_codes
    df = pd.read_parquet(PARQUET, columns=READ_COLS)
    index = build_index(df, a.n_days, a.horizon, max_codes, end_date=a.train_end,
                        start_date=a.start, stride=a.stride)
    del df
    N, H, W = len(index["idx"]), HEIGHTS[a.n_days], 3 * a.n_days
    os.makedirs(a.out, exist_ok=True)
    mm_path = os.path.join(a.out, "images.mm")
    mm = np.memmap(mm_path, dtype=np.uint8, mode="w+", shape=(N, H, W))
    del mm  # workers 各自映射写入
    print(f"样本 {N} 形状 [{N},{H},{W}] {N * H * W / 1e9:.1f}GB {a.workers} 进程渲染", flush=True)
    import torch.multiprocessing as mp

    jobs = []
    for out_i, (pos, t) in enumerate(index["idx"]):
        code = index["codes"][int(pos)]
        jobs.append((out_i, code, int(t) - a.n_days + 1, int(t)))
    keys = list(index["store"].keys())
    vals = [index["store"][k] for k in keys]
    stride = max(1, len(jobs) // a.workers)
    chunks = []
    for w in range(a.workers):
        part = jobs[w * stride:] if w == a.workers - 1 else jobs[w * stride:(w + 1) * stride]
        if part:
            chunks.append((keys, vals, part, mm_path, (N, H, W)))
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers) as pool:
        done = sum(pool.map(_render_chunk, chunks))
    np.savez(os.path.join(a.out, "meta.npz"), y=index["y"], rets=index["rets"],
             dates=np.asarray(index["dates"]), codes=np.asarray(index["codes"]),
             idx=np.asarray(index["idx"]), n_days=a.n_days, horizon=a.horizon,
             stride=a.stride, train_end=a.train_end)
    print(f"完成 {done}/{N} 已存 {a.out}", flush=True)


if __name__ == "__main__":
    main()
