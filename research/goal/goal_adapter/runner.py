"""goal adapter runner（G01）：pred/market 双源 → 订单引擎 → 评估/manifest。

为什么独立 runner：C05 smoke 用内联组装验证链路（显式声明 runner 属阶段 3）；
G01 主入口切换需要生产级组装（配置/血缘/落盘语义），血缘口径沿 smoke：
order_entry/config_hash/data_fingerprint 三键必现。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.engine import run_account_backtest_from_orders

from goal_adapter.common import SHANGHAI_TZ, fingerprint_mapping
from goal_adapter.daily_policy import (
    DEFAULT_SELL_BUFFER as DAILY_SELL_BUFFER,
)
from goal_adapter.daily_policy import (
    DEFAULT_TOP_N as DAILY_TOP_N,
)
from goal_adapter.daily_policy import (
    DailyOrderStrategy,
)
from goal_adapter.joint_policy import (
    DEFAULT_SELL_BUFFER as JOINT_SELL_BUFFER,
)
from goal_adapter.joint_policy import (
    DEFAULT_TOP_N as JOINT_TOP_N,
)
from goal_adapter.joint_policy import (
    JointOrderStrategy,
)
from goal_adapter.market import GoalMarketDataProvider
from goal_adapter.predictions import GoalPredictionAdapter

__all__ = ["ORDER_ENTRY", "RUNNER_VERSION", "GoalBacktestOutcome", "run_goal_backtest"]

# 订单主路径身份：成交全部经 core 原子订单（等权现金单/整手由引擎裁决）。
ORDER_ENTRY = "atomic_orders_cash_budget"
RUNNER_VERSION = "goal_adapter/runner@g01"


@dataclass(frozen=True)
class GoalBacktestOutcome:
    """runner 产出：引擎结果 + 评估 + 血缘（manifest 落盘由调用方/CLI 承担）。"""

    account_result: Any
    account_metrics: dict
    final_nav: float
    config_hash: str
    data_fingerprint: str
    provenance: dict
    manifest: dict = field(default_factory=dict)


def _resolve_strategy(name: str, adapter, provider, top_n, sell_buffer, min_amount_yuan):
    """策略名 → 订单策略实例；top_n/sell_buffer 缺省取各策略 C04 默认。"""
    if name == "daily":
        return DailyOrderStrategy(adapter, provider, top_n=top_n or DAILY_TOP_N,
                                  sell_buffer=DAILY_SELL_BUFFER if sell_buffer is None else sell_buffer,
                                  min_amount_yuan=min_amount_yuan)
    if name == "joint":
        return JointOrderStrategy(adapter, provider, top_n=top_n or JOINT_TOP_N,
                                  sell_buffer=JOINT_SELL_BUFFER if sell_buffer is None else sell_buffer,
                                  min_amount_yuan=min_amount_yuan)
    raise ValueError(f"未知策略 {name!r}，仅支持 'daily'/'joint'")


def run_goal_backtest(*, pred_path: str, market_path: str, strategy: str = "daily",
                      top_n: int | None = None, sell_buffer: int | None = None,
                      min_amount_yuan: float = 1e8, initial_capital: float = 1_000_000.0,
                      model_name: str = "goal-hgb", model_artifact: str = "unknown",
                      feature_version: str = "unknown", script_version: str = RUNNER_VERSION,
                      dates=None) -> GoalBacktestOutcome:
    """双源订单回测：provider + pred adapter + 策略 → core 引擎 → 血缘组装。"""
    provider = GoalMarketDataProvider(market_path)
    adapter = GoalPredictionAdapter(pred_path, model_name=model_name, model_artifact=model_artifact,
                                    feature_version=feature_version, script_version=script_version)
    resolved = _resolve_strategy(strategy, adapter, provider, top_n, sell_buffer, min_amount_yuan)
    run_dates = list(adapter.available_dates) if dates is None else list(dates)
    result = run_account_backtest_from_orders(
        dates=run_dates, strategy=resolved, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
        cost_config=CostConfig(), run_id=f"g01-{strategy}-top{resolved.top_n}", model_id=model_name,
        initial_capital=initial_capital)
    metrics = dict(result.account_metrics)
    final_nav = float(initial_capital) * (1.0 + float(metrics["total_return"]))
    arrays = {day.isoformat(): np.fromiter((p.value for p in adapter.predictions_for_date(day)),
                                           dtype=np.float64) for day in run_dates}
    # G02 指纹决策：data_fingerprint 仅覆盖 pred 内容（market 以路径入 config_hash）；
    # 未来若加指纹键缓存须用 (config_hash, data_fingerprint) 联合键，禁单用 data_fingerprint。
    data_fingerprint = fingerprint_mapping(arrays)
    config_hash = hashlib.sha1(json.dumps(
        {"strategy": strategy, "top_n": resolved.top_n, "sell_buffer": resolved.sell_buffer,
         "min_amount_yuan": float(min_amount_yuan), "initial_capital": float(initial_capital),
         "pred_path": str(pred_path), "market_path": str(market_path),
         "order_entry": ORDER_ENTRY, "runner_version": RUNNER_VERSION},
        sort_keys=True).encode("utf-8")).hexdigest()
    provenance = dict(adapter.provenance)
    provenance.update({"order_entry": ORDER_ENTRY, "strategy": strategy,
                       "top_n": str(resolved.top_n), "sell_buffer": str(resolved.sell_buffer),
                       "initial_capital": str(float(initial_capital)), "config_hash": config_hash,
                       "data_fingerprint": data_fingerprint,
                       "market_counters": str(provider.counters),
                       "strategy_counters": str(resolved.counters)})
    manifest = {"config_hash": config_hash, "data_fingerprint": data_fingerprint,
                "order_entry": ORDER_ENTRY, "strategy": strategy,
                "run_id": f"g01-{strategy}-top{resolved.top_n}",
                "created_at": datetime.now(SHANGHAI_TZ).isoformat(), "provenance": provenance}
    return GoalBacktestOutcome(account_result=result, account_metrics=metrics, final_nav=final_nav,
                               config_hash=config_hash, data_fingerprint=data_fingerprint,
                               provenance=provenance, manifest=manifest)
