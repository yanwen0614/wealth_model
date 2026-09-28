"""连续波动率缩放纸面合成(只读已有 NAV,不碰选股,不跑 GPU).

仓位 = clip(target_vol/realized_vol, floor, 1.0),realized_vol
为 ohlc 等权序列过去 20 日收益 std 年化,只用 T 及之前数据.
合成: scaled_ret[t] = pos[t-1] * base_ret[t],pos 预热期为 1.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
from backtest.engine import nav_metrics

ANN = 252.0


def market_index(close_m):
    """等权市场序列:逐日收盘 nanmean."""
    return np.nanmean(np.asarray(close_m, dtype=np.float64), axis=0)


def realized_vol_ann(mkt, win=20):
    """过去 win 日收益 std 年化;只用 T 及之前,不足置 nan."""
    mkt = np.asarray(mkt, dtype=np.float64)
    n = len(mkt)
    ret = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret[1:] = mkt[1:] / mkt[:-1] - 1.0
    vol = np.full(n, np.nan)
    for t in range(win, n):
        w = ret[t - win + 1:t + 1]
        if np.isfinite(w).all():
            vol[t] = float(np.std(w) * np.sqrt(ANN))
    return vol


def scale_pos(vol, target, floor):
    """连续仓位:clip(target/vol,floor,1),vol 无效时 1."""
    vol = np.asarray(vol, dtype=np.float64)
    pos = np.ones_like(vol)
    ok = np.isfinite(vol) & (vol > 1e-12)
    pos[ok] = np.clip(target / vol[ok], floor, 1.0)
    return pos


def gate_vol90(mkt, vol_win=20, lookback=60):
    """二值 VOL90 门(与 gate_backtest 同口径,仅作对照)."""
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


def synthesize(nav, pos):
    """纸面合成:scaled_ret[t]=pos[t-1]*base_ret[t],起点 1."""
    nav = np.asarray(nav, dtype=np.float64)
    pos = np.asarray(pos, dtype=np.float64)
    n = len(nav)
    out = np.ones(n, dtype=np.float64)
    for t in range(1, n):
        base = nav[t] / nav[t - 1] - 1.0
        out[t] = out[t - 1] * (1.0 + pos[t - 1] * base)
    return out


def aug_stats(dates, nav, scaled, pos_lag):
    """2026-08 反转检验:8 月基/缩放收益与平均仓位."""
    d = np.asarray(dates).astype("datetime64[D]")
    nav = np.asarray(nav, dtype=np.float64)
    scaled = np.asarray(scaled, dtype=np.float64)
    cut = np.asarray("2026-08-01", dtype="datetime64[D]")
    idx = np.flatnonzero(d >= cut)
    if len(idx) == 0:
        return {}
    i0 = int(idx[0])
    pre = nav[i0 - 1] if i0 > 0 else 1.0
    spre = scaled[i0 - 1] if i0 > 0 else 1.0
    return {"base_aug": float(nav[-1] / pre - 1.0),
            "scaled_aug": float(scaled[-1] / spre - 1.0),
            "avg_pos_aug": float(np.mean(pos_lag[idx])),
            "miss": float(nav[-1] / pre - scaled[-1] / spre)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+",
                    default=["I5R5", "I20R20", "I60R60"])
    ap.add_argument("--years", nargs="+", type=int,
                    default=[2024, 2025, 2026])
    ap.add_argument("--targets", nargs="+", type=float,
                    default=[0.15, 0.20])
    ap.add_argument("--floors", nargs="+", type=float,
                    default=[0.2, 0.3])
    ap.add_argument("--vol_win", type=int, default=20)
    ap.add_argument("--out_dir", default="paper_jkx/logs/volscale")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    metrics, aug = {}, {}
    for m in a.models:
        for y in a.years:
            o = np.load(f"paper_jkx/logs/ohlc_full_{y}.npz",
                        allow_pickle=False)
            mkt = market_index(o["close_m"])
            tdays = np.asarray(o["dates"])
            vol = realized_vol_ann(mkt, a.vol_win)
            nav = np.load(f"paper_jkx/logs/backtest_{m}_{y}/"
                          "nav_target100.npy").astype(np.float64)
            assert len(nav) == len(mkt), f"{m}/{y} 长度不一致"
            base = nav_metrics(nav)
            metrics[f"{m}/{y}/base"] = {**base,
                                        "final_nav": float(nav[-1])}
            gate = gate_vol90(mkt)
            pos_bin = np.where(gate, 0.0, 1.0)
            lag_bin = np.ones_like(pos_bin)
            lag_bin[1:] = pos_bin[:-1]
            nav_bin = synthesize(nav, pos_bin)
            mb = nav_metrics(nav_bin)
            metrics[f"{m}/{y}/VOL90paper"] = {
                **mb, "final_nav": float(nav_bin[-1]),
                "avg_pos": float(lag_bin.mean()),
                "gate_days": int(gate.sum())}
            np.save(os.path.join(a.out_dir, f"nav_{m}_{y}_VOL90.npy"),
                    nav_bin)
            for tv in a.targets:
                for fl in a.floors:
                    pos = scale_pos(vol, tv, fl)
                    lag = np.ones_like(pos)
                    lag[1:] = pos[:-1]
                    ns = synthesize(nav, pos)
                    mm = nav_metrics(ns)
                    key = f"{m}/{y}/t{int(tv*100)}_f{fl}"
                    metrics[key] = {**mm,
                                    "final_nav": float(ns[-1]),
                                    "avg_pos": float(lag.mean())}
                    np.save(os.path.join(a.out_dir, f"nav_{m}_{y}_"
                                          f"t{int(tv*100)}_f{fl}.npy"), ns)
                    if y == 2026:
                        aug[key] = aug_stats(tdays, nav, ns, lag)
                    print(f"{key}: annual={mm['annual']:.4f} "
                          f"sharpe={mm['sharpe']:.3f} "
                          f"mdd={mm['mdd']:.4f} nav={ns[-1]:.4f} "
                          f"pos={lag.mean():.3f}", flush=True)
            if y == 2026:
                aug[f"{m}/{y}/VOL90paper"] = aug_stats(
                    tdays, nav, nav_bin, lag_bin)
                aug[f"{m}/{y}/base"] = aug_stats(
                    tdays, nav, nav, np.ones_like(pos_bin))
    with open(os.path.join(a.out_dir, "metrics.json"), "w",
              encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "aug.json"), "w",
              encoding="utf-8") as f:
        json.dump(aug, f, indent=2, ensure_ascii=False)
    rows = [["model", "year", "cfg", "annual", "sharpe", "mdd",
             "final_nav", "avg_pos"]]
    for k, v in metrics.items():
        mm_, yy, cfg = k.split("/")
        rows.append([mm_, yy, cfg, f"{v['annual']:.4f}",
                     f"{v['sharpe']:.3f}", f"{v['mdd']:.4f}",
                     f"{v['final_nav']:.4f}",
                     f"{v.get('avg_pos', 1.0):.3f}"])
    with open(os.path.join(a.out_dir, "summary.csv"), "w",
              encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"已保存 {a.out_dir}/metrics.json+aug.json+summary.csv",
          flush=True)


if __name__ == "__main__":
    main()
