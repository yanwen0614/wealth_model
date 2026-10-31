"""参数邻域验证（交接文档 §4）：target_size / topn 邻域扫描 + 稳定性诊断。

判据（§4.2）：
  1. 主参数在样本外跑赢沪深300（税后）
  2. 邻域参数也有效
  3. 邻域内不出现符号翻转

口径冻结（不可中途改）：费用万2/万2/印花万5/过户万1 + min5、本金 100 万、
持仓上限 10（``target_strategy._MAX_HOLDINGS``）、基准 000300.SH close-to-close。

样本内外切分依据训练默认区间（``config/defaults.py`` TRAIN_END=2025-06-30）：
2025H2 为样本外，2025 全年仅作交叉复核。

用法：
  uv run --project . python -m scripts.research.neighborhood_validation --preds logs/preds_fullA_2025.npz
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from backtest.cnn_adapter.runner import run_cnn_backtest
from backtest.engine import benchmark_index_nav, nav_metrics
from config.defaults import DEFAULT_PARQUET

DEFAULT_INDEX_DIR_WIN = "Z:/prd/kline_index/day"
DEFAULT_INDEX_DIR_POSIX = "data/test/kline_index/day"
DEFAULT_BENCHMARK = "000300.SH"
INITIAL_CAPITAL = 1_000_000.0

FEES = {"commission_rate_buy": 0.0002, "commission_rate_sell": 0.0002,
        "min_commission": 5.0, "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}

TARGET_SIZE_GRID = (50, 80, 100, 120, 150)
TOPN_GRID = (8, 9, 10, 11, 12)

WINDOWS = (
    ("OOS_2025H2", "2025-07-01", "2025-12-31"),
    ("FULL_2025", "2025-01-01", "2025-12-31"),
)


def load_index(index_dir: str, code: str) -> tuple[np.ndarray, np.ndarray]:
    """读取指数 (kline_time, close)；文件缺失显式报错。"""
    import pyarrow.parquet as pq

    path = Path(index_dir) / f"{code}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"指数数据缺失: {path}")
    table = pq.read_table(path, columns=["kline_time", "close"])
    dates = np.asarray(table.column("kline_time").to_numpy()).astype("datetime64[D]")
    close = np.asarray(table.column("close").to_numpy(), dtype=np.float64)
    return dates, close


def slice_window(preds: dict, lo: str, hi: str) -> tuple[dict, np.ndarray]:
    """按归属日裁出子窗口，返回 (pred_cache, 交易日数组)。"""
    days_all = np.asarray(preds["dates"]).astype("datetime64[D]")
    mask = (days_all >= np.datetime64(lo)) & (days_all <= np.datetime64(hi))
    cache = {key: np.asarray(preds[key])[mask] for key in ("exp_ret", "true_ret", "dates", "codes")}
    return cache, np.unique(days_all[mask])


def backtest(cache: dict, parquet: str, *, mode: str, **params) -> dict:
    """跑一次 adapter 回测，返回 account_evaluation。"""
    return run_cnn_backtest(
        pred_cache=cache, parquet_path=parquet, mode=mode,
        initial_capital=INITIAL_CAPITAL, **FEES, **params,
    ).account_evaluation


def sweep(cache: dict, days: np.ndarray, parquet: str,
          index_dates: np.ndarray, index_close: np.ndarray,
          window_label: str) -> list[dict]:
    """在单窗口上扫两个维度，返回逐点结果。"""
    bench = benchmark_index_nav(index_dates, index_close, days.astype("datetime64[D]"))
    bench_annual = nav_metrics(bench)["annual"]
    print(f"\n===== {window_label} ({len(days)} 天)  基准 annual={bench_annual:+.4f}")

    rows: list[dict] = []
    print("-- target_size (sell_buffer=500) --")
    for target_size in TARGET_SIZE_GRID:
        m = backtest(cache, parquet, mode="target", target_size=target_size, sell_buffer=500)
        excess = m["annualized_return"] - bench_annual
        rows.append({"window": window_label, "dim": "target_size", "value": target_size,
                     "annual": m["annualized_return"], "sharpe": m["sharpe"],
                     "mdd": m["max_drawdown"], "excess": excess, "turnover": m["turnover"]})
        print(f"   target_size={target_size:>4} annual={m['annualized_return']:+.4f} "
              f"sharpe={m['sharpe']:+.3f} mdd={m['max_drawdown']:.4f} "
              f"超额={excess:+.4f} turnover={m['turnover']:.1f}")

    print("-- rolling topn --")
    for top_n in TOPN_GRID:
        m = backtest(cache, parquet, mode="rolling", top_n=top_n)
        excess = m["annualized_return"] - bench_annual
        rows.append({"window": window_label, "dim": "topn", "value": top_n,
                     "annual": m["annualized_return"], "sharpe": m["sharpe"],
                     "mdd": m["max_drawdown"], "excess": excess, "turnover": m["turnover"]})
        print(f"   topn={top_n:>3} annual={m['annualized_return']:+.4f} "
              f"sharpe={m['sharpe']:+.3f} mdd={m['max_drawdown']:.4f} "
              f"超额={excess:+.4f} turnover={m['turnover']:.1f}")

    return rows


def summarize(rows: list[dict]) -> None:
    """按 §4.2 三条判据汇总。"""
    print("\n===== 判据汇总")
    for window in ("OOS_2025H2", "FULL_2025"):
        for dim in ("target_size", "topn"):
            subset = [r for r in rows if r["window"] == window and r["dim"] == dim]
            if not subset:
                continue
            excess = [r["excess"] for r in subset]
            flipped = min(excess) < 0.0 < max(excess)
            best = max(subset, key=lambda r: r["excess"])
            print(f"{window:12s} {dim:12s} "
                  f"超额区间 [{min(excess):+.4f}, {max(excess):+.4f}] "
                  f"全正={all(e > 0 for e in excess)} 符号翻转={flipped} "
                  f"最高档={best['value']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="参数邻域验证（§4 判据）")
    parser.add_argument("--preds", required=True, help="preds npz（需含 exp_ret/true_ret/dates/codes）")
    parser.add_argument("--parquet", default=DEFAULT_PARQUET, help="train parquet（真实 OHLC）")
    parser.add_argument("--index_dir", default=None,
                        help="指数日线目录；默认 win32 用 Z:/prd/kline_index/day")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径")
    args = parser.parse_args(argv)

    index_dir = args.index_dir or (DEFAULT_INDEX_DIR_WIN if sys.platform == "win32"
                                   else DEFAULT_INDEX_DIR_POSIX)
    raw = np.load(args.preds)
    preds = {key: raw[key] for key in ("exp_ret", "true_ret", "dates", "codes")}
    index_dates, index_close = load_index(index_dir, DEFAULT_BENCHMARK)

    all_rows: list[dict] = []
    for label, lo, hi in WINDOWS:
        cache, days = slice_window(preds, lo, hi)
        if len(days) < 10:
            print(f"[skip] {label}: 仅 {len(days)} 天")
            continue
        all_rows.extend(sweep(cache, days, args.parquet, index_dates, index_close, label))

    summarize(all_rows)

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nsaved {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
