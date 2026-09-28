"""bottom 负向过滤:买 top 前先剔除 bottomN(多头可执行版,复用 target 引擎).

做法:按日对 exp_ret 截面排名,被剔除的 bottomN 当日 exp_ret 置极小(-1e18),
其余不变,再调 run_backtest_target(默认 sell_buffer=500,无 exit/strong_buy)。
引擎买入带只取前 target_size 名,bottom 永不进带;剔除后不足不补位、留现金。
费用口径与引擎一致(佣金万2.5最低5元+卖出印花税万2.5,无滑点);--slip_bp 可选
买卖各加滑点(以 buy_rate/sell_rate 等比例附加实现,仅做稳健性重验)。
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from backtest.engine import nav_metrics, run_backtest_target

NEG = -1e18
RATE0 = 0.00025


def apply_bottom_filter(exp_ret, dates, n):
    """返回过滤后 exp_ret 拷贝;逐日把 exp_ret 最小的 n 只置 NEG."""
    e = np.asarray(exp_ret, dtype=np.float64).copy()
    if n <= 0:
        return e
    d = np.asarray(dates)
    for day in np.unique(d):
        idx = np.where(d == day)[0]
        if len(idx) <= n:
            continue
        order = np.argsort(e[idx], kind="stable")[:n]
        e[idx[order]] = NEG
    return e


def run_one(exp, codes, dates, ohlc, target, bottom_n, sell_buffer, slip_bp=0.0):
    """单配置回测,返回 (nav, n_trades, metrics, avg_cash)。"""
    ef = apply_bottom_filter(exp, dates, bottom_n)
    slip = float(slip_bp) / 10000.0
    r = run_backtest_target(ef, codes, dates, ohlc, target_size=target,
                            sell_buffer=sell_buffer,
                            buy_rate=RATE0 + slip, sell_rate=RATE0 + slip)
    m = nav_metrics(r.nav)
    m = {**m, "final_nav": float(r.nav[-1]), "n_closed_trades": len(r.holdings),
         "avg_cash_ratio": float(r.avg_cash_ratio)}
    return r.nav, m


def monthly_returns(nav, trade_days):
    """由日净值算自然月收益 {YYYY-MM: ret}。"""
    nav = np.asarray(nav, dtype=np.float64)
    days = np.asarray(trade_days).astype("datetime64[D]")
    months = np.array([str(x)[:7] for x in days.tolist()])
    out = {}
    for mo in sorted(set(months.tolist())):
        ii = np.where(months == mo)[0]
        start_nav = nav[ii[0] - 1] if ii[0] > 0 else 1.0
        out[mo] = float(nav[ii[-1]] / start_nav - 1.0)
    return out


def truncate_inputs(exp, codes, dates, ohlc, cutoff):
    """只保留 <=cutoff(YYYY-MM-DD) 的预测与 OHLC,用于去 8 月稳健性检验。"""
    cut = np.datetime64(cutoff)
    dn = np.asarray(dates).astype("datetime64[D]")
    keep_p = dn <= cut
    td = np.asarray(ohlc["dates"]).astype("datetime64[D]")
    keep_t = td <= cut
    o2 = {"codes": np.asarray(ohlc["codes"]),
          "dates": np.asarray(ohlc["dates"])[keep_t],
          "open_m": np.asarray(ohlc["open_m"])[:, keep_t],
          "close_m": np.asarray(ohlc["close_m"])[:, keep_t]}
    return (np.asarray(exp)[keep_p], np.asarray(codes)[keep_p],
            np.asarray(dates)[keep_p], o2)


def bottom_basket_nav(exp, codes, dates, ohlc, target, sell_buffer):
    """bottom 篮子(买预测最差 topN 作等价多头):年化为负=负向信号有效。"""
    e = np.asarray(exp, dtype=np.float64)
    r = run_backtest_target(-e, codes, dates, ohlc, target_size=target,
                            sell_buffer=sell_buffer)
    m = nav_metrics(r.nav)
    return {"annual": float(m["annual"]), "sharpe": float(m["sharpe"]),
            "final_nav": float(r.nav[-1])}


def load_year(year):
    z = np.load(f"paper_jkx/logs/preds_I5R5_{year}.npz", allow_pickle=False)
    o = np.load(f"paper_jkx/logs/ohlc_full_{year}.npz", allow_pickle=False)
    ohlc = {k: o[k] for k in ("codes", "dates", "open_m", "close_m")}
    return (z["exp_ret"].astype(np.float64), np.asarray(z["codes"]),
            np.asarray(z["dates"]), ohlc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", default=["2024", "2025", "2026"])
    ap.add_argument("--bottom_ns", type=int, nargs="+", default=[0, 100, 200, 500])
    ap.add_argument("--sizes", type=int, nargs="+", default=[20, 100])
    ap.add_argument("--sell_buffer", type=int, default=500)
    ap.add_argument("--slip_bp", type=float, default=0.0)
    ap.add_argument("--aug_cutoff", default="2026-07-31")
    ap.add_argument("--out_dir", default="paper_jkx/logs/bottom_filter")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    rows = []
    navs = {}
    for y in a.years:
        exp, codes, dates, ohlc = load_year(y)
        for t in a.sizes:
            bb = bottom_basket_nav(exp, codes, dates, ohlc, t, a.sell_buffer)
            for n in a.bottom_ns:
                nav, m = run_one(exp, codes, dates, ohlc, t, n,
                                 a.sell_buffer, a.slip_bp)
                rows.append({"year": y, "target": t, "bottom_n": n, **m,
                             "bottom_basket_annual": bb["annual"],
                             "bottom_basket_nav": bb["final_nav"]})
                navs[(y, t, n)] = nav
                print(f"{y} t{t} N{n}: annual={m['annual']:.4f} "
                      f"sharpe={m['sharpe']:.3f} mdd={m['mdd']:.4f} "
                      f"nav={m['final_nav']:.4f} trades={m['n_closed_trades']} "
                      f"cash={m['avg_cash_ratio']:.3f}", flush=True)
                np.save(os.path.join(a.out_dir, f"nav_{y}_t{t}_N{n}.npy"), nav)
    keys = ["annual", "sharpe", "mdd", "final_nav", "n_closed_trades",
            "avg_cash_ratio", "bottom_basket_annual"]
    with open(os.path.join(a.out_dir, "summary.csv"), "w",
              encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "target", "bottom_n"] + keys)
        for r in rows:
            w.writerow([r["year"], r["target"], r["bottom_n"]] +
                       [f"{r[k]:.6f}" for k in keys])
    with open(os.path.join(a.out_dir, "metrics.json"), "w",
              encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    aug = {}
    if "2026" in a.years:
        exp, codes, dates, ohlc = load_year("2026")
        for t in a.sizes:
            for n in a.bottom_ns:
                mo = monthly_returns(navs[("2026", t, n)],
                                     ohlc["dates"])
                aug[f"t{t}_N{n}_aug_ret"] = mo.get("2026-08", float("nan"))
                aug[f"t{t}_N{n}_monthly"] = mo
        e2, c2, d2, o2 = truncate_inputs(exp, codes, dates, ohlc,
                                         a.aug_cutoff)
        for t in a.sizes:
            for n in a.bottom_ns:
                _, m = run_one(e2, c2, d2, o2, t, n, a.sell_buffer,
                               a.slip_bp)
                aug[f"no_aug_t{t}_N{n}_annual"] = m["annual"]
                aug[f"no_aug_t{t}_N{n}_nav"] = m["final_nav"]
        print("2026-08 单月:", {k: round(v, 4) for k, v in aug.items()
              if k.endswith("_aug_ret")}, flush=True)
        print("去 8 月后年化:", {k: round(v, 4) for k, v in aug.items()
              if k.endswith("_annual")}, flush=True)
    with open(os.path.join(a.out_dir, "aug_check.json"), "w",
              encoding="utf-8") as f:
        json.dump(aug, f, indent=2, ensure_ascii=False)
    print(f"已保存 {a.out_dir}/summary.csv + metrics.json + aug_check.json",
          flush=True)


if __name__ == "__main__":
    main()
