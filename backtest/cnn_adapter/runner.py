"""cnn 订单路径 runner（B04）：缓存 + 行情 → 订单引擎 → 整段核验 → 结果对象。

数据流：``CnnPredictionAdapter``（B03，成交只消费 Prediction/exp_ret）
→ ``CnnOrderStrategy``（top_n 等权现金单）→ core ``run_account_backtest_from_orders``
（引擎内部以 MarketState 包装 provider 后按日回调）
→ ``evaluate_account`` 整段核验（逐键一致，不一致抛错，防两层口径分叉）。
ResultStore 复用 core ``io``（cnn 不自立存储口径）；注释只写"为什么"。
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from math import isclose
from pathlib import Path

import backtest_core
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import EventStatus
from backtest_core.contracts.result import SCHEMA_VERSION, EvaluationResult, MetricMethodology
from backtest_core.contracts.validation import ensure_calendar_date
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.evaluation import evaluate_account
from backtest_core.io import DEFAULT_CHUNK_SIZE, ResultStore, RunManifest

from backtest.cnn_adapter.common import SHANGHAI_TZ, npz_fingerprint
from backtest.cnn_adapter.market import CnnMarketDataProvider
from backtest.cnn_adapter.order_strategy import CnnOrderStrategy
from backtest.cnn_adapter.predictions import PREDICTED_HORIZON, CnnPredictionAdapter
from backtest.cnn_adapter.target_strategy import CnnTargetOrderStrategy

__all__ = ["CnnBacktestOutcome", "run_cnn_backtest", "write_cnn_result"]

# 订单入口标识（manifest provenance 事实，B05 血缘消费）
ORDER_ENTRY = "atomic_orders_cash_budget"

logger = logging.getLogger(__name__)

# 只有真实成交计入换手（与 core DefaultEvaluationEngine 同口径，不把 skipped/locked 计入）
_FILLED_STATUSES = frozenset({EventStatus.FILLED, EventStatus.FORCED_EXIT})


@dataclass(frozen=True)
class CnnBacktestOutcome:
    """B04 打包结果：账户整段 + 复算指标 + 清单 + 血缘 + 指纹."""

    result: EvaluationResult
    account_evaluation: Mapping[str, float]
    manifest: RunManifest
    provenance: Mapping[str, str]
    config_hash: str
    data_fingerprint: str


def _config_hash(payload: Mapping) -> str:
    """归一化 sha1：键排序 JSON，同输入跨进程稳定."""
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _verify_account_metrics(evaluated: Mapping[str, float], engine: Mapping[str, float]) -> None:
    """整段核验：快照复算与引擎 account_metrics 键集/数值一致，任一漂移显式失败."""
    if set(evaluated) != set(engine):
        mismatch = sorted(set(evaluated) ^ set(engine))
        raise ValueError(f"evaluate_account/engine account_metrics key mismatch: {mismatch}")
    for key, value in evaluated.items():
        if not isclose(value, engine[key], rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(
                f"account metric {key!r} mismatch: evaluate_account={value!r} engine={engine[key]!r}"
            )


def run_cnn_backtest(*, pred_cache: Mapping, parquet_path: str,
                     dates: Sequence[date] | None = None, top_n: int = 10,
                     initial_capital: float = 1_000_000.0, model_name: str = "cnn_transformer",
                     checkpoint: str = "unknown", bins_version: str = "unknown",
                     eval_script_version: str = "unknown", epoch=None, ohlc_path=None,
                     st_codes=None, run_id: str | None = None,
                     methodology: MetricMethodology | None = None,
                     verify_account_metrics: bool = True, mode: str = "rolling",
                     commission_rate_buy: float | None = None,
                     commission_rate_sell: float | None = None,
                     min_commission: float | None = None,
                     stamp_tax_rate: float | None = None, target_size: int = 100,
                     sell_buffer: int = 500, exit_on_nonpositive: bool = False,
                     exit_threshold: float = 0.0,
                     strong_buy_threshold: float = 0.0) -> CnnBacktestOutcome:
    """cnn 订单路径端到端：组装 adapter/策略 → core 引擎 → 整段核验 → 打包结果.

    ``dates`` 默认为缓存全部归属日；显式传入时必须为缓存子集（误传日期 fail-fast，
    不依赖 B03 空元组告警）；``run_id`` 格式待 B05 对齐，缺省派生自模型标识。

    ``mode`` 选策略：``rolling``（top_n 等权）为旧行为；``target`` 走滞后带目标持仓
    （``top_n`` 被忽略，持仓规模取 ``target_size``；rolling 下 target 五参被忽略）。
    费用四参默认 ``None`` 即 core ``CostConfig`` 默认（旧行为零变化）；显式值逐项覆盖。
    """
    if not isinstance(initial_capital, (int, float)) or not initial_capital > 0.0:
        raise ValueError(f"initial_capital must be positive, got {initial_capital!r}")
    adapter = CnnPredictionAdapter(pred_cache, model_name=model_name, checkpoint=checkpoint,
                                   bins_version=bins_version, eval_script_version=eval_script_version,
                                   epoch=epoch)
    available = set(adapter.available_dates)
    ordered_dates = tuple(adapter.available_dates) if dates is None else tuple(dates)
    if not ordered_dates:
        raise ValueError("dates must be a non-empty sequence")
    for day in ordered_dates:
        ensure_calendar_date(day, "dates item")
        if day not in available:
            raise ValueError(f"dates {day!r} 不在预测缓存覆盖内，拒绝误传日期（fail-fast）")
    provider = CnnMarketDataProvider(parquet_path, ohlc_path=ohlc_path, st_codes=st_codes)
    if mode not in ("rolling", "target"):
        raise ValueError(f"mode must be 'rolling' or 'target', got {mode!r}")
    # 费用只覆盖显式值（None 即 core 默认，不依赖 core 默认值语义）；负阈值由策略 raise。
    cost_kwargs: dict = {}
    if commission_rate_buy is not None:
        cost_kwargs["commission_rate_buy"] = commission_rate_buy
    if commission_rate_sell is not None:
        cost_kwargs["commission_rate_sell"] = commission_rate_sell
    if min_commission is not None:
        cost_kwargs["min_commission"] = min_commission
    if stamp_tax_rate is not None:
        cost_kwargs["stamp_tax_rate"] = stamp_tax_rate
    cost_config = CostConfig(**cost_kwargs)
    if mode == "target":
        strategy = CnnTargetOrderStrategy(adapter, target_size=target_size,
                                          sell_buffer=sell_buffer,
                                          exit_on_nonpositive=exit_on_nonpositive,
                                          exit_threshold=exit_threshold,
                                          strong_buy_threshold=strong_buy_threshold)
        portfolio_top_n = target_size
    else:
        strategy = CnnOrderStrategy(adapter, top_n=top_n)
        portfolio_top_n = top_n
    resolved_methodology = methodology if methodology is not None else MetricMethodology()
    if not isinstance(resolved_methodology, MetricMethodology):
        raise ValueError(  # noqa: TRY004
            f"methodology must be a MetricMethodology or None, got {methodology!r}"
        )
    resolved_run_id = run_id if run_id is not None else f"{model_name}@{checkpoint}#top{top_n}"
    if not resolved_run_id.strip():
        raise ValueError(f"run_id must be a non-empty string, got {run_id!r}")
    result = run_account_backtest_from_orders(
        dates=ordered_dates, strategy=strategy, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(top_n=portfolio_top_n),
        cost_config=cost_config, methodology=resolved_methodology, run_id=resolved_run_id,
        model_id=model_name, initial_capital=float(initial_capital),
        signal_time_of_day=time(15, 0),
    )
    filled_amounts = tuple(event.amount for event in result.trades if event.status in _FILLED_STATUSES)
    account_evaluation = evaluate_account(
        result.account_snapshots, result.methodology, initial_capital=float(initial_capital),
        trade_amounts=filled_amounts,
    )
    if verify_account_metrics:
        _verify_account_metrics(account_evaluation, result.account_metrics)
    data_fingerprint = npz_fingerprint(dict(pred_cache))
    config_hash = _config_hash({"top_n": top_n, "horizon": PREDICTED_HORIZON,
                                "initial_capital": float(initial_capital), "model_name": model_name,
                                "checkpoint": checkpoint, "epoch": epoch, "bins_version": bins_version,
                                "eval_script_version": eval_script_version,
                                "start": ordered_dates[0].isoformat(),
                                "end": ordered_dates[-1].isoformat(), "count": len(ordered_dates),
                                "mode": mode, "commission_rate_buy": commission_rate_buy,
                                "commission_rate_sell": commission_rate_sell,
                                "min_commission": min_commission,
                                "stamp_tax_rate": stamp_tax_rate, "target_size": target_size,
                                "sell_buffer": sell_buffer,
                                "exit_on_nonpositive": exit_on_nonpositive,
                                "exit_threshold": exit_threshold,
                                "strong_buy_threshold": strong_buy_threshold})
    provenance = {key: value for key, value in adapter.provenance.items() if value.strip()}
    provenance.update({"run_id": resolved_run_id, "order_entry": ORDER_ENTRY, "top_n": str(top_n),
                       "initial_capital": str(float(initial_capital)), "config_hash": config_hash,
                       "data_fingerprint": data_fingerprint, "mode": mode})
    merged = {**dict(result.provenance), **provenance}
    manifest = RunManifest(schema_version=SCHEMA_VERSION, engine_version=backtest_core.__version__,
                           policy_version="v1", run_id=resolved_run_id, model_id=model_name,
                           config_hash=config_hash, data_fingerprint=data_fingerprint,
                           methodology=result.methodology,
                           created_at=datetime.now(SHANGHAI_TZ), trades_location="result",
                           layer="account")
    return CnnBacktestOutcome(result=replace(result, provenance=merged),
                              account_evaluation=dict(account_evaluation), manifest=manifest,
                              provenance=provenance, config_hash=config_hash,
                              data_fingerprint=data_fingerprint)


def write_cnn_result(outcome: CnnBacktestOutcome, out_dir: str | Path, *,
                     chunk_size: int = DEFAULT_CHUNK_SIZE) -> Path:
    """写三件套（manifest.json/metrics.json/trades.parquet）并返回结果目录（透传 core ResultStore）."""
    if not isinstance(outcome, CnnBacktestOutcome):
        raise ValueError(f"outcome must be a CnnBacktestOutcome, got {outcome!r}")  # noqa: TRY004
    return ResultStore(out_dir, chunk_size=chunk_size).write(outcome.result, outcome.manifest)
