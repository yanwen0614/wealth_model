"""Exp1: prune 6 masks + G8 five cols, same config (max_iter=150), VAL select + TEST report.

Note on dims: 49 = 45 scaler-out + 4 hand. Dropping 6 masks + G8 five = 11 cols
-> 38 dims total (34 scaler-out + 4 hand). Task text says "(43维)" which equals
49-6 (masks only); we run the full intent (38-dim) and report the correction.
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
    G8_COLS,
    HAND_COLS,
    MASK_COLS,
    batched_predict,
    build_samples,
    cross_section_ic,
    fit_hgb,
    load_scaler,
    sample_weights,
    split_frame,
)

OUT_DIR = ROOT / "artifacts" / "opt_feat"
METRICS_OUT = OUT_DIR / "metrics_exp1_prune.json"
PRED_OUT = OUT_DIR / "pred_exp1_prune.parquet"


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scaler = load_scaler()
    base_in = list(scaler.feature_cols)  # 39
    pruned_in = [c for c in base_in if c not in set(G8_COLS)]  # 34
    print(f"[exp1] base_in={len(base_in)} pruned_in={len(pruned_in)} "
          f"dropped_G8={G8_COLS} dropped_masks={MASK_COLS}", flush=True)
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + pruned_in))
    df = pq.read_table(str(DEFAULT_FULL), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[exp1] read {len(df):,} rows", flush=True)
    splits = split_frame(df)
    del df
    Xtr, ytr, _, _ = build_samples(splits["TRAIN"], scaler, pruned_in, drop_out_names=MASK_COLS)
    del splits["TRAIN"]
    print(f"[exp1] TRAIN X={Xtr.shape}", flush=True)
    Xva, yva, _, mva = build_samples(splits["VAL"], scaler, pruned_in, drop_out_names=MASK_COLS)
    del splits["VAL"]
    print(f"[exp1] VAL X={Xva.shape}", flush=True)
    wtr = sample_weights(ytr)
    m, fit_s = fit_hgb(Xtr, ytr, wtr, 150)
    sc = batched_predict(m, Xva)
    dv = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                       "realizable_ret": yva.astype(np.float64)})
    vic, vir, vnd = cross_section_ic(dv)
    print(f"[exp1] VAL IC={vic:.4f} IR={vir:.4f} days={vnd} (champ VAL 0.0610, pass band +-0.003)",
          flush=True)
    del sc, dv
    Xf = np.concatenate([Xtr, Xva], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr, ytr, Xva, yva
    wf = sample_weights(yf)
    final, final_s = fit_hgb(Xf, yf, wf, 150)
    del Xf, yf, wf
    Xte, yte, yote, mte = build_samples(splits["TEST"], scaler, pruned_in, drop_out_names=MASK_COLS)
    del splits["TEST"]
    ste = batched_predict(final, Xte)
    del Xte
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": ste.astype(np.float64),
                        "realizable_ret": yte.astype(np.float64),
                        "future_ret_5d": yote.astype(np.float64)})
    tic, tir, tnd = cross_section_ic(dte)
    print(f"[exp1] TEST IC={tic:.4f} IR={tir:.4f} days={tnd} (champ TEST 0.0764)", flush=True)
    pred = dte[["code", "kline_time", "score", "realizable_ret", "future_ret_5d"]].copy()
    pred.to_parquet(PRED_OUT, index=False)
    feat_names = [c for c in pruned_in if c in scaler.feature_cols]  # 34 in-transformed
    feat_names = [c for c in list(scaler.feature_cols_out) if c not in set(MASK_COLS) and c not in set(G8_COLS)]
    metrics = {"exp": "prune_masks_G8", "dims": int(dte.shape[0] and (len(feat_names) + len(HAND_COLS))),
               "n_features": len(feat_names) + len(HAND_COLS),
               "feature_names": feat_names + HAND_COLS,
               "dropped": {"masks": MASK_COLS, "G8": G8_COLS},
               "dim_note": "49-11=38 (task text says 43 which is masks-only; full intent run)",
               "max_iter": 150, "val_ic": vic, "val_ir": vir, "val_n_days": vnd,
               "champ_val_ic": 0.06104204735470689, "val_bias": vic - 0.06104204735470689,
               "pass_zero_loss": bool(abs(vic - 0.06104204735470689) <= 0.003),
               "test_ic": tic, "test_ir": tir, "test_n_days": tnd,
               "champ_test_ic": 0.07643673104838995,
               "fit_secs": fit_s, "fit_final_secs": final_s,
               "total_secs": time.time() - t0}
    with open(METRICS_OUT, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[exp1] saved {METRICS_OUT} {PRED_OUT}", flush=True)


if __name__ == "__main__":
    main()
