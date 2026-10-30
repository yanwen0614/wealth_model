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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from math import isclose, isfinite
from pathlib import Path

import backtest_core
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import EventStatus
from backtest_core.contracts.result import SCHEMA_VERSION, EvaluationResult, MetricMethodology
from backtest_core.contracts.validation import ensure_calendar_date
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.evaluation import evaluate_account
from backtest_core.io import DEFAULT_CHUNK_SIZE, ResultStore, RunManifest

from backtest.cnn_adapter.ca.corporate_actions import CorporateActionProvider, TaxPolicy
from backtest.cnn_adapter.ca.raw_market_provider import CnnRawMarketDataProvider
from backtest.cnn_adapter.common import SHANGHAI_TZ, npz_fingerprint
from backtest.cnn_adapter.execution_audit import (
    ExitOnlyStrategy,
    SuppressedOrder,
    build_terminal_plan,
    validate_terminal_execution,
)
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
    buffer_evaluation: Mapping[str, float] | None = None
    evaluation_date: date | None = None
    settlement_end: date | None = None
    suppressed_orders: tuple[SuppressedOrder, ...] = ()


def _config_hash(payload: Mapping) -> str:
    """归一化 sha1：键排序 JSON，同输入跨进程稳定."""
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _label_quality_metadata(pred_cache: Mapping) -> dict[str, str]:
    """报告标签覆盖，不从有限预测值推造真值或 RankIC。"""
    true_values = pred_cache.get("true_ret")
    labeled_rows = 0
    if true_values is not None:
        for raw_value in true_values:
            try:
                labeled_rows += int(isfinite(float(raw_value)))
            except (TypeError, ValueError, OverflowError):
                continue
    availability = pred_cache.get("label_availability")
    if availability is None:
        label_state = "not_loaded" if true_values is None else ("loaded" if labeled_rows else "unknown")
    else:
        if len(availability) != len(pred_cache["exp_ret"]):
            raise ValueError("label_availability length must match exp_ret")
        states = {str(value.decode() if isinstance(value, bytes) else value) for value in availability}
        label_state = next(iter(states)) if len(states) == 1 else "mixed"
    quality_status = "available" if labeled_rows else "not_available"
    rank_ic_status = "not_computed" if labeled_rows else "not_available"
    return {
        "label_availability": label_state,
        "labeled_rows": str(labeled_rows),
        "quality_metrics_status": quality_status,
        "rank_ic": rank_ic_status,
    }


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
                      stamp_tax_rate: float | None = None,
                      transfer_fee_rate: float | None = 0.00001,
                       target_size: int = 100,
                      sell_buffer: int = 500, exit_on_nonpositive: bool = False,
                      exit_threshold: float = 0.0,
                      strong_buy_threshold: float = 0.0,
                      min_edge: float = 0.0,
                      min_edge_tail_ratio: float = 0.3,
                      stop_half: float | None = None,
                      stop_full: float | None = None,
                       ic_gate_window: int | None = None,
                       ic_gate_min_ic: float | None = None,
                        cost_config_resolver: Callable[[date, str], CostConfig] | None = None,
                        execution_config: ExecutionConfig | None = None,
                        execution_calendar: Sequence[date] | None = None,
                        evaluation_end: date | None = None,
                          raw_market_path: str | Path | None = None,
                          corporate_action_provider: CorporateActionProvider | None = None,
                          corporate_action_tax_policy: TaxPolicy = "pretax",
                          require_known_share_tax: bool = False,
                          period_id: str | None = None,
                        verified_execution_states: Mapping[tuple[str, date], Mapping[str, object]] | None = None,
                        ) -> CnnBacktestOutcome:
    """cnn 订单路径端到端：组装 adapter/策略 → core 引擎 → 整段核验 → 打包结果.

    ``dates`` 默认为缓存全部归属日；显式传入时必须为缓存子集（误传日期 fail-fast，
    不依赖 B03 空元组告警）；``run_id`` 格式待 B05 对齐，缺省派生自模型标识。

    ``mode`` 选策略：``rolling``（top_n 等权）为旧行为；``target`` 走滞后带目标持仓
    （``top_n`` 被忽略，持仓规模取 ``target_size``；rolling 下 target 五参被忽略）。
    ``cost_config_resolver``（可选，默认 None 行为零变化）：按 ``(execution_date, instrument_id)``
    解析成交日 ``CostConfig`` 的回调（如 ``historical_costs.resolve_historical_costs`` 桥接），
    引擎在每笔订单执行（含预算折算、容量截断与尾日清算）时逐单调用；回调非可调用或返回
    非 ``CostConfig`` 由引擎显式拒绝。callable 不可哈希，故不进入 config_hash。
    费用前四参默认 ``None`` 即 core ``CostConfig`` 默认（旧行为零变化）；显式值逐项覆盖。
    ``transfer_fee_rate`` 默认 ``0.00001``（过户费万1双边，A股实盘口径；2023-08-28 起印花税为卖出单边万5，
    core 默认佣金万2/min5/印花万5与之一致）；传 ``None`` 回退 core 默认 0.0（无过户费旧口径）。
    滑点一律走 core σ-ADV v1（``CostConfig`` 默认，不做逐项覆盖）。
    ``corporate_action_tax_policy`` 默认 ``pretax``；20% 选项仅是现金分红压力情景，非实际个人税结果。
    ``require_known_share_tax`` 开启时，遇到未知送转税务会拒绝运行；默认结果会在 provenance 明示税务覆盖不完整。
    target 模式另有两道买入门槛（均为策略层参数，不进 core）：``strong_buy_threshold`` 全带门槛、
    ``min_edge`` + ``min_edge_tail_ratio`` 尾部门槛（默认后30%）；0.0 均为关闭。
    """
    if not isinstance(initial_capital, (int, float)) or not initial_capital > 0.0:
        raise ValueError(f"initial_capital must be positive, got {initial_capital!r}")
    adapter = CnnPredictionAdapter(pred_cache, model_name=model_name, checkpoint=checkpoint,
                                   bins_version=bins_version, eval_script_version=eval_script_version,
                                   epoch=epoch)
    available = set(adapter.available_dates)
    signal_days = tuple(adapter.available_dates) if dates is None else tuple(dates)
    if not signal_days:
        raise ValueError("dates must be a non-empty sequence")
    for day in signal_days:
        ensure_calendar_date(day, "dates item")
        if day not in available:
            raise ValueError(f"dates {day!r} 不在预测缓存覆盖内，拒绝误传日期（fail-fast）")
    if signal_days != tuple(sorted(set(signal_days))):
        raise ValueError("signal dates must be strictly increasing and unique")
    if corporate_action_provider is not None and not isinstance(corporate_action_provider, CorporateActionProvider):
        raise ValueError("corporate_action_provider must be a CorporateActionProvider or None")
    if corporate_action_provider is not None and (period_id is None or not period_id.strip()):
        raise ValueError("company-action accounting requires an explicit period_id")
    if corporate_action_tax_policy not in ("pretax", "cash_dividend_20pct_stress"):
        raise ValueError(f"unsupported corporate action tax policy: {corporate_action_tax_policy!r}")
    if not isinstance(require_known_share_tax, bool):
        raise TypeError("require_known_share_tax must be bool")
    if corporate_action_tax_policy != "pretax" and corporate_action_provider is None:
        raise ValueError("a non-pretax corporate action policy requires a corporate_action_provider")
    tax_metadata = (corporate_action_provider.tax_metadata(corporate_action_tax_policy)
                    if corporate_action_provider is not None else {
                        "corporate_action_tax_policy": "pretax",
                        "corporate_action_tax_scope": "cash_dividend_only",
                        "corporate_action_cash_tax_is_actual": "false",
                        "corporate_action_share_tax_status": "not_applicable",
                        "corporate_action_share_tax_unknown_events": "none",
                        "corporate_action_tax_completeness": "cash_dividend_only",
                        "corporate_action_after_tax_result_status": "not_actual_tax_policy",
                    })
    if (require_known_share_tax and
            tax_metadata["corporate_action_share_tax_status"] == "unknown"):
        unknown_events = tax_metadata["corporate_action_share_tax_unknown_events"]
        raise ValueError(f"unknown share tax prevents complete-tax backtest: {unknown_events}")
    corporate_action_fingerprint = (
        corporate_action_provider.fingerprint if corporate_action_provider is not None else "none"
    )
    terminal_plan = None
    execution_days = signal_days
    if execution_calendar is not None:
        execution_days = tuple(execution_calendar)
        if not execution_days or execution_days != tuple(sorted(set(execution_days))):
            raise ValueError("execution_calendar must be non-empty, strictly increasing, and unique")
        for day in execution_days:
            ensure_calendar_date(day, "execution_calendar item")
        if not set(signal_days).issubset(execution_days) or not set(signal_days).issubset(
            day for day in execution_days if day <= (evaluation_end or execution_days[-1])
        ):
            raise ValueError("signal dates must be within the execution calendar and evaluation period")
        if evaluation_end is None or raw_market_path is None:
            raise ValueError("terminal execution requires evaluation_end and explicit raw_market_path")
        terminal_plan = build_terminal_plan(execution_days, evaluation_end, buffer_days=3)
        if terminal_plan.evaluation_date not in signal_days:
            raise ValueError("E-day prediction must remain in signal dates for audit and buy suppression")
        if terminal_plan.calendar[0] >= signal_days[0]:
            raise ValueError("execution_calendar must begin with the prior-close initial-capital anchor")
        corporate_dates = frozenset(
            (event.instrument_id, event.ex_date) for event in corporate_action_provider.events
            if event.ex_date is not None
        ) if corporate_action_provider is not None else frozenset()
        provider = CnnRawMarketDataProvider(
            raw_market_path, signal_start=signal_days[0], signal_end=terminal_plan.evaluation_date,
            execution_end=terminal_plan.settlement_end, corporate_action_dates=corporate_dates,
            verified_states=verified_execution_states,
        )
    else:
        if evaluation_end is not None or raw_market_path is not None or corporate_action_provider is not None:
            raise ValueError("raw execution and company actions require execution_calendar")
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
    if transfer_fee_rate is not None:
        cost_kwargs["transfer_fee_rate"] = transfer_fee_rate
    cost_config = CostConfig(**cost_kwargs)
    if mode == "target":
        strategy = CnnTargetOrderStrategy(adapter, target_size=target_size,
                                          sell_buffer=sell_buffer,
                                          exit_on_nonpositive=exit_on_nonpositive,
                                          exit_threshold=exit_threshold,
                                          strong_buy_threshold=strong_buy_threshold,
                                          min_edge=min_edge,
                                          min_edge_tail_ratio=min_edge_tail_ratio,
                                          stop_half=stop_half,
                                          stop_full=stop_full)
        portfolio_top_n = target_size
    else:
        ic_gate = None
        if ic_gate_window is not None or ic_gate_min_ic is not None:
            from backtest.cnn_adapter.order_strategy import RollingIcGate
            ic_gate = RollingIcGate(
                pred_cache["exp_ret"], pred_cache["true_ret"],
                pred_cache["dates"], pred_cache["codes"],
                window=ic_gate_window or 10, min_ic=ic_gate_min_ic or 0.02,
            )
        strategy = CnnOrderStrategy(adapter, top_n=top_n, ic_gate=ic_gate)
        portfolio_top_n = top_n
    resolved_methodology = methodology if methodology is not None else MetricMethodology()
    if not isinstance(resolved_methodology, MetricMethodology):
        raise ValueError(  # noqa: TRY004
            f"methodology must be a MetricMethodology or None, got {methodology!r}"
        )
    resolved_run_id = run_id if run_id is not None else f"{model_name}@{checkpoint}#top{top_n}"
    if not resolved_run_id.strip():
        raise ValueError(f"run_id must be a non-empty string, got {run_id!r}")
    resolved_execution_config = execution_config if execution_config is not None else ExecutionConfig()
    if not isinstance(resolved_execution_config, ExecutionConfig):
        raise ValueError(f"execution_config must be an ExecutionConfig or None, got {execution_config!r}")  # noqa: TRY004
    terminal_strategy = None
    if terminal_plan is not None:
        validate_terminal_execution(resolved_execution_config, PortfolioConfig(top_n=portfolio_top_n))
        terminal_strategy = ExitOnlyStrategy(strategy, terminal_plan)
        strategy = terminal_strategy
    action_hook = (
        (lambda day: corporate_action_provider.account_operations_for_day(
            day, period_id=period_id, tax_policy=corporate_action_tax_policy,
        ))
        if corporate_action_provider is not None and period_id is not None else None
    )
    result = run_account_backtest_from_orders(
        dates=execution_days, execution_calendar=execution_days, signal_dates=signal_days,
        maintenance_dates=terminal_plan.buffer_dates if terminal_plan is not None else (),
        evaluation_end=terminal_plan.evaluation_date if terminal_plan is not None else None,
        anchor_date=execution_days[0] if terminal_plan is not None else None,
        account_actions_provider=action_hook,
        strategy=strategy, market=provider,
        execution_config=resolved_execution_config, portfolio_config=PortfolioConfig(top_n=portfolio_top_n),
        cost_config=cost_config, cost_config_resolver=cost_config_resolver,
        methodology=resolved_methodology, run_id=resolved_run_id,
        model_id=model_name, initial_capital=float(initial_capital),
        signal_time_of_day=time(15, 0),
    )
    if terminal_plan is None:
        main_snapshots = result.account_snapshots
        main_initial = float(initial_capital)
        buffer_evaluation = None
        main_trades = result.trades
    else:
        evaluation_snapshot = next(
            item for item in result.account_snapshots if item.date == terminal_plan.evaluation_date
        )
        main_snapshots = tuple(
            item for item in result.account_snapshots
            if execution_days[0] < item.date <= terminal_plan.evaluation_date
        )
        main_initial = float(initial_capital)
        buffer_snapshots = tuple(
            item for item in result.account_snapshots
            if terminal_plan.evaluation_date < item.date <= terminal_plan.settlement_end
        )
        buffer_trades = tuple(
            event for event in result.trades if event.execution_time.date() > terminal_plan.evaluation_date
        )
        buffer_evaluation = evaluate_account(
            buffer_snapshots, result.methodology, initial_capital=evaluation_snapshot.nav,
            trade_amounts=tuple(event.amount for event in buffer_trades if event.status in _FILLED_STATUSES),
        )
        main_trades = tuple(
            event for event in result.trades if event.execution_time.date() <= terminal_plan.evaluation_date
        )
    filled_amounts = tuple(event.amount for event in main_trades if event.status in _FILLED_STATUSES)
    account_evaluation = evaluate_account(
        main_snapshots, result.methodology, initial_capital=main_initial, trade_amounts=filled_amounts,
    )
    if verify_account_metrics:
        _verify_account_metrics(account_evaluation, result.account_metrics)
    data_fingerprint = npz_fingerprint(dict(pred_cache))
    config_hash = _config_hash({"top_n": top_n, "horizon": PREDICTED_HORIZON,
                                "initial_capital": float(initial_capital), "model_name": model_name,
                                "checkpoint": checkpoint, "epoch": epoch, "bins_version": bins_version,
                                "eval_script_version": eval_script_version,
                                 "start": signal_days[0].isoformat(),
                                 "end": signal_days[-1].isoformat(), "count": len(signal_days),
                                 "execution_start": execution_days[0].isoformat(),
                                 "execution_end": execution_days[-1].isoformat(),
                                 "evaluation_end": terminal_plan.evaluation_date.isoformat() if terminal_plan else None,
                                  "period_id": period_id,
                                  "corporate_action_tax_policy": corporate_action_tax_policy,
                                  "corporate_action_fingerprint": corporate_action_fingerprint,
                                  "require_known_share_tax": require_known_share_tax,
                                 "raw_market_path": str(raw_market_path) if raw_market_path is not None else None,
                                 "mode": mode, "commission_rate_buy": commission_rate_buy,
                                 "commission_rate_sell": commission_rate_sell,
                                 "min_commission": min_commission,
                                 "stamp_tax_rate": stamp_tax_rate,
                                 "transfer_fee_rate": transfer_fee_rate, "target_size": target_size,
                                 "sell_buffer": sell_buffer,
                                 "exit_on_nonpositive": exit_on_nonpositive,
                                 "exit_threshold": exit_threshold,
                                 "strong_buy_threshold": strong_buy_threshold,
                                 "min_edge": min_edge,
                                 "min_edge_tail_ratio": min_edge_tail_ratio,
                                  "stop_half": stop_half,
                                  "stop_full": stop_full,
                                  "ic_gate_window": ic_gate_window,
                                  "ic_gate_min_ic": ic_gate_min_ic})
    provenance = {key: value for key, value in adapter.provenance.items() if value.strip()}
    provenance.update({"run_id": resolved_run_id, "order_entry": ORDER_ENTRY, "top_n": str(top_n),
                        "initial_capital": str(float(initial_capital)), "config_hash": config_hash,
                        "data_fingerprint": data_fingerprint, "mode": mode,
                        "corporate_action_fingerprint": corporate_action_fingerprint})
    provenance.update(tax_metadata)
    provenance.update(_label_quality_metadata(pred_cache))
    merged = {**dict(result.provenance), **provenance}
    manifest = RunManifest(schema_version=SCHEMA_VERSION, engine_version=backtest_core.__version__,
                           policy_version="v1", run_id=resolved_run_id, model_id=model_name,
                           config_hash=config_hash, data_fingerprint=data_fingerprint,
                           methodology=result.methodology,
                           created_at=datetime.now(SHANGHAI_TZ), trades_location="result",
                           layer="account")
    if terminal_plan is not None:
        provenance.update({
            "evaluation_date": terminal_plan.evaluation_date.isoformat(),
            "settlement_end": terminal_plan.settlement_end.isoformat(),
            "anchor_date": execution_days[0].isoformat(),
            "execution_calendar_count": str(len(execution_days)),
        })
        merged.update(provenance)
    return CnnBacktestOutcome(result=replace(result, provenance=merged),
                              account_evaluation=dict(account_evaluation), manifest=manifest,
                              provenance=provenance, config_hash=config_hash,
                              data_fingerprint=data_fingerprint,
                              buffer_evaluation=buffer_evaluation,
                              evaluation_date=terminal_plan.evaluation_date if terminal_plan else None,
                              settlement_end=terminal_plan.settlement_end if terminal_plan else None,
                              suppressed_orders=(terminal_strategy.suppressed_orders
                                                 if terminal_strategy is not None else ()))


def write_cnn_result(outcome: CnnBacktestOutcome, out_dir: str | Path, *,
                     chunk_size: int = DEFAULT_CHUNK_SIZE) -> Path:
    """写三件套（manifest.json/metrics.json/trades.parquet）并返回结果目录（透传 core ResultStore）."""
    if not isinstance(outcome, CnnBacktestOutcome):
        raise ValueError(f"outcome must be a CnnBacktestOutcome, got {outcome!r}")  # noqa: TRY004
    return ResultStore(out_dir, chunk_size=chunk_size).write(outcome.result, outcome.manifest)
