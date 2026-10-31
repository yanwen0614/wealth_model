"""邻域结论的稳定性诊断：按月/季度分解 + 剔除最强月 + 参数排名翻转检查。

为什么需要：邻域扫描只能回答「整片区域是否有效」，回答不了「是否靠少数月份撑起来」。
本脚本用三项独立检验回答后者，对应交接文档 §4.2 的「单点最优即过拟合」判据。

用法：
  uv run --project . python -m scripts.research.neighborhood_stability --preds logs/preds_fullA_2025.npz
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from backtest.engine import benchmark_index_nav, nav_metrics
from config.defaults import DEFAULT_PARQUET
from scripts.research.neighborhood_validation import (
    DEFAULT_BENCHMARK,
    DEFAULT_INDEX_DIR_POSIX,
    DEFAULT_INDEX_DIR_WIN,
    backtest,
    load_index,
    slice_window,
)

QUARTERS = (
    ("2025Q1", "2025-01-01", "2025-03-31"),
    ("2025Q2", "2025-04-01", "2025-06-30"),
    ("2025Q3", "2025-07-01", "2025-09-30"),
    ("2025Q4", "2025-10-01", "2025-12-31"),
)

# 每月末（2 月按 28、其余按实际天数）
MONTH_ENDS = {1: "31", 2: "28", 3: "31", 4: "30", 5: "31", 6: "30",
              7: "31", 8: "31", 9: "30", 10: "31", 11: "30", 12: "31"}

# 参数排名翻转检验用到的子窗口
RANK_WINDOWS = (
    ("OOS_2025H2", "2025-07-01", "2025-12-31"),
    ("FULL_2025", "2025-01-01", "2025-12-31"),
)
RANK_GRID = (50, 80, 100, 120, 150)


def monthly(preds: dict, parquet: str) -> None:
    """按月分解（target_size=100, sell_buffer=500）。"""
    print("=== 按月分解（target_size=100, sell_buffer=500）")
    print(f"{'月份':10s} {'天数':>4s} {'年化':>9s} {'sharpe':>8s} {'mdd':>8s} {'月收益':>9s}")
    for month in range(1, 13):
        lo = f"2025-{month:02d}-01"
        hi = f"2025-{month:02d}-{MONTH_ENDS[month]}"
        cache, days = slice_window(preds, lo, hi)
        if len(days) < 5:
            continue
        m = backtest(cache, parquet, mode="target", target_size=100, sell_buffer=500)
        print(f"2025-{month:02d}   {len(days):>4d} {m['annualized_return']:+9.4f} "
              f"{m['sharpe']:+8.3f} {m['max_drawdown']:8.4f} {m['total_return']:+9.4f}")


def quarterly(preds: dict, parquet: str) -> None:
    """按季度分解。"""
    print("\n=== 季度分解（target_size=100, sell_buffer=500）")
    for label, lo, hi in QUARTERS:
        cache, days = slice_window(preds, lo, hi)
        if len(days) < 5:
            continue
        m = backtest(cache, parquet, mode="target", target_size=100, sell_buffer=500)
        print(f"{label}  annual={m['annualized_return']:+.4f} sharpe={m['sharpe']:+.3f} "
              f"mdd={m['max_drawdown']:.4f} ret={m['total_return']:+.4f}")


def drop_best_month(preds: dict, parquet: str,
                    index_dates: np.ndarray, index_close: np.ndarray) -> None:
    """剔除最强月后的超额（判断是否靠单月撑着）。"""
    print("\n=== 剔除最强月检验")
    cases = (
        ("OOS 全期", "2025-07-01", "2025-12-31"),
        ("只留 7 月", "2025-07-01", "2025-07-31"),
        ("剔除 8 月后 09-01~12-31", "2025-09-01", "2025-12-31"),
    )
    for label, lo, hi in cases:
        cache, days = slice_window(preds, lo, hi)
        if len(days) < 10:
            continue
        m = backtest(cache, parquet, mode="target", target_size=100, sell_buffer=500)
        bench = benchmark_index_nav(index_dates, index_close, days.astype("datetime64[D]"))
        bench_annual = nav_metrics(bench)["annual"]
        print(f"{label:26s} {len(days):>3d}天 策略={m['annualized_return']:+.4f} "
              f"基准={bench_annual:+.4f} 超额={m['annualized_return'] - bench_annual:+.4f}")


def rank_flip(preds: dict, parquet: str) -> None:
    """参数排名翻转检验：同一批参数在不同窗口的排名是否稳定。"""
    print("\n=== 参数排名翻转检验（target_size 超额，pp）")
    rankings: dict[str, list[tuple[int, float]]] = {}
    for label, lo, hi in RANK_WINDOWS:
        cache, days = slice_window(preds, lo, hi)
        if len(days) < 10:
            continue
        bench = benchmark_index_nav(
            *load_index(_index_dir(), DEFAULT_BENCHMARK), days.astype("datetime64[D]"))
        bench_annual = nav_metrics(bench)["annual"]
        scored = []
        for target_size in RANK_GRID:
            m = backtest(cache, parquet, mode="target", target_size=target_size, sell_buffer=500)
            scored.append((target_size, m["annualized_return"] - bench_annual))
        rankings[label] = sorted(scored, key=lambda item: -item[1])
        pretty = " ".join(f"{ts}→{ex * 100:+.1f}" for ts, ex in rankings[label])
        print(f"{label:12s} 排名: {pretty}")

    if len(rankings) == 2:
        first, second = rankings.values()
        same_order = [ts for ts, _ in first] == [ts for ts, _ in second]
        print(f"\n两窗口第 1 名: {first[0][0]} vs {second[0][0]} "
              f"→ 翻转={'是' if first[0][0] != second[0][0] else '否'}")
        print(f"两窗口排名顺序一致={'是' if same_order else '否'}")
        # 同一参数在两窗口的位次差（越大说明排名越不可信）
        pos_first = {ts: idx + 1 for idx, (ts, _) in enumerate(first)}
        pos_second = {ts: idx + 1 for idx, (ts, _) in enumerate(second)}
        spread = max(abs(pos_first[ts] - pos_second[ts]) for ts in pos_first)
        print(f"单个参数的最大位次差={spread}（{len(RANK_GRID)} 档中；"
              f"{'排名不稳定' if spread >= 2 else '排名稳定'}）")


def _index_dir() -> str:
    return DEFAULT_INDEX_DIR_WIN if sys.platform == "win32" else DEFAULT_INDEX_DIR_POSIX


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="邻域结论稳定性诊断")
    parser.add_argument("--preds", required=True)
    parser.add_argument("--parquet", default=DEFAULT_PARQUET)
    parser.add_argument("--index_dir", default=None)
    args = parser.parse_args(argv)

    raw = np.load(args.preds)
    preds = {key: raw[key] for key in ("exp_ret", "true_ret", "dates", "codes")}
    index_dates, index_close = load_index(args.index_dir or _index_dir(), DEFAULT_BENCHMARK)

    monthly(preds, args.parquet)
    quarterly(preds, args.parquet)
    drop_best_month(preds, args.parquet, index_dates, index_close)
    rank_flip(preds, args.parquet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
