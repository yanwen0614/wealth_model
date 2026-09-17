"""逐日回测 CLI（adapter 唯一路径骨架）。

默认 rolling 路径走 backtest.cnn_adapter 订单引擎（需 --parquet 指定 train parquet，
直读真实 OHLC，不走 ohlc 路径表）；--mode target 由 run_adapter_target 承接
（本骨架为占位，fee/target 的 runner 接线是 T04/T05 的事）。

用法：
  .venv/bin/python -m scripts.run_backtest --parquet <train.parquet> --preds logs/preds.npz
  .venv/bin/python -m scripts.run_backtest --parquet <train.parquet> --preds logs/preds.npz \
    --mode target --target_size 100 --sell_buffer 500

--ohlc/--full_ohlc/--cost_rate 均为废弃参数：显式传入仅告警并忽略。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

import numpy as np

from backtest.cnn_adapter.runner import run_cnn_backtest
from backtest.engine import (
    BUY_COMMISSION_RATE,
    DEFAULT_CAPITAL,
    MIN_COMMISSION,
    SELL_COMMISSION_RATE,
    STAMP_DUTY_RATE,
    benchmark_index_nav,
    nav_metrics,
)
from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR_WIN = "Z:/test/kline_index/day"
DEFAULT_INDEX_DIR_POSIX = "data/test/kline_index/day"
DEFAULT_BENCHMARK_INDEX = "000300.SH"
NOTE = ("adapter 口径：parquet 直读真实 OHLC（停牌 None 语义），不走 ohlc 路径表；"
        "策略为 open-open 口径（T+1 open 买入，T+1+horizon open 卖出）。"
        "逐笔 A 股费用（买/卖佣金 + 卖出印花税）；基准为大盘指数 close-to-close（不收费率）。")
NOTE_TARGET = ("adapter 口径 target：parquet 直读真实 OHLC（停牌 None 语义），不走 ohlc 路径表；"
               "目标持仓模式：买入带 rank<=target_size，卖出带 rank>target_size+sell_buffer"
               "（或 exit_on_nonpositive 时 exp_ret<=exit_threshold）；"
               "strong_buy_threshold>0 时买入带内 exp_ret<阈值跳过留现金不补位（0.0 关闭）；"
               "逐笔 A 股费用（买/卖佣金 + 卖出印花税）；基准为大盘指数 close-to-close（不收费率）。")

# 新引擎身份：默认 rolling 路径写 adapter 口径。
ADAPTER_ENGINE_NAME = "cnn_adapter"
ADAPTER_EVAL_VERSION = "scripts/run_backtest@n01"


def load_preds(path: str) -> dict:
    z = np.load(path, allow_pickle=False)
    arrays = {key: z[key] for key in PREDICTION_CACHE_KEYS if key in z.files}
    validate_prediction_cache_arrays(arrays, path)
    return {"exp_ret": arrays["exp_ret"].astype(np.float64), "true_ret": arrays["true_ret"].astype(np.float64),
            "dates": arrays["dates"], "codes": arrays["codes"]}


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


def _resolve_benchmark(args, trade_days):
    """指数基准：缺文件让 FileNotFoundError 透出；无交集告警并返回 (None, None)."""
    index_dates, index_close = load_index_close(args.index_dir, args.benchmark_index)
    if not index_covers_trade_days(index_dates, trade_days):
        print(f"[bt-adapter] 警告: 指数 {args.benchmark_index} 在策略区间无数据，跳过基准与超额")
        return None, None
    bench = benchmark_index_nav(index_dates, index_close, trade_days)
    return bench, nav_metrics(bench)


def run_adapter_rolling(args, out_dir: str) -> None:
    """默认 rolling 路径：preds npz → cnn_adapter 订单引擎 → metrics.json（adapter 口径）。

    为什么不用 ohlc 路径表：adapter 直接消费 train parquet 真实 OHLC（停牌 None 语义），
    与旧 t_close/open_t1/open_t6 路径表不是同一口径，不做静默桥接。
    费用四参透传 runner（--capital→initial_capital；--buy_rate/--sell_rate/--min_commission/--stamp_rate
    → commission_rate_buy/sell + min_commission + stamp_tax_rate）；指数基准缺文件透出 FileNotFoundError，
    无交集告警跳过，有交集则 metrics["benchmark"] + 每档 excess_annual（年化口径，键缺失跳过）。
    """
    metrics = {"engine": ADAPTER_ENGINE_NAME, "mode": "rolling-adapter", "note": NOTE,
               "eval_script_version": ADAPTER_EVAL_VERSION, "topn_list": list(args.topn),
               "capital": args.capital, "buy_rate": args.buy_rate, "sell_rate": args.sell_rate,
               "stamp_rate": args.stamp_rate, "min_commission": args.min_commission,
               "index": args.benchmark_index, "models": {}}
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        trade_days = np.unique(preds["dates"])
        bench, bm = _resolve_benchmark(args, trade_days)
        if bm is not None and "benchmark" not in metrics:
            assert bench is not None  # _resolve_benchmark：bm 非空 ⟺ bench 非空
            metrics["benchmark"] = {"index": args.benchmark_index, **bm, "final_nav": float(bench[-1])}
            print(f"[bt-adapter] === {name} === 基准(大盘指数 {args.benchmark_index}): "
                  f"annual={bm['annual']:.4f} sharpe={bm['sharpe']:.3f} "
                  f"mdd={bm['mdd']:.4f} win={bm['win_rate']:.4f}")
        model_metrics = {}
        for n in args.topn:
            outcome = run_cnn_backtest(pred_cache=preds, parquet_path=args.parquet, top_n=n, mode="rolling",
                                       initial_capital=args.capital, commission_rate_buy=args.buy_rate,
                                       commission_rate_sell=args.sell_rate, min_commission=args.min_commission,
                                       stamp_tax_rate=args.stamp_rate, model_name=args.model_name,
                                       checkpoint=args.checkpoint, bins_version=args.bins_version,
                                       eval_script_version=ADAPTER_EVAL_VERSION)
            m = outcome.account_evaluation
            final_nav = float(args.capital) * (1.0 + float(m["total_return"]))
            entry = {**m, "final_nav": final_nav, "config_hash": outcome.config_hash,
                     "data_fingerprint": outcome.data_fingerprint}
            excess_desc = ""
            if bm is not None and "annualized_return" in m:
                entry["excess_annual"] = float(m["annualized_return"]) - float(bm["annual"])
                excess_desc = f" 超额={entry['excess_annual']:+.4f}"
            model_metrics[f"top{n}"] = entry
            print(f"[bt-adapter] === {name} === top{n}: annual={m.get('annualized_return', 0.0):.4f} "
                  f"sharpe={m.get('sharpe', 0.0):.3f} mdd={m.get('max_drawdown', 0.0):.4f} "
                  f"final_nav={final_nav:.2f}{excess_desc}")
        metrics["models"][name] = model_metrics
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt-adapter] 指标已保存: {metrics_path}")


def run_adapter_target(args, out_dir: str) -> None:
    """target 模式：preds npz → cnn_adapter target 策略 → metrics.json（adapter 口径）。

    mode="target" 调 runner，target 五参透传；费用四参同 rolling；指数基准同 rolling。
    core outcome 无 skipped 语义，不硬造 skipped，只写 account_evaluation + final_nav +
    config_hash/data_fingerprint（+ 有 bm 且有年化键时 excess_annual）。
    """
    metrics = {"engine": ADAPTER_ENGINE_NAME, "mode": "target-adapter", "note": NOTE_TARGET,
               "eval_script_version": ADAPTER_EVAL_VERSION, "capital": args.capital,
               "buy_rate": args.buy_rate, "sell_rate": args.sell_rate, "stamp_rate": args.stamp_rate,
               "min_commission": args.min_commission, "index": args.benchmark_index,
               "target_size": args.target_size, "sell_buffer": args.sell_buffer,
               "exit_on_nonpositive": args.exit_on_nonpositive, "exit_threshold": args.exit_threshold,
               "strong_buy_threshold": args.strong_buy_threshold, "models": {}}
    for path in args.preds:
        preds = load_preds(path)
        name = os.path.splitext(os.path.basename(path))[0]
        trade_days = np.unique(preds["dates"])
        bench, bm = _resolve_benchmark(args, trade_days)
        if bm is not None and "benchmark" not in metrics:
            assert bench is not None  # _resolve_benchmark：bm 非空 ⟺ bench 非空
            metrics["benchmark"] = {"index": args.benchmark_index, **bm, "final_nav": float(bench[-1])}
            print(f"[bt-adapter] === {name} === 基准(大盘指数 {args.benchmark_index}): "
                  f"annual={bm['annual']:.4f} sharpe={bm['sharpe']:.3f} "
                  f"mdd={bm['mdd']:.4f} win={bm['win_rate']:.4f}")
        outcome = run_cnn_backtest(pred_cache=preds, parquet_path=args.parquet, mode="target",
                                   initial_capital=args.capital, commission_rate_buy=args.buy_rate,
                                   commission_rate_sell=args.sell_rate, min_commission=args.min_commission,
                                   stamp_tax_rate=args.stamp_rate, target_size=args.target_size,
                                   sell_buffer=args.sell_buffer, exit_on_nonpositive=args.exit_on_nonpositive,
                                   exit_threshold=args.exit_threshold,
                                   strong_buy_threshold=args.strong_buy_threshold,
                                   model_name=args.model_name, checkpoint=args.checkpoint,
                                   bins_version=args.bins_version, eval_script_version=ADAPTER_EVAL_VERSION)
        m = outcome.account_evaluation
        final_nav = float(args.capital) * (1.0 + float(m["total_return"]))
        target_metrics = {**m, "final_nav": final_nav, "config_hash": outcome.config_hash,
                          "data_fingerprint": outcome.data_fingerprint}
        excess_desc = "n/a"
        if bm is not None and "annualized_return" in m:
            target_metrics["excess_annual"] = float(m["annualized_return"]) - float(bm["annual"])
            excess_desc = f"{target_metrics['excess_annual']:+.4f}"
        metrics["models"][name] = {"target": target_metrics}
        print(f"[bt-adapter] === {name} === target(size={args.target_size}, buffer={args.sell_buffer}, "
              f"strong_buy={args.strong_buy_threshold}): annual={m.get('annualized_return', 0.0):.4f} "
              f"sharpe={m.get('sharpe', 0.0):.3f} mdd={m.get('max_drawdown', 0.0):.4f} "
              f"final_nav={final_nav:.2f} 超额={excess_desc}")
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f"[bt-adapter] 指标已保存: {metrics_path}")


def main(argv=None):
    args = parse_args(argv)
    if args.ohlc is not None:
        logger.warning("--ohlc 已废弃并被忽略（adapter 直读 --parquet 真实 OHLC，不走 ohlc 路径表）")
    if args.full_ohlc is not None:
        logger.warning("--full_ohlc 已废弃并被忽略（adapter 直读 --parquet 真实 OHLC）")
    if args.cost_rate is not None:
        logger.warning("--cost_rate 已废弃并被忽略；费用改用逐笔模型 "
                       "(--capital/--buy_rate/--sell_rate/--stamp_rate/--min_commission)")
        args.cost_rate = None
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir if args.out_dir else os.path.join("logs", f"backtest_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    if not args.parquet:
        raise ValueError("默认 adapter 路径需要 --parquet 指定 train parquet")
    if args.mode == "target":
        run_adapter_target(args, out_dir)
        return
    run_adapter_rolling(args, out_dir)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="逐日回测报告（adapter 唯一路径；直读 parquet 真实 OHLC）")
    p.add_argument("--preds", nargs="+", required=True, help="preds npz 路径（exp_ret/true_ret/dates/codes），多个做模型对比")
    p.add_argument("--parquet", default=None, help="adapter 默认路径必填：train parquet（真实 OHLC）")
    p.add_argument("--initial_capital", type=float, default=1_000_000.0)
    p.add_argument("--model_name", default="cnn_transformer")
    p.add_argument("--checkpoint", default="unknown")
    p.add_argument("--bins_version", default="unknown")
    p.add_argument("--topn", nargs="+", type=int, default=[5, 10, 20])
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--mode", choices=["rolling", "target"], default="rolling",
                   help="rolling=cnn_adapter 订单引擎等权（默认）；target=adapter 目标持仓（滞后带+强买门槛）")
    p.add_argument("--capital", type=float, default=DEFAULT_CAPITAL, help="组合本金（元），用于最低佣金折算")
    p.add_argument("--buy_rate", type=float, default=BUY_COMMISSION_RATE, help="买入佣金费率")
    p.add_argument("--sell_rate", type=float, default=SELL_COMMISSION_RATE, help="卖出佣金费率")
    p.add_argument("--stamp_rate", type=float, default=STAMP_DUTY_RATE, help="卖出印花税费率")
    p.add_argument("--min_commission", type=float, default=MIN_COMMISSION, help="单笔最低佣金（元）")
    p.add_argument("--index_dir", default=default_index_dir(), help="大盘指数日线 parquet 目录")
    p.add_argument("--benchmark_index", default=DEFAULT_BENCHMARK_INDEX,
                   help="基准指数代码，默认 000300.SH（沪深300）")
    p.add_argument("--cost_rate", type=float, default=None, help="[已废弃] 旧一次性成本率；显式传入仅告警并忽略")
    p.add_argument("--target_size", type=int, default=100, help="target 模式：买入带 rank<=target_size")
    p.add_argument("--sell_buffer", type=int, default=500, help="target 模式：rank>target_size+sell_buffer 才卖出")
    p.add_argument("--exit_on_nonpositive", "--exit-on-nonpositive", dest="exit_on_nonpositive",
                   action="store_true", help="target 模式：持仓 exp_ret<=exit_threshold 即卖出（忽略 rank buffer）")
    p.add_argument("--exit_threshold", type=float, default=0.0, help="target 模式：exit_on_nonpositive 的预测阈值")
    p.add_argument("--strong_buy_threshold", type=float, default=0.0,
                   help="target 模式：绝对预测收益强买门槛，买入带内 exp_ret>=阈值 才买（空槽留现金不补位）；"
                        "默认 0.0=关闭，负数由引擎 raise")
    p.add_argument("--full_ohlc", default=None, help="[已废弃] 旧全期日频矩阵 npz；显式传入仅告警并忽略")
    p.add_argument("--ohlc", default=None, help="[已废弃] 旧 ohlc 路径表 npz；显式传入仅告警并忽略")
    p.add_argument("--out_dir", default=None, help="默认 logs/backtest_<时间戳>")
    return p.parse_args(argv)


if __name__ == "__main__":
    main()
