"""Pairwise RankNet (LTR) 对照: 同49维特征, MLP 49->128->64->1.

标签: 与 models/train_realizable.py 完全同口径的字面可实现
  realizable_ret[t] = open[t+1]/open[t+6]-1 (分code、split内位置序列).
  经济学可吃收益 R_true = open[t+6]/open[t+1]-1 = 1/(1+lit)-1, 与 lit 单调递减.
  训练时 pairwise 目标按 lit 比较 (lit_i>lit_j => 目标1), raw 分 s 排名 lit.
  落盘 score 为可执行方向 s' = -s (大=预测可吃收益高, 与引擎 TopN 一致),
  铁律见 metrics["direction_note"]. 不静默反转, 书面注明.

特征 (49维, 照抄 train_realizable.py):
- 45维 = scaler.pkl (TRAIN-only拟合, 只 load, 绝不重fit) transform_code 窗口末日 t 当行
- 4手工统计 (原始close, 只用<=t): mean_5/mean_20/vol_20/ret_20
- 窗口: 末日 t 要求 60 窗行[t-59..t]+6 horizon[t+1..t+6] 共66行同组 is_trading 全真,
  open[t+1]/open[t+6] 有效且 open[t+1]!=0; 同时要求 close[t]/close[t+5] 有效以附带
  future_ret_5d 作对照. 时段 TRAIN[2013,2021]/VAL[2022,2023]/TEST[2024,2025], 不跨段.

模型: MLP 49->128->64->1 (ReLU), 参数约1.5万 (<10万).
损失: 同截面 pairwise logistic: 对同 kline_time 的股票对 (i,j),
  若 lit_i>lit_j 则目标1, loss=BCEWithLogits(s_i - s_j).
  采样偏向收益差距大的对: 均匀提候选对, 以 p=|d|/(|d|+c) (c=GAP_C, 默认0.01)
  接受采样 (accept-reject), 防噪声小差距对主导; loss 本身不再额外加权
  (采样权重即偏向, 如实记录接受率/候选数).
  每 epoch 全量约 200万对 (smoke 约10万对), <=5 epoch, VAL IC 早停 patience=2.

输出: artifacts/opt_ltr/pred_test_ltr.parquet
  [code,kline_time,score(可执行方向=-raw),realizable_ret,future_ret_5d,q_true]
  q_true = 按 score 的截面 quintile (每 kline_time qcut(score,5)->0..4;
  不足5行/不足5类则该日丢弃, 与任务字面一致; 注意 v2 的 q_true 是按 label 切的, 此处按任务要求按 score 切).
  + metrics_ltr.json (VAL/TEST IC literal/true/old 三口径, 耗时, device, 超参).
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
DEFAULT_PRED = ROOT / "artifacts" / "opt_ltr" / "pred_test_ltr.parquet"
DEFAULT_METRICS = ROOT / "artifacts" / "opt_ltr" / "metrics_ltr.json"

HORIZON_CLOSE = 5
HORIZON_OPEN = 6
HAND_COLS = ["mean_5", "mean_20", "vol_20", "ret_20"]
GAP_C = 0.01  # accept-reject 偏向强度: p=|d|/(|d|+c)


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
    # 日期内行索引表
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
        # 跳过相等标签 (目标未定义)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--pairs-per-epoch", type=int, default=None)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=8192)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--gap-c", type=float, default=GAP_C)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", choices=["cpu", "cuda", "auto"], default="auto")
    ap.add_argument("--pred-out", default=str(DEFAULT_PRED))
    ap.add_argument("--metrics-out", default=str(DEFAULT_METRICS))
    args = ap.parse_args()

    import torch
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
    print(f"[ltr] mode={mode} parquet={parquet} pairs/epoch={pairs_per_epoch:,} "
          f"epochs_max={epochs_max} batch={args.batch} lr={args.lr} gap_c={args.gap_c} "
          f"device_req={dev_req} -> {device}", flush=True)

    t0 = time.time()
    scaler = PerCodeGroupedScaler.load(str(DEFAULT_SCALER))
    feature_cols = list(scaler.feature_cols)
    feat_out = list(scaler.feature_cols_out)
    assert len(feat_out) == 45, f"scaler输出须45维, 实得{len(feat_out)}"
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    import pyarrow.parquet as pq
    df = pq.read_table(str(parquet), columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[ltr] read {len(df):,} rows codes={df['code'].nunique()} ({time.time()-t0:.1f}s)", flush=True)
    splits = split_frame(df)
    del df
    for k in list(splits.keys()):
        print(f"[ltr] split {k}: rows={len(splits[k]):,}", flush=True)

    t0 = time.time()
    Xtr, ytr_lit, _ytr_old, mtr = build_split_samples(splits["TRAIN"], scaler, feature_cols)
    del splits["TRAIN"]
    print(f"[ltr] TRAIN windows={len(ytr_lit):,} X={Xtr.shape} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xva, yva_lit, yva_old, mva = build_split_samples(splits["VAL"], scaler, feature_cols)
    del splits["VAL"]
    print(f"[ltr] VAL windows={len(yva_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    t0 = time.time()
    Xte, yte_lit, yte_old, mte = build_split_samples(splits["TEST"], scaler, feature_cols)
    del splits["TEST"]
    print(f"[ltr] TEST windows={len(yte_lit):,} ({time.time()-t0:.1f}s)", flush=True)
    assert len(ytr_lit) > 0 and len(yva_lit) > 0 and len(yte_lit) > 0, "某split窗口数为0, BLOCKED"
    assert Xtr.shape[1] == 49, f"特征须49维, 实得{Xtr.shape[1]}"
    t_build = time.time() - t_start

    # 日期编码 (int64 day) 供同截面采样
    tr_days = mtr["kline_time"].values.astype("datetime64[D]").astype(np.int64)
    del mtr

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
    print(f"[ltr] arch MLP {in_dim}->128->64->1 params={n_params}", flush=True)
    del probe

    Xtr_t = torch.from_numpy(Xtr)  # CPU常驻, batch转device
    Xva_t = torch.from_numpy(Xva)

    def batched_score(model, X, bs=65536):
        model.eval()
        outs = []
        import torch as _t
        with _t.no_grad():
            for s in range(0, len(X), bs):
                xb = X[s:s + bs].to(device, non_blocking=True)
                outs.append(model(xb).float().cpu().numpy())
        return np.concatenate(outs) if outs else np.zeros((0,), np.float64)

    def run_epochs(dev, model, opt, loss_fn, Xtr_t, tr_days):
        best_ic = -np.inf
        best_state = None
        bad = 0
        epochs_run = 0
        hist = []
        n_cand_all = 0
        for ep in range(epochs_max):
            t_ep = time.time()
            ia, ib, n_cand = gen_pairs(tr_days, ytr_lit, pairs_per_epoch, rng, gap_c=args.gap_c)
            n_cand_all += n_cand
            acc_rate = len(ia) / max(n_cand, 1)
            # 目标按 lit 比较: lit_i>lit_j => 1 (i赢)
            yi = ytr_lit[ia].astype(np.float64)
            yj = ytr_lit[ib].astype(np.float64)
            tgt = (yi > yj).astype(np.float32)
            # 打乱
            perm = rng.permutation(len(ia))
            ia, ib, tgt = ia[perm], ib[perm], tgt[perm]
            model.train()
            tot_loss, nb = 0.0, 0
            for s in range(0, len(ia), args.batch):
                e = min(s + args.batch, len(ia))
                xa = Xtr_t[ia[s:e]].to(dev, non_blocking=True)
                xb = Xtr_t[ib[s:e]].to(dev, non_blocking=True)
                tb = torch.from_numpy(tgt[s:e]).to(dev)
                opt.zero_grad()
                sa = model(xa)
                sb = model(xb)
                loss = loss_fn(sa - sb, tb)
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
            hist.append({"epoch": ep + 1, "train_bce": float(avg_loss),
                         "val_ic_lit_raw": float(ic_lit), "val_ir_lit_raw": float(ir_lit),
                         "val_days": int(nd), "accept_rate": float(acc_rate),
                         "ep_secs": round(time.time() - t_ep, 1)})
            print(f"[ep{ep+1}] loss={avg_loss:.5f} VAL IC_lit(raw)={ic_lit:.4f} "
                  f"IR={ir_lit:.3f} days={nd} accept={acc_rate:.3f} "
                  f"({time.time()-t_ep:.1f}s)", flush=True)
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
        loss_fn = nn.BCEWithLogitsLoss()
        epochs_run, best_ic, best_state, hist, n_cand_all = run_epochs(device, model, opt, loss_fn, Xtr_t, tr_days)
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
            loss_fn = nn.BCEWithLogitsLoss()
            epochs_run, best_ic, best_state, hist, n_cand_all = run_epochs(device, model, opt, loss_fn, Xtr_t, tr_days)
            assert best_state is not None
            model.load_state_dict(best_state)
        else:
            raise
    t_train = time.time() - t0
    loss_down = bool(len(hist) >= 1 and (len(hist) == 1 or hist[-1]["train_bce"] < hist[0]["train_bce"]
                                         or min(h["train_bce"] for h in hist) < hist[0]["train_bce"]))

    # 评估: raw 分排名 lit; 落盘 score=-raw (可执行方向, 大=预测可吃收益高)
    t0 = time.time()
    va_raw = batched_score(model, Xva_t)
    Xte_t = torch.from_numpy(Xte)
    te_raw = batched_score(model, Xte_t)
    del Xtr_t, Xtr, tr_days
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
    # raw(未取负) vs lit: 应为正, 验证训练方向正确
    raw_val_ic = float(pd.DataFrame(
        {"kline_time": pd.to_datetime(mva["kline_time"].values), "s": va_raw.astype(np.float64),
         "y": yva_lit.astype(np.float64)}).pipe(
        lambda d: cross_section_ic(d.rename(columns={"s": "score", "y": "realizable_ret"}),
                                   ret_col="realizable_ret")[0]))
    # q_true 按 score 截面 quintile (任务字面)
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
    t_eval = time.time() - t0
    total = time.time() - t_start

    metrics = {
        "mode": mode,
        "arch": "mlp-49-128-64-1",
        "n_params": int(n_params),
        "params_under_100k": bool(n_params < 100_000),
        "loss": "pairwise-logistic BCEWithLogits(s_i-s_j), target=(lit_i>lit_j)",
        "sampling": f"same-kline_time uniform candidates + accept p=|d|/(|d|+{args.gap_c}) "
                    "(bias to large-gap pairs, anti-noise)",
        "gap_c": float(args.gap_c),
        "pairs_per_epoch": int(pairs_per_epoch),
        "pair_candidates_total": int(n_cand_all),
        "epochs_run": int(epochs_run),
        "epochs_max": int(epochs_max),
        "early_stop_patience": 2,
        "early_stop_on": "VAL IC_lit(raw)",
        "best_val_ic_lit_raw": float(best_ic),
        "train_loss_down": bool(loss_down),
        "epoch_history": hist,
        "direction_note": ("Raw score s ranks literal realizable_ret "
                           "(lit=open[t+1]/open[t+6]-1); executable return "
                           "R_true=open[t+6]/open[t+1]-1 is rank-monotone-decreasing in lit, "
                           "so saved score=-s ranks R_true high=good, consistent with engine TopN. "
                           f"Check raw VAL IC_lit={raw_val_ic:.4f} (must be >0); "
                           "final VAL/TEST IC_true_orientation is the comparable number vs v2 +0.0764."),
        "raw_val_ic_lit": float(raw_val_ic),
        "score_sign": "negated (-raw) to executable direction",
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
    mo = Path(args.metrics_out)
    mo.parent.mkdir(parents=True, exist_ok=True)
    with open(mo, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[ltr] saved {po} rows={len(pred):,} | {mo} total={total:.1f}s", flush=True)
    print(json.dumps({k: metrics[k] for k in
                      ["mode", "arch", "n_params", "epochs_run", "train_loss_down",
                       "raw_val_ic_lit", "val_ic_true_orientation",
                       "test_ic_true_orientation", "test_ic_old_contrast",
                       "device_actual", "total_secs"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
