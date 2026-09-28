"""滚动归一化对照重训：v2 同配置，特征换成 t-300 滚动版。

复用 models/train_realizable.py 逻辑（窗口/标签/权重/HGB 超参逐字一致），唯一差别：
  - 45 维特征来自 artifacts/opt_roll/feat_roll.parquet（data/rolling_norm.py 生成，
    与 frozen 同维度同列序），不再调用 scaler.transform_code；
  - 窗口末日 t 若 _roll_valid 为 False（滚动历史不足 60 天）则该窗口弃用并计数；
  - max_iter 固定 150（任务指定；v2 在 VAL 上 150>300，故与 v2 选中档一致）；
  - 流程仍镜像 v2：TRAIN 拟合 -> VAL 上 IC 验证 -> TRAIN+VAL 合并重训最终版；
  - score 取负（-score），方向与可吃收益 R_true=open[t+6]/open[t+1]-1 一致；
    metrics_roll.json 的 headline VAL/TEST IC 均为可执行方向（score vs R_true），
    与冠军 0.0764（字面 IC，经取负后数值等同可执行 IC）直接可比；同时保留字面口径对照。

产物：artifacts/opt_roll/model_roll.pkl / pred_test_roll.parquet / metrics_roll.json
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
from prep import SEQ_LEN, split_frame

OPT_ROLL = ROOT / "artifacts" / "opt_roll"
FEAT_ROLL = OPT_ROLL / "feat_roll.parquet"
DEFAULT_PRED = OPT_ROLL / "pred_test_roll.parquet"
DEFAULT_METRICS = OPT_ROLL / "metrics_roll.json"
DEFAULT_MODEL = OPT_ROLL / "model_roll.pkl"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
PRED_BATCH = 200_000
MAX_ITER = 150


def build_split_samples_roll(df_split: pd.DataFrame, feat_cols45: list
                             ) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame, dict]:
    """返回 (X [M,49], y_lit, y_old, meta, info)。X=45滚动+4手工；无效 t 弃用计数。"""
    Xs, yns, yos, codes, times = [], [], [], [], []
    n_drop_invalid = 0
    n_win_total = 0
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        n = len(grp)
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        op = grp["open"].values.astype(np.float64)
        tvals = grp["kline_time"].values
        trans = grp[feat_cols45].values.astype(np.float32)
        rvalid = grp["_roll_valid"].values.astype(bool)
        # 4 手工统计（照抄 train_realizable.py，只用<=t）
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
        r20 = np.zeros(n)
        if n >= 20:
            c0 = close[:-19]
            c1 = close[19:]
            ok = np.isfinite(c0) & np.isfinite(c1) & (c0 != 0)
            r20[19:][ok] = c1[ok] / c0[ok] - 1.0
        r20[:19] = 0.0
        ret_20 = np.where(np.isnan(r20), 0.0, r20)
        # 窗口（realizable 口径：66 行 [t-59..t+6] 同组 is_trading 全真）
        H = HORIZON_OPEN
        t = np.arange(n)
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        win_bad = np.full(n, 1, dtype=np.int64)
        m = (t >= SEQ_LEN - 1) & (t + H < n)
        a = t[m] - SEQ_LEN + 1
        b = t[m] + H
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
        n_win_total += int(okm.sum())
        okm = okm & rvalid  # 滚动无效的末日 t 弃用
        n_drop_invalid += int((m & (win_bad == 0) & ~rvalid).sum())
        if not okm.any():
            continue
        tt = t[okm]
        y_new = o1[okm] / o6[okm] - 1.0  # 字面公式（与 v2 一致）
        y_old = c_5[okm] / c_t[okm] - 1.0
        fin = np.isfinite(y_new) & np.isfinite(y_old)
        if not fin.any():
            continue
        tt = tt[fin]
        y_new = y_new[fin]
        y_old = y_old[fin]
        hand = np.stack([mean_5[tt], mean_20[tt], vol_20[tt], ret_20[tt]], axis=1).astype(np.float32)
        Xc = np.concatenate([trans[tt].astype(np.float32), hand], axis=1)
        # 防御：滚动无效已剔除；残差 nan/inf 置 0 并计数
        badv = ~np.isfinite(Xc)
        if badv.any():
            Xc[badv] = 0.0
        Xs.append(Xc)
        yns.append(y_new.astype(np.float32))
        yos.append(y_old.astype(np.float32))
        codes.extend([str(code)] * len(tt))
        times.extend(tvals[tt])
    info = {"n_windows_gross": int(n_win_total), "n_drop_roll_invalid": int(n_drop_invalid)}
    if not Xs:
        d = len(feat_cols45) + len(HAND_COLS)
        return (np.zeros((0, d), dtype=np.float32), np.zeros((0,), dtype=np.float32),
                np.zeros((0,), dtype=np.float32),
                pd.DataFrame({"code": [], "kline_time": []}), info)
    X = np.concatenate(Xs, axis=0)
    yn = np.concatenate(yns, axis=0)
    yo = np.concatenate(yos, axis=0)
    meta = pd.DataFrame({"code": codes, "kline_time": pd.to_datetime(times)})
    return X, yn, yo, meta, info


def sample_weights(y: np.ndarray) -> np.ndarray:
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


def cross_section_ic(d: pd.DataFrame, score_col="score", ret_col="R_true",
                     min_rows=5) -> tuple[float, float, int]:
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
        return 0.0, 0.0, 0
    a = np.array(rhos)
    ir = float(a.mean() / a.std(ddof=1)) if len(a) > 1 and a.std(ddof=1) > 0 else 0.0
    return float(a.mean()), ir, len(a)


def batched_predict(model, X: np.ndarray, batch=PRED_BATCH) -> np.ndarray:
    out = np.empty(len(X), dtype=np.float64)
    for s in range(0, len(X), batch):
        out[s:s + batch] = model.predict(X[s:s + batch])
    return out


def fit_hgb(X, y, w, max_iter: int, max_leaf_nodes: int = 63):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=max_iter, max_leaf_nodes=max_leaf_nodes,
        early_stopping=cast(Any, True), validation_fraction=0.1, random_state=42)
    t0 = time.time()
    m.fit(X, y, sample_weight=w)
    return m, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--pred-out", default=str(DEFAULT_PRED))
    ap.add_argument("--metrics-out", default=str(DEFAULT_METRICS))
    ap.add_argument("--model-out", default=str(DEFAULT_MODEL))
    args = ap.parse_args()
    t_start = time.time()

    import pickle

    import pyarrow.parquet as pq

    with open(ROOT / "artifacts" / "scaler.pkl", "rb") as _f:
        scaler = pickle.load(_f)
    feat_order = list(scaler["feature_cols_out"])  # 45 列，与 feat_roll 同序
    feature_cols = list(scaler["feature_cols"])
    print(f"[roll-train] feats 45-roll + 4 hand = 49, max_iter={MAX_ITER}")

    if args.smoke:
        # smoke：sample_100 上验证管线（需 feat_roll 由 sample 生成；此处走 verify 路径重算小矩阵）
        sys.path.insert(0, str(ROOT / "data"))
        from rolling_norm import compute_rolling_features
        use = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
        df = pq.read_table(str(ROOT / "data" / "sample_100.parquet"), columns=use).to_pandas()
        df["kline_time"] = pd.to_datetime(df["kline_time"])
        feat, _ = compute_rolling_features(df, feature_cols)
        base = df[["code", "kline_time", "close", "open", "is_trading"]].reset_index(drop=True)
        f45 = feat[feat_order + ["_roll_valid"]].reset_index(drop=True)
        # rolling 'open' 与 raw 'open' 同名冲突 -> rolling 侧改名，特征矩阵用改名后列
        f45 = cast(pd.DataFrame, f45).rename(columns={"open": "open_r"})
        full = pd.concat([base, f45], axis=1)
        feat_mat_cols = ["open_r" if c == "open" else c for c in feat_order]
    else:
        if not FEAT_ROLL.exists():
            raise SystemExit(f"BLOCKED: {FEAT_ROLL} 不存在，先跑 data/rolling_norm.py --full")
        feat = pq.read_table(str(FEAT_ROLL)).to_pandas()
        raw = pq.read_table(str(ROOT / "data" / "train_data.parquet"),
                            columns=["code", "kline_time", "close", "open", "is_trading"]).to_pandas()
        raw["kline_time"] = pd.to_datetime(raw["kline_time"])
        feat["kline_time"] = pd.to_datetime(feat["kline_time"])
        full = raw.merge(feat, on=["code", "kline_time"], how="inner", validate="one_to_one",
                         suffixes=("", "_r"))
        feat_mat_cols = ["open_r" if c == "open" else c for c in feat_order]
        assert "open_r" in full.columns, "merge 后应有 open_r（rolling open）"
        print(f"[roll-train] merge raw {len(raw):,} + feat {len(feat):,} -> {len(full):,}")
        del raw, feat
    print(f"[roll-train] rows={len(full):,} roll_valid_rate={full['_roll_valid'].mean():.4f}")
    splits = split_frame(full)
    del full

    Xtr, ytr, _yor_tr, _mtr, itr = build_split_samples_roll(splits["TRAIN"], feat_mat_cols)
    del splits["TRAIN"]
    print(f"[roll-train] TRAIN windows={len(ytr):,} X={Xtr.shape} drop_invalid={itr}")
    Xva, yva, _yor_va, mva, iva = build_split_samples_roll(splits["VAL"], feat_mat_cols)
    del splits["VAL"]
    print(f"[roll-train] VAL windows={len(yva):,} drop_invalid={iva}")

    wtr = sample_weights(ytr)
    model, fit_secs = fit_hgb(Xtr, ytr, wtr, MAX_ITER)
    sc_va = batched_predict(model, Xva)
    # 可执行方向：score=-pred，R_true=1/(1+lit)-1
    lit_va = yva.astype(np.float64)
    rt_va = 1.0 / (1.0 + lit_va) - 1.0
    dva = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": -sc_va, "R_true": rt_va,
                        "lit": lit_va})
    val_ic, val_ir, val_nd = cross_section_ic(dva, ret_col="R_true")
    val_ic_lit, _, _ = cross_section_ic(
        pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc_va, "R_true": lit_va}),
        ret_col="R_true")
    print(f"[roll-train] VAL IC_exec={val_ic:.4f} IR={val_ir:.4f} days={val_nd} (IC_lit={val_ic_lit:.4f})")
    del sc_va, dva

    Xf = np.concatenate([Xtr, Xva], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr, ytr, Xva, yva
    wf = sample_weights(yf)
    final, final_secs = fit_hgb(Xf, yf, wf, MAX_ITER)
    n_final = len(yf)
    del Xf, yf, wf
    print(f"[roll-train] final refit TRAIN+VAL n={n_final:,} secs={final_secs:.1f}")
    with open(args.model_out, "wb") as f:
        pickle.dump(final, f)

    Xte, yte, yote, mte, ite = build_split_samples_roll(splits["TEST"], feat_mat_cols)
    del splits["TEST"]
    print(f"[roll-train] TEST windows={len(yte):,} drop_invalid={ite}")
    ste_lit = batched_predict(final, Xte)
    del Xte
    lit_te = yte.astype(np.float64)
    rt_te = 1.0 / (1.0 + lit_te) - 1.0
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": (-ste_lit).astype(np.float64),
                        "R_true": rt_te,
                        "realizable_ret": lit_te,
                        "future_ret_5d": yote.astype(np.float64)})
    del mte, yte, yote, ste_lit
    tic, tir, tnd = cross_section_ic(dte, ret_col="R_true")
    tic_lit, _, _ = cross_section_ic(
        pd.DataFrame({"kline_time": dte["kline_time"].values, "score": (-dte["score"].to_numpy(dtype=np.float64)),
                      "R_true": dte["realizable_ret"].values}), ret_col="R_true")
    tic_old, _, _ = cross_section_ic(
        pd.DataFrame({"kline_time": dte["kline_time"].values, "score": dte["score"].values,
                      "R_true": dte["future_ret_5d"].values}), ret_col="R_true")
    print(f"[roll-train] TEST IC_exec={tic:.4f} IR={tir:.4f} days={tnd} "
          f"(IC_lit={tic_lit:.4f} IC_old_contrast={tic_old:.4f})")

    # pred 文件：score 与可吃收益同方向；保留 future_ret_5d 供引擎/纸面 quintile
    parts = []
    for _dt, g in dte.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g["R_true"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
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
    pred = pred.astype({"code": str, "score": float, "R_true": float,
                        "realizable_ret": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred_out = pred[["code", "kline_time", "score", "future_ret_5d", "realizable_ret", "R_true", "q_true"]]
    po = Path(args.pred_out)
    po.parent.mkdir(parents=True, exist_ok=True)
    pred_out.to_parquet(po, index=False)
    print(f"[roll-train] saved {po} rows={len(pred_out):,}")

    metrics = {
        "mode": "full-roll",
        "label": "realizable",
        "label_formula": "open[t+1]/open[t+6]-1 (literal); score stored negated => executable orientation",
        "norm": "rolling t-300 expanding(min_periods=60) per-code; G1 rel+robust±5, G3/G4/macd winsor1/99, G5-rest/G8 passthrough, G9 fill0+mask",
        "selected_max_iter": MAX_ITER,
        "selected_params": {"loss": "squared_error", "max_iter": MAX_ITER,
                            "max_leaf_nodes": 63, "early_stopping": True,
                            "validation_fraction": 0.1, "random_state": 42},
        "val_ic": float(val_ic), "val_ir": float(val_ir), "val_n_days": int(val_nd),
        "val_ic_literal": float(val_ic_lit),
        "test_ic": float(tic), "test_ir": float(tir), "test_n_days": int(tnd),
        "test_ic_literal": float(tic_lit),
        "test_ic_old_contrast": float(tic_old),
        "n_train_windows": int(n_final),
        "n_test_rows": len(pred_out),
        "drop_roll_invalid": {"train": itr, "val": iva, "test": ite},
        "fit_train_secs": float(fit_secs),
        "fit_final_secs": float(final_secs),
        "total_secs": time.time() - t_start,
        "feature_cols_out": feat_order + HAND_COLS,
    }
    mo = Path(args.metrics_out)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[roll-train] saved {mo} total={metrics['total_secs']:.1f}s")


if __name__ == "__main__":
    main()
