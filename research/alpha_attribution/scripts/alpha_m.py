"""alpha + m 分解横评: r = m_t + alpha 逐日截面分解 + topN 归因. 只读, 不改仓库.

方法口径与 rv_R346.py / rv_common.py 完全一致(项目 H1-H6 那轮), 仅扩展到全部模型。
用法:
  uv run --project . python alpha_m.py --models A-25,B-25 --tag main
  uv run --project . python alpha_m.py --models all --tag all
产物: %TEMP%/opencode/alpha_m/alpha_m_<tag>.json
"""
import os
import sys
import json
import argparse
import numpy as np

ROOT = r"D:\code\cnn_full_20260905\cnn"
OUTDIR = r"C:\Users\yanwen\AppData\Local\Temp\opencode\alpha_m"

# name -> (preds 路径(相对 ROOT), 真实 horizon)
MODELS = {
    "A-25": ("logs/preds_fullA_2025.npz", 10),
    "A-26": ("logs/preds_fullA_2026.npz", 10),
    "B-25": ("logs/preds_fullB_2025.npz", 10),
    "B-26": ("logs/preds_fullB_2026.npz", 10),
    "J30-25": ("logs/preds_jkxI30_2025.npz", 5),
    "J30-26": ("logs/preds_jkxI30_2026.npz", 5),
    "J5-25": ("logs/preds_jkxI5_2025.npz", 5),
    "J5-26": ("logs/preds_jkxI5_2026.npz", 5),
    "HGB-25": ("logs/tree_verify/preds_p1_hgb_val.npz", 5),
    "HGB-26": ("logs/tree_verify/preds_p1_hgb_test.npz", 5),
    "XGB-25": ("logs/tree_verify/preds_p1_xgb_val.npz", 5),
    "XGB-26": ("logs/tree_verify/preds_p1_xgb_test.npz", 5),
    "HGBroll-25": ("logs/tree_verify/preds_p2_hgb_roll_2025.npz", 5),
    "HGBroll-26": ("logs/tree_verify/preds_p2_hgb_roll_2026.npz", 5),
    "XGBroll-25": ("logs/tree_verify/preds_p2_xgb_roll_2025.npz", 5),
    "XGBroll-26": ("logs/tree_verify/preds_p2_xgb_roll_2026.npz", 5),
}


def load(path):
    p = path if os.path.isabs(path) else os.path.join(ROOT, path)
    z = np.load(p, allow_pickle=False)
    d = np.asarray(z["dates"]).astype("datetime64[D]")
    return (np.asarray(z["exp_ret"], np.float64),
            np.asarray(z["true_ret"], np.float64), d, np.asarray(z["codes"]))


def day_groups(dates):
    order = np.argsort(dates, kind="stable")
    sd = dates[order]
    uniq, start = np.unique(sd, return_index=True)
    return uniq, np.split(order, start[1:])


def tt(x):
    x = np.asarray(x, float)
    if len(x) < 2 or x.std(ddof=1) <= 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))))


def decomp(pred, true, dates):
    """R6/C1 方差分解 + C2 pred 截面 std/与 m_t 相关."""
    uniq, idxs = day_groups(dates)
    n_list, m_list, v_list = [], [], []
    xs, pm, mt = [], [], []
    for ix in idxs:
        r, p = true[ix], pred[ix]
        rv = r[~np.isnan(r)]
        if len(rv) >= 20:
            n_list.append(len(rv)); m_list.append(rv.mean()); v_list.append(rv.var(ddof=1))
        if len(ix) >= 20 and np.isfinite(p).all() and np.isfinite(r).all():
            xs.append(p.std()); pm.append(p.mean()); mt.append(r.mean())
    n = np.array(n_list, float); m = np.array(m_list); v = np.array(v_list)
    N = n.sum(); grand = (n * m).sum() / N
    between = (n * (m - grand) ** 2).sum(); within = (n * v).sum()
    pooled = within / (within + between)
    med = np.median(n)
    keep = (n >= 0.5 * med) & (n <= 1.5 * med)
    denom = n[keep].sum()
    bk = (n[keep] * (m[keep] - (n[keep] * m[keep]).sum() / denom) ** 2).sum()
    wk = (n[keep] * v[keep]).sum()
    pooled_k = wk / (wk + bk)
    pm, mt, xs = map(np.array, (pm, mt, xs))
    return dict(num_days=int(len(n)), n_med=int(med),
                within_pooled=float(pooled), market_pooled=float(1 - pooled),
                within_near=float(pooled_k),
                std_alpha_mean=float(np.sqrt(v).mean()), std_m=float(m.std()),
                std_pred_mean=float(xs.mean()),
                corr_predmean_m=float(np.corrcoef(pm, mt)[0, 1]),
                m_min=float(m.min()), m_max=float(m.max()))


def topn(pred, true, dates, N, horizon, nonoverlap):
    """C4/C5: 取每日 pred 最高的 N 只, 组合收益 = m_t + 选股 alpha."""
    uniq, idxs = day_groups(dates)
    use = set(uniq[::horizon]) if nonoverlap else set(uniq)
    port, mp, alp = [], [], []
    for ix in idxs:
        if dates[ix[0]] not in use:
            continue
        p, r = pred[ix], true[ix]
        ok = np.isfinite(p) & np.isfinite(r)
        if int(ok.sum()) < N:
            continue
        p, r = p[ok], r[ok]
        sel = np.argpartition(-p, N - 1)[:N]
        mm = r.mean(); pr = r[sel].mean()
        port.append(pr); mp.append(mm); alp.append(pr - mm)
    port, mp, alp = map(np.array, (port, mp, alp))
    share = float(mp.mean() / port.mean()) if port.mean() != 0 else float("nan")
    return dict(N=N, nonoverlap=bool(nonoverlap), horizon=horizon, periods=int(len(port)),
                port=float(port.mean()), m=float(mp.mean()), m_t=tt(mp),
                alpha=float(alp.mean()), alpha_t=tt(alp), m_share=share,
                alpha_win=float(np.mean(alp > 0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="all")
    ap.add_argument("--tag", default="all")
    a = ap.parse_args()
    names = list(MODELS) if a.models == "all" else a.models.split(",")
    os.makedirs(OUTDIR, exist_ok=True)
    res = {}
    for name in names:
        path, h = MODELS[name]
        pred, true, dates, codes = load(path)
        print("=" * 100, flush=True)
        d = decomp(pred, true, dates)
        d.update(horizon=h, path=path, n_rows=int(len(pred)),
                 nan_pred=int(np.isnan(pred).sum()), nan_true=int(np.isnan(true).sum()))
        d["topn"] = []
        for N in (10, 50, 200):
            for nonov in (False, True):
                d["topn"].append(topn(pred, true, dates, N, h, nonov))
        res[name] = d
        t10, t200 = d["topn"][0], d["topn"][4]
        print(f"{name:11s} h={h:2d} n={len(pred):>8d} within={d['within_pooled']:.4f} "
              f"market={d['market_pooled']:.4f} | top10 组合={t10['port']:+.5f} "
              f"m={t10['m']:+.5f} a={t10['alpha']:+.5f}(t={t10['alpha_t']:+.2f}) "
              f"m占比={t10['m_share']:.3f} | top200 a={t200['alpha']:+.5f}"
              f"(t={t200['alpha_t']:+.2f}) m占比={t200['m_share']:.3f}", flush=True)
    out = os.path.join(OUTDIR, f"alpha_m_{a.tag}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("WROTE", out, flush=True)


if __name__ == "__main__":
    main()
