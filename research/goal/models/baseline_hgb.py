"""Baseline: HistGradientBoostingRegressor on window-end features.

窗口定义(与 data/prep.py 契约一致, 复用其函数不重造切分/投影逻辑):
- SPLITS: TRAIN[2013,2021] / VAL[2022,2023] / TEST[2024,2025], split_frame 先切分, 窗口绝不跨 split/跨股.
- 标签: future_ret_5d[t] = close[t+5]/close[t]-1.
- 窗口末日 t 要求: 60 窗行[t-59..t] + 5 horizon 行[t+1..t+5] 共 65 行同(split,code)组
  且 is_trading 全真, close[t]/close[t+5] 有效且 close[t]!=0.
  (枚举条件与 prep.count_windows_split 逐字等价, 此处向量化实现以支撑全量速度;
   标签公式与 prep.add_future_ret_within_split 等价.)

特征 (49 维 = 45 + 4):
- 45 维 = scaler.pkl (TRAIN-only 拟合, 此处只 load 复用, 绝不重 fit)
  transform_code 逐股输出, 取窗口末日 t 当行.
- 4 手工统计口径 (代码内注明, 均基于原始 close 序列, 缺失填 0):
    r1[i] = close[i]/close[i-1]-1 (i>=1, 分母无效记 NaN->填0)
    mean_5[t]  = mean(r1[t-4..t])
    mean_20[t] = mean(r1[t-19..t])
    vol_20[t]  = std(r1[t-19..t], ddof=0)
    ret_20[t]  = close[t]/close[t-19]-1
  (t>=59 的有效窗口恒有完整 20 日回看, 无需截断修正.)

样本权重: |y| 分 10 档 (pd.qcut, duplicates='drop' 兜底), 权重 = 1/档频,
再除以权重均值归一化 (均值=1, 总和=N), 抑制极端收益样本主导.

流程:
1. TRAIN 上分别拟合 max_iter=300 / 150 (其余相同), VAL 上以截面 IC 选其一.
2. TRAIN+VAL 合并重训最终版 (early_stopping 保留).
3. TEST 输出 pred_test.parquet + metrics.json; predict 分块防 OOM.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from prep import SEQ_LEN, read_projected, split_frame
from vendor_scaler import PerCodeGroupedScaler

DEFAULT_SCALER = ROOT / "artifacts" / "scaler.pkl"
DEFAULT_SAMPLE = ROOT / "data" / "sample_100.parquet"
DEFAULT_FULL = ROOT / "data" / "train_data.parquet"
DEFAULT_PRED = ROOT / "artifacts" / "baseline" / "pred_test.parquet"
DEFAULT_METRICS = ROOT / "artifacts" / "baseline" / "metrics.json"

HORIZON = 5
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
CANDIDATE_MAX_ITERS = [300, 150]
FIT_TIMEOUT_S = 3600  # 单次 fit 超 60min 则降到 150
PRED_BATCH = 200_000


def build_split_samples(df_split: pd.DataFrame, scaler: PerCodeGroupedScaler,
                        feature_cols: list) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """在单个 split 内按 code 枚举窗口, 返回 (X float32 [M,49], y float32 [M], meta)."""
    Xs, ys, codes, times = [], [], [], []
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        n = len(grp)
        if n < SEQ_LEN + HORIZON:
            continue
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        tvals = grp["kline_time"].values
        feat = grp[feature_cols].values.astype(np.float64)
        trans = scaler.transform_code(str(code), feat, feature_cols, close)  # [N,45] float32
        # --- 4 手工统计 (原始 close 口径, 见模块 docstring) ---
        r1 = np.full(n, np.nan)
        prev = close[:-1]
        cur = close[1:]
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
        ret_20 = np.full(n, np.nan)
        c0 = close[:-19] if n >= 20 else np.array([])
        c1 = close[19:]
        ok = np.isfinite(c0) & np.isfinite(c1) & (c0 != 0)
        r20 = np.zeros(n)
        r20[19:][ok] = c1[ok] / c0[ok] - 1.0
        r20[:19] = 0.0
        ret_20 = np.where(np.isnan(r20), 0.0, r20)
        # --- 窗口有效性 (与 prep.count_windows_split 等价) ---
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        t = np.arange(n)
        win_bad = np.full(n, 1, dtype=np.int64)
        m = (t >= SEQ_LEN - 1) & (t + HORIZON < n)
        a = t[m] - SEQ_LEN + 1
        b = t[m] + HORIZON
        win_bad[m] = cs[b + 1] - cs[a]
        c_t, c_5 = close[t], np.full(n, np.nan)
        c_5[m] = close[t[m] + HORIZON]
        okm = (m & (win_bad == 0) & np.isfinite(c_t) & np.isfinite(c_5)
               & (c_t != 0))
        if not okm.any():
            continue
        tt = t[okm]
        y = c_5[okm] / c_t[okm] - 1.0
        fin = np.isfinite(y)
        if not fin.any():
            continue
        tt = tt[fin]
        y = y[fin]
        hand = np.stack([mean_5[tt], mean_20[tt], vol_20[tt], ret_20[tt]], axis=1).astype(np.float32)
        Xc = np.concatenate([trans[tt].astype(np.float32), hand], axis=1)
        Xs.append(Xc)
        ys.append(y.astype(np.float32))
        codes.extend([str(code)] * len(tt))
        times.extend(tvals[tt])
    if not Xs:
        d = len(feature_cols) + 6 + len(HAND_COLS)
        return (np.zeros((0, d), dtype=np.float32), np.zeros((0,), dtype=np.float32),
                pd.DataFrame({"code": [], "kline_time": []}))
    X = np.concatenate(Xs, axis=0)
    y = np.concatenate(ys, axis=0)
    meta = pd.DataFrame({"code": codes, "kline_time": pd.to_datetime(times)})
    return X, y, meta


def sample_weights(y: np.ndarray) -> np.ndarray:
    """|y| 分 10 档, 权重=1/档频, 除均值归一化."""
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


def cross_section_ic(d: pd.DataFrame, score_col="score", ret_col="future_ret_5d",
                     min_rows=5) -> tuple[float, float, int, list]:
    """逐截面 Spearman(用 rank+pearson 实现, 免 scipy 依赖)均值=IC; IR=均值/标准差(ddof=1)."""
    rhos = []
    for _dt, g in d.groupby("kline_time", sort=True):
        if len(g) < min_rows:
            continue
        if g[score_col].std() == 0 or g[ret_col].std() == 0:
            continue
        # 变量键 getitem 被 stub 宽化：两侧收窄为 Series 后 corr 解析正常。
        s_rank = cast("pd.Series", g[score_col]).rank()
        o_rank = cast("pd.Series", g[ret_col]).rank()
        rho = s_rank.corr(o_rank)
        if np.isfinite(rho):
            rhos.append(float(cast(float, rho)))
    if not rhos:
        return 0.0, 0.0, 0, []
    a = np.array(rhos)
    ir = float(a.mean() / a.std(ddof=1)) if len(a) > 1 and a.std(ddof=1) > 0 else 0.0
    return float(a.mean()), ir, len(a), rhos


def quintile_means(d: pd.DataFrame, score_col="score", ret_col="future_ret_5d") -> dict:
    """按每截面 score 五分位分组的平均真实收益 (分位单调性)."""
    qq = []
    for _dt, g in d.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g[score_col], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
        except Exception:  # noqa: BLE001, S112 -- 退化截面跳过
            continue
        if getattr(q, "cat", None) is not None and len(q.cat.categories) != 5:
            continue
        gg = g.copy()
        gg["_pq"] = np.asarray(q)
        qq.append(gg)
    if not qq:
        return {}
    allq = pd.concat(qq, ignore_index=True)
    return {str(k): float(v) for k, v in cast(Any, allq.groupby("_pq")[ret_col].mean()).items()}


def batched_predict(model, X: np.ndarray, batch=PRED_BATCH) -> np.ndarray:
    out = np.empty(len(X), dtype=np.float64)
    for s in range(0, len(X), batch):
        out[s:s + batch] = model.predict(X[s:s + batch])
    return out


def fit_hgb(X, y, w, max_iter: int):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=max_iter, max_leaf_nodes=63,
        early_stopping=cast(Any, True), validation_fraction=0.1, random_state=42)
    t0 = time.time()
    m.fit(X, y, sample_weight=w)
    return m, time.time() - t0


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="sample_100 全流程 (<10min)")
    ap.add_argument("--full", action="store_true", help="全量 train_data")
    ap.add_argument("--pred-out", default=str(DEFAULT_PRED))
    ap.add_argument("--metrics-out", default=str(DEFAULT_METRICS))
    ap.add_argument("--scaler", default=str(DEFAULT_SCALER),
                    help="scaler.pkl 路径（缺省为全量口径；smoke 请传 [1/5] 产物）")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    mode = "full" if args.full else "smoke"
    parquet = Path(DEFAULT_FULL if args.full else DEFAULT_SAMPLE)
    t_start = time.time()

    scaler = PerCodeGroupedScaler.load(str(args.scaler))
    feature_cols = list(scaler.feature_cols)  # 39 列, 与 scaler 对齐
    feat_out = list(scaler.feature_cols_out)  # 45 列
    print(f"[base] mode={mode} parquet={parquet} feats={len(feature_cols)}->{len(feat_out)}")

    df = read_projected(parquet, feature_cols)
    print(f"[base] read {len(df):,} rows codes={df['code'].nunique()}")
    splits = split_frame(df)
    del df

    # TRAIN / VAL 建窗
    Xtr, ytr, _ = build_split_samples(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[base] TRAIN windows={len(ytr):,} X={Xtr.shape}")
    Xva, yva, mva = build_split_samples(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[base] VAL windows={len(yva):,}")

    wtr = sample_weights(ytr)
    # 两档对照
    cands = {}
    for mi in CANDIDATE_MAX_ITERS:
        m, secs = fit_hgb(Xtr, ytr, wtr, mi)
        sc = batched_predict(m, Xva)
        dv = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                           "future_ret_5d": yva.astype(np.float64)})
        ic, ir, nd, _ = cross_section_ic(dv)
        cands[mi] = {"model": m, "secs": secs, "ic": ic, "ir": ir, "n_days": nd}
        print(f"[cand] max_iter={mi} fit={secs:.1f}s VAL IC={ic:.4f} IR={ir:.4f} days={nd}")
        del sc, dv
    best_mi = max(cands, key=lambda k: cands[k]["ic"])
    print(f"[base] selected max_iter={best_mi} (VAL IC 最高)")
    for mi in CANDIDATE_MAX_ITERS:
        if mi != best_mi:
            del cands[mi]["model"]

    # TRAIN+VAL 合并重训最终版
    Xf = np.concatenate([Xtr, Xva], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr, ytr, Xva, yva
    wf = sample_weights(yf)
    final, final_secs = fit_hgb(Xf, yf, wf, best_mi)
    fallback = False
    if final_secs > FIT_TIMEOUT_S and best_mi != 150:
        print(f"[base] final fit {final_secs:.0f}s > 60min, 降到 max_iter=150 重训")
        del final
        final, final_secs = fit_hgb(Xf, yf, wf, 150)
        best_mi = 150
        fallback = True
    n_final = len(yf)
    del Xf, yf, wf
    print(f"[base] final fit done n={n_final:,} secs={final_secs:.1f} fallback={fallback}")

    # TEST
    Xte, yte, mte = build_split_samples(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    print(f"[base] TEST windows={len(yte):,}")
    ste = batched_predict(final, Xte)
    del Xte
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": ste.astype(np.float64),
                        "future_ret_5d": yte.astype(np.float64)})
    del mte, yte, ste
    # q_true: TEST 内每截面 qcut 真实分位; 不足 5 行/不足 5 档的截面整日舍去 (与 prep.q5 口径一致)
    parts = []
    for _dt, g in dte.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g["future_ret_5d"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
        except Exception:  # noqa: BLE001, S112 -- 退化截面跳过
            continue
        if getattr(q, "cat", None) is not None and len(q.cat.categories) != 5:
            continue
        gg = g.copy()
        gg["q_true"] = np.asarray(q).astype(int)
        parts.append(gg)
    pred = pd.concat(parts, ignore_index=True) if parts else dte.iloc[0:0].copy()
    if len(pred):
        pred["q_true"] = pred["q_true"].astype(int)
    pred = pred.astype({"code": str, "score": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred = cast(pd.DataFrame, pred[["code", "kline_time", "score", "future_ret_5d", "q_true"]])
    po = Path(args.pred_out)
    po.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    print(f"[base] saved {po} rows={len(pred):,}")

    tic, tir, tnd, _ = cross_section_ic(pred)
    qm = quintile_means(pred)
    b = cands[best_mi]
    metrics = {
        "mode": mode,
        "selected_max_iter": best_mi,
        "selected_params": {"loss": "squared_error", "max_iter": best_mi,
                            "max_leaf_nodes": 63, "early_stopping": True,
                            "validation_fraction": 0.1, "random_state": 42},
        "candidates": {str(mi): {"max_iter": mi, "val_ic": c["ic"], "val_ir": c["ir"],
                                 "val_n_days": c["n_days"], "fit_secs": c["secs"]}
                       for mi, c in cands.items()},
        "val_ic": b["ic"], "val_ir": b["ir"], "val_n_days": b["n_days"],
        "test_ic": tic, "test_ir": tir, "test_n_days": tnd, "n_days": tnd,
        "test_quintile_means": qm,
        "n_train_windows": int(n_final),
        "n_test_rows": len(pred),
        "fit_final_secs": final_secs,
        "fit_timeout_fallback": fallback,
        "total_secs": time.time() - t_start,
        "feature_cols_out": feat_out + HAND_COLS,
    }
    mo = Path(args.metrics_out)
    mo.parent.mkdir(parents=True, exist_ok=True)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[base] saved {mo} total={metrics['total_secs']:.1f}s")
    print(json.dumps({k: metrics[k] for k in
                      ["mode", "selected_max_iter", "val_ic", "val_ir", "val_n_days",
                       "test_ic", "test_ir", "test_n_days", "test_quintile_means",
                       "fit_final_secs", "total_secs"]}, indent=2))


if __name__ == "__main__":
    main()
