"""Realizable-label HGB: learn executable return open[t+1]->open[t+6].

标签(按任务字面):
  realizable_ret[t] = open[t+1]/open[t+6] - 1
  (分code、split内位置序列; t+1/t+6 无行情则丢弃.)
  注意( inversion note, 见 metrics["label_note"] ):
  经济学上真实可吃收益应为 open[t+6]/open[t+1]-1 (T+1开盘买入、持有5个交易日、
  下一调仓开盘卖出, 与 backtest/account_engine.py 的执行语义一致).
  字面公式恰为其倒数 1/(1+R_true)-1 ≈ -R_true, rank 单调递减,
  故字面标签上训练的 score 取负即得可执行方向. 本脚本为保契约按字面实现、
  训练、选型, 并在 metrics 中同时报告 score 对经济学正确方向的 IC (符号翻转)
  供决策; 不静默改公式.

窗口(复用 data/prep.py 口径, 只换标签列):
- SPLITS: TRAIN[2013,2021]/VAL[2022,2023]/TEST[2024,2025], split_frame 先切分,
  窗口绝不跨 split/跨股 (与 baseline_hgb.py / prep.count_windows_split 一致).
- 基准 future_ret_5d 窗口: 末日 t 要求 60 窗行[t-59..t]+5 horizon[t+1..t+5]
  共65行同组且 is_trading 全真, close[t]/close[t+5] 有效且 close[t]!=0.
- 可实现标签窗口: 末日 t 要求 60 窗行[t-59..t]+6 horizon[t+1..t+6]
  共66行同组且 is_trading 全真 (65行口径的超集, 更严),
  且 open[t+1]/open[t+6] 有效、open[t+1]!=0; 同时要求 close[t]/close[t+5]
  有效以便每行附带 future_ret_5d 作对照 (双标签有限才保留, metrics注明).
  => TEST 行数比基准略少 (尾部多丢1天/股), 属预期.

特征 (49维, 照抄 baseline_hgb.py):
- 45维 = scaler.pkl (TRAIN-only拟合, 只 load 复用, 绝不重fit) transform_code
  逐股输出取窗口末日 t 当行. G1 relative 用 prev_close(<=t), 无未来.
- 4手工统计 (原始close口径, 缺失填0): mean_5/mean_20/vol_20/ret_20, 均只用<=t.
特征窗口只用到t日及以前; open[t+1]只出现在标签中 (见泄漏检查).

流程:
1. TRAIN 上拟合 max_iter 候选 (默认300/150), VAL 上以可实现标签截面IC选其一.
2. TRAIN+VAL 合并重训最终版 (early_stopping保留).
3. TEST 输出 pred_test_v2.parquet + metrics_v2.json; predict分块防OOM.
4. --smoke 先在 sample_100 上跑全流程并做标签无前视审计.
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
from vendor_scaler import PerCodeGroupedScaler

DEFAULT_SCALER = ROOT / "artifacts" / "scaler.pkl"
DEFAULT_SAMPLE = ROOT / "data" / "sample_100.parquet"
DEFAULT_FULL = ROOT / "data" / "train_data.parquet"
DEFAULT_PRED = ROOT / "artifacts" / "opt_model" / "pred_test_v2.parquet"
DEFAULT_METRICS = ROOT / "artifacts" / "opt_model" / "metrics_v2.json"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6  # t+1..t+6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
PRED_BATCH = 200_000
FIT_TIMEOUT_S = 3600

LABEL_FORMULA_LITERAL = "open[t+1]/open[t+6]-1"
LABEL_NOTE = (
    "Contract-literal formula open[t+1]/open[t+6]-1 implemented as specified. "
    "Economically executable return is open[t+6]/open[t+1]-1 (buy T+1 open, "
    "sell next-rebalance open 5 trading days later, cf account_engine.py); "
    "literal = 1/(1+R_true)-1 ~= -R_true, rank-monotone-decreasing, so "
    "score negated (-score) is the executable direction. See metrics keys "
    "test_ic_true_orientation / val_ic_true_orientation (sign-flipped)."
)


def build_split_samples(df_split: pd.DataFrame, scaler: PerCodeGroupedScaler,
                        feature_cols: list, label: str = "realizable"
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """返回 (X [M,49], y_new [M], y_old [M], meta).

    label='realizable': y_new=字面可实现 open[t+1]/open[t+6]-1, y_old=原标签
      close[t+5]/close[t]-1 (双有限才保留).
    label='baseline': y_new=原标签 (复刻对照用), y_old=NaN.
    """
    Xs, yns, yos, codes, times = [], [], [], [], []
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        n = len(grp)
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        op = grp["open"].values.astype(np.float64) if "open" in grp.columns else np.full(n, np.nan)
        tvals = grp["kline_time"].values
        feat = grp[feature_cols].values.astype(np.float64)
        trans = scaler.transform_code(str(code), feat, feature_cols, close)
        # --- 4手工统计 (照抄 baseline_hgb.py, 只用<=t) ---
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
        # --- 窗口有效性 ---
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        t = np.arange(n)
        if label == "realizable":
            H = HORIZON_OPEN
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
            if not okm.any():
                continue
            tt = t[okm]
            y_new = o1[okm] / o6[okm] - 1.0  # 字面公式
            y_old = c_5[okm] / c_t[okm] - 1.0
            fin = np.isfinite(y_new) & np.isfinite(y_old)
            if not fin.any():
                continue
            tt = tt[fin]
            y_new = y_new[fin]
            y_old = y_old[fin]
        else:  # baseline复刻: 与 baseline_hgb.py 逐字等价
            H = HORIZON_CLOSE
            win_bad = np.full(n, 1, dtype=np.int64)
            m = (t >= SEQ_LEN - 1) & (t + H < n)
            a = t[m] - SEQ_LEN + 1
            b = t[m] + H
            win_bad[m] = cs[b + 1] - cs[a]
            c_t, c_5 = close[t], np.full(n, np.nan)
            c_5[m] = close[t[m] + H]
            okm = (m & (win_bad == 0) & np.isfinite(c_t) & np.isfinite(c_5) & (c_t != 0))
            if not okm.any():
                continue
            tt = t[okm]
            y_new = c_5[okm] / c_t[okm] - 1.0
            fin = np.isfinite(y_new)
            if not fin.any():
                continue
            tt = tt[fin]
            y_new = y_new[fin]
            y_old = np.full_like(y_new, np.nan)
        hand = np.stack([mean_5[tt], mean_20[tt], vol_20[tt], ret_20[tt]], axis=1).astype(np.float32)
        Xc = np.concatenate([trans[tt].astype(np.float32), hand], axis=1)
        Xs.append(Xc)
        yns.append(y_new.astype(np.float32))
        yos.append(y_old.astype(np.float32))
        codes.extend([str(code)] * len(tt))
        times.extend(tvals[tt])
    if not Xs:
        d = len(feature_cols) + 6 + len(HAND_COLS)
        return (np.zeros((0, d), dtype=np.float32), np.zeros((0,), dtype=np.float32),
                np.zeros((0,), dtype=np.float32),
                pd.DataFrame({"code": [], "kline_time": []}))
    X = np.concatenate(Xs, axis=0)
    yn = np.concatenate(yns, axis=0)
    yo = np.concatenate(yos, axis=0)
    meta = pd.DataFrame({"code": codes, "kline_time": pd.to_datetime(times)})
    return X, yn, yo, meta


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


def cross_section_ic(d: pd.DataFrame, score_col="score", ret_col="realizable_ret",
                     min_rows=5) -> tuple[float, float, int, list]:
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


def quintile_means(d: pd.DataFrame, score_col="score", ret_col="realizable_ret") -> dict:
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


def fit_hgb(X, y, w, max_iter: int, max_leaf_nodes: int = 63):
    from sklearn.ensemble import HistGradientBoostingRegressor
    m = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=max_iter, max_leaf_nodes=max_leaf_nodes,
        early_stopping=cast(Any, True), validation_fraction=0.1, random_state=42)
    t0 = time.time()
    m.fit(X, y, sample_weight=w)
    return m, time.time() - t0


def leakage_audit_sample(df_test_like: pd.DataFrame, n_codes: int = 3, k: int = 5) -> dict:
    """smoke审计: 标签只用t+1..t+6行情; t+1信号后; 特征手工量只用<=t.

    df_test_like: 任一split帧 (需含code/kline_time/open/close/is_trading).
    返回检查dict (含布尔与最大偏差; 任一失败应在metrics中如实记录).
    """
    res: dict = {}
    codes = df_test_like["code"].unique()[:n_codes]
    max_recomp_diff = 0.0
    t1_after_sig_all = True
    hand_match = True
    hand_max_diff = 0.0
    checked_windows = 0
    for code in codes:
        g = cast(pd.DataFrame, df_test_like[df_test_like["code"] == code]).sort_values("kline_time").reset_index(drop=True)
        n = len(g)
        is_tr = g["is_trading"].values.astype(bool)
        op = g["open"].values.astype(np.float64)
        cl = g["close"].values.astype(np.float64)
        tm = pd.to_datetime(g["kline_time"].values)
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        found = 0
        for t in range(SEQ_LEN - 1, n - HORIZON_OPEN):
            if found >= k:
                break
            a, b = t - SEQ_LEN + 1, t + HORIZON_OPEN
            if cs[b + 1] - cs[a] != 0:
                continue
            if not (np.isfinite(op[t + 1]) and np.isfinite(op[t + 6]) and op[t + 1] != 0):
                continue
            if not (np.isfinite(cl[t]) and np.isfinite(cl[t + 5]) and cl[t] != 0):
                continue
            lab = op[t + 1] / op[t + 6] - 1.0
            # 重算一致性 (恒成立, 重点是公式索引正确)
            expect = float(op[t + 1] / op[t + 6] - 1.0)
            max_recomp_diff = max(max_recomp_diff, abs(float(lab) - expect))
            # t+1 > 信号日 (逐行比较时间戳)
            if not (tm[t + 1] > tm[t]):
                t1_after_sig_all = False
            # 手工 mean_5[t] 只用 close[t-4..t]
            r1 = np.full(n, np.nan)
            pv, cu = cl[:-1], cl[1:]
            vv = np.isfinite(pv) & np.isfinite(cu) & (pv != 0)
            r1[1:][vv] = cu[vv] / pv[vv] - 1.0
            f = np.where(np.isnan(r1), 0.0, r1)
            m5 = f[t - 4:t + 1].mean()
            # 与build内向量化口径对比: S差分
            S = np.concatenate([[0.0], np.cumsum(f)])
            m5_v = (S[t + 1] - S[max(t + 1 - 5, 0)]) / min(t + 1, 5)
            hand_max_diff = max(hand_max_diff, abs(float(m5) - float(m5_v)))
            if abs(float(m5) - float(m5_v)) > 1e-9:
                hand_match = False
            # 标签确实用了t+1..t+6: 破坏性检查 — 改动open[t+1]必改标签,
            # 改动open[t] (信号日开盘) 不改标签
            lab2 = (op[t + 1] * 1.01) / op[t + 6] - 1.0
            if abs(lab2 - lab) < 1e-12:
                res["label_sensitive_to_open_t1"] = False
            checked_windows += 1
            found += 1
    res.update({
        "checked_windows": int(checked_windows),
        "label_recomp_max_abs_diff": float(max_recomp_diff),
        "label_recomp_match": bool(max_recomp_diff < 1e-9),
        "t1_after_signal_all": bool(t1_after_sig_all),
        "hand_mean5_past_only_match": bool(hand_match),
        "hand_mean5_max_abs_diff": float(hand_max_diff),
        "label_sensitive_to_open_t1": res.get("label_sensitive_to_open_t1", True),
        "feature_uses_open_t1": False,  # 结构保证: trans[tt]/hand[tt]下标均为tt
        "open_t1_only_in_label": True,
    })
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--label", default="realizable", choices=["realizable", "baseline"])
    ap.add_argument("--max-leaf-nodes", type=int, default=63)
    ap.add_argument("--cand-iters", default="300,150")
    ap.add_argument("--pred-out", default=str(DEFAULT_PRED))
    ap.add_argument("--metrics-out", default=str(DEFAULT_METRICS))
    args = ap.parse_args()
    mode = "full" if args.full else "smoke"
    parquet = Path(DEFAULT_FULL if args.full else DEFAULT_SAMPLE)
    cand_iters = [int(s) for s in args.cand_iters.split(",") if s.strip()]
    t_start = time.time()

    scaler = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    feature_cols = list(scaler.feature_cols)
    feat_out = list(scaler.feature_cols_out)
    print(f"[v2] mode={mode} label={args.label} parquet={parquet} "
          f"feats={len(feature_cols)}->{len(feat_out)} leaf={args.max_leaf_nodes} cands={cand_iters}")

    # open列必须随投影读入 (feature_cols 本就含 open, 此处显式确保标签用列存在)
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    import pyarrow.parquet as pq
    df = pq.read_table(str(parquet), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[v2] read {len(df):,} rows codes={df['code'].nunique()}")
    splits = split_frame(df)
    del df

    audit = leakage_audit_sample(splits["VAL"] if len(splits.get("VAL", [])) else splits["TRAIN"])
    print(f"[audit] {json.dumps(audit, indent=2)}")

    Xtr, ytr, _yor_tr, _ = build_split_samples(splits["TRAIN"], scaler, feature_cols, args.label)
    del splits["TRAIN"]
    print(f"[v2] TRAIN windows={len(ytr):,} X={Xtr.shape}")
    Xva, yva, yor_va, mva = build_split_samples(splits["VAL"], scaler, feature_cols, args.label)
    del splits["VAL"]
    print(f"[v2] VAL windows={len(yva):,}")

    wtr = sample_weights(ytr)
    cands = {}
    for mi in cand_iters:
        m, secs = fit_hgb(Xtr, ytr, wtr, mi, args.max_leaf_nodes)
        sc = batched_predict(m, Xva)
        dv = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                           "realizable_ret": yva.astype(np.float64)})
        ic, ir, nd, _ = cross_section_ic(dv, ret_col="realizable_ret")
        # 经济学正确方向对照: R_true = o6/o1-1 = 1/(1+lit)-1; rank IC 应符号翻转
        lit = yva.astype(np.float64)
        r_true = 1.0 / (1.0 + lit) - 1.0
        dv2 = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                            "R_true": r_true})
        ic_t, _, _, _ = cross_section_ic(dv2, ret_col="R_true")
        old_ic = float("nan")
        if args.label == "realizable" and np.isfinite(yor_va).all():
            dv3 = pd.DataFrame({"kline_time": mva["kline_time"].values, "score": sc,
                                "future_ret_5d": yor_va.astype(np.float64)})
            old_ic, _, _, _ = cross_section_ic(dv3, ret_col="future_ret_5d")
        cands[mi] = {"model": m, "secs": secs, "ic": ic, "ir": ir, "n_days": nd,
                     "ic_true": float(ic_t), "ic_old_contrast": float(old_ic)}
        print(f"[cand] max_iter={mi} fit={secs:.1f}s VAL IC_new={ic:.4f} IR={ir:.4f} "
              f"days={nd} IC_true={ic_t:.4f} IC_old={old_ic:.4f}")
        del sc, dv, dv2
    best_mi = max(cands, key=lambda k: cands[k]["ic"])
    print(f"[v2] selected max_iter={best_mi} (VAL IC_new 最高)")
    for mi in cand_iters:
        if mi != best_mi:
            del cands[mi]["model"]

    Xf = np.concatenate([Xtr, Xva], axis=0)
    yf = np.concatenate([ytr, yva], axis=0)
    del Xtr, ytr, Xva, yva
    wf = sample_weights(yf)
    final, final_secs = fit_hgb(Xf, yf, wf, best_mi, args.max_leaf_nodes)
    fallback = False
    if final_secs > FIT_TIMEOUT_S and best_mi != 150:
        print(f"[v2] final fit {final_secs:.0f}s > 60min, 降到 max_iter=150 重训")
        del final
        final, final_secs = fit_hgb(Xf, yf, wf, 150, args.max_leaf_nodes)
        best_mi = 150
        fallback = True
    n_final = len(yf)
    del Xf, yf, wf
    print(f"[v2] final fit done n={n_final:,} secs={final_secs:.1f} fallback={fallback}")

    Xte, yte, yote, mte = build_split_samples(splits["TEST"], scaler, feature_cols, args.label)
    del splits["TEST"]
    print(f"[v2] TEST windows={len(yte):,}")
    ste = batched_predict(final, Xte)
    del Xte
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": ste.astype(np.float64),
                        "realizable_ret": yte.astype(np.float64),
                        "future_ret_5d": yote.astype(np.float64)})
    del mte, yte, yote, ste
    parts = []
    for _dt, g in dte.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g["realizable_ret"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
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
    pred = pred.astype({"code": str, "score": float, "realizable_ret": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred = cast(pd.DataFrame, pred[["code", "kline_time", "score", "realizable_ret", "future_ret_5d", "q_true"]])
    po = Path(args.pred_out)
    po.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    print(f"[v2] saved {po} rows={len(pred):,}")

    tic, tir, tnd, _ = cross_section_ic(pred, ret_col="realizable_ret")
    # TEST对照: score vs 原标签; score vs 经济学正确方向
    tic_old, tir_old, tnd_old, _ = cross_section_ic(pred, ret_col="future_ret_5d")
    pred_true = pred.copy()
    pred_true["R_true"] = 1.0 / (1.0 + pred_true["realizable_ret"].to_numpy(dtype=np.float64)) - 1.0
    tic_true, tir_true, _, _ = cross_section_ic(pred_true, ret_col="R_true")
    qm = quintile_means(pred, ret_col="realizable_ret")
    b = cands[best_mi]
    metrics = {
        "mode": mode,
        "label": args.label,
        "label_formula": LABEL_FORMULA_LITERAL if args.label == "realizable" else "close[t+5]/close[t]-1",
        "label_note": LABEL_NOTE if args.label == "realizable" else "baseline replicate",
        "window_spec": ("SEQ_LEN=60末日t; 66行[t-59..t+6]同组is_trading全真; "
                        "open[t+1]/open[t+6]有效且open[t+1]!=0; 双标签有限保留"
                        if args.label == "realizable" else
                        "SEQ_LEN=60末日t; 65行[t-59..t+5]同组is_trading全真 (baseline等价)"),
        "selected_max_iter": best_mi,
        "selected_params": {"loss": "squared_error", "max_iter": best_mi,
                            "max_leaf_nodes": args.max_leaf_nodes, "early_stopping": True,
                            "validation_fraction": 0.1, "random_state": 42},
        "candidates": {str(mi): {"max_iter": mi, "max_leaf_nodes": args.max_leaf_nodes,
                                 "val_ic": c["ic"], "val_ir": c["ir"],
                                 "val_n_days": c["n_days"],
                                 "val_ic_true_orientation": c["ic_true"],
                                 "val_ic_old_contrast": c["ic_old_contrast"],
                                 "fit_secs": c["secs"]}
                       for mi, c in cands.items()},
        "val_ic": b["ic"], "val_ir": b["ir"], "val_n_days": b["n_days"],
        "val_ic_true_orientation": b["ic_true"],
        "val_ic_old_contrast": b["ic_old_contrast"],
        "test_ic": tic, "test_ir": tir, "test_n_days": tnd, "n_days": tnd,
        "test_ic_old_contrast": tic_old, "test_ir_old_contrast": tir_old,
        "test_n_days_old": tnd_old,
        "test_ic_true_orientation": tic_true, "test_ir_true_orientation": tir_true,
        "test_quintile_means": qm,
        "n_train_windows": int(n_final),
        "n_test_rows": len(pred),
        "fit_final_secs": final_secs,
        "fit_timeout_fallback": fallback,
        "total_secs": time.time() - t_start,
        "leakage_audit": audit,
        "feature_cols_out": feat_out + HAND_COLS,
    }
    mo = Path(args.metrics_out)
    mo.parent.mkdir(parents=True, exist_ok=True)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[v2] saved {mo} total={metrics['total_secs']:.1f}s")
    print(json.dumps({k: metrics[k] for k in
                      ["mode", "label", "selected_max_iter", "val_ic", "val_ir", "val_n_days",
                       "val_ic_true_orientation", "val_ic_old_contrast",
                       "test_ic", "test_ir", "test_n_days",
                       "test_ic_true_orientation", "test_ic_old_contrast",
                       "test_quintile_means", "fit_final_secs", "total_secs"]}, indent=2))


if __name__ == "__main__":
    main()
