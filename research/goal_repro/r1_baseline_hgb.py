"""R1 基线复现：goal HGB 信号存在性链 → F60 最新数据 + 16 rank 特征 + HGB(CPU)。

标签沿 goal 基线口径：close[t+5]/close[t]-1（诊断用，不可执行）；
年度 walk-forward（训5年→测下一年），防泄露断言；产物落 runs/r1/。
用法：uv run --project . --no-sync python research/goal_repro/r1_baseline_hgb.py [--smoke]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from data.labels import rank_ic

PARQUET = "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"
RANK_FEATS = (
    "dmi", "adx", "boll", "kelch", "trend_duokong_dev",
    "volatility_5d", "volatility_10d", "volatility_20d",
    "volume_ratio_5d", "volume_ratio_10d", "amihud", "macd",
    "gross_margin", "net_margin", "debt_to_equity", "roe",
)
FOLDS = [
    {"name": "fold1", "train": ("2019-07-01", "2024-06-30"), "pred": ("2024-07-01", "2025-06-30")},
    {"name": "fold2", "train": ("2020-07-01", "2025-06-30"), "pred": ("2025-07-01", "2026-08-31")},
]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", "r1")


def load_frame(smoke: bool) -> pd.DataFrame:
    cols = ["code", "kline_time", "is_trading", "open", "close", *RANK_FEATS]
    df = pd.read_parquet(PARQUET, columns=cols)
    df = df[df["is_trading"]].sort_values(["code", "kline_time"]).reset_index(drop=True)
    # F60 新 vintage 脏行：is_trading=True 但 OHLC=0（多为 2026-08 停牌误标），实质不可交易，剔除
    df = df[(df["open"] > 0) & (df["close"] > 0)].reset_index(drop=True)
    if smoke:
        codes = df["code"].unique()[:100]
        df = df[df["code"].isin(codes)].reset_index(drop=True)
    return df


def add_features_labels(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["kline_time"]).dt.date
    for feat in RANK_FEATS:
        df[f"cs_{feat}"] = df.groupby("date")[feat].rank(pct=True).fillna(0.5).astype(np.float32)
    df["future_ret_5d"] = df.groupby("code")["close"].transform(lambda s: s.shift(-5) / s - 1.0)
    return df


def daily_metrics(dates, exp, tru) -> dict:
    ics, spreads, q5s = [], [], []
    for day in np.unique(dates):
        m = dates == day
        if int(m.sum()) < 50:
            continue
        e, r = exp[m], tru[m]
        finite = np.isfinite(e) & np.isfinite(r)
        if int(finite.sum()) < 50:
            continue
        e, r = e[finite], r[finite]
        ics.append(rank_ic(e, r))
        order = np.argsort(-e)
        n5 = max(1, len(order) // 5)
        q5s.append(float(r[order[:n5]].mean()))
        spreads.append(float(r[order[:n5]].mean() - r[order[-n5:]].mean()))
    ics = np.asarray(ics)
    return {"days": len(ics), "rank_ic": float(ics.mean()),
            "q5_q1_spread_annual": float(np.mean(spreads) * 242),
            "q5_mean_annual": float(np.mean(q5s) * 242)}


def run_fold(df, feat_cols, fold, out_dir, smoke: bool) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor

    tr = (df["date"] >= pd.to_datetime(fold["train"][0]).date()) & (
        df["date"] <= pd.to_datetime(fold["train"][1]).date())
    pr = (df["date"] >= pd.to_datetime(fold["pred"][0]).date()) & (
        df["date"] <= pd.to_datetime(fold["pred"][1]).date())
    assert int(tr.sum()) and int(pr.sum()), f"{fold['name']} 空折"
    assert df.loc[tr, "date"].max() < df.loc[pr, "date"].min(), "泄露"
    train = df.loc[tr].dropna(subset=["future_ret_5d"])
    Xtr = train[feat_cols].to_numpy(dtype=np.float32)
    ytr = train["future_ret_5d"].to_numpy(dtype=np.float64)
    lo, hi = np.percentile(ytr, [0.5, 99.5])
    ytr = np.clip(ytr, lo, hi)
    t0 = time.time()
    model = HistGradientBoostingRegressor(max_iter=200 if not smoke else 20,
                                          max_leaf_nodes=31, min_samples_leaf=50,
                                          l2_regularization=1.0, random_state=42)
    model.fit(Xtr, ytr)
    pred = df.loc[pr]
    exp = model.predict(pred[feat_cols].to_numpy(dtype=np.float32)).astype(np.float64)
    tru = pred["future_ret_5d"].to_numpy(dtype=np.float64)
    dates = pred["date"].to_numpy()
    codes = pred["code"].to_numpy()
    valid = np.isfinite(tru)
    met = daily_metrics(dates[valid], exp[valid], tru[valid])
    met.update({"fold": fold["name"], "train_n": int(tr.sum()), "pred_n": int(pr.sum()),
                "secs": round(time.time() - t0, 1)})
    os.makedirs(out_dir, exist_ok=True)
    np.savez(os.path.join(out_dir, f"preds_{fold['name']}.npz"), exp_ret=exp,
             true_ret=tru, dates=dates, codes=codes)
    print(f"[{fold['name']}] n={int(pr.sum())} IC={met['rank_ic']:.4f} "
          f"spread={met['q5_q1_spread_annual']:.4f} {met['secs']}s", flush=True)
    return met


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    df = load_frame(args.smoke)
    print(f"rows={len(df)} codes={df['code'].nunique()}", flush=True)
    df = add_features_labels(df)
    feat_cols = [f"cs_{f}" for f in RANK_FEATS]
    recs = [run_fold(df, feat_cols, fold, OUT, args.smoke) for fold in FOLDS]
    with open(os.path.join(OUT, "metrics.json"), "w") as fh:
        json.dump(recs, fh, indent=2)
    print(f"saved {OUT} total={round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    main()
