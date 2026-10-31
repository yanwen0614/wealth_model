"""backtest 适配器测试共用夹具：合成 parquet + pred npz → 真实 run_cnn_backtest 链路.

为什么需要：迁移自 legacy ``test_engine.py`` 的语义测试都需要「确定性小行情 + 预测缓存
→ 新订单引擎」这条真实链路（不用 mock，避免测到替身而非引擎）。集中在本模块，
使三个测试文件（rolling/target/metrics）共享同一 fixture 口径，不各自复制一遍。

口径约定：
- ``build_synthetic_sample`` 的 ``sample`` 为 ``(day, code, score, open, close)`` 逐行；
  价格取 open/close，high/low 由二者 ±0.1% 派生（引擎需要完整 OHLC 才判可交易）；
- ``run_synthetic_backtest`` 只填测试无关的谱系字段，其余参数透传给
  ``run_cnn_backtest``（费用/模式/门槛均走生产默认或显式覆盖）。
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.runner import run_cnn_backtest

# 合成行情起点：工作日连续（跳过周末），与真实交易日语义一致。
FIRST_DAY = date(2025, 3, 3)

__all__ = ["FIRST_DAY", "build_synthetic_sample", "run_synthetic_backtest", "trading_days"]


def trading_days(count: int, start: date = FIRST_DAY) -> list[date]:
    """从 ``start`` 起取 ``count`` 个连续工作日（跳过周六日）。"""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError(f"count must be a positive int, got {count!r}")
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def build_synthetic_sample(tmpdir: str, sample: Iterable[Sequence], name: str = "fixture"
                           ) -> tuple[dict, str]:
    """``(day, code, score, open, close)`` 逐行 → (pred_cache, parquet_path).

    同一 ``(day, code)`` 重复写入会被 pandas 保留为多行，由 provider 的
    ``drop_duplicates(keep="last")`` 与 adapter 的重复检测各自拒斥/收敛；本 helper
    要求调用方不要重复，以免测到未定义语义。
    """
    rows: list[dict] = []
    exp_ret: list[float] = []
    true_ret: list[float] = []
    days: list[str] = []
    codes: list[str] = []
    for day, code, score, open_price, close_price in sample:
        rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": float(open_price),
                     "high": max(float(open_price), float(close_price)) * 1.001,
                     "low": min(float(open_price), float(close_price)) * 0.999,
                     "close": float(close_price), "volume": 2_000_000.0,
                     "amount": 2_000_000.0 * float(close_price), "is_trading": True})
        exp_ret.append(float(score))
        true_ret.append(0.001)
        days.append(pd.Timestamp(day).date().isoformat())
        codes.append(code)
    parquet_path = os.path.join(tmpdir, f"{name}.parquet")
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    cache_path = os.path.join(tmpdir, f"{name}_preds.npz")
    save_prediction_cache(cache_path, np.asarray(exp_ret), np.asarray(true_ret),
                          np.asarray(days, dtype="datetime64[D]"), np.asarray(codes))
    return load_prediction_cache(cache_path), parquet_path


def run_synthetic_backtest(pred_cache: dict, parquet_path: str, **kwargs):
    """真实 ``run_cnn_backtest`` 薄包装：只补谱系字段，其余参数原样透传。"""
    params = {"pred_cache": pred_cache, "parquet_path": parquet_path,
              "model_name": "cnn_transformer", "checkpoint": "logs/run_demo/best_model.pth",
              "bins_version": "BINS52_v1", "eval_script_version": "eval_bins_mapping@v1"}
    params.update(kwargs)
    return run_cnn_backtest(**params)


def cash_ratios(outcome) -> list[float]:
    """逐日 cash/nav（快照口径），替代 legacy 结果里的 ``avg_cash_ratio`` 字段。"""
    return [snapshot.cash / snapshot.nav for snapshot in outcome.result.account_snapshots]


def fill_events(outcome) -> list:
    """真实成交事件（filled + forced_exit），排除 skipped/locked。"""
    from backtest_core.contracts import EventStatus

    return [event for event in outcome.result.trades
            if event.status in (EventStatus.FILLED, EventStatus.FORCED_EXIT)]
