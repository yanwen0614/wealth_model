"""高确信度加权验证:分桶单调性 + 加权组合 + 2026-08 剔除 + I60 校准诊断.

方法声明(全文统一):
- prob = exp_ret + 0.5(npz 无 prob 键,由 exp_ret 派生).
- 加权组合采用滚动固定持有合成:每日决策日 T 按 exp_ret 取 top100,
  T+1 open 买入、T+6 open 卖出(horizon=5,与引擎 run_backtest 同口径;
  true_ret 经核验与该口径 corr=0.997,等价可交易).
  每日新批投入 nav/5,批内按权重分配;费率/最低佣金/涨停跳过与引擎一致
  (复用 commission/net_return_after_fees,capital=1e6).
  权重:equal 等权 / rank 线性秩加权((N+1-rank)/sum) /
  prob (prob-0.5).clip(min=0) 加权(全零时回退等权).
- 分层合成 tiered = 0.5*NAV_top20 + 0.5*NAV_21_100,资本各半、
  各自滚动合成,作为"分层 target 近似"对照.
- 事前阈值仅 3 个:0.52 / 0.53 / 0.55,全部报告,不挑最优.
"""

import argparse
import json
import os

import numpy as np

from backtest.engine import nav_metrics, net_return_after_fees, run_backtest_target

TAG_I5 = "I5R5"
TAG_I60 = "I60R60"
YEARS = (2024, 2025, 2026)
TAIL_THRS = (0.52, 0.53, 0.55)
HORIZON = 5
TOPN = 100
CAPITAL = 1_000_000.0
AUG_CUTOFF = np.datetime64("2026-08-01")
OUT_DIR = "paper_jkx/logs/confweight"


def quintile_table(prob, true):
    """prob 五等分桶(等样本量),返回每桶 dict 列表."""
    qs = np.quantile(prob, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    rows = []
    for b in range(5):
        lo, hi = qs[b], qs[b + 1]
        m = (prob >= lo) & (prob <= hi if b == 4 else prob < hi)
        # 边界重复导致空桶时回退到等宽划分
        if m.sum() == 0:
            m = np.zeros_like(prob, dtype=bool)
        p, t = prob[m], true[m]
        rows.append({"bucket": b + 1, "prob_lo": float(lo), "prob_hi": float(hi),
                     "n": int(m.sum()), "mean_prob": float(p.mean()) if len(p) else float("nan"),
                     "mean_true": float(t.mean()) if len(t) else float("nan"),
                     "acc": float(((p > 0.5) == (t > 0)).mean()) if len(p) else float("nan"),
                     "pos_rate": float((t > 0).mean()) if len(t) else float("nan")})
    return rows


def tail_table(prob, true, thrs=TAIL_THRS):
    """事前阈值尾部统计,全部阈值如实报告."""
    base = float(true.mean())
    rows = []
    for thr in thrs:
        m = prob > thr
        p, t = prob[m], true[m]
        rows.append({"thr": thr, "n": int(m.sum()), "share": float(m.mean()),
                     "mean_prob": float(p.mean()) if len(p) else float("nan"),
                     "mean_true": float(t.mean()) if len(t) else float("nan"),
                     "lift_vs_base": float(t.mean() - base) if len(t) else float("nan"),
                     "acc": float(((p > 0.5) == (t > 0)).mean()) if len(p) else float("nan")})
    return rows, base


def load_year(tag, year):
    """载入某年 preds 与矩阵 ohlc,返回字典."""
    z = np.load(f"paper_jkx/logs/preds_{tag}_{year}.npz", allow_pickle=False)
    o = np.load(f"paper_jkx/logs/ohlc_full_{year}.npz", allow_pickle=False)
    exp = z["exp_ret"].astype(np.float64)
    codes = np.asarray(z["codes"])
    dates = np.asarray(z["dates"]).astype("datetime64[D]")
    true_ret = z["true_ret"].astype(np.float64)
    prob = exp + 0.5
    tdays = np.asarray(o["dates"]).astype("datetime64[D]")
    return {"exp": exp, "codes": codes, "dates": dates, "true": true_ret, "prob": prob,
            "ohlc": {"codes": np.asarray(o["codes"]), "dates": tdays,
                     "open_m": np.asarray(o["open_m"], dtype=np.float64),
                     "close_m": np.asarray(o["close_m"], dtype=np.float64)}}


def _batch_weights(order_exp, topn, mode):
    """批内权重:equal / rank 线性 / prob 超 0.5 部分."""
    k = len(order_exp)
    if k == 0:
        return np.zeros(0)
    if mode == "equal":
        return np.full(k, 1.0 / k)
    if mode == "rank":
        w = (topn + 1.0 - np.arange(1, k + 1)) / max(topn, 1)
        return w / w.sum()
    if mode == "prob":
        w = np.clip(order_exp + 0.5 - 0.5, 0.0, None)
        if w.sum() <= 0:
            return np.full(k, 1.0 / k)
        return w / w.sum()
    raise ValueError(f"未知 mode={mode}")


def rolling_weighted_nav(exp, codes, dates, ohlc, mode, topn=TOPN, horizon=HORIZON, fee=True):
    """滚动固定持有加权合成,涨停跳过/费率与引擎同口径,返回 (nav, 批数, 跳过数).

    fee=False 时为无费用毛收益口径(隔离加权效应本身,不受最低佣金地板干扰).
    """
    exp = np.asarray(exp, dtype=np.float64)
    codes_arr = np.asarray(codes)
    dates_n = np.asarray(dates).astype("datetime64[D]")
    tdays = np.asarray(ohlc["dates"]).astype("datetime64[D]")
    n_days = len(tdays)
    open_m = np.asarray(ohlc["open_m"], dtype=np.float64)
    close_m = np.asarray(ohlc["close_m"], dtype=np.float64)
    row_of = {str(c): i for i, c in enumerate(np.asarray(ohlc["codes"]))}
    order_of_day = {}
    for d in np.unique(dates_n):
        m = dates_n == d
        e = exp[m]
        idx = np.argsort(-e, kind="stable")[:topn]
        order_of_day[d] = (np.asarray(codes_arr[m])[idx], e[idx])
    day_gw = [[] for _ in range(n_days)]
    n_batch, n_skip = 0, 0
    for i in range(n_days):
        d = tdays[i]
        end_i = i + 1 + horizon
        if end_i >= n_days or d not in order_of_day:
            continue
        cs, es = order_of_day[d]
        items = []
        for s_raw, ev in zip(cs.tolist(), es.tolist()):
            s = s_raw.decode() if isinstance(s_raw, bytes) else str(s_raw)
            r = row_of.get(s)
            if r is None:
                continue
            o1, o6, pc = open_m[r, i + 1], open_m[r, end_i], close_m[r, i]
            if np.isnan(o1) or np.isnan(o6) or np.isnan(pc):
                continue
            thr = 1.198 if s[:3] in ("300", "688") else 1.098
            if o1 >= pc * thr:
                n_skip += 1
                continue
            items.append((float(o6) / float(o1) - 1.0, float(ev)))
        if not items:
            continue
        w = _batch_weights(np.array([v[1] for v in items]), topn, mode)
        day_gw[i] = [(g, float(ww)) for (g, _), ww in zip(items, w.tolist())]
        n_batch += 1
    nav = np.ones(n_days, dtype=np.float64)
    pending: dict = {}
    nb = max(int(horizon), 1)
    for i in range(n_days):
        if i > 0:
            nav[i] = nav[i - 1]
        nav[i] += pending.pop(i, 0.0)
        gw = day_gw[i]
        if not gw:
            continue
        end_i = i + 1 + horizon
        if end_i >= n_days:
            continue
        gain = 0.0
        for g, w in gw:
            alloc = nav[i] / nb * w
            if fee:
                notion = alloc * CAPITAL
                gain += alloc * net_return_after_fees(notion, notion * (1.0 + g))
            else:
                gain += alloc * g
        pending[end_i] = pending.get(end_i, 0.0) + gain
    return nav, n_batch, n_skip


def run_year_weights(data, modes=("equal", "rank", "prob")):
    """某年 top100 三种加权 + top20/21-100/分层合成,统一返回 (metrics, navs)."""
    exp, codes, dates = data["exp"], data["codes"], data["dates"]
    ohlc = data["ohlc"]
    metrics, navs = {}, {}
    for mode in modes:
        nav, nb, ns = rolling_weighted_nav(exp, codes, dates, ohlc, mode)
        m = nav_metrics(nav)
        metrics[f"w_{mode}"] = {**m, "final_nav": float(nav[-1]), "n_batch": nb, "n_skip": ns}
        navs[f"w_{mode}"] = nav
    nav20, nb20, ns20 = rolling_weighted_nav(exp, codes, dates, ohlc, "equal", topn=20)
    metrics["w_top20"] = {**nav_metrics(nav20), "final_nav": float(nav20[-1]),
                          "n_batch": nb20, "n_skip": ns20}
    navs["w_top20"] = nav20
    nav21100 = _rankslice_nav(exp, codes, dates, ohlc, lo=21, hi=100)
    metrics["w_21_100"] = {**nav_metrics(nav21100), "final_nav": float(nav21100[-1])}
    navs["w_21_100"] = nav21100
    tiered = 0.5 * nav20 + 0.5 * nav21100
    metrics["w_tiered"] = {**nav_metrics(tiered), "final_nav": float(tiered[-1])}
    navs["w_tiered"] = tiered
    gross = {}
    for mode in modes:
        nav, _, _ = rolling_weighted_nav(exp, codes, dates, ohlc, mode, fee=False)
        m = nav_metrics(nav)
        metrics[f"g_{mode}"] = {**m, "final_nav": float(nav[-1])}
        gross[mode] = nav
        navs[f"g_{mode}"] = nav
    nav20g, _, _ = rolling_weighted_nav(exp, codes, dates, ohlc, "equal", topn=20, fee=False)
    nav21g = _rankslice_nav_fee(exp, codes, dates, ohlc, fee=False)
    tieredg = 0.5 * nav20g + 0.5 * nav21g
    metrics["g_tiered"] = {**nav_metrics(tieredg), "final_nav": float(tieredg[-1])}
    navs["g_tiered"] = tieredg
    for ts in (20, 100):
        r = run_backtest_target(exp, codes, dates, ohlc, target_size=ts)
        m = nav_metrics(r.nav)
        metrics[f"target{ts}"] = {**m, "final_nav": float(r.nav[-1]),
                                  "n_closed_trades": len(r.holdings)}
        navs[f"target{ts}"] = np.asarray(r.nav, dtype=np.float64)
    return metrics, navs


def _rankslice_nav(exp, codes, dates, ohlc, lo=21, hi=100, fee=True):
    """取每日 rank[lo..hi] 等权滚动合成(分层合成的第二腿)."""
    exp = np.asarray(exp, dtype=np.float64)
    codes_arr, dates_n = np.asarray(codes), np.asarray(dates).astype("datetime64[D]")
    keep_m = np.zeros(len(exp), dtype=bool)
    for d in np.unique(dates_n):
        m = dates_n == d
        idx = np.argsort(-exp[m], kind="stable")[lo - 1:hi]
        mm = np.where(m)[0][idx]
        keep_m[mm] = True
    nav, _, _ = rolling_weighted_nav(exp[keep_m], codes_arr[keep_m], dates_n[keep_m],
                                     ohlc, "equal", topn=hi - lo + 1, fee=fee)
    return nav


def _rankslice_nav_fee(exp, codes, dates, ohlc, fee=False):
    return _rankslice_nav(exp, codes, dates, ohlc, fee=fee)


def august_robustness(data, year_metrics):
    """2026-08 剔除稳健性:决策日<2026-08-01 重算 + 全序列在截止日处分段归因."""
    out = {"cutoff": str(AUG_CUTOFF)}
    exp = np.asarray(data["exp"])
    pre = np.asarray(data["dates"]).astype("datetime64[D]") < AUG_CUTOFF
    out["pre_share"] = float(pre.mean())
    prob, true = data["prob"][pre], data["true"][pre]
    out["buckets_pre"] = quintile_table(prob, true)
    out["tails_pre"], out["base_pre"] = tail_table(prob, true)
    out["tails_full"], out["base_full"] = tail_table(data["prob"], data["true"])
    sub = {"exp": exp[pre], "codes": np.asarray(data["codes"])[pre],
           "dates": np.asarray(data["dates"])[pre], "true": true, "prob": prob,
           "ohlc": data["ohlc"]}
    for mode in ("equal", "rank", "prob"):
        nav, nb, ns = rolling_weighted_nav(sub["exp"], sub["codes"], sub["dates"],
                                           sub["ohlc"], mode)
        tdays = np.asarray(sub["ohlc"]["dates"]).astype("datetime64[D]")
        cut = int((tdays < AUG_CUTOFF).sum())
        nav_pre = float(nav[max(cut - 1, 0)])
        out[f"w_{mode}_preAug"] = {**nav_metrics(nav[:cut]), "final_nav_pre": nav_pre,
                                   "n_batch": nb, "n_skip": ns, "cut_days": cut}
    for key, m in year_metrics.items():
        nav = m.get("_nav")
        if nav is None:
            continue
        tdays = np.asarray(data["ohlc"]["dates"]).astype("datetime64[D]")
        cut = int((tdays < AUG_CUTOFF).sum())
        nav_pre = float(nav[max(cut - 1, 0)])
        out[f"{key}_split"] = {"nav_preAug": nav_pre, "nav_full": float(nav[-1]),
                               "aug_ret": float(nav[-1] / nav_pre - 1.0),
                               "pre_ret": float(nav_pre - 1.0)}
    return out


def _auc_rank(prob, label):
    """Mann-Whitney 秩 AUC,纯 numpy."""
    p = np.asarray(prob, dtype=np.float64)
    y = np.asarray(label).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    ranks = np.argsort(np.argsort(p, kind="stable"), kind="stable") + 1.0
    return float((ranks[y].sum() - n1 * (n1 + 1.0) / 2.0) / (n1 * n0))


def reliability(prob, true, n_bins=10):
    """可靠性诊断:等样本分桶 + ECE/Brier/bias/平移校准前后对照(样本内诊断上限)."""
    p = np.asarray(prob, dtype=np.float64)
    y = (np.asarray(true, dtype=np.float64) > 0).astype(float)
    base = float(y.mean())
    bias = float(p.mean() - base)
    qs = np.quantile(p, np.linspace(0.0, 1.0, n_bins + 1))
    rows, ece, brier = [], 0.0, float(np.mean((p - y) ** 2))
    for b in range(n_bins):
        lo, hi = qs[b], qs[b + 1]
        m = (p >= lo) & (p <= hi if b == n_bins - 1 else p < hi)
        if m.sum() == 0:
            continue
        mp, hr = float(p[m].mean()), float(y[m].mean())
        rows.append({"bin": b + 1, "prob_lo": float(lo), "prob_hi": float(hi),
                     "n": int(m.sum()), "mean_prob": mp, "hit_rate": hr,
                     "gap": mp - hr})
        ece += float(m.mean()) * abs(mp - hr)
    p2 = np.clip(p - bias, 0.0, 1.0)
    ece2 = 0.0
    qs2 = np.quantile(p2, np.linspace(0.0, 1.0, n_bins + 1))
    for b in range(n_bins):
        lo, hi = qs2[b], qs2[b + 1]
        m = (p2 >= lo) & (p2 <= hi if b == n_bins - 1 else p2 < hi)
        if m.sum() == 0:
            continue
        ece2 += float(m.mean()) * abs(float(p2[m].mean()) - float(y[m].mean()))
    acc = float(((p > 0.5) == (y > 0.5)).mean())
    acc2 = float(((p2 > 0.5) == (y > 0.5)).mean())
    return {"n": len(p), "base_rate": base, "mean_prob": float(p.mean()), "bias": bias,
            "acc": acc, "acc_shift": acc2, "auc": _auc_rank(p, y),
            "brier": brier, "brier_shift": float(np.mean((p2 - y) ** 2)),
            "ece": ece, "ece_shift": ece2, "bins": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default=OUT_DIR)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    buckets_all, tails_all, wmetrics_all, nav_store = [], [], {}, {}
    for year in YEARS:
        d = load_year(TAG_I5, year)
        for r in quintile_table(d["prob"], d["true"]):
            buckets_all.append({"year": year, **r})
        trows, base = tail_table(d["prob"], d["true"])
        for r in trows:
            tails_all.append({"year": year, "base": base, **r})
        wm, navs = run_year_weights(d)
        row = {"year": year}
        for k, m in wm.items():
            row[k] = {kk: vv for kk, vv in m.items()}
            nav_store[f"I5_{year}_{k}"] = navs[k]
        wmetrics_all[str(year)] = row
        with_nav = {k: {**m, "_nav": navs[k]} for k, m in wm.items()}
        if year == 2026:
            aug = august_robustness(d, with_nav)
            with open(os.path.join(a.out_dir, "aug_robust.json"), "w", encoding="utf-8") as f:
                json.dump(aug, f, indent=2, ensure_ascii=False)
    calib = {}
    for tag in (TAG_I5, TAG_I60):
        for year in YEARS:
            d = load_year(tag, year)
            calib[f"{tag}_{year}"] = reliability(d["prob"], d["true"])
        pall = np.concatenate([load_year(tag, y)["prob"] for y in YEARS])
        tall = np.concatenate([load_year(tag, y)["true"] for y in YEARS])
        calib[f"{tag}_pooled"] = reliability(pall, tall)
    with open(os.path.join(a.out_dir, "buckets_I5.json"), "w", encoding="utf-8") as f:
        json.dump(buckets_all, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "tails_I5.json"), "w", encoding="utf-8") as f:
        json.dump(tails_all, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "weights_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(wmetrics_all, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "calib.json"), "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, ensure_ascii=False)
    np.savez_compressed(os.path.join(a.out_dir, "nav_weights.npz"), **nav_store)
    for r in buckets_all:
        print(f"BKT I5 {r['year']} b{r['bucket']} n={r['n']} p=[{r['prob_lo']:.3f},{r['prob_hi']:.3f}] "
              f"meanp={r['mean_prob']:.4f} meantrue={r['mean_true']:.4f} acc={r['acc']:.3f}")
    for r in tails_all:
        print(f"TAIL I5 {r['year']} thr={r['thr']} share={r['share']:.3f} n={r['n']} "
              f"meantrue={r['mean_true']:.4f} lift={r['lift_vs_base']:.4f} acc={r['acc']:.3f}")
    for y, row in wmetrics_all.items():
        for k, m in row.items():
            if k == "year":
                continue
            print(f"W {y} {k}: annual={m['annual']:.4f} sharpe={m['sharpe']:.3f} "
                  f"mdd={m['mdd']:.4f} nav={m['final_nav']:.4f}")
    for k, c in calib.items():
        print(f"CAL {k}: base={c['base_rate']:.4f} meanp={c['mean_prob']:.4f} bias={c['bias']:+.4f} "
              f"acc={c['acc']:.3f}->shift{c['acc_shift']:.3f} auc={c['auc']:.3f} "
              f"ece={c['ece']:.4f}->{c['ece_shift']:.4f} brier={c['brier']:.4f}->{c['brier_shift']:.4f}")
    print(f"已落盘 {a.out_dir}/buckets_I5.json tails_I5.json weights_metrics.json calib.json "
          f"nav_weights.npz aug_robust.json")


if __name__ == "__main__":
    main()
