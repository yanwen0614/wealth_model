"""Magnitude-weighted LambdaRank (幅度加权极限对照): 以 models/train_lambda.py 为底座逐字复用.

复用 (与 train_lambda.py 完全一致, 只 load artifacts/scaler.pkl 绝不重fit):
- 49维 = scaler 45维 transform_code 窗口末日 t 当行 + 4手工统计 (原始close只用<=t).
- 窗口/时段/标签字面 realizable_ret lit[t]=open[t+1]/open[t+6]-1, R_true=1/(1+lit)-1 单调递减.
- 训练 raw s 排名 lit; 落盘 score=-s (可执行方向); VAL IC_true<0 则再取负并书面注明.
- MLP 49->128->64->1 (~1.5万参<10万), ΔNDCG权重 (|ΔNDCG|=|G_i-G_j|*|D_i-D_j|/IDCG),
  gain G=2^q-1 (q=截面quintile of lit), 每epoch起全量重打分冻结排名, epoch内不变.
- 采样 gen_pairs (同截面均匀候选+p=|Δlit|/(|Δlit|+c)接受, c=GAP_C默认0.01).
- <=5 epoch, VAL IC_lit(raw)早停 patience=2. q_true按score截面quintile重算.

新增 (唯一改动): 幅度核 f(|Δret|), loss=Σ|ΔNDCG|·f(|Δret|)·softplus(-(s_w-s_l)),
batch loss=mean(w*softplus) (与Σ式仅差常数尺度, 如实注明).
|Δret| := 同对两行 realizable_ret(lit) 之差绝对值 |lit_i-lit_j| (lit空间; 与可吃收益
R_true差值单调对应, |ΔR|≈|Δlit|/(1+lit)^2, 排序加权下等价, 如实注明).

四档 (--mag):
- W1: f=|Δret| 线性 (温和baseline, 无归一化, 原始尺度).
- W2: f=|Δret|^2 平方重罚大差距对 (无归一化, 原始尺度).
- W3: f=|Δret|^2 + 只保留 winner 在截面 lit Top40% 的对 (头部集中, 不管尾部排序).
- W4 (极限): f_raw=exp(min(|Δret|/0.02, 5.0)) (指数截断 EXP_CLIP=5.0, max~148.4防爆),
  f=f_raw/mean(f_raw) (按本epoch采样对均值归一化, 均值=1, 保持loss尺度与LambdaRank可比),
  + 只保留 winner 在截面 lit Top40% 的对, loser任意 (几乎只学头部内部幅度排序).

Top40% 定义: 同 kline_time 截面内按 lit 降序排名, 前 ceil(0.4*n) 行 flag=1 (并列按稳定排序
切分, 如实注明); winner须flag=1. 随机对中 P(winner在Top40%)≈1-0.6^2=0.64, 过滤后仍百万级对,
若某epoch过滤后为空则 BLOCKED 报错 (如实记录 filter_drop_rate).
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
OPT_MAG = ROOT / "artifacts" / "opt_mag"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
GAP_C = 0.01
EXP_TAU = 0.02
EXP_CLIP = 5.0
MAG_CHOICES = ("W1", "W2", "W3", "W4")


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
    """同截面均匀候选 + p=|d|/(|d|+c) 接受. 返回 ia,ib(numpy int64), n_candidates."""
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
    """预计算每行 gain=2^q-1 (q=截面quintile of lit) 与每行所属日期的 IDCG."""
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
    """每行是否截面 lit Top40%: 同日期按 lit 降序前 ceil(0.4*n) 行=1. 返回 bool[N]."""
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
    """按当前 scores 降序排名算每行 discount=1/log2(rank+1). 向量化分日期 argsort."""
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
    """对采样对算定向后 (iw, il, w). w=|ΔNDCG|. gain相等/IDCG无效 -> 丢弃."""
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


def mag_kernel(delta, mag):
    """幅度核 f(|Δret|). W4 返回 (f_raw, f_norm, norm_mean); 其余返回 (f, None, None).

    W1: f=|d|; W2/W3: f=d^2; W4: f_raw=exp(min(d/0.02,5)), f=f_raw/mean(f_raw)(调用方归一化).
    """
    d = np.asarray(delta, dtype=np.float64)
    if mag == "W1":
        return np.where(np.isfinite(d), d, 0.0), None, None
    if mag in ("W2", "W3"):
        return np.where(np.isfinite(d), d * d, 0.0), None, None
    raw = np.exp(np.minimum(d / EXP_TAU, EXP_CLIP))
    raw = np.where(np.isfinite(raw), raw, 0.0)
    return raw, raw, None


MAG_DESC = {
    "W1": "f=|Δret| linear (温和baseline, 无归一化)",
    "W2": "f=|Δret|^2 square (平方重罚大差距对, 无归一化)",
    "W3": "f=|Δret|^2 + winner须截面lit Top40% (头部集中, 不管尾部)",
    "W4": "f=exp(min(|Δret|/0.02,5))/mean (指数截断EXP_CLIP=5归一化) + winner须Top40%",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mag", choices=list(MAG_CHOICES), default="W1")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--pairs-per-epoch", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--gap-c", type=float, default=GAP_C)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", choices=["cpu", "cuda", "auto"], default="auto")
    ap.add_argument("--pred-out", default=None)
    ap.add_argument("--metrics-out", default=None)
    args = ap.parse_args()
    mag = args.mag

    import torch
    import torch.nn.functional as F
    from torch import nn

    smoke = args.smoke and not args.full
    pairs_per_epoch = args.pairs_per_epoch or (100_000 if smoke else 2_000_000)
    epochs_max = 1 if smoke else min(args.epochs, 5)
    t_start = time.time()

    dev_req = args.device
    if args.device == "cpu":
        device = torch.device("cpu")
    elif args.device == "cuda":
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    oom_fallback = False

    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)

    parquet = Path(DEFAULT_SAMPLE if smoke else DEFAULT_FULL)
    mode = "smoke" if smoke else "full"
    pred_out = Path(args.pred_out) if args.pred_out else (OPT_MAG / f"pred_test_mag_{mag}.parquet")
    metrics_out = Path(args.metrics_out) if args.metrics_out else (OPT_MAG / f"metrics_mag_{mag}.json")
    print(f"[mag-{mag}] mode={mode} parquet={parquet} pairs/epoch={pairs_per_epoch:,} "
          f"epochs_max={epochs_max} batch={args.batch} lr={args.lr} gap_c={args.gap_c} "
          f"device_req={dev_req} -> {device} f={MAG_DESC[mag]}", flush=True)

    t0 = time.time()
    scaler = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    feature_cols = list(scaler.feature_cols)
    feat_out = list(scaler.feature_cols_out)
    assert len(feat_out) == 45, f"scaler输出须45维, 实得{len(feat_out)}"
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    import pyarrow.parquet as pq
    df = pq.read_table(str(parquet), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[mag-{mag}] read {len(df):,} rows codes={df['code'].nunique()} ({time.time()-t0:.1f}s)", flush=True)
    splits = split_frame(df)
    del df
    for k in list(splits.keys()):
        print(f"[mag-{mag}] split {k}: rows={len(splits[k]):,}", flush=True)

    t0 = time.time()
    Xtr, ytr_lit, _ytr_old, mtr = build_split_samples(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[mag-{mag}] TRAIN windows={len(ytr_lit):,} X={Xtr.shape} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xva, yva_lit, yva_old, mva = build_split_samples(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[mag-{mag}] VAL windows={len(yva_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xte, yte_lit, yte_old, mte = build_split_samples(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    print(f"[mag-{mag}] TEST windows={len(yte_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    assert len(ytr_lit) > 0 and len(yva_lit) > 0 and len(yte_lit) > 0, "某split窗口数为0, BLOCKED"
    assert Xtr.shape[1] == 49, f"特征须49维, 实得{Xtr.shape[1]}"
    t_build = time.time() - t_start

    tr_days = mtr["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    del mtr

    t0 = time.time()
    gains_tr, idcg_tr, n_gainzero = compute_gains_idcg(tr_days, ytr_lit)
    top40_tr = compute_top40_flags(tr_days, ytr_lit)
    print(f"[mag-{mag}] gains precomputed: mean_gain={gains_tr.mean():.3f} "
          f"gainzero_dates={n_gainzero} top40_rate={top40_tr.mean():.3f} ({time.time()-t0:.1f}s)", flush=True)

    in_dim = int(Xtr.shape[1])

    class RankMLP(nn.Module):
        def __init__(self, d=in_dim):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(d, 128), nn.ReLU(),
                nn.Linear(128, 64), nn.ReLU(),
                nn.Linear(64, 1),
            )

        def forward(self, x):
            return self.net(x).squeeze(-1)

    def count_params(m):
        return sum(p.numel() for p in m.parameters())

    probe = RankMLP()
    n_params = count_params(probe)
    assert n_params < 100_000, f"参数量{n_params}超10万上限"
    print(f"[mag-{mag}] arch MLP {in_dim}->128->64->1 params={n_params}", flush=True)
    del probe

    Xtr_t = torch.from_numpy(Xtr)
    Xva_t = torch.from_numpy(Xva)
    ytr_lit64 = np.asarray(ytr_lit, dtype=np.float64)

    def batched_score(model, X, bs=65536):
        model.eval()
        outs = []
        import torch as _t
        with _t.no_grad():
            for s in range(0, len(X), bs):
                xb = X[s:s + bs].to(device, non_blocking=True)
                outs.append(model(xb).float().cpu().numpy())
        return np.concatenate(outs) if outs else np.zeros((0,), np.float64)

    def run_epochs(dev, model, opt, Xtr_t, tr_days, gains_tr, idcg_tr, top40_tr):
        best_ic = -np.inf
        best_state = None
        bad = 0
        epochs_run = 0
        hist = []
        n_cand_all = 0
        for ep in range(epochs_max):
            t_ep = time.time()
            s_cur = batched_score(model, Xtr_t)
            disc = compute_discounts(tr_days, s_cur)
            ia, ib, n_cand = gen_pairs(tr_days, ytr_lit, pairs_per_epoch, rng, gap_c=args.gap_c)
            n_cand_all += n_cand
            acc_rate = len(ia) / max(n_cand, 1)
            iw, il, w_lam, keep_rate = lambda_weights(ia, ib, gains_tr, disc, idcg_tr)
            del ia, ib, disc, s_cur
            if len(iw) == 0:
                raise RuntimeError("lambda weights all zero, BLOCKED")
            n_pre_filter = len(iw)
            # Top40% 过滤 (W3/W4): winner 须截面 lit Top40%
            if mag in ("W3", "W4"):
                keep40 = top40_tr[iw]
                iw, il, w_lam = iw[keep40], il[keep40], w_lam[keep40]
                if len(iw) == 0:
                    raise RuntimeError(f"{mag} Top40 filter emptied pairs, BLOCKED")
            filter_drop = 1.0 - len(iw) / max(n_pre_filter, 1)
            # 幅度核
            delta = np.abs(ytr_lit64[iw] - ytr_lit64[il])
            if mag == "W1":
                fmag = np.where(np.isfinite(delta), delta, 0.0)
                fnorm_note = "none"
            elif mag in ("W2", "W3"):
                fmag = np.where(np.isfinite(delta), delta * delta, 0.0)
                fnorm_note = "none"
            else:  # W4
                f_raw = np.exp(np.minimum(delta / EXP_TAU, EXP_CLIP))
                f_raw = np.where(np.isfinite(f_raw), f_raw, 0.0)
                fmean = float(f_raw.mean()) if len(f_raw) else 0.0
                if not np.isfinite(fmean) or fmean <= 0:
                    raise RuntimeError("W4 f_raw mean invalid, BLOCKED")
                fmag = f_raw / fmean
                fnorm_note = f"raw=exp(min(|d|/{EXP_TAU},{EXP_CLIP}))/mean({fmean:.4g})"
            w = w_lam * fmag
            w = np.where(np.isfinite(w), w, 0.0)
            w_mean = float(w.mean())
            w_sum = float(w.sum())
            f_mean = float(fmag.mean())
            f_max = float(fmag.max()) if len(fmag) else 0.0
            d_mean = float(delta.mean()) if len(delta) else 0.0
            perm = rng.permutation(len(iw))
            iw, il, w = iw[perm], il[perm], w[perm]
            model.train()
            tot_loss, nb = 0.0, 0
            w_t_all = torch.from_numpy(w)
            for s in range(0, len(iw), args.batch):
                e = min(s + args.batch, len(iw))
                xa = Xtr_t[iw[s:e]].to(dev, non_blocking=True)
                xb = Xtr_t[il[s:e]].to(dev, non_blocking=True)
                wb = w_t_all[s:e].to(dev, dtype=torch.float32)
                opt.zero_grad()
                sa = model(xa)
                sb = model(xb)
                diff = sa - sb
                per = F.softplus(-diff)
                loss = (wb * per).mean()
                loss.backward()
                opt.step()
                tot_loss += loss.item() * (e - s)
                nb += (e - s)
            avg_loss = tot_loss / max(nb, 1)
            va_raw = batched_score(model, Xva_t)
            dv = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                               "score": va_raw.astype(np.float64),
                               "realizable_ret": yva_lit.astype(np.float64)})
            ic_lit, ir_lit, nd = cross_section_ic(dv, ret_col="realizable_ret")
            epochs_run += 1
            hist.append({"epoch": ep + 1, "train_mag_loss": float(avg_loss),
                         "w_mean": float(w_mean), "w_sum": float(w_sum),
                         "f_mean": float(f_mean), "f_max": float(f_max),
                         "delta_mean": float(d_mean),
                         "top40_filter_drop": float(filter_drop),
                         "fnorm": fnorm_note,
                         "val_ic_lit_raw": float(ic_lit), "val_ir_lit_raw": float(ir_lit),
                         "val_days": int(nd), "accept_rate": float(acc_rate),
                         "lambda_keep_rate": float(keep_rate),
                         "ep_secs": round(time.time() - t_ep, 1)})
            print(f"[ep{ep+1}] loss={avg_loss:.5f} wmean={w_mean:.6f} fmean={f_mean:.5g} "
                  f"fmax={f_max:.5g} drop40={filter_drop:.3f} keep={keep_rate:.3f} "
                  f"VAL IC_lit(raw)={ic_lit:.4f} IR={ir_lit:.3f} days={nd} "
                  f"accept={acc_rate:.3f} ({time.time()-t_ep:.1f}s)", flush=True)
            if ic_lit > best_ic + 1e-6:
                best_ic = ic_lit
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                bad = 0
            else:
                bad += 1
                if bad >= 2:
                    print(f"[early-stop] patience=2 at ep{ep+1} best_ic={best_ic:.4f}", flush=True)
                    break
        return epochs_run, best_ic, best_state, hist, n_cand_all

    t0 = time.time()
    device_actual = str(device)
    try:
        model = RankMLP().to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
        epochs_run, best_ic, best_state, hist, n_cand_all = run_epochs(device, model, opt, Xtr_t, tr_days, gains_tr, idcg_tr, top40_tr)
        assert best_state is not None
        model.load_state_dict({k: v.to(device) for k, v in best_state.items()})
    except (RuntimeError, torch.cuda.OutOfMemoryError) as ex:
        if "out of memory" in str(ex).lower() and str(device) != "cpu":
            import torch as _t
            _t.cuda.empty_cache()
            oom_fallback = True
            device = torch.device("cpu")
            device_actual = "cpu"
            print(f"[device] GPU OOM -> fallback CPU ({ex})", flush=True)
            model = RankMLP().to(device)
            opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
            epochs_run, best_ic, best_state, hist, n_cand_all = run_epochs(device, model, opt, Xtr_t, tr_days, gains_tr, idcg_tr, top40_tr)
            assert best_state is not None
            model.load_state_dict(best_state)
        else:
            raise
    t_train = time.time() - t0
    loss_down = bool(len(hist) >= 1 and (len(hist) == 1 or hist[-1]["train_mag_loss"] < hist[0]["train_mag_loss"]
                                         or min(h["train_mag_loss"] for h in hist) < hist[0]["train_mag_loss"]))

    t0 = time.time()
    va_raw = batched_score(model, Xva_t)
    Xte_t = torch.from_numpy(Xte)
    te_raw = batched_score(model, Xte_t)
    del Xtr_t, Xtr, tr_days, gains_tr, idcg_tr, top40_tr
    va_score = (-va_raw).astype(np.float64)
    te_score = (-te_raw).astype(np.float64)
    r_va = 1.0 / (1.0 + yva_lit.astype(np.float64)) - 1.0
    r_te = 1.0 / (1.0 + yte_lit.astype(np.float64)) - 1.0
    dva = pd.DataFrame({"kline_time": pd.to_datetime(mva["kline_time"].values),
                        "score": va_score, "realizable_ret": yva_lit.astype(np.float64),
                        "R_true": r_va, "future_ret_5d": yva_old.astype(np.float64)})
    val_ic_lit, val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
    val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
    val_ic_old, val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")
    dte = pd.DataFrame({"code": mte["code"].values,
                        "kline_time": pd.to_datetime(mte["kline_time"].values),
                        "score": te_score,
                        "realizable_ret": yte_lit.astype(np.float64),
                        "R_true": r_te,
                        "future_ret_5d": yte_old.astype(np.float64)})
    test_ic_lit, test_ir_lit, test_days = cross_section_ic(dte, ret_col="realizable_ret")
    test_ic_true, test_ir_true, _ = cross_section_ic(dte, ret_col="R_true")
    test_ic_old, test_ir_old, _ = cross_section_ic(dte, ret_col="future_ret_5d")
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
        val_ic_lit, val_ir_lit, val_days = cross_section_ic(dva, ret_col="realizable_ret")
        val_ic_true, val_ir_true, _ = cross_section_ic(dva, ret_col="R_true")
        val_ic_old, val_ir_old, _ = cross_section_ic(dva, ret_col="future_ret_5d")
        dte = pd.DataFrame({"code": mte["code"].values,
                            "kline_time": pd.to_datetime(mte["kline_time"].values),
                            "score": te_score,
                            "realizable_ret": yte_lit.astype(np.float64),
                            "R_true": r_te,
                            "future_ret_5d": yte_old.astype(np.float64)})
        test_ic_lit, test_ir_lit, test_days = cross_section_ic(dte, ret_col="realizable_ret")
        test_ic_true, test_ir_true, _ = cross_section_ic(dte, ret_col="R_true")
        test_ic_old, test_ir_old, _ = cross_section_ic(dte, ret_col="future_ret_5d")
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
    po = Path(pred_out)
    po.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(po, index=False)
    t_eval = time.time() - t0
    total = time.time() - t_start

    if direction_flipped:
        dir_note = ("WARNING方向修正: 初版score=-raw得VAL IC_true<0, 已再取负 "
                    "(落盘score=+raw). 最终落盘score方向以本metrics的VAL/TEST "
                    f"IC_true_orientation>0为准, 与引擎TopN一致. raw VAL IC_lit={raw_val_ic:.4f}.")
    else:
        dir_note = ("Raw score s ranks literal realizable_ret "
                    "(lit=open[t+1]/open[t+6]-1); executable return "
                    "R_true=open[t+6]/open[t+1]-1 is rank-monotone-decreasing in lit, "
                    "so saved score=-s ranks R_true high=good, consistent with engine TopN. "
                    f"Check raw VAL IC_lit={raw_val_ic:.4f} (must be >0); "
                    "final VAL/TEST IC_true_orientation is the comparable number vs v2 +0.0764.")
    metrics = {
        "mode": mode,
        "mag": mag,
        "mag_formula": MAG_DESC[mag],
        "mag_detail": {
            "delta": "|Δret|=|lit_i-lit_j| (lit空间; 与|ΔR_true|单调对应, |ΔR|≈|Δlit|/(1+lit)^2)",
            "W1": "f=|d| raw, 无归一化",
            "W2": "f=d^2 raw, 无归一化",
            "W3": "f=d^2 raw + winner须截面lit Top40% (同日期lit降序前ceil(0.4n))",
            "W4": f"f_raw=exp(min(|d|/{EXP_TAU},{EXP_CLIP})) (max~{math.exp(EXP_CLIP):.1f}), "
                  "f=f_raw/mean(f_raw per-epoch, 均值=1) + winner须Top40%",
            "top40_def": "同kline_time按lit降序, 前ceil(0.4*n)行flag=1 (stable argsort切分)",
        },
        "arch": "mlp-49-128-64-1",
        "n_params": int(n_params),
        "params_under_100k": bool(n_params < 100_000),
        "loss": "MagLambdaRank: w=|DeltaNDCG|*f(|Δret|) * softplus(-(s_w-s_l)), winner=Gain大者; batch loss=mean(w*softplus) (与任务Σ式仅差常数尺度)",
        "lambdarank": {
            "gain": "G=2^q-1, q=per-kline_time quintile of realizable_ret(lit) 0..4 (qcut; fail->gain0/IDCG0/skip)",
            "discount": "D=1/log2(rank+1), rank by current raw score s descending (rank1=最高分)",
            "idcg": "IDCG_d=sum G_sorted_desc[k]/log2(k+2), per-date normalized",
            "delta": "|DeltaNDCG|=|G_i-G_j|*|D_i-D_j|/IDCG_d, G相等或IDCG无效则w=0跳过",
            "orientation": "winner=Gain大者(lit quintile高者)=raw s应更大; saved score=-raw executable",
            "weight_refresh": "每epoch起全量TRAIN重打分后冻结排名算w, epoch内不变 (经典LambdaRank迭代)",
        },
        "sampling": f"same-kline_time uniform candidates + accept p=|d|/(|d|+{args.gap_c}) "
                    "(bias to large-gap pairs, anti-noise; 复用F2)",
        "gap_c": float(args.gap_c),
        "pairs_per_epoch": int(pairs_per_epoch),
        "pair_candidates_total": int(n_cand_all),
        "gainzero_dates_train": int(n_gainzero),
        "epochs_run": int(epochs_run),
        "epochs_max": int(epochs_max),
        "early_stop_patience": 2,
        "early_stop_on": "VAL IC_lit(raw)",
        "best_val_ic_lit_raw": float(best_ic),
        "train_loss_down": bool(loss_down),
        "epoch_history": hist,
        "direction_note": dir_note,
        "direction_flipped_second_negation": bool(direction_flipped),
        "raw_val_ic_lit": float(raw_val_ic),
        "score_sign": "double-negated (+raw) after IC_true<0 check" if direction_flipped else "negated (-raw) to executable direction",
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
        "optim": "AdamW",
        "lr": float(args.lr),
        "batch_pairs": int(args.batch),
        "seed": int(args.seed),
        "device_requested": dev_req,
        "device_actual": device_actual,
        "oom_fallback_to_cpu": bool(oom_fallback),
        "t_build_s": round(float(t_build), 1),
        "t_train_s": round(float(t_train), 1),
        "t_eval_s": round(float(t_eval), 1),
        "total_secs": round(float(total), 1),
        "feature_cols_out": feat_out + HAND_COLS,
    }
    mo = Path(metrics_out)
    mo.parent.mkdir(parents=True, exist_ok=True)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[mag-{mag}] saved {po} rows={len(pred):,} | {mo} total={total:.1f}s", flush=True)
    print(json.dumps({k: metrics[k] for k in
                      ["mode", "mag", "arch", "n_params", "epochs_run", "train_loss_down",
                       "raw_val_ic_lit", "val_ic_true_orientation",
                       "test_ic_true_orientation", "test_ic_old_contrast",
                       "direction_flipped_second_negation",
                       "device_actual", "total_secs"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
