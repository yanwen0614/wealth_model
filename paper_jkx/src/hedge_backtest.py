"""对冲合成:多top + 空bottom(引擎无做空,用 -exp_ret 跑同一引擎得空头等价多头)."""
import argparse
import csv
import json
import os

import numpy as np

from backtest.engine import nav_metrics, run_backtest_target

GROUPS = ["I5R5", "I20R20", "I60R60"]
YEARS = ["2024", "2025", "2026"]
SIZES = [20, 100]


def hedge_nav(long_nav, short_nav):
    """对冲日收益 = 多头日收益 - 空头等价多头日收益,首日对齐为 1.0."""
    lo = np.asarray(long_nav, dtype=np.float64)
    sh = np.asarray(short_nav, dtype=np.float64)
    assert len(lo) == len(sh) and len(lo) >= 2
    rl = lo[1:] / lo[:-1] - 1.0
    rs = sh[1:] / sh[:-1] - 1.0
    return np.concatenate([[1.0], (1.0 + rl - rs).cumprod()])


def one(group, year, size, out_dir):
    pp = f"paper_jkx/logs/preds_{group}_{year}.npz"
    op = f"paper_jkx/logs/ohlc_full_{year}.npz"
    lp = f"paper_jkx/logs/backtest_{group}_{year}/nav_target{size}.npy"
    z = np.load(pp, allow_pickle=False)
    o = np.load(op, allow_pickle=False)
    ohlc = {k: o[k] for k in ("codes", "dates", "open_m", "close_m")}
    long_nav = np.load(lp).astype(np.float64)
    e = z["exp_ret"].astype(np.float64)
    c, d = np.asarray(z["codes"]), np.asarray(z["dates"])
    short = run_backtest_target(-e, c, d, ohlc, target_size=size)
    assert len(long_nav) == len(short.nav) == len(ohlc["dates"]), (len(long_nav), len(short.nav))
    hn = hedge_nav(long_nav, short.nav)
    np.save(os.path.join(out_dir, f"nav_hedge_{group}_{year}_t{size}.npy"), hn)
    np.save(os.path.join(out_dir, f"nav_short_{group}_{year}_t{size}.npy"), short.nav)
    ml, ms, mh = nav_metrics(long_nav), nav_metrics(short.nav), nav_metrics(hn)
    return {"group": group, "year": year, "target": size,
            "long": {**ml, "final_nav": float(long_nav[-1])},
            "short": {**ms, "final_nav": float(short.nav[-1])},
            "hedge": {**mh, "final_nav": float(hn[-1])}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default="paper_jkx/logs/hedge_2026")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    rows = [one(g, y, s, a.out_dir) for g in GROUPS for y in YEARS for s in SIZES]
    with open(os.path.join(a.out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    keys = ["annual", "sharpe", "mdd", "final_nav"]
    with open(os.path.join(a.out_dir, "summary.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["group", "year", "target"] + [f"long_{k}" for k in keys]
                   + [f"short_{k}" for k in keys] + [f"hedge_{k}" for k in keys])
        for r in rows:
            w.writerow([r["group"], r["year"], r["target"]]
                       + [f"{r['long'][k]:.6f}" for k in keys]
                       + [f"{r['short'][k]:.6f}" for k in keys]
                       + [f"{r['hedge'][k]:.6f}" for k in keys])
    for r in rows:
        print(f"{r['group']} {r['year']} t{r['target']}: "
              f"long annual={r['long']['annual']:.4f} sharpe={r['long']['sharpe']:.3f} "
              f"mdd={r['long']['mdd']:.4f} nav={r['long']['final_nav']:.4f} | "
              f"hedge annual={r['hedge']['annual']:.4f} sharpe={r['hedge']['sharpe']:.3f} "
              f"mdd={r['hedge']['mdd']:.4f} nav={r['hedge']['final_nav']:.4f}", flush=True)
    print(f"已保存 {a.out_dir}/summary.json + summary.csv", flush=True)


if __name__ == "__main__":
    main()
