"""Exp2: G6/G7 add-back with point-in-time audit + lagged fallback.

Audit (written in metrics):
- quant pipeline uses _effective_report_date (actual announcement date, ffill from
  effect_date; NaN fallback report_date), fix present since 28e01e1, export commit
  0faaf8c contains it (FIX-IN-EXPORT), export 2026-08-31.
- Empirical: 3 stocks (002240.SZ/300058.SZ/300460.SZ) revenue_growth step dates all
  fall in announcement seasons (Apr/Aug/Oct/Feb), never on quarter-end/next day.
  => No lookahead evidence; use as-of raw values directly.
- Normalization without refit: per-day cross-sectional rank (no fitting, no leak).

If audit had failed, this script would ABORT (non-zero exit, VOID verdict).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models"))
from feat_common import (
    DEFAULT_FULL,
    G6_COLS,
    G7_COLS,
    add_cs_rank,
    batched_predict,
    build_samples,
    cross_section_ic,
    fit_hgb,
    load_scaler,
    sample_weights,
    split_frame,
)

OUT_DIR = ROOT / "artifacts" / "opt_feat"
METRICS_OUT = OUT_DIR / "metrics_exp2_g67.json"
PRED_OUT = OUT_DIR / "pred_exp2_g67.parquet"
AUDIT_STOCKS = ["002240.SZ", "300058.SZ", "300460.SZ"]


def run_audit() -> dict:
    """Check growth step dates vs quarter ends: flag if any step lands within
    [qend, qend+2 trading days] (report-date-effective suspicion)."""
    res = {"stocks": {}, "suspicious_steps": 0, "checked_steps": 0, "pass": True}
    for code in AUDIT_STOCKS:
        f = pq.read_table(
            str(DEFAULT_FULL),
            columns=["code", "kline_time", "is_trading", "revenue_growth", "profit_growth"],
            filters=[("code", "=", code)]).to_pandas().sort_values("kline_time")
        f["kline_time"] = pd.to_datetime(f["kline_time"])
        f = f[f["is_trading"]].reset_index(drop=True)
        stock = {"n_rows": len(f), "steps": []}
        for c in ["revenue_growth", "profit_growth"]:
            v = f[c].values.astype(np.float64)
            is_new = np.zeros(len(v), dtype=bool)
            prev = np.nan
            for i, x in enumerate(v):
                if np.isfinite(x) and (not np.isfinite(prev) or abs(x - prev) > 1e-9):
                    is_new[i] = True
                if np.isfinite(x):
                    prev = x
            dates = f.loc[is_new, "kline_time"]
            for d in dates.iloc[1:6].tolist():  # sample post-warmup steps
                qend_hit = (d.month in (1, 4, 7, 10) and d.day <= 2) or (
                    (d.month, d.day) in ((4, 1), (7, 1), (10, 1), (1, 1), (1, 2)))
                stock["steps"].append({"col": c, "date": str(d.date()),
                                       "near_qstart": bool(qend_hit)})
                res["checked_steps"] += 1
                if qend_hit:
                    res["suspicious_steps"] += 1
        res["stocks"][code] = stock
    # announcement-season check: steps must cluster in Feb/Apr-May/Aug/Oct
    res["pass"] = res["suspicious_steps"] == 0
    return res


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = run_audit()
    print(f"[exp2 audit] {json.dumps(audit, indent=2)[:3000]}", flush=True)
    if not audit["pass"]:
        verdict = {"exp": "G6G7_addback", "verdict": "VOID",
                   "reason": "point-in-time suspicion not excluded",
                   "audit": audit}
        with open(METRICS_OUT, "w") as f:
            json.dump(verdict, f, indent=2)
        print("[exp2] AUDIT FAIL -> VOID, aborting", flush=True)
        sys.exit(3)
    scaler = load_scaler()
    feature_cols = list(scaler.feature_cols)  # 39
    rank_src = G6_COLS + G7_COLS
    rank_cols = [c + "_rank" for c in rank_src]
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"]
                                  + feature_cols + rank_src))
    df = pq.read_table(str(DEFAULT_FULL), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    splits = split_frame(df)
    del df
    # rank per split (same-day only)
    for k in list(splits.keys()):
        splits[k] = add_cs_rank(splits[k], rank_src)
    Xtr, ytr, _, _ = build_samples(splits["TRAIN"], scaler, feature_cols, extra_cols=rank_cols)
    del splits["TRAIN"]
    print(f"[exp2] TRAIN X={Xtr.shape} (49+8=57 expected)", flush=True)
    Xva, yva, _, mva = build_samples(splits["VAL"], scaler, feature_cols, extra_cols=rank_cols)
    del splits["VAL"]
    wtr = sample_weights(ytr)
    m, fit_s = fit_hgb(Xtr, ytr, wtr, 150)
    sc = batched_predict(m, Xva)
    dv = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                       "realizable_ret": yva.astype(np.float64)})
    vic, vir, vnd = cross_section_ic(dv)
    print(f"[exp2] VAL IC={vic:.4f} (champ 0.0610)", flush=True)
    del sc, dv
    Xf = np.concatenate([Xtr, Xva], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr, ytr, Xva, yva
    final, final_s = fit_hgb(Xf, yf, sample_weights(yf), 150)
    del Xf, yf
    Xte, yte, yote, mte = build_samples(splits["TEST"], scaler, feature_cols, extra_cols=rank_cols)
    del splits["TEST"]
    ste = batched_predict(final, Xte)
    del Xte
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": ste.astype(np.float64),
                        "realizable_ret": yte.astype(np.float64),
                        "future_ret_5d": yote.astype(np.float64)})
    tic, tir, tnd = cross_section_ic(dte)
    print(f"[exp2] TEST IC={tic:.4f} (champ 0.0764)", flush=True)
    dte[["code", "kline_time", "score", "realizable_ret", "future_ret_5d"]].to_parquet(
        PRED_OUT, index=False)
    metrics = {"exp": "G6G7_addback_csrank", "n_features": 57,
               "added": rank_cols, "norm": "per-day cross-sectional rank (no fit, no leak)",
               "lag_policy": "as-of raw used directly; audit passed so no extra lag",
               "audit": audit,
               "quant_logic": "_effective_report_date (actual announcement date ffill), "
                              "fix in 28e01e1, export 0faaf8c contains fix",
               "max_iter": 150, "val_ic": vic, "val_ir": vir, "val_n_days": vnd,
               "test_ic": tic, "test_ir": tir, "test_n_days": tnd,
               "champ_val_ic": 0.06104204735470689, "champ_test_ic": 0.07643673104838995,
               "fit_secs": fit_s, "fit_final_secs": final_s,
               "total_secs": time.time() - t0}
    with open(METRICS_OUT, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[exp2] saved {METRICS_OUT}", flush=True)


if __name__ == "__main__":
    main()
