"""I5 降频调仓对照:决策降频(stride隔行取)+粘性持有(buffer)+集中度(t20/t50/t100).

只读输入 paper_jkx/logs/preds_I5R5_{YYYY}.npz + ohlc_full_{YYYY}.npz,
复用 backtest.engine run_backtest_target,输出到 paper_jkx/logs/lowfreq/.
"""
import argparse
import csv
import json
import os

import numpy as np

from backtest.engine import nav_metrics, run_backtest_target

YEARS = (2024, 2025, 2026)
SIZES = (20, 50, 100)
BUFFERS = (500, 50)
STRIDES = (1, 2)
FEE = {"buy_rate": 0.00025, "sell_rate": 0.00025,
       "stamp_rate": 0.00025, "min_commission": 5.0}
SLIP = {"buy_rate": 0.00125, "sell_rate": 0.00125,
        "stamp_rate": 0.00025, "min_commission": 5.0}
ZERO = {"buy_rate": 0.0, "sell_rate": 0.0, "stamp_rate": 0.0, "min_commission": 0.0}


def load_year(year):
    """载入单年 preds 与全量 ohlc(返回 exp/codes/dates/sig_days/ohlc)."""
    z = np.load(f"paper_jkx/logs/preds_I5R5_{year}.npz", allow_pickle=False)
    o = np.load(f"paper_jkx/logs/ohlc_full_{year}.npz", allow_pickle=False)
    exp = z["exp_ret"].astype(np.float64)
    codes = np.asarray(z["codes"])
    dates = np.asarray(z["dates"]).astype("datetime64[D]")
    ohlc = {k: o[k] for k in ("codes", "dates", "open_m", "close_m")}
    return exp, codes, dates, np.unique(dates), ohlc


def stride_filter(exp, codes, dates, sig_days, stride):
    """按信号日序号隔行取(stride=2 即降频,决策日减半,持有自然拉长)."""
    keep = {sig_days[i] for i in range(0, len(sig_days), stride)}
    m = np.array([d in keep for d in dates])
    return exp[m], codes[m], dates[m]


def run_one(exp, codes, dates, ohlc, size, buf, fee):
    """单配置回测,返回(result, metrics dict)."""
    r = run_backtest_target(exp, codes, dates, ohlc, target_size=size,
                            sell_buffer=buf, buy_rate=fee["buy_rate"],
                            sell_rate=fee["sell_rate"], stamp_rate=fee["stamp_rate"],
                            min_commission=fee["min_commission"])
    m = nav_metrics(r.nav)
    return r, {"annual": m["annual"], "sharpe": m["sharpe"], "mdd": m["mdd"],
               "final_nav": float(r.nav[-1]), "trades": len(r.holdings),
               "cash": float(r.avg_cash_ratio)}


def halflife(exp, codes, dates, sig_days, ohlc, topn=100):
    """信号半衰期:top篮子第1个5天 vs 第2个5天平均毛收益(open-open)."""
    fc = np.asarray(ohlc["codes"])
    td = np.asarray(ohlc["dates"]).astype("datetime64[D]")
    om = np.asarray(ohlc["open_m"], dtype=np.float64)
    row = {str(c): i for i, c in enumerate(fc)}
    col = {d: i for i, d in enumerate(td.tolist())}
    r1, r2, nd = [], [], 0
    for d in sig_days.tolist():
        p = col.get(d)
        if p is None or p + 11 >= len(td):
            continue
        m = dates == np.datetime64(d)
        e, c = exp[m], codes[m]
        top = np.argsort(-e, kind="stable")[:topn]
        g1, g2 = [], []
        for j in top:
            s = str(c[j])
            i = row.get(s)
            if i is None:
                continue
            a, b, cc = om[i, p + 1], om[i, p + 6], om[i, p + 11]
            if np.isnan(a) or np.isnan(b) or np.isnan(cc) or a <= 0 or b <= 0:
                continue
            g1.append(b / a - 1.0)
            g2.append(cc / b - 1.0)
        if g1 and g2:
            r1.append(float(np.mean(g1)))
            r2.append(float(np.mean(g2)))
            nd += 1
    m1 = float(np.mean(r1)) if r1 else 0.0
    m2 = float(np.mean(r2)) if r2 else 0.0
    return {"leg1_5d": m1, "leg2_5d": m2, "decay_pp": m2 - m1,
            "retain": (m2 / m1) if m1 else 0.0, "n_days": nd}


def grid(out_dir, years):
    """主网格:size×buffer×stride,附零费率毛利算摩擦占比."""
    rows, detail = [], {}
    for y in years:
        exp, codes, dates, sig, ohlc = load_year(y)
        detail[str(y)] = {"halflife": halflife(exp, codes, dates, sig, ohlc)}
        for size in SIZES:
            for buf in BUFFERS:
                for st in STRIDES:
                    e2, c2, d2 = (exp, codes, dates) if st == 1 else stride_filter(
                        exp, codes, dates, sig, st)
                    tag = f"{y}_t{size}_b{buf}_s{st}"
                    r, m = run_one(e2, c2, d2, ohlc, size, buf, FEE)
                    rg, _ = run_one(e2, c2, d2, ohlc, size, buf, ZERO)
                    fric = float(rg.nav[-1] - r.nav[-1])
                    gp = float(rg.nav[-1] - 1.0)
                    m.update({"fric_pp": fric, "gross_nav": float(rg.nav[-1]),
                              "fric_share": fric / gp if gp > 1e-9 else 0.0})
                    detail[str(y)][tag] = {**m, "nav": [float(x) for x in r.nav]}
                    rows.append({"year": y, "size": size, "buf": buf, "stride": st, **m})
                    print(f"{tag}: ann={m['annual']:.4f} shp={m['sharpe']:.2f} "
                          f"mdd={m['mdd']:.3f} nav={m['final_nav']:.4f} "
                          f"tr={m['trades']} fric={fric:.4f}", flush=True)
    return rows, detail


def aug_excl(detail, ohlc26):
    """2026-08剔除:截断8月前NAV重算metrics,检验是否错过V型反弹."""
    td = np.asarray(ohlc26["dates"]).astype("datetime64[D]")
    cut = int(np.searchsorted(td, np.datetime64("2026-08-01")))
    out = {}
    for tag, v in detail["2026"].items():
        if tag == "halflife" or "nav" not in v:
            continue
        nav = np.asarray(v["nav"])[:cut]
        m = nav_metrics(nav)
        out[tag] = {"final_nav": float(nav[-1]), "annual": m["annual"],
                    "sharpe": m["sharpe"], "mdd": m["mdd"]}
    return {"cut_days": cut, "results": out}


def slippage(out_rows, years):
    """买卖各+10bp滑点重验(t20/t100×full/low2,buffer=500)."""
    out = {}
    for y in years:
        exp, codes, dates, sig, ohlc = load_year(y)
        for size in (20, 100):
            for st in STRIDES:
                e2, c2, d2 = (exp, codes, dates) if st == 1 else stride_filter(
                    exp, codes, dates, sig, st)
                _, m = run_one(e2, c2, d2, ohlc, size, 500, SLIP)
                out[f"{y}_t{size}_s{st}"] = m
                print(f"SLIP {y}_t{size}_s{st}: nav={m['final_nav']:.4f} "
                      f"ann={m['annual']:.4f} tr={m['trades']}", flush=True)
    out_rows.append(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default="paper_jkx/logs/lowfreq")
    ap.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    ap.add_argument("--no_slip", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    rows, detail = grid(a.out_dir, tuple(a.years))
    with open(os.path.join(a.out_dir, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    _, _, _, _, ohlc26 = load_year(2026)
    aug = aug_excl(detail, ohlc26)
    slip = {} if a.no_slip else slippage([], tuple(a.years))
    for v in detail.values():
        for tag in list(v):
            if tag != "halflife" and "nav" in v[tag]:
                del v[tag]["nav"]
    with open(os.path.join(a.out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"grid": detail, "aug_excl_2026": aug, "slippage_10bp": slip},
                  f, indent=2, ensure_ascii=False)
    print(f"已保存 {a.out_dir}/summary.csv + metrics.json", flush=True)


if __name__ == "__main__":
    main()
