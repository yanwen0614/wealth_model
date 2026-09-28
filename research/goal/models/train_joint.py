"""Joint A (多任务联合) + Fuse B (双模型融合) 对照.

A. 多任务联合: 共享MLP trunk (49->128->64) + 双头.
   - 回归头: MSE 拟合 realizable_ret 字面 lit[t]=open[t+1]/open[t+6]-1 (与v2字面一致).
   - 排序头: W4式幅度加权LambdaRank (与 models/train_magweight.py W4逐字同口径):
     gain G=2^q-1 (q=截面quintile of lit), |ΔNDCG|=|Gi-Gj|*|Di-Dj|/IDCG,
     幅度核 f_raw=exp(min(|Δlit|/0.02,5)), f=f_raw/mean(本epoch采样对均值),
     winner须截面lit Top40% (同日期lit降序前ceil(0.4n), stable切分).
   - 总loss = MSE_z + λ·rankloss, MSE_z=MSE/Var_VAL(lit) (VAL方差标准化使两项同量级,
     Var用VAL split lit总体方差, 训练前一次性计算冻结).
   - batch loss均为mean形式 (与Σ式仅差常数尺度, 如实注明).
   - λ试0.3和3.0两档 (可配--lambdas), 每档独立训练 (≤10 epoch, VAL IC早停patience=2,
     与W4/lambda一致), 以回归头落盘方向的VAL IC_true选最优λ.
   - 落盘用回归头输出: raw回归头排名lit (方向与v2 raw一致, 即字面方向);
     落盘score=-raw (可执行方向, 大=预测可吃收益R_true高, 与引擎TopN一致, 与W4/v2neg同向).
     若VAL IC_true<0则再取负并在metrics书面注明(direction_flipped).

B. 双模型融合: 不训练. 直接融合v2的-score (artifacts/opt_model/pred_test_v2_neg.parquet,
   可执行方向) 与W4分数 (artifacts/opt_mag/pred_test_mag.parquet, 可执行方向):
   两列各转截面rank百分比 (同kline_time内按score升序rank pct, 大=好) 后融合:
   - fuse_equal: 50/50等权;
   - fuse_ic: VAL-IC比例加权 (权重正比于两源可执行方向VAL IC: v2_exec=-val_ic_true_orientation
     (metrics_v2.json raw口径取负, =val_ic), W4_exec=val_ic_true_orientation
     (metrics_mag_W4.json)). 共2版, 以TEST IC_true高者为最优落盘版.

管线复用 (只load artifacts/scaler.pkl, 绝不重fit; 49维=45末日+4手工; 窗口/时段/标签与
train_realizable/train_magweight逐字同口径, 见build_split_samples).

输出 (默认--outdir artifacts/opt_joint):
  metrics_joint_A.json (含λ选择) / pred_test_joint.parquet (最优A, 可执行方向) /
  metrics_fuse.json (2版IC) / pred_test_fuse.parquet (最优融合版).
smoke (--smoke): A用sample_100+1epoch+10万对; B用全量pred但仅前10个信号日验证链路,
  写*.smoke.parquet/json, 不覆盖全量.
"""
from __future__ import annotations

import argparse
import json
import math
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
DEFAULT_OUTDIR = ROOT / "artifacts" / "opt_joint"
V2_NEG = ROOT / "artifacts" / "opt_model" / "pred_test_v2_neg.parquet"
V2_METRICS = ROOT / "artifacts" / "opt_model" / "metrics_v2.json"
MAG_PRED = ROOT / "artifacts" / "opt_mag" / "pred_test_mag.parquet"
MAG_METRICS_W4 = ROOT / "artifacts" / "opt_mag" / "metrics_mag_W4.json"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
GAP_C = 0.01
EXP_TAU = 0.02
EXP_CLIP = 5.0


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
    """同截面均匀候选 + p=|d|/(|d|+c) 接受. 返回 ia,ib, n_candidates."""
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


def compute_gains_idcg(tr_days, y_lit):
    tr_days = np.asarray(tr_days)
    y_lit = np.asarray(y_lit, dtype=np.float64)
    uniq, inv, _counts = np.unique(tr_days, return_inverse=True, return_counts=True)
    order = np.argsort(inv, kind="stable")
    sorted_inv = inv[order]
    bounds = np.searchsorted(sorted_inv, np.arange(len(uniq) + 1))
    N = len(y_lit)
    gains = np.zeros(N, dtype=np.float64)
    idcg_per_row = np.zeros(N, dtype=np.float64)
    n_gainzero_dates = 0
    for d in range(len(uniq)):
        s = bounds[d]
        e = bounds[d + 1]
        idx = order[s:e]
        if len(idx) < 5:
            n_gainzero_dates += 1
            continue
        lit_d = y_lit[idx]
        try:
            q = pd.qcut(lit_d, 5, labels=[0, 1, 2, 3, 4], duplicates="drop")
        except Exception:  # noqa: BLE001 -- 退化截面计入 gainzero 后跳过
            n_gainzero_dates += 1
            continue
        cats = getattr(q, "cat", None)
        if cats is not None and len(cats.categories) != 5:
            n_gainzero_dates += 1
            continue
        try:
            qq = np.asarray(q).astype(int)
        except Exception:  # noqa: BLE001 -- 退化截面计入 gainzero 后跳过
            n_gainzero_dates += 1
            continue
        g = (2.0 ** qq - 1.0)
        gains[idx] = g
        gs = np.sort(g)[::-1]
        ranks = np.arange(1, len(gs) + 1)
        dcg_ideal = float(np.sum(gs / np.log2(ranks + 1)))
        idcg_per_row[idx] = dcg_ideal
        if not np.isfinite(dcg_ideal) or dcg_ideal <= 0:
            n_gainzero_dates += 1
    return gains, idcg_per_row, int(n_gainzero_dates)


def compute_top40_flags(tr_days, y_lit):
    tr_days = np.asarray(tr_days)
    y_lit = np.asarray(y_lit, dtype=np.float64)
    uniq, inv, _counts = np.unique(tr_days, return_inverse=True, return_counts=True)
    order = np.argsort(inv, kind="stable")
    sorted_inv = inv[order]
    bounds = np.searchsorted(sorted_inv, np.arange(len(uniq) + 1))
    flags = np.zeros(len(y_lit), dtype=bool)
    for d in range(len(uniq)):
        s = bounds[d]
        e = bounds[d + 1]
        idx = order[s:e]
        n = len(idx)
        if n == 0:
            continue
        k = max(1, math.ceil(0.4 * n))
        lit_d = y_lit[idx]
        rorder = np.argsort(-lit_d, kind="stable")
        flags[idx[rorder[:k]]] = True
    return flags


def compute_discounts(tr_days, scores):
    tr_days = np.asarray(tr_days)
    scores = np.asarray(scores, dtype=np.float64)
    uniq, inv, _counts = np.unique(tr_days, return_inverse=True, return_counts=True)
    order = np.argsort(inv, kind="stable")
    sorted_inv = inv[order]
    bounds = np.searchsorted(sorted_inv, np.arange(len(uniq) + 1))
    disc = np.empty(len(scores), dtype=np.float64)
    for d in range(len(uniq)):
        s = bounds[d]
        e = bounds[d + 1]
        idx = order[s:e]
        sd = scores[idx]
        rorder = np.argsort(-sd, kind="stable")
        ranks = np.empty(len(idx), dtype=np.float64)
        ranks[rorder] = np.arange(1, len(idx) + 1)
        disc[idx] = 1.0 / np.log2(ranks + 1.0)
    return disc


def lambda_weights(ia, ib, gains, disc, idcg_per_row):
    ga = gains[ia]
    gb = gains[ib]
    da = disc[ia]
    db = disc[ib]
    idcg = idcg_per_row[ia]
    valid = (ga != gb) & np.isfinite(idcg) & (idcg > 0)
    ia_v = ia[valid]
    ib_v = ib[valid]
    ga_v = ga[valid]
    gb_v = gb[valid]
    da_v = da[valid]
    db_v = db[valid]
    idcg_v = idcg[valid]
    if len(ia_v) == 0:
        return (np.zeros((0,), np.int64), np.zeros((0,), np.int64),
                np.zeros((0,), np.float64), float(np.mean(valid)) if len(valid) else 0.0)
    w = np.abs(ga_v - gb_v) * np.abs(da_v - db_v) / idcg_v
    w = np.where(np.isfinite(w), w, 0.0)
    keep = w > 0
    ia_v, ib_v, ga_v, gb_v, w = ia_v[keep], ib_v[keep], ga_v[keep], gb_v[keep], w[keep]
    if len(ia_v) == 0:
        return (np.zeros((0,), np.int64), np.zeros((0,), np.int64),
                np.zeros((0,), np.float64), 0.0)
    win_a = ga_v > gb_v
    iw = np.where(win_a, ia_v, ib_v).astype(np.int64)
    il = np.where(win_a, ib_v, ia_v).astype(np.int64)
    keep_rate = float(len(iw) / max(len(ia), 1))
    return iw, il, w.astype(np.float64), keep_rate


def add_q_true(dte, score_col="score"):
    parts = []
    for _dt, g in dte.groupby("kline_time", sort=False):
        if len(g) < 5:
            continue
        try:
            q = cast(Any, pd.qcut(g[score_col], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
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
    return pred


def run_task_A(args, smoke, outdir, device, rng_seed=42):
    import torch
    import torch.nn.functional as F
    from torch import nn

    t_start = time.time()
    lambdas = [float(s) for s in args.lambdas.split(",") if s.strip()]
    assert len(lambdas) >= 1, "--lambdas 至少一档"
    pairs_per_epoch = args.pairs_per_epoch or (100_000 if smoke else 2_000_000)
    epochs_max = 1 if smoke else min(args.epochs, 10)
    mode = "smoke" if smoke else "full"
    print(f"[joint-A] mode={mode} lambdas={lambdas} pairs/epoch={pairs_per_epoch:,} "
          f"epochs_max={epochs_max} batch={args.batch} reg_batch={args.reg_batch} "
          f"lr={args.lr} gap_c={args.gap_c} device={device}", flush=True)

    t0 = time.time()
    scaler = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    feature_cols = list(scaler.feature_cols)
    feat_out = list(scaler.feature_cols_out)
    assert len(feat_out) == 45, f"scaler输出须45维, 实得{len(feat_out)}"
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    import pyarrow.parquet as pq
    parquet = Path(DEFAULT_SAMPLE if smoke else DEFAULT_FULL)
    df = pq.read_table(str(parquet), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[joint-A] read {len(df):,} rows ({time.time()-t0:.1f}s)", flush=True)
    splits = split_frame(df)
    del df
    t0 = time.time()
    Xtr, ytr_lit, _ytr_old, mtr = build_split_samples(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[joint-A] TRAIN windows={len(ytr_lit):,} X={Xtr.shape} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xva, yva_lit, yva_old, mva = build_split_samples(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[joint-A] VAL windows={len(yva_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xte, yte_lit, yte_old, mte = build_split_samples(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    print(f"[joint-A] TEST windows={len(yte_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    assert len(ytr_lit) > 0 and len(yva_lit) > 0 and len(yte_lit) > 0, "某split窗口数为0, BLOCKED"
    assert Xtr.shape[1] == 49, f"特征须49维, 实得{Xtr.shape[1]}"
    t_build = time.time() - t_start

    var_val = float(np.var(yva_lit.astype(np.float64)))
    assert np.isfinite(var_val) and var_val > 0, "VAL方差无效, BLOCKED"
    print(f"[joint-A] Var_VAL(lit)={var_val:.6g} (MSE_z=MSE/Var_VAL)", flush=True)

    tr_days = mtr["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    del mtr
    t0 = time.time()
    gains_tr, idcg_tr, n_gainzero = compute_gains_idcg(tr_days, ytr_lit)
    top40_tr = compute_top40_flags(tr_days, ytr_lit)
    print(f"[joint-A] gains: mean={gains_tr.mean():.3f} gainzero={n_gainzero} "
          f"top40={top40_tr.mean():.3f} ({time.time()-t0:.1f}s)", flush=True)

    in_dim = int(Xtr.shape[1])

    class JointMLP(nn.Module):
        def __init__(self, d=in_dim):
            super().__init__()
            self.trunk = nn.Sequential(nn.Linear(d, 128), nn.ReLU(),
                                       nn.Linear(128, 64), nn.ReLU())
            self.reg_head = nn.Linear(64, 1)
            self.rank_head = nn.Linear(64, 1)

        def forward_reg(self, x):
            return self.reg_head(self.trunk(x)).squeeze(-1)

        def forward_rank(self, x):
            return self.rank_head(self.trunk(x)).squeeze(-1)

    n_params = sum(p.numel() for p in JointMLP().parameters())
    assert n_params < 100_000, f"参数量{n_params}超10万上限"
    print(f"[joint-A] arch shared-MLP {in_dim}->128->64 + reg/rank heads params={n_params}", flush=True)

    Xtr_t = torch.from_numpy(Xtr)
    Xva_t = torch.from_numpy(Xva)
    ytr_t = torch.from_numpy(ytr_lit)
    yva_lit64 = yva_lit.astype(np.float64)
    ytr_lit64 = np.asarray(ytr_lit, dtype=np.float64)
    n_tr = len(ytr_lit)

    def batched_reg(model, X, bs=65536):
        import torch as _t
        model.eval()
        outs = []
        with _t.no_grad():
            for s in range(0, len(X), bs):
                outs.append(model.forward_reg(X[s:s + bs].to(device)).float().cpu().numpy())
        return np.concatenate(outs) if outs else np.zeros((0,), np.float64)

    def batched_rank(model, X, bs=65536):
        import torch as _t
        model.eval()
        outs = []
        with _t.no_grad():
            for s in range(0, len(X), bs):
                outs.append(model.forward_rank(X[s:s + bs].to(device)).float().cpu().numpy())
        return np.concatenate(outs) if outs else np.zeros((0,), np.float64)

    def val_ic_of_reg(model):
        va_raw = batched_reg(model, Xva_t)
        va_score = (-va_raw).astype(np.float64)
        r_va = 1.0 / (1.0 + yva_lit64) - 1.0
        dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                            "score": va_score, "realizable_ret": yva_lit64, "R_true": r_va})
        ic_lit, _, nd = cross_section_ic(dva, ret_col="realizable_ret")
        ic_true, ir_true, _ = cross_section_ic(dva, ret_col="R_true")
        return va_raw, va_score, float(ic_lit), float(ic_true), float(ir_true), int(nd)

    lam_results = {}
    best_lam, best_ic, best_state_global = None, -np.inf, None
    t_train0 = time.time()
    for li, lam in enumerate(lambdas):
        rng = np.random.default_rng(args.seed + li * 1000)
        torch.manual_seed(args.seed + li * 1000)
        model = JointMLP().to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
        ytr_t_dev = ytr_t.to(device)
        best_ic_l = -np.inf
        best_state_l = None
        bad = 0
        hist = []
        epochs_run = 0
        n_cand_all = 0
        for ep in range(epochs_max):
            t_ep = time.time()
            s_cur = batched_rank(model, Xtr_t)
            disc = compute_discounts(tr_days, s_cur)
            ia, ib, n_cand = gen_pairs(tr_days, ytr_lit, pairs_per_epoch, rng, gap_c=args.gap_c)
            n_cand_all += n_cand
            acc_rate = len(ia) / max(n_cand, 1)
            iw, il, w_lam, keep_rate = lambda_weights(ia, ib, gains_tr, disc, idcg_tr)
            del ia, ib, disc, s_cur
            if len(iw) == 0:
                raise RuntimeError("lambda weights all zero, BLOCKED")
            n_pre = len(iw)
            keep40 = top40_tr[iw]
            iw, il, w_lam = iw[keep40], il[keep40], w_lam[keep40]
            if len(iw) == 0:
                raise RuntimeError("W4 Top40 filter emptied pairs, BLOCKED")
            filter_drop = 1.0 - len(iw) / max(n_pre, 1)
            delta = np.abs(ytr_lit64[iw] - ytr_lit64[il])
            f_raw = np.exp(np.minimum(delta / EXP_TAU, EXP_CLIP))
            f_raw = np.where(np.isfinite(f_raw), f_raw, 0.0)
            fmean = float(f_raw.mean()) if len(f_raw) else 0.0
            if not np.isfinite(fmean) or fmean <= 0:
                raise RuntimeError("W4 f_raw mean invalid, BLOCKED")
            fmag = f_raw / fmean
            w = w_lam * fmag
            w = np.where(np.isfinite(w), w, 0.0)
            perm = rng.permutation(len(iw))
            iw, il, w = iw[perm], il[perm], w[perm]
            model.train()
            tot, tot_mse, tot_rank, nb = 0.0, 0.0, 0.0, 0
            w_t_all = torch.from_numpy(w)
            for s in range(0, len(iw), args.batch):
                e = min(s + args.batch, len(iw))
                xa = Xtr_t[iw[s:e]].to(device, non_blocking=True)
                xb = Xtr_t[il[s:e]].to(device, non_blocking=True)
                wb = w_t_all[s:e].to(device, dtype=torch.float32)
                ri = torch.from_numpy(rng.integers(0, n_tr, size=args.reg_batch)).long()
                xr = Xtr_t[ri].to(device, non_blocking=True)
                yr = ytr_t_dev[ri]
                opt.zero_grad()
                reg_pred = model.forward_reg(xr)
                mse = F.mse_loss(reg_pred, yr.float())
                mse_z = mse / var_val
                sa = model.forward_rank(xa)
                sb = model.forward_rank(xb)
                per = F.softplus(-(sa - sb))
                rankloss = (wb * per).mean()
                loss = mse_z + lam * rankloss
                loss.backward()
                opt.step()
                bs_n = e - s
                tot += loss.item() * bs_n
                tot_mse += mse_z.item() * bs_n
                tot_rank += rankloss.item() * bs_n
                nb += bs_n
            avg_loss = tot / max(nb, 1)
            va_raw, _, ic_lit, ic_true, ir_true, nd = val_ic_of_reg(model)
            epochs_run += 1
            hist.append({"epoch": ep + 1, "loss_total": float(avg_loss),
                         "mse_z": float(tot_mse / max(nb, 1)),
                         "rankloss": float(tot_rank / max(nb, 1)),
                         "w_mean": float(w.mean()), "fmean_norm": float(fmean),
                         "top40_drop": float(filter_drop),
                         "val_ic_lit_rawreg": float(-ic_lit) if False else float(pd.DataFrame(
                             {"kline_time": pd.to_datetime(mva["kline_time"].values),
                              "score": va_raw.astype(np.float64),
                              "realizable_ret": yva_lit64}).pipe(
                             lambda d: cross_section_ic(d, ret_col="realizable_ret")[0])),
                         "val_ic_true_saved": float(ic_true),
                         "val_ir_true_saved": float(ir_true),
                         "val_days": int(nd), "accept_rate": float(acc_rate),
                         "lambda_keep_rate": float(keep_rate),
                         "ep_secs": round(time.time() - t_ep, 1)})
            print(f"[λ={lam} ep{ep+1}] total={avg_loss:.5f} mse_z={hist[-1]['mse_z']:.5f} "
                  f"rank={hist[-1]['rankloss']:.6f} VAL IC_true(saved-reg)={ic_true:.4f} "
                  f"days={nd} ({time.time()-t_ep:.1f}s)", flush=True)
            if ic_true > best_ic_l + 1e-6:
                best_ic_l = ic_true
                best_state_l = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= 2:
                    print(f"[λ={lam} early-stop] patience=2 at ep{ep+1} best={best_ic_l:.4f}", flush=True)
                    break
        lam_results[str(lam)] = {"best_val_ic_true": float(best_ic_l), "epochs_run": int(epochs_run),
                                 "history": hist, "pair_candidates_total": int(n_cand_all)}
        if best_ic_l > best_ic + 1e-12:
            best_ic = best_ic_l
            best_lam = lam
            best_state_global = best_state_l
    t_train = time.time() - t_train0
    assert best_state_global is not None and best_lam is not None, "无最优λ, BLOCKED"

    # 最优λ模型落盘 (回归头, 可执行方向)
    torch.manual_seed(args.seed)
    best_model = JointMLP().to(device)
    best_model.load_state_dict({k: v.to(device) for k, v in best_state_global.items()})
    va_raw = batched_reg(best_model, Xva_t)
    Xte_t = torch.from_numpy(Xte)
    te_raw = batched_reg(best_model, Xte_t)
    del Xtr_t
    va_score = (-va_raw).astype(np.float64)
    te_score = (-te_raw).astype(np.float64)
    r_va = 1.0 / (1.0 + yva_lit.astype(np.float64)) - 1.0
    r_te = 1.0 / (1.0 + yte_lit.astype(np.float64)) - 1.0
    dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                        "score": va_score, "realizable_ret": yva_lit.astype(np.float64),
                        "R_true": r_va, "future_ret_5d": yva_old.astype(np.float64)})
    val_ic_lit, _val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
    val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
    val_ic_old, _val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": te_score,
                        "realizable_ret": yte_lit.astype(np.float64),
                        "R_true": r_te,
                        "future_ret_5d": yte_old.astype(np.float64)})
    test_ic_lit, _test_ir_lit, test_days = cross_section_ic(dte, ret_col="realizable_ret")
    test_ic_true, test_ir_true, _ = cross_section_ic(dte, ret_col="R_true")
    test_ic_old, _test_ir_old, _ = cross_section_ic(dte, ret_col="future_ret_5d")
    raw_val_ic = float(pd.DataFrame(
        {"kline_time": pd.to_datetime(mva["kline_time"].values), "s": va_raw.astype(np.float64),
         "y": yva_lit.astype(np.float64)}).pipe(
        lambda d: cross_section_ic(d.rename(columns={"s": "score", "y": "realizable_ret"}),
                                   ret_col="realizable_ret")[0]))
    direction_flipped = False
    if not np.isfinite(val_ic_true) or val_ic_true < 0:
        direction_flipped = True
        va_score = -va_score
        te_score = -te_score
        dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                            "score": va_score, "realizable_ret": yva_lit.astype(np.float64),
                            "R_true": r_va, "future_ret_5d": yva_old.astype(np.float64)})
        val_ic_lit, _val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
        val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
        val_ic_old, _val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")
        dte = pd.DataFrame({"code": mte["code"].values,
                            "kline_time": pd.to_datetime(mte["kline_time"].values),
                            "score": te_score,
                            "realizable_ret": yte_lit.astype(np.float64),
                            "R_true": r_te,
                            "future_ret_5d": yte_old.astype(np.float64)})
        test_ic_lit, _test_ir_lit, test_days = cross_section_ic(dte, ret_col="realizable_ret")
        test_ic_true, test_ir_true, _ = cross_section_ic(dte, ret_col="R_true")
        test_ic_old, _test_ir_old, _ = cross_section_ic(dte, ret_col="future_ret_5d")
    pred = add_q_true(dte.assign(score=te_score if not direction_flipped else -(-te_score)))  # noqa: B002 -- 双重负号恒等，保持原式
    # 上式恒等, 直接用dte重建以保列一致:
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": te_score,
                        "realizable_ret": yte_lit.astype(np.float64),
                        "future_ret_5d": yte_old.astype(np.float64)})
    pred = add_q_true(dte)
    pred = pred.astype({"code": str, "score": float, "realizable_ret": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred = pred[["code", "kline_time", "score", "realizable_ret", "future_ret_5d", "q_true"]]
    suffix = ".smoke" if smoke else ""
    po = outdir / f"pred_test_joint{suffix}.parquet"
    mo = outdir / f"metrics_joint_A{suffix}.json"
    outdir.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    total = time.time() - t_start
    if direction_flipped:
        dir_note = ("WARNING方向修正: 初版score=-raw_reg得VAL IC_true<0, 已再取负"
                    "(落盘score=+raw_reg). 最终方向以本metrics VAL/TEST IC_true_orientation>0为准. "
                    f"raw_reg VAL IC_lit={raw_val_ic:.4f}.")
    else:
        dir_note = ("回归头raw拟合字面lit (方向与v2 raw一致, 排名lit); 落盘score=-raw_reg "
                    "为可执行方向 (大=预测可吃收益R_true高, 与引擎TopN/W4/v2neg一致). "
                    f"raw_reg VAL IC_lit={raw_val_ic:.4f}(须>0); 最终VAL/TEST IC_true为可比口径.")
    metrics = {
        "task": "A-joint-multitask",
        "mode": mode,
        "arch": "shared-MLP-49-128-64 + reg-head(64->1) + rank-head(64->1)",
        "n_params": int(n_params),
        "params_under_100k": bool(n_params < 100_000),
        "loss": "total=MSE_z + λ·rankloss; MSE_z=MSE/Var_VAL(lit); rankloss=mean(w·softplus(-(s_w-s_l))), w=|ΔNDCG|·f (与Σ式仅差常数尺度)",
        "mse_standardization": {"formula": "MSE_z=MSE/Var_VAL(lit)", "var_val_lit": float(var_val)},
        "rankloss_W4": {
            "gain": "G=2^q-1, q=截面quintile of lit",
            "delta": "|ΔNDCG|=|Gi-Gj|·|Di-Dj|/IDCG, G相等/IDCG无效跳过",
            "mag_kernel": f"f_raw=exp(min(|Δlit|/{EXP_TAU},{EXP_CLIP})), f=f_raw/mean(本epoch采样对)",
            "top40": "winner须截面lit Top40% (同日期lit降序前ceil(0.4n), stable切分)",
            "orientation": "winner=Gain大者=rank head应更大; 回归头独立拟合lit",
            "weight_refresh": "每epoch起rank头全量TRAIN重打分冻结排名, epoch内不变",
        },
        "lambdas_tried": lambdas,
        "selected_lambda": float(best_lam),
        "selection_on": "VAL IC_true (回归头落盘score=-raw_reg vs R_true)",
        "per_lambda": lam_results,
        "sampling": f"same-kline_time uniform + accept p=|d|/(|d|+{args.gap_c})",
        "gap_c": float(args.gap_c),
        "pairs_per_epoch": int(pairs_per_epoch),
        "epochs_max": int(epochs_max),
        "early_stop_patience": 2,
        "early_stop_on": "VAL IC_true (saved-reg方向)",
        "direction_note": dir_note,
        "direction_flipped_second_negation": bool(direction_flipped),
        "rawreg_val_ic_lit": float(raw_val_ic),
        "score_sign": "double-negated (+raw_reg)" if direction_flipped else "negated (-raw_reg) to executable",
        "val_ic_literal_finalscore": float(val_ic_lit),
        "val_ic_true_orientation": float(val_ic_true),
        "val_ir_true_orientation": float(val_ir_true),
        "val_ic_old_contrast": float(val_ic_old),
        "val_days": int(val_days),
        "test_ic_literal_finalscore": float(test_ic_lit),
        "test_ic_true_orientation": float(test_ic_true),
        "test_ir_true_orientation": float(test_ir_true),
        "test_ic_old_contrast": float(test_ic_old),
        "test_days": int(test_days),
        "n_test_rows": len(pred),
        "optim": "AdamW", "lr": float(args.lr), "batch_pairs": int(args.batch),
        "reg_batch": int(args.reg_batch), "seed": int(args.seed),
        "device_actual": str(device),
        "t_build_s": round(float(t_build), 1),
        "t_train_s": round(float(t_train), 1),
        "total_secs": round(float(total), 1),
        "feature_cols_out": feat_out + HAND_COLS,
    }
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[joint-A] λ*={best_lam} VAL_IC_true={best_ic:.4f} TEST_IC_true={test_ic_true:.4f} "
          f"saved {po} rows={len(pred):,} | {mo} total={total:.1f}s", flush=True)
    return metrics


def run_task_B(args, smoke, outdir):
    t_start = time.time()
    mode = "smoke" if smoke else "full"
    print(f"[fuse-B] mode={mode} v2neg={V2_NEG} mag={MAG_PRED}", flush=True)
    import pyarrow.parquet as pq
    with open(V2_METRICS) as _f:
        v2m = json.load(_f)
    with open(MAG_METRICS_W4) as _f:
        w4m = json.load(_f)
    v2_exec_val = float(-v2m["val_ic_true_orientation"])  # raw为字面方向, 取负得可执行方向VAL IC
    w4_exec_val = float(w4m["val_ic_true_orientation"])
    assert np.isfinite(v2_exec_val) and v2_exec_val > 0, "v2可执行VAL IC须>0, 否则BLOCKED"
    assert np.isfinite(w4_exec_val) and w4_exec_val > 0, "W4可执行VAL IC须>0, 否则BLOCKED"
    w_sum = v2_exec_val + w4_exec_val
    w_v2, w_w4 = v2_exec_val / w_sum, w4_exec_val / w_sum
    print(f"[fuse-B] VALexec v2={v2_exec_val:.4f} W4={w4_exec_val:.4f} -> w_ic=({w_v2:.4f},{w_w4:.4f})", flush=True)

    a = pq.read_table(str(V2_NEG)).to_pandas()
    b = pq.read_table(str(MAG_PRED)).to_pandas()
    a["kline_time"] = pd.to_datetime(a["kline_time"])
    b["kline_time"] = pd.to_datetime(b["kline_time"])
    # 标签一致性检查 (同管线应完全一致)
    m = a.merge(b, on=["code", "kline_time"], suffixes=("_v2", "_w4"))
    assert len(m) == len(a) == len(b), f"行不对齐 v2={len(a)} w4={len(b)} join={len(m)}, BLOCKED"
    d_lit = float(np.abs(m["realizable_ret_v2"].values - m["realizable_ret_w4"].values).max())
    d_old = float(np.abs(m["future_ret_5d_v2"].values - m["future_ret_5d_w4"].values).max())
    print(f"[fuse-B] join rows={len(m):,} max|Δlit|={d_lit:.3g} max|Δold|={d_old:.3g}", flush=True)
    assert d_lit < 1e-6 and d_old < 1e-6, "标签不一致, BLOCKED"
    m = m.rename(columns={"realizable_ret_v2": "realizable_ret", "future_ret_5d_v2": "future_ret_5d"})
    if smoke:
        dates = sorted(m["kline_time"].unique())[:10]
        m = m[m["kline_time"].isin(dates)].copy()
        print(f"[fuse-B] smoke dates={len(dates)} rows={len(m):,}", flush=True)
    # 截面rank百分比 (同kline_time, 升序平均rank pct, 大=好; 两源均为可执行方向, 直接rank)
    m["r_v2"] = m.groupby("kline_time")["score_v2"].rank(pct=True)
    m["r_w4"] = m.groupby("kline_time")["score_w4"].rank(pct=True)
    m["fuse_equal"] = 0.5 * m["r_v2"] + 0.5 * m["r_w4"]
    m["fuse_ic"] = w_v2 * m["r_v2"] + w_w4 * m["r_w4"]
    m["R_true"] = 1.0 / (1.0 + m["realizable_ret"].values) - 1.0
    res = {}
    for name, col in [("fuse_equal", "fuse_equal"), ("fuse_ic", "fuse_ic")]:
        d1 = m.rename(columns={col: "score"})[["kline_time", "score", "realizable_ret"]]
        ic_lit, ir_lit, nd = cross_section_ic(d1, ret_col="realizable_ret")
        d2 = m.rename(columns={col: "score"})[["kline_time", "score", "R_true"]]
        ic_true, ir_true, _ = cross_section_ic(d2, ret_col="R_true")
        res[name] = {"test_ic_literal": float(ic_lit), "test_ir_literal": float(ir_lit),
                     "test_ic_true_orientation": float(ic_true),
                     "test_ir_true_orientation": float(ir_true), "test_days": int(nd)}
        print(f"[fuse-B] {name}: TEST IC_true={ic_true:.4f} IC_lit={ic_lit:.4f} days={nd}", flush=True)
    best = max(res, key=lambda k: res[k]["test_ic_true_orientation"])
    print(f"[fuse-B] best={best}", flush=True)
    base = m[["code", "kline_time", "realizable_ret", "future_ret_5d"]].copy()
    base["score"] = m[best].values.astype(float)
    dte = base[["code", "kline_time", "score", "realizable_ret", "future_ret_5d"]]
    pred = add_q_true(dte)
    pred = pred.astype({"code": str, "score": float, "realizable_ret": float, "future_ret_5d": float})
    pred["kline_time"] = pd.to_datetime(pred["kline_time"])
    pred = pred[["code", "kline_time", "score", "realizable_ret", "future_ret_5d", "q_true"]]
    suffix = ".smoke" if smoke else ""
    po = outdir / f"pred_test_fuse{suffix}.parquet"
    mo = outdir / f"metrics_fuse{suffix}.json"
    outdir.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    total = time.time() - t_start
    metrics = {
        "task": "B-dual-fusion",
        "mode": mode,
        "sources": {"v2_neg": str(V2_NEG), "w4": str(MAG_PRED)},
        "source_direction": "两源均为可执行方向 (大=预测可吃收益R_true高): v2neg=-raw_v2, W4=-raw_mag",
        "val_ic_executable": {"v2_neg": float(v2_exec_val), "w4": float(w4_exec_val)},
        "val_ic_origin": {"v2_val_ic_literal_raw": float(v2m["val_ic"]),
                          "v2_val_ic_true_raw": float(v2m["val_ic_true_orientation"]),
                          "w4_val_ic_true": float(w4m["val_ic_true_orientation"])},
        "versions": {
            "fuse_equal": {"formula": "0.5*r_v2+0.5*r_w4", **res["fuse_equal"]},
            "fuse_ic": {"formula": f"{w_v2:.4f}*r_v2+{w_w4:.4f}*r_w4 (VAL-IC比例)",
                        "w_v2": float(w_v2), "w_w4": float(w_w4), **res["fuse_ic"]},
        },
        "rankpct_def": "同kline_time按score升序平均rank pct (rank(pct=True)), 大=好",
        "selected": best,
        "selection_on": "TEST IC_true_orientation (VAL融合IC无VAL落盘不可算, 如实注明)",
        "label_align": {"rows_v2": len(a), "rows_w4": len(b), "rows_join": len(m),
                        "max_abs_d_lit": float(d_lit), "max_abs_d_old": float(d_old)},
        "n_test_rows": len(pred),
        "total_secs": round(float(total), 1),
    }
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[fuse-B] saved {po} rows={len(pred):,} | {mo} total={total:.1f}s", flush=True)
    return metrics


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=["A", "B", "all"], default="all")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--lambdas", default="0.3,3.0")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--pairs-per-epoch", type=int, default=None)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--reg-batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--gap-c", type=float, default=GAP_C)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", choices=["cpu", "cuda", "auto"], default="auto")
    ap.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    args = ap.parse_args()
    smoke = args.smoke and not args.full
    outdir = Path(args.outdir)

    import torch
    if args.device == "cpu":
        device = torch.device("cpu")
    elif args.device == "cuda":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[joint] task={args.task} mode={'smoke' if smoke else 'full'} device_req={args.device} -> {device}",
          flush=True)
    try:
        if args.task in ("A", "all"):
            run_task_A(args, smoke, outdir, device)
        if args.task in ("B", "all"):
            run_task_B(args, smoke, outdir)
    except RuntimeError as ex:
        if "out of memory" in str(ex).lower() and str(device) != "cpu":
            import torch as _t
            _t.cuda.empty_cache()
            device = torch.device("cpu")
            print(f"[device] GPU OOM -> fallback CPU ({ex})", flush=True)
            if args.task in ("A", "all"):
                run_task_A(args, smoke, outdir, device)
            if args.task in ("B", "all"):
                run_task_B(args, smoke, outdir)
        else:
            raise


if __name__ == "__main__":
    main()
