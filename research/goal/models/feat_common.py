"""Shared helpers for opt_feat experiments (prune / G6G7 / seq-stats).

Constraints honored:
- scaler.pkl load-only, never refit (vendor_scaler).
- New features: TRAIN-only stats or cross-sectional rank (no fitting on VAL/TEST),
  or raw past-only (<=t) values.
- Labels/windows identical to models/train_realizable.py (realizable literal).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from prep import SEQ_LEN, split_frame  # noqa: F401 -- 重导出：exp_* 经此取 split_frame
from vendor_scaler import PerCodeGroupedScaler

DEFAULT_SCALER = ROOT / "artifacts" / "scaler.pkl"
DEFAULT_FULL = ROOT / "data" / "train_data.parquet"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
PRED_BATCH = 200_000

G8_COLS = ["gross_margin", "net_margin", "roe", "roa", "debt_to_equity"]
G6_COLS = ["pe", "pb", "pcf", "ps"]
G7_COLS = ["revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq"]
MASK_COLS = ["margin_balance_ratio_mask", "margin_buy_ratio_mask",
             "margin_net_buy_ratio_mask", "margin_balance_chg_5d_mask",
             "short_balance_ratio_mask", "short_sell_vol_ratio_mask"]


def load_scaler():
    sc = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    return sc


def base_hand(close: np.ndarray):
    n = len(close)
    r1 = np.full(n, np.nan)
    prev, cur = close[:-1], close[1:]
    valid = np.isfinite(prev) & np.isfinite(cur) & (prev != 0)
    r1[1:][valid] = cur[valid] / prev[valid] - 1.0
    f = np.where(np.isnan(r1), 0.0, r1)
    S = np.concatenate([[0.0], np.cumsum(f)])
    S2 = np.concatenate([[0.0], np.cumsum(f * f)])
    idx = np.arange(n)
    mean_5 = (S[idx + 1] - S[np.maximum(idx + 1 - 5, 0)]) / np.minimum(idx + 1, 5)
    mean_20 = (S[idx + 1] - S[np.maximum(idx + 1 - 20, 0)]) / np.minimum(idx + 1, 20)
    e2_20 = (S2[idx + 1] - S2[np.maximum(idx + 1 - 20, 0)]) / np.minimum(idx + 1, 20)
    vol_20 = np.sqrt(np.maximum(e2_20 - mean_20 ** 2, 0.0))
    r20 = np.zeros(n)
    if n >= 20:
        c0, c1 = close[:-19], close[19:]
        ok = np.isfinite(c0) & np.isfinite(c1) & (c0 != 0)
        r20[19:][ok] = c1[ok] / c0[ok] - 1.0
    r20[:19] = 0.0
    ret_20 = np.where(np.isnan(r20), 0.0, r20)
    return mean_5, mean_20, vol_20, ret_20


def build_samples(df_split, scaler, feature_cols, extra_cols=None, drop_out_names=None):
    """Generic builder mirroring train_realizable.build_split_samples.

    extra_cols: already-present columns in df_split (past-only or rank) taken at tt.
    drop_out_names: scaler output names to drop (e.g. masks).
    Returns X, y_lit, y_old, meta(code,kline_time).
    """
    extra_cols = extra_cols or []
    Xs, yns, yos, codes, times = [], [], [], [], []
    out_names_full = list(feature_cols) + list(scaler.mask_cols)
    if drop_out_names:
        keep_idx = np.array([i for i, nm in enumerate(out_names_full) if nm not in set(drop_out_names)],
                            dtype=np.int64)
    else:
        keep_idx = None
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        n = len(grp)
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        op = grp["open"].values.astype(np.float64) if "open" in grp.columns else np.full(n, np.nan)
        tvals = grp["kline_time"].values
        feat = grp[feature_cols].values.astype(np.float64)
        trans = scaler.transform_code(str(code), feat, feature_cols, close)
        if keep_idx is not None:
            trans = trans[:, keep_idx]
        mean_5, mean_20, vol_20, ret_20 = base_hand(close)
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
        okm = (m & (win_bad == 0)
               & np.isfinite(o1) & np.isfinite(o6) & (o1 != 0)
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
        parts = [trans[tt].astype(np.float32), hand]
        if extra_cols:
            ex = grp[extra_cols].values.astype(np.float64)[tt]
            ex = np.where(np.isnan(ex) | np.isinf(ex), 0.0, ex).astype(np.float32)
            parts.append(ex)
        Xc = np.concatenate(parts, axis=1)
        Xs.append(Xc)
        yns.append(y_new.astype(np.float32))
        yos.append(y_old.astype(np.float32))
        codes.extend([str(code)] * len(tt))
        times.extend(tvals[tt])
    if not Xs:
        d = (len(feature_cols) - (len(drop_out_names) if drop_out_names else 0)
             + len(HAND_COLS) + len(extra_cols))
        return (np.zeros((0, d), dtype=np.float32), np.zeros((0,), dtype=np.float32),
                np.zeros((0,), dtype=np.float32),
                pd.DataFrame({"code": [], "kline_time": []}))
    X = np.concatenate(Xs, axis=0)
    return (X, np.concatenate(yns, axis=0), np.concatenate(yos, axis=0),
            pd.DataFrame({"code": codes, "kline_time": pd.to_datetime(times)}))


def sample_weights(y):
    ay = np.abs(y.astype(np.float64))
    try:
        bins = pd.qcut(ay, 10, labels=False, duplicates="drop")
    except Exception:  # noqa: BLE001 -- qcut 退化即回退均匀权重
        return np.ones(len(y), dtype=np.float64)
    bins = np.asarray(bins)
    mask = ~pd.isna(bins)
    w = np.ones(len(y), dtype=np.float64)
    if mask.any():
        b = bins[mask].astype(int)
        freq = np.bincount(b, minlength=int(b.max()) + 1).astype(np.float64)
        freq[freq == 0] = 1.0
        w[mask] = 1.0 / freq[b]
        w = w / w.mean()
    return w


def cross_section_ic(d, score_col="score", ret_col="realizable_ret", min_rows=5):
    rhos = []
    for _dt, g in d.groupby("kline_time", sort=True):
        if len(g) < min_rows:
            continue
        if g[score_col].std() == 0 or g[ret_col].std() == 0:
            continue
        rho = g[score_col].rank().corr(g[ret_col].rank())
        if np.isfinite(rho):
            rhos.append(float(rho))
    if not rhos:
        return 0.0, 0.0, 0
    a = np.array(rhos)
    ir = float(a.mean() / a.std(ddof=1)) if len(a) > 1 and a.std(ddof=1) > 0 else 0.0
    return float(a.mean()), ir, len(a)


def fit_hgb(X, y, w, max_iter=150, max_leaf_nodes=63):
    from sklearn.ensemble import HistGradientBoostingRegressor

    m = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=max_iter, max_leaf_nodes=max_leaf_nodes,
        early_stopping=cast(Any, True), validation_fraction=0.1, random_state=42)
    t0 = time.time()
    m.fit(X, y, sample_weight=w)
    return m, time.time() - t0


def batched_predict(model, X, batch=PRED_BATCH):
    out = np.empty(len(X), dtype=np.float64)
    for s in range(0, len(X), batch):
        out[s:s + batch] = model.predict(X[s:s + batch])
    return out


def add_cs_rank(df_split, cols):
    """Per-day cross-sectional rank in [0,1], NaN->0.5. Same-day data only: no fit, no leak."""
    df_split = df_split.copy()
    for c in cols:
        r = df_split.groupby("kline_time")[c].rank(pct=True)
        df_split[c + "_rank"] = r.fillna(0.5).astype(np.float64).values
    return df_split
