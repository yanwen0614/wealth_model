"""趋势/波动空仓门验证(诚实无未来函数,复用 backtest.engine).

门信号只用 T 日及之前收盘:等权市场序列 mkt=nanmean(close_m).
门触发日当截面 exp_ret 置 GATE_MASK(-1.0,低于理论下限 -0.5);
配合 exit_on_nonpositive + strong_buy 使引擎真清仓变现金.
有门/无门统一同套引擎参数,对比公平.
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

GATE_MASK = -1.0
EXIT_THR = 0.0
STRONG_BUY = 1e-9
SELL_BUFFER = 500


def market_index(close_m):
    """等权市场序列:逐日收盘 nanmean."""
    return np.nanmean(np.asarray(close_m, dtype=np.float64), axis=0)


def gate_ma(mkt, window):
    """趋势门:T 收盘 < 过去 window 日均值(含 T).预热期 False."""
    mkt = np.asarray(mkt, dtype=np.float64)
    n = len(mkt)
    gate = np.zeros(n, dtype=bool)
    fill = np.where(np.isfinite(mkt), mkt, 0.0)
    c = np.cumsum(fill)
    cnt = np.cumsum(np.isfinite(mkt).astype(int))
    for t in range(window - 1, n):
        pre_c = c[t - window] if t - window >= 0 else 0.0
        pre_k = cnt[t - window] if t - window >= 0 else 0
        k = cnt[t] - pre_k
        ma = (c[t] - pre_c) / k if k > 0 else np.nan
        gate[t] = bool(np.isfinite(mkt[t]) and np.isfinite(ma)
                       and mkt[t] < ma)
    return gate


def gate_vol90(mkt, vol_win=20, lookback=60):
    """波动门:过去 vol_win 日收益波动 > 前 lookback 个波动 P90."""
    mkt = np.asarray(mkt, dtype=np.float64)
    n = len(mkt)
    ret = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = mkt[1:] / mkt[:-1] - 1.0
    vol = np.full(n, np.nan)
    for t in range(vol_win, n):
        w = ret[t - vol_win + 1:t + 1]
        if np.isfinite(w).all():
            vol[t] = float(np.std(w))
    gate = np.zeros(n, dtype=bool)
    for t in range(vol_win + lookback, n):
        hist = vol[t - lookback:t]
        if np.isfinite(hist).all() and np.isfinite(vol[t]):
            gate[t] = bool(vol[t] > np.quantile(hist, 0.9))
    return gate


def apply_gate(exp_ret, dates, trade_days, gate):
    """门触发日当截面 exp_ret 置 GATE_MASK,恢复原值靠原数组."""
    e = np.asarray(exp_ret, dtype=np.float64).copy()
    d = np.asarray(dates).astype("datetime64[D]")
    tdays = np.asarray(trade_days).astype("datetime64[D]")
    lut = {t: i for i, t in enumerate(tdays)}
    for day in np.unique(d):
        j = lut.get(day)
        if j is not None and bool(gate[j]):
            e[d == day] = GATE_MASK
    return e


def run_all(pred_path, ohlc, sizes, gates):
    """全组合回测,返回 {gate: {size: (nav, result)}}."""
    z = np.load(pred_path, allow_pickle=False)
    e = z["exp_ret"].astype(np.float64)
    c = np.asarray(z["codes"])
    d = np.asarray(z["dates"])
    out = {}
    for gname, g in gates.items():
        eg = e if g is None else apply_gate(e, d, ohlc["dates"], g)
        out[gname] = {}
        for s in sizes:
            r = run_backtest_target(eg, c, d, ohlc, target_size=s,
                                    sell_buffer=SELL_BUFFER,
                                    exit_on_nonpositive=True,
                                    exit_threshold=EXIT_THR,
                                    strong_buy_threshold=STRONG_BUY)
            out[gname][s] = (r.nav, r)
    return out


def gate_periods(gate, tdays):
    """触发日起止段(连续触发合并),字符串日期."""
    idx = np.flatnonzero(gate)
    if len(idx) == 0:
        return []
    segs, s0, p0 = [], idx[0], idx[0]
    for i in idx[1:]:
        if i == p0 + 1:
            p0 = i
        else:
            segs.append((s0, p0))
            s0, p0 = i, i
    segs.append((s0, p0))
    return [(str(tdays[a]), str(tdays[b])) for a, b in segs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+",
                    default=["I5R5", "I20R20", "I60R60"])
    ap.add_argument("--years", nargs="+", type=int,
                    default=[2024, 2025, 2026])
    ap.add_argument("--sizes", nargs="+", type=int, default=[20, 100])
    ap.add_argument("--out_dir", default="paper_jkx/logs/gate_2026")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    metrics, gstats = {}, {}
    for m in a.models:
        for y in a.years:
            o = np.load(f"paper_jkx/logs/ohlc_full_{y}.npz",
                        allow_pickle=False)
            ohlc = {k: o[k] for k in ("codes", "dates", "open_m",
                                      "close_m")}
            mkt = market_index(ohlc["close_m"])
            tdays = np.asarray(ohlc["dates"]).astype("datetime64[D]")
            gates = {"nogate": None, "MA20": gate_ma(mkt, 20),
                     "MA60": gate_ma(mkt, 60),
                     "VOL90": gate_vol90(mkt)}
            key0 = f"{m}/{y}"
            for gname, g in gates.items():
                if g is None:
                    continue
                gstats[f"{key0}/{gname}"] = {
                    "gate_days": int(g.sum()),
                    "total_days": len(g),
                    "ratio": float(g.mean()),
                    "periods": gate_periods(g, tdays)}
            res = run_all(f"paper_jkx/logs/preds_{m}_{y}.npz", ohlc,
                          a.sizes, gates)
            for gname, per_size in res.items():
                for s, (nav, r) in per_size.items():
                    mm = nav_metrics(nav)
                    key = f"{key0}/{gname}/target{s}"
                    metrics[key] = {**mm, "final_nav": float(nav[-1]),
                                    "n_closed_trades": len(r.holdings),
                                    "avg_cash_ratio": float(r.avg_cash_ratio)}
                    np.save(os.path.join(a.out_dir, f"nav_{m}_{y}_"
                                         f"{gname}_t{s}.npy"), nav)
                    print(f"{key}: annual={mm['annual']:.4f} "
                          f"sharpe={mm['sharpe']:.3f} mdd={mm['mdd']:.4f} "
                          f"nav={nav[-1]:.3f} cash={r.avg_cash_ratio:.3f} "
                          f"n={len(r.holdings)}", flush=True)
    with open(os.path.join(a.out_dir, "metrics.json"), "w",
              encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "gate_stats.json"), "w",
              encoding="utf-8") as f:
        json.dump(gstats, f, indent=2, ensure_ascii=False)
    rows = [["model", "year", "gate", "size", "annual", "sharpe",
             "mdd", "final_nav", "cash", "trades"]]
    for k, v in metrics.items():
        mm_, yy, gg, ss = k.split("/")
        rows.append([mm_, yy, gg, ss.replace("target", ""),
                     f"{v['annual']:.4f}", f"{v['sharpe']:.3f}",
                     f"{v['mdd']:.4f}", f"{v['final_nav']:.4f}",
                     f"{v['avg_cash_ratio']:.3f}",
                     str(v["n_closed_trades"])])
    with open(os.path.join(a.out_dir, "summary.csv"), "w",
              encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"已保存 {a.out_dir}/metrics.json+gate_stats.json+"
          "summary.csv", flush=True)


if __name__ == "__main__":
    main()
