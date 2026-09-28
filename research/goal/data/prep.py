"""goal 数据地基 prep: 列投影读取 / 时段切分 / TRAIN-only scaler拟合 / 100股采样 / --check体检.

列投影: code,kline_time,close,is_trading + 特征列(照抄cnn排除逻辑,39列).
切分: TRAIN[2013-01-01,2021-12-31] / VAL[2022-01-01,2023-12-31] / TEST[2024-01-01,2025-12-31].
scaler: 只在TRAIN拟合 -> artifacts/scaler.pkl (import自 data.vendor_scaler,零cnn依赖).
--check: 各段行数 / 可建窗口数(SEQ_LEN=60,horizon=5,窗口末日t要求t~t+5同股且is_trading全真,close有效)
         / q5(每kline_time截面pd.qcut(future_ret_5d,5),各split内各自做) / 特征NaN率 -> artifacts/data_check.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PARQUET = ROOT / "data" / "train_data.parquet"
DEFAULT_SAMPLE = ROOT / "data" / "sample_100.parquet"
DEFAULT_SCALER = ROOT / "artifacts" / "scaler.pkl"
DEFAULT_CHECK = ROOT / "artifacts" / "data_check.json"

SEQ_LEN = 60
HORIZON = 5

# 照抄 cnn/data/dataset.py _default_feature_cols (第88-100行) 的排除集
FEATURE_EXCLUDE = {
    "code", "kline_time", "is_trading",
    "return_1d", "return_5d", "return_10d", "return_20d",
    "TOT_SHARE", "volume", "amount", "close",
    "pe", "pb", "pcf", "ps",
    "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
}

SPLITS = {
    "TRAIN": ("2013-01-01", "2021-12-31"),
    "VAL": ("2022-01-01", "2023-12-31"),
    "TEST": ("2024-01-01", "2025-12-31"),
}


def default_feature_cols(all_columns):
    return [c for c in all_columns if c not in FEATURE_EXCLUDE]


def read_projected(parquet_path: Path, feature_cols):
    use_cols = ["code", "kline_time", "close", "is_trading"] + feature_cols
    use_cols = list(dict.fromkeys(use_cols))
    table = pq.read_table(str(parquet_path), columns=use_cols)
    df = table.to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    return df


def split_frame(df: pd.DataFrame):
    out = {}
    for name, (s, e) in SPLITS.items():
        m = (df["kline_time"] >= pd.Timestamp(s)) & (df["kline_time"] <= pd.Timestamp(e))
        out[name] = df.loc[m].copy()
    return out


def add_future_ret_within_split(g: pd.DataFrame) -> pd.DataFrame:
    """split内按code排序, future_ret_5d[t]=close[t+5]/close[t]-1, 要求t..t+5同split同股且is_trading全真且close有效."""
    g = g.sort_values(["code", "kline_time"]).copy()
    g["future_ret_5d"] = np.nan
    for _code, grp in g.groupby("code", sort=False):
        idx = grp.index.values
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        n = len(grp)
        fr = np.full(n, np.nan)
        # t+5 必须仍在同一(code,split)组内: 位置t+5<n
        for t in range(n - HORIZON):
            if is_tr[t:t + HORIZON + 1].all():
                c0, c5 = close[t], close[t + HORIZON]
                if np.isfinite(c0) and np.isfinite(c5) and c0 != 0:
                    fr[t] = c5 / c0 - 1.0
        g.loc[idx, "future_ret_5d"] = fr
    return g


def count_windows_split(df_split: pd.DataFrame) -> int:
    """精确枚举: 窗口末日t, 要求60窗行[i-59..i]+5 horizon[i+1..i+5]共65行同组且is_trading全真,close[i],close[i+5]有效.
    在split内按code分组枚举,不跨split/不跨股."""
    total = 0
    for _code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        n = len(grp)
        if n < SEQ_LEN + HORIZON:
            continue
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])  # cs[k]=前k行bad数
        # 末日t范围: t>=59 且 t+5<n
        for t in range(SEQ_LEN - 1, n - HORIZON):
            a, b = t - SEQ_LEN + 1, t + HORIZON
            if cs[b + 1] - cs[a] != 0:
                continue
            c0, c5 = close[t], close[t + HORIZON]
            if np.isfinite(c0) and np.isfinite(c5) and c0 != 0:
                total += 1
    return int(total)


def estimate_windows_split(df_split: pd.DataFrame, k: int, seed: int):
    """抽样估算: 随机抽K股精确计数, 按股数比例外推. 返回(est, sample_windows, k_used)."""
    codes = df_split["code"].unique()
    n_total = len(codes)
    rng = np.random.default_rng(seed)
    k_used = min(k, n_total)
    sel = rng.choice(cast(Any, codes), k_used, replace=False)
    sub = df_split[df_split["code"].isin(cast(Any, sel))]
    w = count_windows_split(cast(pd.DataFrame, sub))
    est = round(w * (n_total / k_used)) if k_used else 0
    return est, int(w), int(k_used), int(n_total)


def q5_within_split(df_split: pd.DataFrame):
    """各split内各自做: 每kline_time截面pd.qcut(future_ret_5d,5). 返回分布dict+统计."""
    valid = df_split[np.isfinite(df_split["future_ret_5d"].values)].copy()
    n_labeled = len(valid)
    dist = {str(i): 0 for i in range(5)}
    n_dates = 0
    n_skip_dates = 0
    n_skip_rows = 0
    if n_labeled:
        for _dt, grp in valid.groupby("kline_time", sort=False):
            n_dates += 1
            if len(grp) < 5:
                n_skip_dates += 1
                n_skip_rows += len(grp)
                continue
            try:
                q = cast(Any, pd.qcut(grp["future_ret_5d"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
            except Exception:  # noqa: BLE001 -- 退化截面跳过计数，收窄会漏计
                n_skip_dates += 1
                n_skip_rows += len(grp)
                continue
            if getattr(q, "cat", None) is not None and len(q.cat.categories) != 5:
                n_skip_dates += 1
                n_skip_rows += len(grp)
                continue
            for v in q.values:
                if pd.isna(v):
                    n_skip_rows += 1
                else:
                    dist[str(int(v))] += 1
    labeled_used = sum(dist.values())
    pct = {kk: (vv / labeled_used if labeled_used else 0.0) for kk, vv in dist.items()}
    return {"counts": dist, "pct": pct, "n_labeled_rows": int(n_labeled),
            "n_used_rows": int(labeled_used), "n_dates": int(n_dates),
            "n_skip_dates": int(n_skip_dates), "n_skip_rows": int(n_skip_rows)}


def nan_rates(df: pd.DataFrame, feature_cols):
    rates = {}
    for c in feature_cols:
        rates[c] = float(cast(float, df[c].isna().mean())) if len(df) else 0.0
    return rates


def cmd_make_sample(parquet_path: Path, out_path: Path, seed: int, n: int):
    t = pq.read_table(str(parquet_path), columns=["code"]).to_pandas()
    codes = t["code"].unique()
    rng = np.random.default_rng(seed)
    sel = rng.choice(codes, min(n, len(codes)), replace=False)
    full = pq.read_table(str(parquet_path)).to_pandas()
    samp = full[full["code"].isin(sel)].sort_values(["code", "kline_time"]).reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    samp.to_parquet(out_path, index=False)
    print(f"[sample] codes {len(codes)} -> {len(sel)} (seed={seed}), rows {len(samp)}, saved {out_path}")
    return sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--make-sample", action="store_true")
    ap.add_argument("--sample-out", default=str(DEFAULT_SAMPLE))
    ap.add_argument("--scaler-out", default=str(DEFAULT_SCALER))
    ap.add_argument("--check-out", default=str(DEFAULT_CHECK))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-n", type=int, default=100)
    ap.add_argument("--estimate-windows-codes", type=int, default=0,
                    help=">0则窗口数用抽K股外推估算(行数/q5/NaN仍精确)")
    args = ap.parse_args()

    parquet_path = Path(args.parquet)
    pf = pq.ParquetFile(str(parquet_path))
    all_cols = pf.schema.names
    feature_cols = default_feature_cols(all_cols)
    print(f"[prep] parquet={parquet_path} rows={pf.metadata.num_rows} cols={len(all_cols)}")
    print(f"[prep] feature_cols={len(feature_cols)} (exclude={len(FEATURE_EXCLUDE)}), e.g. {feature_cols[:6]}")

    if args.make_sample:
        cmd_make_sample(parquet_path, Path(args.sample_out), args.seed, args.sample_n)

    if not args.check:
        print("[prep] done (no --check, no fit). Use --check to run 体检+fit.")
        return

    df = read_projected(parquet_path, feature_cols)
    print(f"[prep] projected read: {len(df):,} rows, dtypes ok; time {df['kline_time'].min()} -> {df['kline_time'].max()}, codes {df['code'].nunique()}")
    splits = split_frame(df)

    # NaN率(原始,scaler前)
    nan_overall = nan_rates(df, feature_cols)
    # future_ret + 窗口 + q5, 各split内各自做
    result = {"params": {"seq_len": SEQ_LEN, "horizon": HORIZON, "seed": args.seed,
                         "parquet": str(parquet_path), "src_rows": pf.metadata.num_rows,
                         "src_cols": len(all_cols),
                         "estimate_windows_codes": args.estimate_windows_codes},
              "feature_cols": feature_cols,
              "feature_exclude": sorted(FEATURE_EXCLUDE),
              "splits": {}}
    for name, sdf in splits.items():
        sdf = add_future_ret_within_split(sdf)
        splits[name] = sdf  # 写回带future_ret的帧
        if args.estimate_windows_codes > 0:
            est, sw, ku, kn = estimate_windows_split(sdf, args.estimate_windows_codes, args.seed)
            win_info = {"n_windows": est, "estimated": True, "sample_windows": sw,
                        "sample_codes": ku, "total_codes": kn,
                        "method": f"sample {ku}/{kn} codes exact, scale by code count"}
        else:
            win_info = {"n_windows": count_windows_split(sdf), "estimated": False}
        q5 = q5_within_split(sdf)
        nan_sp = nan_rates(sdf, feature_cols)
        result["splits"][name] = {
            "n_rows": len(sdf),
            "n_codes": int(cast(int, sdf["code"].nunique())) if len(sdf) else 0,
            "n_trading_true": int(cast(int, sdf["is_trading"].sum())) if len(sdf) else 0,
            "windows": win_info,
            "q5": q5,
            "nan_rate": nan_sp,
            "nan_max": float(max(nan_sp.values())) if nan_sp else 0.0,
        }
        w = win_info
        print(f"[{name}] rows={len(sdf):,} codes={result['splits'][name]['n_codes']} "
              f"is_trading_true={result['splits'][name]['n_trading_true']:,} "
              f"windows={w['n_windows']:,}{' (EST)' if w.get('estimated') else ''} "
              f"q5pct={[round(q5['pct'][str(i)], 4) for i in range(5)]} nan_max={result['splits'][name]['nan_max']:.4f}")

    result["nan_overall"] = nan_overall
    result["nan_overall_max"] = float(max(nan_overall.values())) if nan_overall else 0.0

    # scaler只在TRAIN拟合
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from vendor_scaler import PerCodeGroupedScaler
    train_df = splits["TRAIN"]
    t0 = datetime.now()  # noqa: DTZ005 -- 仅计时用，时区会污染产物字符串
    scaler = PerCodeGroupedScaler(add_mask=True)
    scaler.fit(train_df, feature_cols)
    # 快速无NaN自检: 取TRAIN首股transform
    code0 = train_df["code"].iloc[0]
    g0 = train_df[train_df["code"] == code0].sort_values("kline_time")
    feat0 = g0[feature_cols].values.astype(np.float64)
    close0 = g0["close"].values.astype(np.float64)
    out0 = scaler.transform_code(code0, feat0, feature_cols, close0)
    post_nan = bool(np.isnan(out0).any() or np.isinf(out0).any())
    sout = Path(args.scaler_out)
    sout.parent.mkdir(parents=True, exist_ok=True)
    scaler.save(str(sout))
    fit_s = (datetime.now() - t0).total_seconds()  # noqa: DTZ005 -- 仅计时用
    result["scaler"] = {"fit_on": "TRAIN only", "train_rows": len(train_df),
                        "train_codes": int(train_df["code"].nunique()),
                        "feature_in": len(scaler.feature_cols),
                        "feature_out": len(scaler.feature_cols_out),
                        "mask_cols": scaler.mask_cols, "path": str(sout),
                        "post_transform_nan_inf_on_first_code": post_nan,
                        "fit_seconds": fit_s}
    print(f"[scaler] TRAIN-only fit: {len(scaler.feature_cols)} -> {len(scaler.feature_cols_out)}, "
          f"mask={scaler.mask_cols}, post_nan/inf(first code)={post_nan}, saved {sout}")

    cout = Path(args.check_out)
    cout.parent.mkdir(parents=True, exist_ok=True)
    result["generated_at"] = datetime.now().isoformat()  # noqa: DTZ005 -- 产物时间戳保持 naive 口径
    with open(cout, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[check] saved {cout}")


if __name__ == "__main__":
    main()
