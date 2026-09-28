"""Pairwise HGB-LTR (tree + ranking objective) 对照: 49维 -> 98维concat对分类 + 中位数参照打分.

管线 (照抄 models/train_realizable.py label='realizable' 口径):
- 49维 = scaler.pkl (TRAIN-only拟合, 只load绝不重fit) transform_code 窗口末日t当行
  + 4手工统计 (原始close, 只用<=t): mean_5/mean_20/vol_20/ret_20.
- 窗口: 末日t要求60窗行[t-59..t]+6 horizon[t+1..t+6]共66行同组is_trading全真,
  open[t+1]/open[t+6]有效且open[t+1]!=0; 同时要求close[t]/close[t+5]有效以附带
  future_ret_5d作对照. 时段 TRAIN[2013,2021]/VAL[2022,2023]/TEST[2024,2025], 不跨段.
- 标签字面: realizable_ret lit[t] = open[t+1]/open[t+6]-1.
  经济学可吃收益 R_true = open[t+6]/open[t+1]-1 = 1/(1+lit)-1, 与lit单调递减.

Pairwise (TRAIN段内):
- 同kline_time截面内采样股票对, 均匀提候选 + p=|d|/(|d|+c)接受采样 (c=GAP_C默认0.01,
  照抄train_ltr.py, 即按|Δret|加权、抑制噪声小差距对; loss本身不再加权).
- 全量约200万对 (smoke约10万对), 特征=concat(x_i,x_j)共98维float32,
  标签=1若lit_i>lit_j (相等跳过).
- HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=63,
  early_stopping=True, random_state=42) 拟合 P(i胜j). 只在TRAIN上训练 (不合并VAL).

打分 (中位数参照法, 解决pairwise分类器无法直接打分):
- 每截面取特征中位数向量m_d = median(X_d, axis=0)作参照,
  score_raw(x) = predict_proba(concat(x, m_d))[:,1] = P(x胜当日中位数).
- score_raw排名lit (大=lit高=可吃收益低), 与引擎TopN (越大越好=可吃收益高) 反向,
  故落盘score = -score_raw (可执行方向, 照抄train_realizable的-score约定与
  train_ltr.py的-score落盘). 若验证得IC_true<0则再取负并在metrics书面注明
  (direction_flipped flag + direction_note).
- TEST全量逐截面批量推理 (420截面×平均~5k行, 每次predict_proba一批, 速度快).

输出: artifacts/opt_ltr_hgb/pred_test_ltrhgb.parquet
  [code,kline_time,score(可执行方向),realizable_ret,future_ret_5d,q_true]
  q_true = 按score的截面quintile (每kline_time qcut(score,5)->0..4;
  不足5行/不足5类则该日丢弃, 与任务字面一致).
  + metrics_ltrhgb.json (VAL/TEST IC literal/true/old三口径, 耗时, 超参, 方向说明).
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
DEFAULT_PRED = ROOT / "artifacts" / "opt_ltr_hgb" / "pred_test_ltrhgb.parquet"
DEFAULT_METRICS = ROOT / "artifacts" / "opt_ltr_hgb" / "metrics_ltrhgb.json"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
GAP_C = 0.01
PRED_BATCH = 200_000


def build_split_samples(df_split, scaler, feature_cols):
    """与 train_realizable.py label='realizable' 逐字同口径. 返回 X,y_lit,y_old,meta."""
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
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        t = np.arange(n)
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
        y_new = o1[okm] / o6[okm] - 1.0
        y_old = c_5[okm] / c_t[okm] - 1.0
        fin = np.isfinite(y_new) & np.isfinite(y_old)
        if not fin.any():
            continue
        tt = tt[fin]
        y_new = y_new[fin]
        y_old = y_old[fin]
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


def gen_pairs(date_codes, y, n_pairs, rng, gap_c=GAP_C, chunk=300_000):
    """同截面均匀候选 + p=|d|/(|d|+c)接受. 返回 ia,ib(int64), n_candidates."""
    date_codes = np.asarray(date_codes)
    y = np.asarray(y, dtype=np.float64)
    uniq, inv, counts = np.unique(date_codes, return_inverse=True, return_counts=True)
    valid_dates = np.where(counts >= 2)[0]
    if len(valid_dates) == 0:
        raise RuntimeError("no date with >=2 rows, BLOCKED")
    order = np.argsort(inv, kind="stable")
    sorted_inv = inv[order]
    bounds = np.searchsorted(sorted_inv, np.arange(len(uniq) + 1))
    ia_list, ib_list = [], []
    n_cand_total = 0
    guard = 0
    need = n_pairs
    starts = bounds[:-1]
    counts_d = counts
    while need > 0:
        guard += 1
        if guard > 1000:
            raise RuntimeError("pair sampling guard tripped, BLOCKED")
        m = min(chunk, max(need * 3, 10_000))
        di = rng.integers(0, len(valid_dates), size=m)
        dates = valid_dates[di]
        s_arr = starts[dates]
        c_arr = counts_d[dates]
        u1 = (rng.random(m) * c_arr).astype(np.int64)
        u2 = (rng.random(m) * (c_arr - 1)).astype(np.int64)
        u2 = np.where(u2 >= u1, u2 + 1, u2)
        i1 = order[s_arr + u1]
        i2 = order[s_arr + u2]
        avec = y[i1]
        bvec = y[i2]
        neq = avec != bvec
        i1, i2 = i1[neq], i2[neq]
        avec, bvec = avec[neq], bvec[neq]
        n_cand_total += m
        if len(i1) == 0:
            continue
        delt = np.abs(avec - bvec)
        p = delt / (delt + gap_c)
        u = rng.random(len(i1))
        keep = u < p
        acc = np.where(keep)[0]
        if len(acc) == 0:
            continue
        take = acc[:need]
        ia_list.append(i1[take])
        ib_list.append(i2[take])
        need -= len(take)
    ia = np.concatenate(ia_list).astype(np.int64)
    ib = np.concatenate(ib_list).astype(np.int64)
    return ia, ib, int(n_cand_total)


def median_ref_scores(clf, X, day_codes, batch=PRED_BATCH):
    """每截面中位数参照打分: score_raw = P(concat(x, m_d)), m_d=当日中位数向量.

    按day_codes分组, 每组一次(或分批)predict_proba. 返回与X同序的raw prob数组.
    """
    X = np.asarray(X)
    day_codes = np.asarray(day_codes)
    out = np.empty(len(X), dtype=np.float64)
    uniq = np.unique(day_codes)
    for d in uniq:
        idx = np.where(day_codes == d)[0]
        Xd = X[idx].astype(np.float32)
        m = np.median(Xd.astype(np.float64), axis=0).astype(np.float32)
        M = np.broadcast_to(m, Xd.shape)
        Xp = np.concatenate([Xd, M], axis=1)
        prob = np.empty(len(idx), dtype=np.float64)
        for a in range(0, len(idx), batch):
            b = min(a + batch, len(idx))
            prob[a:b] = clf.predict_proba(Xp[a:b])[:, 1]
        out[idx] = prob
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--pairs", type=int, default=None)
    ap.add_argument("--gap-c", type=float, default=GAP_C)
    ap.add_argument("--max-iter", type=int, default=150)
    ap.add_argument("--max-leaf-nodes", type=int, default=63)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pred-out", default=str(DEFAULT_PRED))
    ap.add_argument("--metrics-out", default=str(DEFAULT_METRICS))
    args = ap.parse_args()

    smoke = args.smoke and not args.full
    n_pairs = args.pairs or (100_000 if smoke else 2_000_000)
    mode = "smoke" if smoke else "full"
    parquet = Path(DEFAULT_SAMPLE if smoke else DEFAULT_FULL)
    t_start = time.time()

    rng = np.random.default_rng(args.seed)

    t0 = time.time()
    scaler = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    feature_cols = list(scaler.feature_cols)
    feat_out = list(scaler.feature_cols_out)
    assert len(feat_out) == 45, f"scaler输出须45维, 实得{len(feat_out)}"
    print(f"[ltrhgb] mode={mode} parquet={parquet} pairs={n_pairs:,} "
          f"max_iter={args.max_iter} leaves={args.max_leaf_nodes} gap_c={args.gap_c} "
          f"seed={args.seed} feats=45+4=49", flush=True)
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    import pyarrow.parquet as pq
    df = pq.read_table(str(parquet), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[ltrhgb] read {len(df):,} rows codes={df['code'].nunique()} ({time.time()-t0:.1f}s)", flush=True)
    splits = split_frame(df)
    del df
    for k in list(splits.keys()):
        print(f"[ltrhgb] split {k}: rows={len(splits[k]):,}", flush=True)
    t_read = time.time() - t_start

    t0 = time.time()
    Xtr, ytr_lit, ytr_old, mtr = build_split_samples(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[ltrhgb] TRAIN windows={len(ytr_lit):,} X={Xtr.shape} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xva, yva_lit, yva_old, mva = build_split_samples(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[ltrhgb] VAL windows={len(yva_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xte, yte_lit, yte_old, mte = build_split_samples(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    print(f"[ltrhgb] TEST windows={len(yte_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    assert len(ytr_lit) > 0 and len(yva_lit) > 0 and len(yte_lit) > 0, "某split窗口数为0, BLOCKED"
    assert Xtr.shape[1] == 49, f"特征须49维, 实得{Xtr.shape[1]}"
    t_build = time.time() - t_start - t_read

    # --- 同截面pair采样 (TRAIN) ---
    t0 = time.time()
    tr_days = mtr["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    del mtr
    ia, ib, n_cand = gen_pairs(tr_days, ytr_lit, n_pairs, rng, gap_c=args.gap_c)
    accept_rate = len(ia) / max(n_cand, 1)
    yi = ytr_lit[ia].astype(np.float64)
    yj = ytr_lit[ib].astype(np.float64)
    tgt = (yi > yj).astype(np.int64)
    pos_rate = float(tgt.mean())
    print(f"[ltrhgb] pairs={len(ia):,} candidates={n_cand:,} accept={accept_rate:.3f} "
          f"pos_rate={pos_rate:.3f} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xpair = np.concatenate([Xtr[ia].astype(np.float32), Xtr[ib].astype(np.float32)], axis=1)
    del ia, ib, yi, yj
    print(f"[ltrhgb] Xpair {Xpair.shape} ({time.time()-t0:.1f}s)", flush=True)
    assert Xpair.shape[1] == 98
    t_pair = time.time() - t_start - t_read - t_build
    # 释放原始TRAIN (pair已物化)
    del Xtr, ytr_lit, ytr_old, tr_days

    # --- HGB分类拟合 ---
    from sklearn.ensemble import HistGradientBoostingClassifier
    t0 = time.time()
    clf = HistGradientBoostingClassifier(
        max_iter=args.max_iter, max_leaf_nodes=args.max_leaf_nodes,
        early_stopping=cast(Any, True), validation_fraction=0.1, random_state=args.seed)
    clf.fit(Xpair, tgt)
    t_fit = time.time() - t0
    train_acc = float(clf.score(Xpair[:min(200_000, len(Xpair))], tgt[:min(200_000, len(Xpair))]))
    print(f"[ltrhgb] fit done iters={clf.n_iter_} train_acc(sub200k)={train_acc:.4f} ({t_fit:.1f}s)", flush=True)
    del Xpair, tgt

    # --- 中位数参照打分 (VAL/TEST) ---
    t0 = time.time()
    va_days = mva["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    va_raw = median_ref_scores(clf, Xva, va_days)
    del Xva
    te_days = mte["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    te_raw = median_ref_scores(clf, Xte, te_days)
    del Xte
    t_score = time.time() - t0
    print(f"[ltrhgb] scored VAL={len(va_raw):,} TEST={len(te_raw):,} ({t_score:.1f}s)", flush=True)

    # --- 方向约定: 落盘score须与可吃收益同向 (大=好, 引擎TopN) ---
    # raw P排名lit; 可执行方向 score_exec=-raw. 如IC_true<0则再取负并书面注明.
    va_score0 = (-va_raw).astype(np.float64)
    te_score0 = (-te_raw).astype(np.float64)
    r_va = 1.0 / (1.0 + yva_lit.astype(np.float64)) - 1.0
    r_te = 1.0 / (1.0 + yte_lit.astype(np.float64)) - 1.0
    dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                        "score": va_score0, "realizable_ret": yva_lit.astype(np.float64),
                        "R_true": r_va, "future_ret_5d": yva_old.astype(np.float64)})
    val_ic_lit, val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
    val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
    val_ic_old, val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")
    # raw vs lit (应为正, 验证pairwise方向学对了)
    draw = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                         "score": va_raw.astype(np.float64),
                         "realizable_ret": yva_lit.astype(np.float64)})
    raw_val_ic_lit, _, _ = cross_section_ic(draw, ret_col="realizable_ret")
    direction_flipped = False
    if not np.isfinite(val_ic_true) or val_ic_true < 0:
        # 方向错了: 取负 (score_exec -> -score_exec = raw), 书面注明
        direction_flipped = True
        va_score0 = (-va_score0)
        te_score0 = (-te_score0)
        dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                            "score": va_score0, "realizable_ret": yva_lit.astype(np.float64),
                            "R_true": r_va, "future_ret_5d": yva_old.astype(np.float64)})
        val_ic_lit, val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
        val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
        val_ic_old, val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")

    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": te_score0,
                        "realizable_ret": yte_lit.astype(np.float64),
                        "R_true": r_te,
                        "future_ret_5d": yte_old.astype(np.float64)})
    test_ic_lit, test_ir_lit, test_days = cross_section_ic(dte, ret_col="realizable_ret")
    test_ic_true, test_ir_true, _ = cross_section_ic(dte, ret_col="R_true")
    test_ic_old, test_ir_old, _ = cross_section_ic(dte, ret_col="future_ret_5d")

    # q_true 按score截面quintile (任务字面)
    parts = []
    for _dt, g in dte.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g["score"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
        except Exception:  # noqa: BLE001, S112 -- 退化截面跳过
            continue
        if getattr(q, "cat", None) is not None and len(q.cat.categories) != 5:
            continue
        gg = g.copy()
        gg["q_true"] = np.asarray(q).astype(int)
        parts.append(gg)
    pred = (pd.concat(parts, ignore_index=True) if parts else dte.iloc[0:0].copy())
    if len(pred):
        pred["q_true"] = pred["q_true"].astype(int)
    pred = pred.astype({"code": str, "score": float, "realizable_ret": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred = pred[["code", "kline_time", "score", "realizable_ret", "future_ret_5d", "q_true"]]
    po = Path(args.pred_out)
    po.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    total = time.time() - t_start

    if direction_flipped:
        dir_note = ("WARNING方向修正: 初版score=-P(x胜median)得VAL IC_true<0, 已再取负 "
                    "(落盘score=+P). 最终落盘score方向以本metrics的VAL/TEST "
                    "IC_true_orientation>0为准, 与引擎TopN一致. "
                    f"raw P vs lit VAL IC={raw_val_ic_lit:.4f}.")
    else:
        dir_note = ("Raw P(x胜median)排名字面lit (lit=open[t+1]/open[t+6]-1); "
                    "可执行收益R_true=open[t+6]/open[t+1]-1与lit单调递减, 故落盘"
                    "score=-P排名R_true (大=好, 与引擎TopN一致, 照抄train_realizable "
                    "-score约定). "
                    f"Check raw VAL IC_lit={raw_val_ic_lit:.4f}(须>0); 最终VAL/TEST "
                    "IC_true_orientation为与v2/MLP可比口径.")

    metrics = {
        "mode": mode,
        "arch": "hgb-pairwise-98concat-classifier + median-ref",
        "pairwise": f"same-kline_time uniform candidates + accept p=|d|/(|d|+{args.gap_c})",
        "gap_c": float(args.gap_c),
        "n_pairs": len(pred) * 0 + int(n_pairs),
        "pair_candidates_total": int(n_cand),
        "pair_accept_rate": float(accept_rate),
        "pair_pos_rate": float(pos_rate),
        "n_features_pair": 98,
        "hgb_params": {"loss": "log_loss", "max_iter": args.max_iter,
                       "max_leaf_nodes": args.max_leaf_nodes, "early_stopping": True,
                       "validation_fraction": 0.1, "random_state": args.seed},
        "hgb_n_iter": int(getattr(clf, "n_iter_", args.max_iter)),
        "hgb_train_acc_sub200k": float(train_acc),
        "scoring": "per-date median m_d=median(X_d); score_raw=P(concat(x,m_d)); saved score=-raw",
        "direction_note": dir_note,
        "direction_flipped_second_negation": bool(direction_flipped),
        "score_sign": "negated (-P) to executable direction" if not direction_flipped else "double-negated (+P) after IC_true<0 check",
        "raw_val_ic_lit": float(raw_val_ic_lit),
        "val_ic_literal_finalscore": float(val_ic_lit),
        "val_ir_literal_finalscore": float(val_ir_lit),
        "val_ic_true_orientation": float(val_ic_true),
        "val_ir_true_orientation": float(val_ir_true),
        "val_ic_old_contrast": float(val_ic_old),
        "val_ir_old_contrast": float(val_ir_old),
        "val_days": int(val_days),
        "test_ic_literal_finalscore": float(test_ic_lit),
        "test_ir_literal_finalscore": float(test_ir_lit),
        "test_ic_true_orientation": float(test_ic_true),
        "test_ir_true_orientation": float(test_ir_true),
        "test_ic_old_contrast": float(test_ic_old),
        "test_ir_old_contrast": float(test_ir_old),
        "test_days": int(test_days),
        "n_test_rows": len(pred),
        "seed": int(args.seed),
        "t_read_s": round(float(t_read), 1),
        "t_build_s": round(float(t_build), 1),
        "t_pair_s": round(float(t_pair), 1),
        "t_fit_s": round(float(t_fit), 1),
        "t_score_s": round(float(t_score), 1),
        "total_secs": round(float(total), 1),
        "feature_cols_out": feat_out + HAND_COLS,
    }
    mo = Path(args.metrics_out)
    mo.parent.mkdir(parents=True, exist_ok=True)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[ltrhgb] saved {po} rows={len(pred):,} | {mo} total={total:.1f}s", flush=True)
    print(json.dumps({k: metrics[k] for k in
                      ["mode", "n_pairs", "pair_accept_rate", "hgb_n_iter",
                       "raw_val_ic_lit", "val_ic_true_orientation",
                       "test_ic_true_orientation", "test_ic_old_contrast",
                       "direction_flipped_second_negation", "total_secs"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
