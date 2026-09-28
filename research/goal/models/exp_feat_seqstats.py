"""Exp3: cheap past-only sequence stats for HGB (<=t only).

Candidates (11): mom5/mom10/mom60, volratio_5_20, dist_high20, dist_low20,
range_pos20, vol_chg_20, divergence(ret20 - vol_chg_20), gap_mean5, gap_mean20.
Overnight gap at day i = open[i]/close[i-1]-1 (i>=1); means over trailing windows
ending at t (uses open[t], known at close[t] signal). No scaler refit: raw
past-only values, NaN->0.

Protocol: build base 49 + all 11 once on TRAIN/VAL; single-add-single-test
(TRAIN fit max_iter=150 -> VAL IC each); keep improvers vs base VAL IC;
refit TRAIN+VAL with kept set -> TEST report.
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
    HORIZON_CLOSE,
    HORIZON_OPEN,
    base_hand,
    batched_predict,
    cross_section_ic,
    fit_hgb,
    load_scaler,
    sample_weights,
    split_frame,
)
from prep import SEQ_LEN

sys.path.insert(0, str(ROOT / "data"))

OUT_DIR = ROOT / "artifacts" / "opt_feat"
METRICS_OUT = OUT_DIR / "metrics_exp3_seq.json"
PRED_OUT = OUT_DIR / "pred_exp3_seq.parquet"

SEQ_NAMES = ["mom5", "mom10", "mom60", "volratio_5_20", "dist_high20", "dist_low20",
             "range_pos20", "vol_chg_20", "divergence", "gap_mean5", "gap_mean20"]


def seq_features(close, high, low, op, vol):
    n = len(close)
    out = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        def ret(k):
            r = np.full(n, np.nan)
            if n > k:
                c0, c1 = close[:-k], close[k:]
                ok = np.isfinite(c0) & np.isfinite(c1) & (c0 != 0)
                r[k:][ok] = c1[ok] / c0[ok] - 1.0
            return r
        out["mom5"], out["mom10"], out["mom60"] = ret(5), ret(10), ret(60)
        # rolling vol of 1d returns
        r1 = np.full(n, np.nan)
        pv, cu = close[:-1], close[1:]
        vv = np.isfinite(pv) & np.isfinite(cu) & (pv != 0)
        r1[1:][vv] = cu[vv] / pv[vv] - 1.0
        f = np.where(np.isnan(r1), 0.0, r1)
        S = np.concatenate([[0.0], np.cumsum(f)])
        S2 = np.concatenate([[0.0], np.cumsum(f * f)])
        idx = np.arange(n)

        def roll_sd(w):
            m = (S[idx + 1] - S[np.maximum(idx + 1 - w, 0)]) / np.minimum(idx + 1, w)
            e2 = (S2[idx + 1] - S2[np.maximum(idx + 1 - w, 0)]) / np.minimum(idx + 1, w)
            return np.sqrt(np.maximum(e2 - m ** 2, 0.0))
        v5, v20 = roll_sd(5), roll_sd(20)
        out["volratio_5_20"] = np.where(v20 > 1e-12, v5 / v20, 0.0)
        # high/low distances over trailing 20 (<=t)
        hh = pd.Series(high).rolling(20, min_periods=1).max().to_numpy(dtype=np.float64)
        ll = pd.Series(low).rolling(20, min_periods=1).min().to_numpy(dtype=np.float64)
        out["dist_high20"] = np.where(np.isfinite(hh) & (hh != 0), close / hh - 1.0, 0.0)
        out["dist_low20"] = np.where(np.isfinite(ll) & (ll != 0), close / ll - 1.0, 0.0)
        rng = hh - ll
        out["range_pos20"] = np.where(np.isfinite(rng) & (rng > 1e-12),
                                      (close - ll) / rng, 0.5)
        # volume change: mean20 / mean60 - 1
        V = np.where(np.isfinite(vol), vol, 0.0)
        Vc = np.concatenate([[0.0], np.cumsum(V)])
        m20 = (Vc[idx + 1] - Vc[np.maximum(idx + 1 - 20, 0)]) / np.minimum(idx + 1, 20)
        m60 = (Vc[idx + 1] - Vc[np.maximum(idx + 1 - 60, 0)]) / np.minimum(idx + 1, 60)
        out["vol_chg_20"] = np.where(m60 > 1e-12, m20 / m60 - 1.0, 0.0)
        out["divergence"] = np.where(np.isfinite(out["mom60"]) | True, 0.0, 0.0)  # placeholder
        r20 = ret(20)
        out["divergence"] = np.where(np.isfinite(r20), r20 - out["vol_chg_20"], 0.0 - out["vol_chg_20"])
        # overnight gaps: open[i]/close[i-1]-1
        gap = np.full(n, np.nan)
        if n > 1:
            o, pc = op[1:], close[:-1]
            ok = np.isfinite(o) & np.isfinite(pc) & (pc != 0)
            gap[1:][ok] = o[ok] / pc[ok] - 1.0
        g = pd.Series(np.where(np.isnan(gap), 0.0, gap))
        out["gap_mean5"] = np.asarray(g.rolling(5, min_periods=1).mean(), dtype=np.float64)
        out["gap_mean20"] = np.asarray(g.rolling(20, min_periods=1).mean(), dtype=np.float64)
    for k, v in out.items():
        out[k] = np.where(np.isnan(v) | np.isinf(v), 0.0, v).astype(np.float32)
    return np.stack([out[k] for k in SEQ_NAMES], axis=1)


def build_with_seq(df_split, scaler, feature_cols):
    Xs, yns, yos, codes, times = [], [], [], [], []
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        n = len(grp)
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        op = grp["open"].values.astype(np.float64)
        high = grp["high"].values.astype(np.float64) if "high" in grp.columns else close.copy()
        low = grp["low"].values.astype(np.float64) if "low" in grp.columns else close.copy()
        vol = grp["volume"].values.astype(np.float64) if "volume" in grp.columns else np.zeros(n)
        tvals = grp["kline_time"].values
        feat = grp[feature_cols].values.astype(np.float64)
        trans = scaler.transform_code(str(code), feat, feature_cols, close)
        mean_5, mean_20, vol_20, ret_20 = base_hand(close)
        seq = seq_features(close, high, low, op, vol)
        t = np.arange(n)
        H = HORIZON_OPEN
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        win_bad = np.full(n, 1, dtype=np.int64)
        m = (t >= SEQ_LEN - 1) & (t + H < n)
        a, b = t[m] - SEQ_LEN + 1, t[m] + H
        win_bad[m] = cs[b + 1] - cs[a]
        o1 = np.full(n, np.nan)
        o6 = np.full(n, np.nan)
        o1[m] = op[t[m] + 1]
        o6[m] = op[t[m] + H]
        c_t = close[t]
        c_5 = np.full(n, np.nan)
        c_5[m] = close[t[m] + HORIZON_CLOSE]
        okm = (m & (win_bad == 0) & np.isfinite(o1) & np.isfinite(o6) & (o1 != 0)
               & np.isfinite(c_t) & np.isfinite(c_5) & (c_t != 0))
        if not okm.any():
            continue
        tt = t[okm]
        y_new = o1[okm] / o6[okm] - 1.0
        y_old = c_5[okm] / c_t[okm] - 1.0
        fin = np.isfinite(y_new) & np.isfinite(y_old)
        if not fin.any():
            continue
        tt = tt[fin]
        y_new, y_old = y_new[fin], y_old[fin]
        hand = np.stack([mean_5[tt], mean_20[tt], vol_20[tt], ret_20[tt]], axis=1).astype(np.float32)
        Xc = np.concatenate([trans[tt].astype(np.float32), hand, seq[tt]], axis=1)
        Xs.append(Xc)
        yns.append(y_new.astype(np.float32))
        yos.append(y_old.astype(np.float32))
        codes.extend([str(code)] * len(tt))
        times.extend(tvals[tt])
    X = np.concatenate(Xs, axis=0) if Xs else np.zeros((0, 49 + len(SEQ_NAMES)), dtype=np.float32)
    return (X, np.concatenate(yns, axis=0) if yns else np.zeros((0,), dtype=np.float32),
            np.concatenate(yos, axis=0) if yos else np.zeros((0,), dtype=np.float32),
            pd.DataFrame({"code": codes, "kline_time": pd.to_datetime(times)}))


def val_ic_for(Xtr_b, cols_idx, ytr, Xva_b, yva, mva):
    w = sample_weights(ytr)
    m, _ = fit_hgb(Xtr_b[:, cols_idx], ytr, w, 150)
    sc = batched_predict(m, Xva_b[:, cols_idx])
    dv = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                       "realizable_ret": yva.astype(np.float64)})
    ic, ir, nd = cross_section_ic(dv)
    del m, sc, dv
    return ic, ir, nd


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scaler = load_scaler()
    feature_cols = list(scaler.feature_cols)
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "high", "low",
                                   "volume", "is_trading"] + feature_cols))
    df = pq.read_table(str(DEFAULT_FULL), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    splits = split_frame(df)
    del df
    Xtr_b, ytr, _, _ = build_with_seq(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[exp3] TRAIN X={Xtr_b.shape}", flush=True)
    Xva_b, yva, _, mva = build_with_seq(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[exp3] VAL X={Xva_b.shape}", flush=True)
    base_idx = list(range(49))
    bic, bir, _bnd = val_ic_for(Xtr_b, base_idx, ytr, Xva_b, yva, mva)
    print(f"[exp3] base VAL IC={bic:.4f}", flush=True)
    single = {}
    for j, nm in enumerate(SEQ_NAMES):
        ic, ir, _nd = val_ic_for(Xtr_b, base_idx + [49 + j], ytr, Xva_b, yva, mva)
        single[nm] = {"val_ic": ic, "val_ir": ir, "gain": ic - bic}
        print(f"[exp3] +{nm}: VAL IC={ic:.4f} (gain {ic - bic:+.4f})", flush=True)
    kept = [nm for nm in SEQ_NAMES if single[nm]["gain"] > 0]
    print(f"[exp3] kept={kept}", flush=True)
    keep_idx = base_idx + [49 + SEQ_NAMES.index(nm) for nm in kept]
    Xf = np.concatenate([Xtr_b[:, keep_idx], Xva_b[:, keep_idx]], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr_b, ytr, Xva_b, yva
    final, final_s = fit_hgb(Xf, yf, sample_weights(yf), 150)
    del Xf, yf
    Xte, yte, yote, mte = build_with_seq(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    ste = batched_predict(final, Xte[:, keep_idx])
    del Xte
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": ste.astype(np.float64),
                        "realizable_ret": yte.astype(np.float64),
                        "future_ret_5d": yote.astype(np.float64)})
    tic, tir, tnd = cross_section_ic(dte)
    print(f"[exp3] TEST IC={tic:.4f} (champ 0.0764)", flush=True)
    dte[["code", "kline_time", "score", "realizable_ret", "future_ret_5d"]].to_parquet(
        PRED_OUT, index=False)
    metrics = {"exp": "cheap_seq_stats", "candidates": SEQ_NAMES, "single_add": single,
               "base_val_ic": bic, "base_val_ir": bir,
               "kept": kept, "n_features": len(keep_idx),
               "feature_names": "v2_49 + kept_seq",
               "max_iter": 150, "test_ic": tic, "test_ir": tir, "test_n_days": tnd,
               "champ_test_ic": 0.07643673104838995,
               "fit_final_secs": final_s, "total_secs": time.time() - t0}
    with open(METRICS_OUT, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[exp3] saved {METRICS_OUT}", flush=True)


if __name__ == "__main__":
    main()
