"""逐日回测 CLI 报告：preds npz(多模型) + 行情 → metrics.json + 持仓csv + 净值png.

preds npz 需含 exp_ret/true_ret/dates/codes（codes 由新版 eval_bins_mapping.py --preds_cache 产出，
旧 npz 缺 codes 会显式报错）。N01 起默认 rolling 路径走 backtest.cnn_adapter 订单引擎
（需 --parquet 指定 train parquet）；旧 backtest.engine rolling/target 体须 --legacy
显式 opt-in（另需 CNN_ALLOW_LEGACY=1），旧回归出口一律拒绝。
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

from backtest.cnn_adapter.runner import run_cnn_backtest
from backtest.engine import benchmark_nav, nav_metrics, run_backtest, run_backtest_target
from backtest.legacy import LegacyBacktestDisabledError, guard_legacy_disabled, mark_legacy_result
from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays

logger = logging.getLogger(__name__)

OHLC_KEYS = ("codes", "dates", "t_close", "open_t1", "open_t6")
FULL_OHLC_KEYS = ("codes", "dates", "open_m", "close_m")
NOTE = ("卖出未做跌停检查（简化口径）；策略与基准均为 open-open 口径"
        "(T+1 open 买入, T+1+horizon open 卖出)，双边成本一次性扣减")
NOTE_TARGET = ("卖出未做跌停检查（简化口径）；目标持仓模式：买入带 rank<=target_size，"
               "卖出带 rank>target_size+sell_buffer，min_edge 过滤命中空槽留现金，"
               "float 股数等权（预算=nav/target_size），双边成本各计一次")

# 新引擎身份：默认 rolling 路径写 adapter 口径；旧结果一律带 legacy 标记以资区分。
ADAPTER_ENGINE_NAME = "cnn_adapter"
ADAPTER_EVAL_VERSION = "scripts/run_backtest@n01"


def run_legacy_regression() -> None:
    """旧回归出口：B05 回归结论已归档为历史记录，本入口一律拒绝执行旧逻辑。"""
    guard_legacy_disabled("scripts/run_backtest:regression")
    raise LegacyBacktestDisabledError(
        "legacy regression is retired (see test_cnn_adapter_regression.py B05 record); "
        "no opt-in re-run path"
    )


def run_adapter_rolling(args, out_dir: str) -> None:
    """默认 rolling 路径：preds npz → cnn_adapter 订单引擎 → metrics.json（adapter 口径）。

    为什么不用 ohlc 路径表：adapter 直接消费 train parquet 真实 OHLC（停牌 None 语义），
    与旧 t_close/open_t1/open_t6 路径表不是同一口径，不做静默桥接。
    """
    metrics = {"engine": ADAPTER_ENGINE_NAME, "mode": "rolling-adapter",
               "eval_script_version": ADAPTER_EVAL_VERSION, "topn_list": list(args.topn), "models": {}}
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        model_metrics = {}
        for n in args.topn:
            outcome = run_cnn_backtest(pred_cache=preds, parquet_path=args.parquet, top_n=n,
                                       initial_capital=args.initial_capital, model_name=args.model_name,
                                       checkpoint=args.checkpoint, bins_version=args.bins_version,
                                       eval_script_version=ADAPTER_EVAL_VERSION)
            m = outcome.account_evaluation
            final_nav = args.initial_capital * (1.0 + float(m["total_return"]))
            model_metrics[f"top{n}"] = {**m, "final_nav": final_nav, "config_hash": outcome.config_hash,
                                        "data_fingerprint": outcome.data_fingerprint}
            print(f"[bt-adapter] === {name} === top{n}: annual={m.get('annualized_return', 0.0):.4f} "
                  f"sharpe={m.get('sharpe', 0.0):.3f} mdd={m.get('max_drawdown', 0.0):.4f} "
                  f"final_nav={final_nav:.2f}")
        metrics["models"][name] = model_metrics
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt-adapter] 指标已保存: {metrics_path}")


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


# OLD_LOGIC（阶段 3 N01/N02）：以下旧 rolling/target 体默认不可达；
# 复用须 --legacy + CNN_ALLOW_LEGACY=1 双显式 opt-in。N02 决策：target 仅
# legacy（opt-in 可达），不设 adapter 等价——target 滞后带/费用感知需新策
# 略类 + runner 接线（>100 行），超收口范围；rolling 已由 adapter 覆盖。
def run_legacy_rolling(args, out_dir: str) -> None:
    guard_legacy_disabled("scripts/run_backtest:rolling")
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
    metrics = mark_legacy_result(metrics)
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt] 指标已保存: {metrics_path}")
    print(f"[bt] 净值曲线已保存: {png_path}")
    print(f"[bt] 持仓明细已保存: holdings_<model>_topn<n>.csv @ {out_dir}")


def run_target_mode(args, out_dir: str) -> None:
    """旧目标持仓体（N02 决策：仅 legacy opt-in 可达，不设 adapter 等价）。"""
    guard_legacy_disabled("scripts/run_backtest:target")
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
    metrics = mark_legacy_result(metrics)
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt] 指标已保存: {metrics_path}")
    print(f"[bt] 净值曲线已保存: {png_path}")
    print(f"[bt] 持仓明细已保存: holdings_<model>_target.csv @ {out_dir}")


def main(argv=None):
    args = parse_args(argv)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir if args.out_dir else os.path.join("logs", f"backtest_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    if args.mode == "target":
        run_target_mode(args, out_dir)
        return
    if args.legacy:
        run_legacy_rolling(args, out_dir)
        return
    if args.ohlc is not None:
        logger.warning("--ohlc 在默认 adapter 路径被忽略（adapter 直读 --parquet 真实 OHLC）；旧路径表请走 --legacy")
    if not args.parquet:
        raise ValueError("默认 adapter 路径需要 --parquet 指定 train parquet；旧 ohlc 路径表请走 --legacy")
    run_adapter_rolling(args, out_dir)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="逐日回测报告（默认 cnn_adapter 订单引擎；旧引擎须 --legacy）")
    p.add_argument("--preds", nargs="+", required=True, help="preds npz 路径（exp_ret/true_ret/dates/codes），多个做模型对比")
    p.add_argument("--ohlc", default=None, help="legacy rolling 必填：ohlc 路径表 npz（codes/dates/t_close/open_t1/open_t6）")
    p.add_argument("--legacy", action="store_true", help="显式 opt-in 旧引擎（另需 CNN_ALLOW_LEGACY=1）")
    p.add_argument("--parquet", default=None, help="adapter 默认路径必填：train parquet（真实 OHLC）")
    p.add_argument("--initial_capital", type=float, default=1_000_000.0)
    p.add_argument("--model_name", default="cnn_transformer")
    p.add_argument("--checkpoint", default="unknown")
    p.add_argument("--bins_version", default="unknown")
    p.add_argument("--topn", nargs="+", type=int, default=[5, 10, 20])
    p.add_argument("--cost_rate", type=float, default=0.0015)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--mode", choices=["rolling", "target"], default="rolling",
                   help="rolling=订单引擎等权（默认）；target=旧目标持仓（仅 legacy opt-in 可达，N02 决策无 adapter 等价）")
    p.add_argument("--target_size", type=int, default=100, help="target 模式：买入带 rank<=target_size")
    p.add_argument("--sell_buffer", type=int, default=200, help="target 模式：rank>target_size+sell_buffer 才卖出")
    p.add_argument("--min_edge", type=float, default=0.01, help="target 模式：费用感知过滤的预测分数阈值")
    p.add_argument("--edge_tail_pct", type=float, default=0.3, help="target 模式：min_edge 过滤只作用于买入带后 edge_tail_pct 名")
    p.add_argument("--full_ohlc", default=None, help="target 模式必填：全期日频矩阵 npz（codes/dates/open_m/close_m）")
    p.add_argument("--out_dir", default=None, help="默认 logs/backtest_<时间戳>")
    return p.parse_args(argv)


if __name__ == "__main__":
    main()
