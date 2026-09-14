"""逐日回测 CLI 报告：preds npz(多模型) + ohlc 路径表 → metrics.json + 持仓csv + 净值png.

preds npz 需含 exp_ret/true_ret/dates/codes（codes 由新版 eval_bins_mapping.py --preds_cache 产出，
旧 npz 缺 codes 会显式报错）。对每个 preds × 每档 TopN 跑 backtest.engine.run_backtest，
基准改为大盘指数 close-to-close 涨跌幅（benchmark_index_nav，默认 000300.SH），超额 = 策略 annual −
指数 annual。指数文件缺失显式报错，区间无数据则告警并跳过基准。

用法：
  uv run --project . python -m scripts.run_backtest \
    --preds logs/preds_dual_ep7.npz logs/preds_base_ep4.npz --ohlc logs/ohlc_path_val.npz
  uv run --project . python -m scripts.run_backtest --mode target \
    --preds logs/preds_dual_ep7.npz --full_ohlc logs/ohlc_full_val.npz \
    --target_size 100 --sell_buffer 500 --min_edge 0.01 --edge_tail_pct 0.3 \
    --exit-on-nonpositive --exit_threshold 0.0

费用为逐笔 A 股模型：买/卖佣金 max(成交额×费率, 最低佣金) + 卖出印花税；--capital 折算最低佣金。
旧 --cost_rate 仅兼容保留，显式传入时告警并忽略。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

from backtest.engine import (
    BUY_COMMISSION_RATE,
    DEFAULT_CAPITAL,
    MIN_COMMISSION,
    SELL_COMMISSION_RATE,
    STAMP_DUTY_RATE,
    benchmark_index_nav,
    nav_metrics,
    run_backtest,
    run_backtest_target,
)
from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays

OHLC_KEYS = ("codes", "dates", "t_close", "open_t1", "open_t6")
FULL_OHLC_KEYS = ("codes", "dates", "open_m", "close_m")
DEFAULT_INDEX_DIR_WIN = "Z:/test/kline_index/day"
DEFAULT_INDEX_DIR_POSIX = "data/test/kline_index/day"
DEFAULT_BENCHMARK_INDEX = "000300.SH"
NOTE = ("卖出未做跌停检查（简化口径）；策略为 open-open 口径"
        "(T+1 open 买入, T+1+horizon open 卖出)，基准为大盘指数 close-to-close 涨跌幅（不收费率）；"
        "逐笔 A 股费用模型：买卖佣金 max(成交额×费率, 最低佣金) + 卖出印花税")
NOTE_TARGET = ("卖出未做跌停检查（简化口径）；目标持仓模式：买入带 rank<=target_size，"
               "卖出带 rank>target_size+sell_buffer（或 exit_on_nonpositive 时 exp_ret<=exit_threshold），"
               "min_edge 过滤命中空槽留现金，float 股数等权，逐笔 A 股费用模型")


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


def default_index_dir() -> str:
    """默认指数日线目录：win32 走 Z: 盘，其它平台回退仓库内路径."""
    return DEFAULT_INDEX_DIR_WIN if sys.platform == "win32" else DEFAULT_INDEX_DIR_POSIX


def load_index_close(index_dir: str, index_code: str) -> tuple[np.ndarray, np.ndarray]:
    """读取指数 parquet 的 (kline_time, close)；文件缺失显式报错."""
    import pyarrow.parquet as pq

    path = os.path.join(index_dir, f"{index_code}.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError(f"指数数据缺失: {path}")
    table = pq.read_table(path, columns=["kline_time", "close"])
    dates = np.asarray(table.column("kline_time").to_numpy()).astype("datetime64[D]")
    close = np.asarray(table.column("close").to_numpy(), dtype=np.float64)
    return dates, close


def index_covers_trade_days(index_dates, trade_days) -> bool:
    """指数区间是否与策略交易日有交集（无交集则不可作基准，须告警跳过）."""
    idates = np.asarray(index_dates).astype("datetime64[D]")
    tdays = np.asarray(trade_days).astype("datetime64[D]")
    if len(tdays) == 0 or len(idates) == 0:
        return False
    return bool(((idates >= tdays.min()) & (idates <= tdays.max())).any())


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
    index_dates, index_close = load_index_close(args.index_dir, args.benchmark_index)
    metrics = {"note": NOTE_TARGET, "mode": "target", "capital": args.capital,
               "buy_rate": args.buy_rate, "sell_rate": args.sell_rate, "stamp_rate": args.stamp_rate,
               "min_commission": args.min_commission,
               "target_size": args.target_size, "sell_buffer": args.sell_buffer,
               "exit_on_nonpositive": args.exit_on_nonpositive, "exit_threshold": args.exit_threshold,
               "min_edge": args.min_edge, "edge_tail_pct": args.edge_tail_pct,
               "models": {}}
    bench = None
    bm = None
    if index_covers_trade_days(index_dates, full_ohlc["dates"]):
        bench = benchmark_index_nav(index_dates, index_close, full_ohlc["dates"])
        bm = nav_metrics(bench)
        metrics["benchmark"] = {"index": args.benchmark_index, **bm, "final_nav": float(bench[-1])}
        print(f"[bt] 基准(大盘指数 {args.benchmark_index}): annual={bm['annual']:.4f} "
              f"sharpe={bm['sharpe']:.3f} mdd={bm['mdd']:.4f} win={bm['win_rate']:.4f}")
    else:
        print(f"[bt] 警告: 指数 {args.benchmark_index} 在策略区间无数据，跳过基准与超额")
    plt.figure(figsize=(12, 7))
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        res = run_backtest_target(preds["exp_ret"], preds["codes"], preds["dates"], full_ohlc,
                                  target_size=args.target_size, sell_buffer=args.sell_buffer,
                                  min_edge=args.min_edge, edge_tail_pct=args.edge_tail_pct,
                                  exit_on_nonpositive=args.exit_on_nonpositive,
                                  exit_threshold=args.exit_threshold,
                                  capital=args.capital, buy_rate=args.buy_rate,
                                  sell_rate=args.sell_rate, stamp_rate=args.stamp_rate,
                                  min_commission=args.min_commission)
        m = nav_metrics(res.nav)
        n_limit = sum(int(v.get("limit_up", 0)) for v in res.skipped.values())
        n_edge = sum(int(v.get("min_edge", 0)) for v in res.skipped.values())
        excess = None if bm is None else m["annual"] - bm["annual"]
        target_metrics = {**m, "final_nav": float(res.nav[-1]),
                          "avg_cash_ratio": float(res.avg_cash_ratio),
                          "n_closed_trades": len(res.holdings),
                          "n_skipped_limit_up": n_limit,
                          "n_skipped_min_edge": n_edge}
        if excess is not None:
            target_metrics["excess_annual"] = excess
        metrics["models"][name] = {"target": target_metrics}
        excess_desc = "n/a" if excess is None else f"{excess:+.4f}"
        print(f"[bt] === {name} === target(size={args.target_size}, buffer={args.sell_buffer}, "
              f"min_edge={args.min_edge}, tail={args.edge_tail_pct}): annual={m['annual']:.4f} "
              f"sharpe={m['sharpe']:.3f} mdd={m['mdd']:.4f} win={m['win_rate']:.4f} "
              f"超额={excess_desc} 平均现金仓位={res.avg_cash_ratio:.2%} "
              f"平仓笔数={len(res.holdings)} 涨停跳过={n_limit} min_edge跳过={n_edge}")
        save_holdings_csv(res.holdings, os.path.join(out_dir, f"holdings_{name}_target.csv"))
        plt.plot(res.nav, label=f"{name} target{args.target_size}")
    if bench is not None:
        plt.plot(bench, label=f"基准 {args.benchmark_index}", linestyle="--", alpha=0.6)
    plt.axhline(1.0, color="gray", linewidth=0.8)
    plt.xlabel("交易日序号")
    plt.ylabel("净值")
    exit_desc = (f"exit<= {args.exit_threshold}" if args.exit_on_nonpositive
                 else f"buffer={args.sell_buffer}")
    plt.title(f"目标持仓回测 (size={args.target_size}, {exit_desc}, min_edge={args.min_edge}, "
              f"本金={args.capital:.0f}, 佣金{args.buy_rate:.4%}+印花税{args.stamp_rate:.4%})")
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
    metrics = {"note": NOTE, "horizon": args.horizon, "capital": args.capital,
               "buy_rate": args.buy_rate, "sell_rate": args.sell_rate, "stamp_rate": args.stamp_rate,
               "min_commission": args.min_commission, "topn_list": list(args.topn), "models": {}}
    index_dates, index_close = load_index_close(args.index_dir, args.benchmark_index)
    plt.figure(figsize=(12, 7))
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        e, c, d = preds["exp_ret"], preds["codes"], preds["dates"]
        trade_days = np.unique(d)
        bench = None
        bm = None
        if index_covers_trade_days(index_dates, trade_days):
            bench = benchmark_index_nav(index_dates, index_close, trade_days)
            bm = nav_metrics(bench)
            metrics["benchmark"] = {"index": args.benchmark_index, **bm, "final_nav": float(bench[-1])}
            print(f"[bt] === {name} === 基准(大盘指数 {args.benchmark_index}): "
                  f"annual={bm['annual']:.4f} sharpe={bm['sharpe']:.3f} "
                  f"mdd={bm['mdd']:.4f} win={bm['win_rate']:.4f}")
        else:
            print(f"[bt] 警告: 指数 {args.benchmark_index} 在策略区间无数据，跳过基准与超额")
        metrics["models"][name] = {}
        for n in args.topn:
            res = run_backtest(e, c, d, ohlc, topn=n, horizon=args.horizon, capital=args.capital,
                               buy_rate=args.buy_rate, sell_rate=args.sell_rate,
                               stamp_rate=args.stamp_rate, min_commission=args.min_commission)
            m = nav_metrics(res.nav)
            excess = None if bm is None else m["annual"] - bm["annual"]
            top_metrics = {**m, "final_nav": float(res.nav[-1]),
                           "avg_cash_ratio": float(res.avg_cash_ratio),
                           "n_holdings": len(res.holdings), "n_skipped": sum(res.skipped.values())}
            if excess is not None:
                top_metrics["excess_annual"] = excess
            metrics["models"][name][f"topn{n}"] = top_metrics
            excess_desc = "n/a" if excess is None else f"{excess:+.4f}"
            print(f"[bt]   top{n}: annual={m['annual']:.4f} sharpe={m['sharpe']:.3f} mdd={m['mdd']:.4f} "
                  f"win={m['win_rate']:.4f} 超额={excess_desc} 平均现金仓位={res.avg_cash_ratio:.2%} "
                  f"持仓批次数={len(res.holdings)} 涨停跳过={int(sum(res.skipped.values()))}")
            save_holdings_csv(res.holdings, os.path.join(out_dir, f"holdings_{name}_topn{n}.csv"))
            plt.plot(res.nav, label=f"{name} top{n}")
        if bench is not None:
            plt.plot(bench, label=f"基准 {args.benchmark_index}", linestyle="--", alpha=0.6)
    plt.axhline(1.0, color="gray", linewidth=0.8)
    plt.xlabel("交易日序号")
    plt.ylabel("净值")
    plt.title(f"逐日回测净值 (open-open, horizon={args.horizon}, 本金={args.capital:.0f}, "
              f"佣金{args.buy_rate:.4%}+印花税{args.stamp_rate:.4%})")
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
    p.add_argument("--index_dir", default=default_index_dir(), help="大盘指数日线 parquet 目录")
    p.add_argument("--benchmark_index", default=DEFAULT_BENCHMARK_INDEX,
                   help="基准指数代码，默认 000300.SH（沪深300）")
    p.add_argument("--cost_rate", type=float, default=None,
                   help="[已废弃] 旧一次性成本率；显式传入仅告警并忽略")
    p.add_argument("--capital", type=float, default=DEFAULT_CAPITAL, help="组合本金（元），用于最低佣金折算")
    p.add_argument("--buy_rate", type=float, default=BUY_COMMISSION_RATE, help="买入佣金费率")
    p.add_argument("--sell_rate", type=float, default=SELL_COMMISSION_RATE, help="卖出佣金费率")
    p.add_argument("--stamp_rate", type=float, default=STAMP_DUTY_RATE, help="卖出印花税费率")
    p.add_argument("--min_commission", type=float, default=MIN_COMMISSION, help="单笔最低佣金（元）")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--mode", choices=["rolling", "target"], default="rolling",
                   help="rolling=固定持有 horizon 滚动（默认）；target=目标持仓（滞后带+min_edge 过滤）")
    p.add_argument("--target_size", type=int, default=100, help="target 模式：买入带 rank<=target_size")
    p.add_argument("--sell_buffer", type=int, default=500, help="target 模式：rank>target_size+sell_buffer 才卖出")
    p.add_argument("--exit-on-nonpositive", dest="exit_on_nonpositive", action="store_true",
                   help="target 模式：持仓 exp_ret<=exit_threshold 即卖出（忽略 rank buffer）")
    p.add_argument("--exit_threshold", type=float, default=0.0, help="target 模式：exit_on_nonpositive 的预测阈值")
    p.add_argument("--min_edge", type=float, default=0.01, help="target 模式：费用感知过滤的预测分数阈值")
    p.add_argument("--edge_tail_pct", type=float, default=0.3, help="target 模式：min_edge 过滤只作用于买入带后 edge_tail_pct 名")
    p.add_argument("--full_ohlc", default=None, help="target 模式必填：全期日频矩阵 npz（codes/dates/open_m/close_m）")
    p.add_argument("--out_dir", default=None, help="默认 logs/backtest_<时间戳>")
    args = p.parse_args()
    if args.cost_rate is not None:
        print("[bt] 警告: --cost_rate 已废弃并被忽略；费用改用逐笔模型 "
              "(--capital/--buy_rate/--sell_rate/--stamp_rate/--min_commission)")
        args.cost_rate = None
    return args


if __name__ == "__main__":
    main()
