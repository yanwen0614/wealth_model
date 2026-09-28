"""一键评估:测试窗成图 → 推理 → preds npz → 现有引擎回测."""
import argparse

import pandas as pd

from scripts.build_ohlc_path import build_ohlc_full

from .backtest import dump_index_cache, predict_index, run_existing_backtest
from .dataset import LazyImageDataset, build_index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--n_days", type=int, default=5)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--test_start", default="2019-01-01")
    ap.add_argument("--test_end", default="2025-12-31")
    ap.add_argument("--max_codes", type=int, default=200)
    ap.add_argument("--preds_out", default="paper_jkx/logs/preds_I5R5.npz")
    ap.add_argument("--target_size", type=int, default=100)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--num_workers", type=int, default=4)
    ap.add_argument("--bs", type=int, default=2048)
    a = ap.parse_args()
    if a.max_codes is not None and a.max_codes <= 0:
        a.max_codes = None
    df = pd.read_parquet(a.parquet, columns=["code", "kline_time", "open",
                                              "high", "low", "close", "volume",
                                              "is_trading", "ma_20", "ma_60",
                                              "volume_ratio_5d", "macd"])
    index = build_index(df, a.n_days, a.horizon, a.max_codes,
                        start_date=a.test_start, end_date=a.test_end,
                        stride=a.stride)
    probs = predict_index(a.ckpt, a.n_days, LazyImageDataset(index),
                          num_workers=a.num_workers, bs=a.bs)
    dump_index_cache(index, probs, a.preds_out)
    print(f"preds 已存 {a.preds_out} 样本 {len(probs)}", flush=True)
    full_ohlc = build_ohlc_full(a.parquet, a.test_start, a.test_end)
    m = run_existing_backtest(a.preds_out, full_ohlc, target_size=a.target_size)
    print(f"现有引擎 target(size={a.target_size}): {m}", flush=True)
    print("如需完整报告(含基准/曲线): python -m scripts.run_backtest "
          f"--mode target --preds {a.preds_out} --full_ohlc <矩阵npz> "
          f"--target_size {a.target_size}", flush=True)


if __name__ == "__main__":
    main()
