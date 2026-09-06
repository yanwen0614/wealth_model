"""逐日回测 CLI 报告：preds npz(多模型) + ohlc 路径表 → metrics.json + 持仓csv + 净值png.

preds npz 需含 exp_ret/true_ret/dates/codes（codes 由新版 eval_bins_mapping.py --preds_cache 产出，
旧 npz 缺 codes 会显式报错）。对每个 preds × 每档 TopN 跑 backtest.engine.run_backtest，
并计算全截面同口径等权基准（benchmark_nav），输出超额（算术差）。

用法：
  uv run --project . python scripts/run_backtest.py \
    --preds logs/preds_dual_ep7.npz logs/preds_base_ep4.npz --ohlc logs/ohlc_path_val.npz
  uv run --project . python scripts/run_backtest.py --mode target \
    --preds logs/preds_dual_ep7.npz --full_ohlc logs/ohlc_full_val.npz \
    --target_size 100 --sell_buffer 200 --min_edge 0.01 --edge_tail_pct 0.3
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

from backtest.engine import benchmark_nav, nav_metrics, run_backtest, run_backtest_target  # noqa: E402
from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays  # noqa: E402

OHLC_KEYS = ("codes", "dates", "t_close", "open_t1", "open_t6")
FULL_OHLC_KEYS = ("codes", "dates", "open_m", "close_m")
NOTE = ("卖出未做跌停检查（简化口径）；策略与基准均为 open-open 口径"
        "(T+1 open 买入, T+1+horizon open 卖出)，双边成本一次性扣减")
NOTE_TARGET = ("卖出未做跌停检查（简化口径）；目标持仓模式：买入带 rank<=target_size，"
               "卖出带 rank>target_size+sell_buffer，min_edge 过滤命中空槽留现金，"
               "float 股数等权（预算=nav/target_size），双边成本各计一次")


def load_preds(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    arrays = {key: z[key] for key in PREDICTION_CACHE_KEYS if key in z.files}
    validate_prediction_cache_arrays(arrays, path)
    return {"exp_ret": arrays["exp_ret"].astype(np.float64), "true_ret": arrays["true_ret"].astype(np.float64),
            "dates": arrays["dates"], "codes": arrays["codes"]}


def load_ohlc(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    missing = [k for k in OHLC_KEYS if k not in z.files]
    if missing:
        raise ValueError(f"{path} 缺少键 {missing}")
    return {k: z[k] for k in OHLC_KEYS}


def load_full_ohlc(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    missing = [k for k in FULL_OHLC_KEYS if k not in z.files]
    if missing:
        raise ValueError(f"{path} 缺少键 {missing}（请用 build_ohlc_path.py --full 产出全期矩阵 npz）")
    return {k: z[k] for k in FULL_OHLC_KEYS}


def save_holdings_csv(holdings: np.ndarray, out_csv: str) -> None:
    cols = ["entry_date", "exit_date", "code", "weight", "open_t1", "open_t6", "ret_gross", "ret_net"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for h in holdings:
            w.writerow([str(h["entry_date"]), str(h["exit_date"]), str(h["code"]),
                        float(h["weight"]), float(h["open_t1"]), float(h["open_t6"]),
                        float(h["ret_gross"]), float(h["ret_net"])])


def run_target_mode(args, out_dir: str) -> None:
    if not args.full_ohlc:
        raise ValueError("--mode target 需要 --full_ohlc 指定全期日频矩阵 npz（build_ohlc_path.py --full 产出）")
    full_ohlc = load_full_ohlc(args.full_ohlc)
    print(f"[bt] full_ohlc 矩阵: {args.full_ohlc} "
          f"({len(full_ohlc['codes']):,} codes x {len(full_ohlc['dates']):,} 交易日)")
    metrics = {"note": NOTE_TARGET, "mode": "target", "cost_rate": args.cost_rate,
               "target_size": args.target_size, "sell_buffer": args.sell_buffer,
               "min_edge": args.min_edge, "edge_tail_pct": args.edge_tail_pct, "models": {}}
    plt.figure(figsize=(12, 7))
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        res = run_backtest_target(preds["exp_ret"], preds["codes"], preds["dates"], full_ohlc,
                                  target_size=args.target_size, sell_buffer=args.sell_buffer,
                                  min_edge=args.min_edge, edge_tail_pct=args.edge_tail_pct,
                                  cost_rate=args.cost_rate)
        m = nav_metrics(res.nav)
        n_limit = sum(int(v.get("limit_up", 0)) for v in res.skipped.values())
        n_edge = sum(int(v.get("min_edge", 0)) for v in res.skipped.values())
        metrics["models"][name] = {"target": {**m, "final_nav": float(res.nav[-1]),
                                              "n_closed_trades": len(res.holdings),
                                              "n_skipped_limit_up": n_limit,
                                              "n_skipped_min_edge": n_edge}}
        print(f"[bt] === {name} === target(size={args.target_size}, buffer={args.sell_buffer}, "
              f"min_edge={args.min_edge}, tail={args.edge_tail_pct}): annual={m['annual']:.4f} "
              f"sharpe={m['sharpe']:.3f} mdd={m['mdd']:.4f} win={m['win_rate']:.4f} "
              f"平仓笔数={len(res.holdings)} 涨停跳过={n_limit} min_edge跳过={n_edge}")
        save_holdings_csv(res.holdings, os.path.join(out_dir, f"holdings_{name}_target.csv"))
        plt.plot(res.nav, label=f"{name} target{args.target_size}")
    plt.axhline(1.0, color="gray", linewidth=0.8)
    plt.xlabel("交易日序号")
    plt.ylabel("净值")
    plt.title(f"目标持仓回测 (size={args.target_size}, buffer={args.sell_buffer}, "
              f"min_edge={args.min_edge}, 成本={args.cost_rate:.2%})")
    plt.grid(True, alpha=0.3)
    plt.legend()
    png_path = os.path.join(out_dir, "nav_curves.png")
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt] 指标已保存: {metrics_path}")
    print(f"[bt] 净值曲线已保存: {png_path}")
    print(f"[bt] 持仓明细已保存: holdings_<model>_target.csv @ {out_dir}")


def main():
    args = parse_args()
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir if args.out_dir else os.path.join("logs", f"backtest_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    if args.mode == "target":
        run_target_mode(args, out_dir)
        return
    if not args.ohlc:
        raise ValueError("--mode rolling 需要 --ohlc 路径表 npz")
    ohlc = load_ohlc(args.ohlc)
    print(f"[bt] ohlc 路径表: {args.ohlc} ({len(ohlc['codes']):,} 行)")
    metrics = {"note": NOTE, "cost_rate": args.cost_rate, "horizon": args.horizon,
               "topn_list": list(args.topn), "models": {}}
    plt.figure(figsize=(12, 7))
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        e, c, d = preds["exp_ret"], preds["codes"], preds["dates"]
        bench = benchmark_nav(c, d, ohlc, cost_rate=args.cost_rate, horizon=args.horizon)
        bm = nav_metrics(bench)
        metrics["models"][name] = {"benchmark": {**bm, "final_nav": float(bench[-1])}}
        print(f"[bt] === {name} === 基准(全截面等权): annual={bm['annual']:.4f} sharpe={bm['sharpe']:.3f} "
              f"mdd={bm['mdd']:.4f} win={bm['win_rate']:.4f}")
        for n in args.topn:
            res = run_backtest(e, c, d, ohlc, topn=n, cost_rate=args.cost_rate, horizon=args.horizon)
            m = nav_metrics(res.nav)
            metrics["models"][name][f"topn{n}"] = {
                **m, "final_nav": float(res.nav[-1]),
                "excess_annual": m["annual"] - bm["annual"],
                "n_holdings": len(res.holdings), "n_skipped": sum(res.skipped.values())}
            print(f"[bt]   top{n}: annual={m['annual']:.4f} sharpe={m['sharpe']:.3f} mdd={m['mdd']:.4f} "
                  f"win={m['win_rate']:.4f} 超额={m['annual'] - bm['annual']:+.4f} "
                  f"持仓批次数={len(res.holdings)} 涨停跳过={int(sum(res.skipped.values()))}")
            save_holdings_csv(res.holdings, os.path.join(out_dir, f"holdings_{name}_topn{n}.csv"))
            plt.plot(res.nav, label=f"{name} top{n}")
        plt.plot(bench, label=f"{name} 基准(全截面等权)", linestyle="--", alpha=0.6)
    plt.axhline(1.0, color="gray", linewidth=0.8)
    plt.xlabel("交易日序号")
    plt.ylabel("净值")
    plt.title(f"逐日回测净值 (open-open, horizon={args.horizon}, 成本={args.cost_rate:.2%})")
    plt.grid(True, alpha=0.3)
    plt.legend()
    png_path = os.path.join(out_dir, "nav_curves.png")
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt] 指标已保存: {metrics_path}")
    print(f"[bt] 净值曲线已保存: {png_path}")
    print(f"[bt] 持仓明细已保存: holdings_<model>_topn<n>.csv @ {out_dir}")


def parse_args():
    p = argparse.ArgumentParser(description="逐日回测报告（open-open 口径）")
    p.add_argument("--preds", nargs="+", required=True, help="preds npz 路径（exp_ret/true_ret/dates/codes），多个做模型对比")
    p.add_argument("--ohlc", default=None, help="rolling 模式必填：ohlc 路径表 npz（codes/dates/t_close/open_t1/open_t6）")
    p.add_argument("--topn", nargs="+", type=int, default=[5, 10, 20])
    p.add_argument("--cost_rate", type=float, default=0.0015)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--mode", choices=["rolling", "target"], default="rolling",
                   help="rolling=固定持有 horizon 滚动（默认）；target=目标持仓（滞后带+min_edge 过滤）")
    p.add_argument("--target_size", type=int, default=100, help="target 模式：买入带 rank<=target_size")
    p.add_argument("--sell_buffer", type=int, default=200, help="target 模式：rank>target_size+sell_buffer 才卖出")
    p.add_argument("--min_edge", type=float, default=0.01, help="target 模式：费用感知过滤的预测分数阈值")
    p.add_argument("--edge_tail_pct", type=float, default=0.3, help="target 模式：min_edge 过滤只作用于买入带后 edge_tail_pct 名")
    p.add_argument("--full_ohlc", default=None, help="target 模式必填：全期日频矩阵 npz（codes/dates/open_m/close_m）")
    p.add_argument("--out_dir", default=None, help="默认 logs/backtest_<时间戳>")
    return p.parse_args()


if __name__ == "__main__":
    main()
