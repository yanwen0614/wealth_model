"""多档 target 净值报告(无指数基准时):复用引擎 + 落盘 metrics/curve."""
import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backtest.engine import nav_metrics, run_backtest_target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", required=True)
    ap.add_argument("--full_ohlc", required=True)
    ap.add_argument("--sizes", type=int, nargs="+", default=[20, 100, 200])
    ap.add_argument("--sell_buffer", type=int, default=500)
    ap.add_argument("--out_dir", default="paper_jkx/logs/backtest_I5R5")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    z = np.load(a.preds, allow_pickle=False)
    o = np.load(a.full_ohlc, allow_pickle=False)
    ohlc = {k: o[k] for k in ("codes", "dates", "open_m", "close_m")}
    e, c, d = z["exp_ret"].astype(np.float64), np.asarray(z["codes"]), np.asarray(z["dates"])
    metrics = {}
    plt.figure(figsize=(12, 7))
    for s in a.sizes:
        r = run_backtest_target(e, c, d, ohlc, target_size=s, sell_buffer=a.sell_buffer)
        m = nav_metrics(r.nav)
        metrics[f"target{s}"] = {**m, "final_nav": float(r.nav[-1]),
                                 "n_closed_trades": len(r.holdings)}
        print(f"target{s}: annual={m['annual']:.4f} sharpe={m['sharpe']:.3f} "
              f"mdd={m['mdd']:.4f} nav={r.nav[-1]:.3f} trades={len(r.holdings)}", flush=True)
        np.save(os.path.join(a.out_dir, f"nav_target{s}.npy"), r.nav)
        plt.plot(r.nav, label=f"target{s}")
    plt.axhline(1.0, color="gray", linewidth=0.8)
    plt.xlabel("Trading days (2019-2025)")
    plt.ylabel("NAV")
    plt.title("Image-CNN I5/R5 target holdings NAV (existing engine, no benchmark)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.savefig(os.path.join(a.out_dir, "nav_curves.png"), dpi=150, bbox_inches="tight")
    plt.close()
    with open(os.path.join(a.out_dir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"已保存 {a.out_dir}/metrics.json + nav_curves.png", flush=True)


if __name__ == "__main__":
    main()
