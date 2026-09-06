"""构建 (code, 标签日) -> 未来 open 路径表 npz（逐日回测数据准备）.

复制 dataset.py 读取模式（pyarrow 列裁剪 + is_trading 过滤 + 时间裁剪 + code/kline_time 排序），
对每 (code, 标签日 T) 输出 t_close(T日close) / open_t1(T+1 open，买入价) /
open_t6(T+1+horizon open，卖出价；horizon=5 即 T+6 open)。code 内不足 horizon+1 个
后续交易日的尾部标签日标 NaN（与 dataset future_ret open-open 口径要求 t+1+horizon
存在一致）。
open-open 口径：持仓毛收益 = open_t6 / open_t1 - 1。

> 口径同步（2026-09-05）: dataset.py 标签已改为 open-open（open[t+6]/open[t+1]-1），
> 本脚本生成逻辑本就是 open-open 口径，与训练标签口径一致，无需随重训改动。

用法：
  uv run --project . python scripts/build_ohlc_path.py --val_start 2025-07-01 --val_end 2025-12-31
  uv run --project . python scripts/build_ohlc_path.py --full --out logs/ohlc_full_val.npz
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

READ_COLS = ["code", "kline_time", "open", "close", "is_trading"]


def build_ohlc_path(parquet: str, val_start: str, val_end: str, horizon: int) -> dict:
    print(f"[ohlc] 读取 parquet(列裁剪 {len(READ_COLS)} 列): {parquet}")
    df = pq.read_table(parquet, columns=READ_COLS).to_pandas()
    print(f"[ohlc] 原始行数: {len(df):,}")
    df = df[df["is_trading"]]
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    cal = df["kline_time"].unique()
    cal = np.sort(cal)
    end_idx = int(np.searchsorted(cal, np.datetime64(pd.to_datetime(val_end)), side="right"))
    cutoff = cal[min(end_idx + horizon + 1, len(cal) - 1)]
    print(f"[ohlc] 时间裁剪: {val_start} ~ {np.datetime_as_string(cutoff, unit='D')} "
          f"(val_end 后预留 horizon+1={horizon + 1} 个交易日)")
    df = df[(df["kline_time"] >= pd.to_datetime(val_start)) & (df["kline_time"] <= pd.Timestamp(cutoff))]
    print(f"[ohlc] 过滤后行数: {len(df):,}")
    df = df.sort_values(["code", "kline_time"]).reset_index(drop=True)
    g = df.groupby("code", sort=False)
    open_t1 = g["open"].shift(-1)
    open_t6 = g["open"].shift(-(1 + horizon))
    t_close = df["close"].to_numpy(dtype=np.float64)
    o1 = open_t1.to_numpy(dtype=np.float64)
    o6 = open_t6.to_numpy(dtype=np.float64)
    dates = df["kline_time"].to_numpy().astype("datetime64[D]")
    codes = df["code"].to_numpy().astype("U16")
    n1, n6 = int(np.isnan(o1).sum()), int(np.isnan(o6).sum())
    print(f"[ohlc] 行数: {len(codes):,} codes: {len(np.unique(codes)):,} "
          f"标签日: {np.datetime_as_string(dates.min(), unit='D')} ~ {np.datetime_as_string(dates.max(), unit='D')}")
    print(f"[ohlc] 尾部 NaN 计数: open_t1={n1:,} open_t6={n6:,} (占比 {n6 / max(len(o6), 1):.4%})")
    return {"codes": codes, "dates": dates, "t_close": t_close, "open_t1": o1, "open_t6": o6}


def build_ohlc_full(parquet: str, val_start: str, val_end: str) -> dict:
    print(f"[ohlc-full] 读取 parquet(列裁剪 {len(READ_COLS)} 列): {parquet}")
    df = pq.read_table(parquet, columns=READ_COLS).to_pandas()
    print(f"[ohlc-full] 原始行数: {len(df):,}")
    df = df[df["is_trading"]]
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    df = df[(df["kline_time"] >= pd.to_datetime(val_start)) & (df["kline_time"] <= pd.to_datetime(val_end))]
    print(f"[ohlc-full] 时间裁剪: {val_start} ~ {val_end} 过滤后行数: {len(df):,}")
    codes = np.sort(df["code"].unique()).astype("U16")
    cal = np.sort(df["kline_time"].unique())
    piv_o = df.pivot(index="code", columns="kline_time", values="open").reindex(index=codes, columns=cal)
    piv_c = df.pivot(index="code", columns="kline_time", values="close").reindex(index=codes, columns=cal)
    open_m = piv_o.to_numpy(dtype=np.float64)
    close_m = piv_c.to_numpy(dtype=np.float64)
    dates = pd.DatetimeIndex(cal).to_numpy().astype("datetime64[D]")
    print(f"[ohlc-full] 矩阵: [{len(codes):,} codes x {len(dates):,} 交易日] "
          f"open_m NaN: {int(np.isnan(open_m).sum()):,} (停牌/未上市段保留 NaN)")
    print(f"[ohlc-full] 日期: {np.datetime_as_string(dates.min(), unit='D')} ~ "
          f"{np.datetime_as_string(dates.max(), unit='D')}")
    return {"codes": codes, "dates": dates, "open_m": open_m, "close_m": close_m}


def parse_args():
    p = argparse.ArgumentParser(description="构建 (code,标签日)->open 路径表 npz（回测数据准备）")
    p.add_argument("--parquet", default="Z:/test/train_data/train_data_v1_20130101-20260831_de850feab96a.parquet")
    p.add_argument("--val_start", default="2025-07-01")
    p.add_argument("--val_end", default="2025-12-31")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--out", default="logs/ohlc_path_val.npz")
    p.add_argument("--full", action="store_true",
                   help="输出全期日频矩阵 npz（键 codes/dates/open_m/close_m，shape [n_codes,n_dates]）"
                        "而非 6 日窗口路径表；target 模式回测用")
    return p.parse_args()


def main():
    args = parse_args()
    if args.full:
        arrays = build_ohlc_full(args.parquet, args.val_start, args.val_end)
        keys = "codes/dates/open_m/close_m"
    else:
        arrays = build_ohlc_path(args.parquet, args.val_start, args.val_end, args.horizon)
        keys = "codes/dates/t_close/open_t1/open_t6"
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    np.savez(args.out, **arrays)
    print(f"[ohlc] 已保存: {args.out} (键: {keys})")


if __name__ == "__main__":
    main()
