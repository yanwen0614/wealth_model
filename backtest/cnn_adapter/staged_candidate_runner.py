"""分批候选账户运行器：单窗 reset（W1/W2）真实 core 端到端。

调用模式：
    python -m backtest.cnn_adapter.staged_candidate_runner \\
        --signal-parquet <path> --expected-sha256 <hex> \\
        --source-id <id> --checkpoint-sha256 <hex> \\
        --anchor-date YYYY-MM-DD --evaluation-end YYYY-MM-DD \\
        --execution-calendar <path> --policy B1 --output-dir <path>

设计约束：
- 直接调用 StagedOrderStrategy（不套 ExitOnlyStrategy）
- StagedExecutionBridge 作为 observer 透传所有 ExecutionUpdate
- buffer 日由策略内部通过 buffer_start_date 处理
- Continuous 模式当前不支持，显式拒绝
- signal Parquet 字段：trading_date, instrument_id, exp_ret, status, buy_eligible
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime, time
from math import isfinite
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import EventStatus
from backtest_core.contracts.execution_feedback import ExecutionUpdate
from backtest_core.contracts.protocols import AccountView, MarketDataProvider, MarketView
from backtest_core.contracts.result import EvaluationResult
from backtest_core.contracts.validation import ensure_calendar_date
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.evaluation import evaluate_account
from pydantic import BaseModel

from backtest.cnn_adapter.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.corporate_action_snapshot_loader import CorporateActionSnapshot
from backtest.cnn_adapter.corporate_actions import (
    CorporateActionProvider,
    TaxPolicy,
)
from backtest.cnn_adapter.quantity_rules import QuantityRule, QuantityRuleError
from backtest.cnn_adapter.staged_allocation import (
    AllocationRegistry,
    Policy,
    budget_per_episode,
)
from backtest.cnn_adapter.staged_execution_bridge import StagedExecutionBridge
from backtest.cnn_adapter.staged_order_strategy import (
    MappingRankingSource,
    RankingSnapshot,
    StagedOrderStrategy,
)

__all__ = [
    "StagedWindowConfig",
    "WindowDefinition",
    "StagedWindowOutcome",
    "load_frozen_signal_parquet",
    "build_signal_ranking",
    "run_staged_window",
]

logger = logging.getLogger(__name__)
_FILLED_STATUSES = frozenset({EventStatus.FILLED, EventStatus.FORCED_EXIT})


def load_frozen_signal_parquet(
    path: str | Path,
    expected_sha256: str,
) -> tuple[dict[date, list[dict]], str]:
    """读取冻结信号 Parquet，验证文件字节 SHA-256，返回 (rows_by_date, actual_sha)。

    接受冻结 F4 的 code/date 列，映射为 instrument_id/trading_date；
    也兼容内部列名。文件必须包含 exp_ret/status/buy_eligible。
    SHA-256 作用于文件原始字节（不是内容 JSON 指纹）。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"信号 Parquet 文件不存在: {p}")
    if (len(expected_sha256) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in expected_sha256)
            or set(expected_sha256) == {"0"}):
        raise ValueError("expected_sha256 必须是非全零的 64 位十六进制值")
    raw_bytes = p.read_bytes()
    actual = hashlib.sha256(raw_bytes).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"信号文件 SHA-256 不匹配\n"
            f"  文件: {p} ({p.stat().st_size} 字节)\n"
            f"  期望: {expected_sha256}\n"
            f"  实际: {actual}"
        )
    table = pq.read_table(pa.BufferReader(raw_bytes))
    columns = set(table.column_names)
    date_col = "date" if "date" in columns else "trading_date"
    code_col = "code" if "code" in columns else "instrument_id"
    required = {date_col, code_col, "exp_ret", "status", "buy_eligible"}
    missing = required - columns
    if missing:
        raise ValueError(f"信号 Parquet 缺少必需列: {missing}")
    rows_by_date: dict[date, list[dict]] = {}
    for batch in table.to_batches():
        for i in range(batch.num_rows):
            row = {col: batch.column(col)[i].as_py()
                   for col in table.column_names}
            td = row.pop(date_col, None)
            if td is None or not isinstance(td, (date, datetime)):
                raise ValueError(f"trading_date 缺失或非日期: {td}")
            if isinstance(td, datetime):
                td = td.date()
            if type(row["buy_eligible"]) is not bool:
                raise ValueError("冻结信号buy_eligible必须为真实bool")
            if date_col == "date" and row.get("trading_date", td) != td:
                raise ValueError("冻结信号日期别名冲突")
            if code_col == "code" and row.get("instrument_id", row[code_col]) != row[code_col]:
                raise ValueError("冻结信号代码别名冲突")
            row["instrument_id"] = row.pop(code_col)
            rows_by_date.setdefault(td, []).append(row)
    if not rows_by_date:
        raise ValueError("信号 Parquet 无任何数据行")
    return rows_by_date, actual


@dataclass(frozen=True)
class StagedWindowConfig:
    """单窗批次配置：来源、资金、成本、税务。"""

    source_id: str
    signal_file_sha256: str
    checkpoint_sha256: str
    initial_capital: float
    policy: Policy
    tick_size: float = 0.01
    lot_size: int = 100
    tax_policy: TaxPolicy = "cash_dividend_20pct_stress"
    cost_config: CostConfig | None = None
    period_id: str | None = None
    require_known_share_tax: bool = False

    def __post_init__(self) -> None:
        if not self.source_id or not self.source_id.strip():
            raise ValueError("source_id 必须非空")
        for label, value in (("signal_file_sha256", self.signal_file_sha256),
                             ("checkpoint_sha256", self.checkpoint_sha256)):
            if (len(value) != 64
                    or any(c not in "0123456789abcdefABCDEF" for c in value)
                    or set(value) == {"0"}):
                raise ValueError(f"{label} 必须是非全零的 64 位十六进制值")
        if (isinstance(self.initial_capital, bool)
                or not isinstance(self.initial_capital, (int, float))
                or not isfinite(self.initial_capital)
                or self.initial_capital <= 0):
            raise ValueError("initial_capital 必须为正数")
        Policy(self.policy)
        if (isinstance(self.tick_size, bool)
                or not isinstance(self.tick_size, (int, float))
                or not isfinite(self.tick_size)
                or self.tick_size <= 0):
            raise ValueError("tick_size 必须为正数")
        if (isinstance(self.lot_size, bool)
                or not isinstance(self.lot_size, int)
                or self.lot_size <= 0):
            raise ValueError("lot_size 必须为正整数")
        if self.tax_policy not in ("pretax", "cash_dividend_20pct_stress"):
            raise ValueError(f"不支持的税务策略: {self.tax_policy}")


@dataclass(frozen=True)
class WindowDefinition:
    """窗口日历：锚点、E 日、完整执行日历；signal/buffer 由 calendar 派生。

    派生规则：
        signal_dates = execution_calendar 中 anchor_date < d <= evaluation_end
        buffer_dates = execution_calendar 中 d > evaluation_end （恰好 3 日）
    """

    anchor_date: date
    evaluation_end: date
    execution_calendar: tuple[date, ...]

    def __post_init__(self) -> None:
        ensure_calendar_date(self.anchor_date, "anchor_date")
        ensure_calendar_date(self.evaluation_end, "evaluation_end")
        if (not self.execution_calendar
                or self.execution_calendar != tuple(sorted(set(
                    self.execution_calendar)))):
            raise ValueError("execution_calendar 必须非空、严格递增、无重复")
        for trading_day in self.execution_calendar:
            ensure_calendar_date(trading_day, "execution_calendar item")
        if self.execution_calendar[0] != self.anchor_date:
            raise ValueError("execution_calendar[0] 必须为 anchor_date")
        if self.evaluation_end not in self.execution_calendar:
            raise ValueError("evaluation_end 必须在 execution_calendar 中")
        if self.anchor_date >= self.evaluation_end:
            raise ValueError("anchor_date 必须早于 evaluation_end")
        sig = [d for d in self.execution_calendar
               if self.anchor_date < d <= self.evaluation_end]
        if not sig:
            raise ValueError("anchor 和 evaluation_end 之间必须含信号日")
        if sig[-1] != self.evaluation_end:
            raise ValueError("evaluation_end 必须是最后一个信号日")
        buf = [d for d in self.execution_calendar if d > self.evaluation_end]
        if len(buf) != 3:
            raise ValueError(f"buffer 必须恰好 3 个交易日, 收到 {len(buf)}")
        if buf and buf[-1] != self.execution_calendar[-1]:
            raise ValueError("buffer 末必须等于 execution_calendar 末")

    @property
    def signal_dates(self) -> tuple[date, ...]:
        return tuple(d for d in self.execution_calendar
                     if self.anchor_date < d <= self.evaluation_end)

    @property
    def buffer_dates(self) -> tuple[date, ...]:
        return tuple(d for d in self.execution_calendar
                     if d > self.evaluation_end)[:3]

    def date_type_check(self) -> None:
        """确认所有日期字段为 date 类型而非 datetime。"""
        for name, val in (("anchor_date", self.anchor_date),
                          ("evaluation_end", self.evaluation_end)):
            if type(val) is not date:
                raise TypeError(f"{name} 必须为 date, 收到 {type(val)}")
        for day in self.execution_calendar:
            if type(day) is not date:
                raise TypeError("execution_calendar 元素必须为 date")


@dataclass(frozen=True)
class StagedWindowOutcome:
    """单窗运行结果：core 评估 + 血缘 + 断言。"""

    config: StagedWindowConfig
    window: WindowDefinition
    result: EvaluationResult
    provenance: dict[str, str]
    config_hash: str
    signal_file_sha256: str
    signal_content_sha256: str
    manifest_sha256: str | None = None
    validation_failures: tuple[str, ...] = ()
    mechanical_status: Literal["PASS", "INCOMPLETE", "FAILED"] = "PASS"
    production_acceptance: Literal["INCOMPLETE", "BLOCKED"] = "INCOMPLETE"


def _signal_content_fingerprint(
    signal_rows_by_date: Mapping[date, Sequence[Mapping]],
) -> str:
    canonical = json.dumps(
        {
            day.isoformat(): [
                dict(sorted(row.items(), key=lambda x: x[0]))
                for row in sorted(rows, key=lambda r: str(r.get("instrument_id", "")))
            ]
            for day, rows in sorted(signal_rows_by_date.items())
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_signal_ranking(
    source_id: str,
    signal_rows_by_date: Mapping[date, Sequence[Mapping]],
) -> dict[date, RankingSnapshot]:
    snapshots: dict[date, RankingSnapshot] = {}
    for day, rows in sorted(signal_rows_by_date.items()):
        snapshots[day] = RankingSnapshot.from_scores(
            day, source_id, list(rows), complete=True,
        )
    return snapshots


def _config_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    """只序列化原始契约字段，避免 mappingproxy 的深拷贝或对象 repr。"""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, BaseModel):
        return _plain(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_plain(v) for v in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def _freeze_fees(days, codes, cost, resolver, prepared=None):
    if prepared is not None:
        table, rows = prepared.fee_table, prepared.fee_rows
    else:
        table = {}
        for day in days:
            for code in codes:
                resolved = resolver(day, code) if resolver is not None else cost
                if not isinstance(resolved, CostConfig):
                    raise TypeError("cost_config_resolver 必须返回 CostConfig")
                table[day, code] = CostConfig(**resolved.model_dump())
        rows = [{"date": d.isoformat(), "code": c, "cost_config": _plain(fee)}
                for (d, c), fee in sorted(table.items())]
    used: list[dict] = []

    def lookup(day: date, code: str) -> CostConfig:
        fee = table[day, code]
        used.append({"date": day.isoformat(), "code": code, "cost_config": _plain(fee)})
        return fee

    return lookup, rows, used


class _RecordingObserver:
    """先原样交付 bridge，再记录不可变 core 事件和 registry 决策状态。"""

    def __init__(self, bridge: StagedExecutionBridge, registry: AllocationRegistry):
        self.bridge = bridge
        self.registry = registry
        self.updates: list[dict] = []
        self.transitions: list[dict] = []
        self.daily: dict[date, dict] = {}
        self.decisions: list[dict] = []

    def on_update(self, update: ExecutionUpdate) -> None:
        self.updates.append(_plain(update))
        if abs(update.post_state.cash - update.pre_state.cash - update.cash_delta) > 1e-6:
            raise ValueError("真实core回调现金差额不守恒")
        self.bridge.on_update(update)
        if sum(v > 0 for v in update.post_state.positions.values()) > 10:
            raise ValueError("真实持仓超过10只")
        if self.registry.snapshot().active_slots > 5:
            raise ValueError("预算槽超过5")
        self.capture(update.trading_date, "execution_update")

    def capture(self, day: date, stage: str) -> None:
        row = {"date": day.isoformat(), "stage": stage,
               "registry": _plain(self.registry.snapshot()),
               "free_cash": self.registry.free_cash,
               "occupied_codes": sorted(self.registry.active_codes),
               "episodes": _episode_summary(self.registry),
               "core_state": self.updates[-1]["post_state"],
               "core_snapshot": _plain(self.registry.core_snapshot)}
        self.transitions.append(row)
        self.daily[day] = row


class _RecordingStrategy(StagedOrderStrategy):
    recorder: _RecordingObserver

    def orders_for(self, *, trading_date: date, signal_time: datetime,
                   account: AccountView, market: MarketView):
        before = len(self.rejection_log)
        orders = super().orders_for(trading_date=trading_date, signal_time=signal_time,
                                    account=account, market=market)
        self.recorder.decisions.append({"signal_date": trading_date.isoformat(),
            "orders": _plain(orders), "rejections": list(self.rejection_log[before:]),
            "position_usage": _plain(self.position_usage)})
        self.recorder.capture(trading_date, "after_close_decision")
        return orders


def _market_coverage(market: MarketDataProvider, codes, days, *, keep_keys=None,
                     stream_path: str | Path | None = None) -> dict:
    """逐代码日期核对状态字段；全表计数不能替代窗口内覆盖。

    必须代码外层循环：懒加载查找（StateLookup/RawRecordLookup）只缓存当前代码。
    """
    states = getattr(market, "verified_states", None)
    rows = []
    missing_count = unknown_count = total = 0
    stream = open(stream_path, "w", encoding="utf-8") if stream_path else None  # noqa: SIM115
    try:
      for code in codes:
        for day in days:
            bar = market.get_bar(code, day)
            state = states.get((code, day)) if states is not None and hasattr(states, "get") else None
            unknown = []
            if bar is None:
                unknown.append("bar")
            else:
                for field in ("market_state_known", "st_state_known", "reference_known", "limit_state_known"):
                    if getattr(bar, field) is not True:
                        unknown.append(field)
                for field in ("absolute_limit_up_price", "absolute_limit_down_price"):
                    if getattr(bar, field) is None:
                        unknown.append(field)
            if not isinstance(state, Mapping):
                unknown.append("verified_states")
            else:
                if state.get("market_state") not in ("trading", "suspended"):
                    unknown.append("market_state")
                for field in ("st_known", "reference_known", "limit_known"):
                    if state.get(field) is not True:
                        unknown.append(field)
            item = {"date": day.isoformat(), "code": code, "bar_present": bar is not None,
                    "unknown_fields": unknown, "verified_state": _plain(state), "bar": _plain(bar)}
            total += 1
            missing_count += bar is None
            unknown_count += bool(unknown)
            if stream:
                stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
            if keep_keys is None or (code, day) in keep_keys:
                rows.append(item)
    finally:
        if stream:
            stream.close()
    return {"expected_count": total, "missing_bar_count": missing_count,
            "unknown_count": unknown_count, "rows": rows,
            "source_known": False, "source_status": "真实快照血缘尚未独立验收"}


def _compute_manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mechanical_status(failures) -> Literal["PASS", "INCOMPLETE"]:
    incomplete = ("market_data_missing", "market_state_coverage_unknown",
                  "corporate_action_exposure", "quantity_rule_exposure", "core_warning:",
                  "buffer_residual", "outstanding_receivables", "unlisted_entitlements")
    return "INCOMPLETE" if any(f.startswith(incomplete) for f in failures) else "PASS"


def _write_jsonl(path: Path, records: Sequence[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False,
                               default=str) + "\n")


def _snapshot_to_row(snap, anchor_date: date) -> dict:
    return {
        "core_snapshot": _plain(snap),
        "date": snap.date.isoformat(),
        "cash": snap.cash,
        "available_cash": snap.available_cash,
        "blocked_cash": snap.cash - (snap.available_cash or 0),
        "nav": snap.nav,
        "positions": [
            {"code": code, "shares": pos.shares, "cost": pos.cost,
             "price": pos.price, "market_value": pos.market_value}
            for code, pos in sorted(snap.positions.items())
        ],
        "held_code_count": len(snap.positions),
        "receivables_value": snap.receivables_value,
        "unlisted_entitlements": [
            {"event_id": eid, "instrument_id": ent.instrument_id,
             "shares": ent.shares, "market_value": ent.market_value}
            for eid, ent in sorted(snap.unlisted_entitlements.items())
        ],
    }


def _trade_to_row(event) -> dict:
    return {
        "signal_date": event.signal_time.date().isoformat(),
        "execution_date": event.execution_time.date().isoformat(),
        "instrument_id": event.instrument_id,
        "side": event.side.value,
        "shares": event.shares,
        "fill_price": event.execution_price,
        "amount": event.amount,
        "commission": event.commission,
        "stamp_tax": event.stamp_tax,
        "transfer_fee": event.transfer_fee,
        "slippage_cost": event.slippage_cost,
        "participation": event.participation,
        "status": event.status.value,
        "reason": event.reason.value if event.reason else None,
        "episode_id": event.episode_id,
        "order_id": event.order_id,
        "fill_id": event.fill_id,
    }


def _full_rank_rows(
    snapshots: Mapping[date, RankingSnapshot],
) -> dict[str, list[dict]]:
    """每信号日全部 code→rank→eligible。"""
    result: dict[str, list[dict]] = {}
    for day, snap in sorted(snapshots.items()):
        rows = [
            {"code": code, "rank": rank,
             "buy_eligible": snap.buy_eligible.get(code, False)}
            for code, rank in sorted(snap.ranks.items(), key=lambda x: x[1])
        ]
        result[day.isoformat()] = rows
    return result


def _episode_summary(registry: AllocationRegistry) -> list[dict]:
    rows = []
    for ep in sorted(registry.episodes.values(), key=lambda x: x.episode_id):
        tranches = [
            {"tranche_id": tid, "decision_date": t.decision_date.isoformat(),
             "status": t.status.value, "budget": t.budget,
             "details": _plain(t),
             "order_id": t.order_id,
             "requested_shares": t.requested_shares,
             "filled_shares": t.filled_shares, "cash_debit": t.cash_debit}
            for (eid, tid), t in sorted(registry.tranches.items())
            if eid == ep.episode_id
        ]
        rows.append({
            "episode_id": ep.episode_id, "code": ep.code,
            "policy": ep.policy.value, "commitment": ep.commitment,
            "investment_cap": ep.investment_cap,
            "cumulative_cash_debit": ep.cumulative_cash_debit,
            "exit_pending": ep.exit_pending,
            "status": ep.status.value, "tranches": tranches,
            "details": _plain(ep),
        })
    return rows


def run_staged_window(*, window: WindowDefinition, config: StagedWindowConfig,
                      signal_parquet_path: str | Path, market: MarketDataProvider,
                      corporate_action_provider: CorporateActionProvider | None = None,
                      cost_config_resolver: Callable[[date, str], CostConfig] | None = None,
                      corporate_action_snapshot: CorporateActionSnapshot | None = None,
                      quantity_rule_resolver: Callable[[date, str], QuantityRule] | None = None,
                      prepared_inputs: Any = None, output_dir: str | Path | None = None,
                      mode: Literal["reset", "continuous"] = "reset") -> StagedWindowOutcome:
    """每次新建真实账户，任何退出路径保存已收到的原始回调。"""
    audit: dict = {"mechanical_status": "INCOMPLETE", "window": _plain(window)}
    out = Path(output_dir) if output_dir is not None else None
    if out is not None:
        os.makedirs(out, exist_ok=False)
    try:
        outcome = _run_staged_window_impl(
            window=window, config=config, signal_parquet_path=signal_parquet_path,
            market=market, corporate_action_provider=corporate_action_provider,
            cost_config_resolver=cost_config_resolver,
            corporate_action_snapshot=corporate_action_snapshot,
            quantity_rule_resolver=quantity_rule_resolver, prepared_inputs=prepared_inputs,
            output_dir=out, mode=mode, audit=audit)
        audit["mechanical_status"] = outcome.mechanical_status
        return outcome
    except Exception as error:
        audit["error"] = {"type": type(error).__name__, "reason": str(error)}
        raise
    finally:
        if out is not None:
            _write_final_audit(out, audit, config)


def _write_final_audit(out: Path, audit: dict, config: StagedWindowConfig) -> None:
    recorder = audit.pop("recorder", None)
    registry = audit.pop("registry", None)
    ctx = audit.pop("context", None)
    if recorder is not None:
        _write_jsonl(out / "execution_updates.jsonl", recorder.updates)
        _write_jsonl(out / "registry_transitions.jsonl", recorder.transitions)
        _write_jsonl(out / "daily_registry.jsonl", list(recorder.daily.values()))
        _write_jsonl(out / "strategy_decisions.jsonl", recorder.decisions)
        _write_jsonl(out / "partial_account_states.jsonl", [
            {"event_id": u["event_id"], "date": u["trading_date"], "state": u["post_state"]}
            for u in recorder.updates])
    if "rank_summary" in audit:
        (out / "rank_summary.json").write_text(json.dumps(
            audit.pop("rank_summary"), ensure_ascii=False, default=str), encoding="utf-8")
    if registry is not None:
        audit["last_registry"] = _plain(registry.snapshot())
    ca = ctx.evidence() if ctx is not None else {"not_integrated": True}
    (out / "corporate_action_evidence.json").write_text(
        json.dumps(ca, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    quantity_rows = audit.pop("quantity_rule_usage", [])
    if recorder is not None:
        for row in quantity_rows:
            row["orders"] = [order for decision in recorder.decisions
                if decision["signal_date"] == str(row["signal_date"])
                for order in decision["orders"] if order["instrument_id"] == row["code"]]
    _write_jsonl(out / "quantity_rule_usage.jsonl", quantity_rows)
    _write_jsonl(out / "opportunity_coverage.jsonl", audit.pop("opportunities", []))
    audit["config"] = _plain(config)
    audit["actual_after_tax_target_eligible"] = False
    audit["window_identity_validation"] = "matched_core_arguments" if ctx else "not_integrated"
    (out / "attempt_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if "error" in audit:
        (out / "manifest.json").write_text(json.dumps(
            audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    artifacts = {p.name: _compute_manifest_sha256(p) for p in sorted(out.iterdir())
                 if p.is_file() and p.name != "artifacts.json"}
    (out / "artifacts.json").write_text(json.dumps(artifacts, indent=2), encoding="utf-8")


def _run_staged_window_impl(
    *,
    window: WindowDefinition,
    config: StagedWindowConfig,
    signal_parquet_path: str | Path,
    market: MarketDataProvider,
    corporate_action_provider: CorporateActionProvider | None = None,
    cost_config_resolver: Callable[[date, str], CostConfig] | None = None,
    corporate_action_snapshot: CorporateActionSnapshot | None = None,
    quantity_rule_resolver: Callable[[date, str], QuantityRule] | None = None,
    prepared_inputs: Any = None,
    audit: dict,
    output_dir: str | Path | None = None,
    mode: Literal["reset", "continuous"] = "reset",
) -> StagedWindowOutcome:
    """执行单窗分批候选运行。

    只消费 signal_parquet_path 中由 config.signal_file_sha256 绑定的冻结文件。
    """
    window.date_type_check()
    if mode == "continuous":
        raise NotImplementedError(
            "continuous 模式未实现：需要单次 core runner 保留账户、"
            "预算、episode 及权益跨窗口延续，本增量不支持。"
        )
    if mode != "reset":
        raise ValueError(f"不支持的运行模式: {mode!r}")
    if corporate_action_provider is not None and not config.period_id:
        raise ValueError("corporate_action_provider 必须绑定非空 period_id")
    if config.require_known_share_tax and corporate_action_snapshot is None:
        raise NotImplementedError("require_known_share_tax 尚未接入已核验送转税上下文")
    if corporate_action_provider is not None:
        raise NotImplementedError(
            "拒绝旧 provider 全市场直接执行；待接入独立 corporate_action_context 与 snapshot_loader")
    if prepared_inputs is None:
        signal_rows_by_date, signal_file_sha256 = load_frozen_signal_parquet(
            signal_parquet_path, config.signal_file_sha256)
    else:
        prepared_inputs.validate(window, config, signal_parquet_path)
        signal_rows_by_date = prepared_inputs.signal_rows
        signal_file_sha256 = prepared_inputs.signal_sha256
    if set(signal_rows_by_date) != set(window.signal_dates):
        missing = sorted(set(window.signal_dates) - set(signal_rows_by_date))
        extra = sorted(set(signal_rows_by_date) - set(window.signal_dates))
        raise ValueError(f"信号文件日期与窗口不一致: missing={missing}, extra={extra}")
    # 文件字节 SHA 与消费内容指纹独立留存。
    content_sha = _signal_content_fingerprint(signal_rows_by_date)
    snapshots = (build_signal_ranking(config.source_id, signal_rows_by_date)
                 if prepared_inputs is None else prepared_inputs.rankings)
    codes = sorted({str(row["instrument_id"]) for rows in signal_rows_by_date.values() for row in rows})
    coverage = (_market_coverage(market, codes, window.execution_calendar)
                if prepared_inputs is None else prepared_inputs.coverage)
    audit["rank_summary"] = _full_rank_rows(snapshots)
    audit["opportunities"] = [
        {"signal_date": day, "execution_date": window.execution_calendar[
            window.execution_calendar.index(day) + 1], "code": code, "rank": rank,
         "buy_eligible": ranking.buy_eligible[code]}
        for day, ranking in snapshots.items() for code, rank in ranking.ranks.items() if rank <= 5]

    sig_dates = window.signal_dates
    missing_dates = [str(d) for d in sig_dates if d not in snapshots]
    if missing_dates:
        raise ValueError(f"信号日期缺少排名快照: {missing_dates}")

    ranking_source = MappingRankingSource(snapshots)
    calendar_days = list(window.execution_calendar)
    registry = AllocationRegistry(
        initial_cash=config.initial_capital, calendar_days=calendar_days,
    )
    bridge = StagedExecutionBridge(registry)
    recorder = _RecordingObserver(bridge, registry)
    audit.update(recorder=recorder, registry=registry, quantity_rule_usage=[])
    ctx = None
    if corporate_action_snapshot is not None:
        if not config.period_id:
            raise ValueError("公司行动 snapshot 必须绑定 period_id")
        ctx = CorporateActionContext(
            corporate_action_snapshot, period_id=config.period_id,
            reset_anchor=window.anchor_date, empty_reset=True,
            strict_tax=config.require_known_share_tax, tax_policy=config.tax_policy,
            delegate=recorder, window_end=window.execution_calendar[-1],
            calendar_sha256=_config_hash([d.isoformat() for d in window.execution_calendar]))
        audit["context"] = ctx
    def quantity_for_signal(day, code):
        index = window.execution_calendar.index(day) + 1
        execution_day = window.execution_calendar[index] if index < len(window.execution_calendar) else None
        usage = {"signal_date": day, "execution_date": execution_day, "code": code}
        audit["quantity_rule_usage"].append(usage)
        if execution_day is None:
            usage["rejected"] = "no_next_execution_day"
            raise QuantityRuleError("无下一执行日，保留真实残留持仓")
        assert quantity_rule_resolver is not None
        try:
            rule = quantity_rule_resolver(execution_day, code)
            usage["rule"] = _plain(rule)
            return rule
        except (ValueError, KeyError) as error:
            usage["rejected"] = str(error)
            raise QuantityRuleError(str(error)) from error
    buf_dates = window.buffer_dates
    buffer_start = buf_dates[0] if buf_dates else None
    cost = config.cost_config if config.cost_config is not None else CostConfig()
    frozen_resolver, fee_table, used_fees = _freeze_fees(
        window.execution_calendar[1:], codes, cost, cost_config_resolver, prepared_inputs)
    strategy = _RecordingStrategy(
        registry=registry, ranking_source=ranking_source,
        policy=config.policy,
        execution_calendar=window.execution_calendar,
        worst_case_cost_config=cost,
        cost_config_resolver=frozen_resolver,
        tick_size=config.tick_size, lot_size=config.lot_size,
        buffer_start_date=buffer_start,
        quantity_rule_resolver=quantity_for_signal if quantity_rule_resolver else None,
    )
    strategy.recorder = recorder
    exec_dates = list(window.execution_calendar)
    run_id = (
        f"staged_{config.policy.value}_{config.source_id}_"
        f"{sig_dates[0].isoformat()}_{window.evaluation_end.isoformat()}"
    )
    # 排他创建输出目录
    out_path = Path(output_dir) if output_dir is not None else None
    execution_config = ExecutionConfig(final_liquidation="mark")
    result = run_account_backtest_from_orders(
        execution_calendar=exec_dates,
        signal_dates=list(sig_dates),
        maintenance_dates=list(buf_dates),
        anchor_date=window.anchor_date,
        evaluation_end=window.evaluation_end,
        strategy=strategy,
        market=market,
        observer=ctx if ctx is not None else recorder,
        account_actions_provider=ctx.account_actions_for_day if ctx is not None else None,
        execution_config=execution_config,
        portfolio_config=PortfolioConfig(top_n=10, lot_size=config.lot_size),
        cost_config=cost,
        cost_config_resolver=frozen_resolver,
        run_id=run_id,
        model_id=f"staged_{config.policy.value}",
        initial_capital=config.initial_capital,
        signal_time_of_day=time(15, 0),
    )
    # 构建 provenance
    for account_snapshot in result.account_snapshots:
        holdings = [p for p in account_snapshot.positions.values() if p.shares > 0]
        if any(p.market_value is None for p in holdings):
            raise ValueError("真实正持仓缺估值，不能以零替代")
        assets = (account_snapshot.cash + account_snapshot.receivables_value
                  + sum(p.market_value or 0 for p in holdings)
                  + sum(e.market_value for e in account_snapshot.unlisted_entitlements.values()))
        if len(holdings) > 10 or abs(assets - account_snapshot.nav) > 1e-6:
            raise ValueError("逐日真实持仓上限或账户净值守恒失败")
    prov: dict[str, str] = {
        "run_id": run_id,
        "source_id": config.source_id,
        "signal_file_sha256": signal_file_sha256,
        "signal_content_sha256": content_sha,
        "checkpoint_sha256": config.checkpoint_sha256,
        "policy": config.policy.value,
        "initial_capital": str(config.initial_capital),
        "tranche_budget": str(budget_per_episode(config.initial_capital)),
        "anchor_date": window.anchor_date.isoformat(),
        "evaluation_end": window.evaluation_end.isoformat(),
        "signal_date_count": str(len(sig_dates)),
        "buffer_date_count": str(len(buf_dates)),
        "mode": mode,
        "tax_policy": config.tax_policy,
        "tax_disclaimer": "cash_dividend_20pct_stress 是现金分红 20% 压力测试，"
                          "非实际个人税制；送转税务未知，税后结果不可作实际税后收益",
        "period_id": config.period_id or "",
        "lot_size": str(config.lot_size),
        "quantity_rule_status": "source_bound_pending_qa" if quantity_rule_resolver else "not_accepted",
        "market_provider_type": type(market).__qualname__,
        "verified_state_count": str(len(getattr(market, "verified_states", {})))
        if hasattr(getattr(market, "verified_states", {}), "__len__") else "lazy_source_bound",
        "cost_config_source": "frozen_resolver" if cost_config_resolver is not None
        else ("argument" if config.cost_config is not None else "default_CostConfig"),
        "corporate_action_provider": corporate_action_provider.fingerprint
        if corporate_action_provider is not None else "none",
    }
    # 排名摘要：全部 code/rank per signal day
    rank_summary = _full_rank_rows(snapshots)
    prov["rank_full"] = json.dumps(rank_summary, sort_keys=True)
    # 预算摘要
    snap = registry.snapshot()
    prov["active_slots_end"] = str(snap.active_slots)
    prov["active_commitments_end"] = str(snap.active_commitments)
    prov["available_cash_end"] = str(snap.available_cash)
    episode_ids = [ep.episode_id for ep in sorted(
        registry.episodes.values(), key=lambda x: x.episode_id)]
    prov["episode_count"] = str(len(episode_ids))
    prov["episode_ids"] = ",".join(episode_ids)
    # 快照分段：主区间与 buffer
    evaluation_snapshot = next(
        item for item in result.account_snapshots
        if item.date == window.evaluation_end
    )
    main_snapshots = tuple(
        item for item in result.account_snapshots
        if window.anchor_date < item.date <= window.evaluation_end
    )
    main_trades = tuple(
        event for event in result.trades
        if event.execution_time.date() <= window.evaluation_end
    )
    buffer_trades = tuple(
        event for event in result.trades
        if event.execution_time.date() > window.evaluation_end
    )
    buf_end = buf_dates[-1] if buf_dates else window.evaluation_end
    buffer_snapshots = tuple(
        item for item in result.account_snapshots
        if window.evaluation_end < item.date <= buf_end
    )
    filled_amounts = tuple(
        event.amount for event in main_trades
        if event.status in _FILLED_STATUSES
    )
    account_evaluation = evaluate_account(
        main_snapshots, result.methodology,
        initial_capital=config.initial_capital,
        trade_amounts=filled_amounts,
    )
    prov["main_nav_end"] = str(evaluation_snapshot.nav)
    prov["main_total_return"] = str(
        account_evaluation.get("total_return", "N/A"))
    if buffer_snapshots:
        buffer_evaluation = evaluate_account(
            buffer_snapshots, result.methodology,
            initial_capital=evaluation_snapshot.nav,
            trade_amounts=tuple(
                event.amount for event in buffer_trades
                if event.status in _FILLED_STATUSES
            ),
        )
        prov["buffer_nav_start"] = str(evaluation_snapshot.nav)
        prov["buffer_nav_end"] = str(buffer_snapshots[-1].nav)
        prov["buffer_return"] = str(
            buffer_evaluation.get("total_return", "N/A"))
    opportunities = []
    demanded = set()
    for day, ranking in snapshots.items():
        next_day = window.execution_calendar[window.execution_calendar.index(day) + 1]
        for code, rank in ranking.ranks.items():
            if rank <= 5:
                eligible = ranking.buy_eligible[code]
                opportunities.append({"signal_date": day, "execution_date": next_day,
                                      "code": code, "rank": rank, "buy_eligible": eligible})
                if eligible and day < window.evaluation_end:
                    demanded.update(((code, day.isoformat()), (code, next_day.isoformat())))
    for update in recorder.updates:
        demanded.update((code, update["trading_date"]) for code, shares in
                        update["post_state"]["positions"].items() if shares > 0)
    exposed = [row for row in coverage["rows"] if (row["code"], row["date"]) in demanded]
    coverage_index = {(r["code"], r["date"]): r for r in coverage["rows"]}
    for opportunity in opportunities:
        code, signal_day = opportunity["code"], str(opportunity["signal_date"])
        opportunity["input_coverage"] = [coverage_index.get((code, str(opportunity[field])))
                                          for field in ("signal_date", "execution_date")]
        opportunity["decisions"] = [d for d in recorder.decisions if d["signal_date"] == signal_day]
        opportunity["unused_slots"] = 5 - recorder.daily[opportunity["signal_date"]]["registry"]["active_slots"]
    audit["exposure_unknown_count"] = sum(bool(r["unknown_fields"]) for r in exposed)
    audit["opportunities"] = opportunities
    failures = ["share_tax_unknown", "market_source_lineage_not_accepted",
                "authoritative_calendar_not_accepted", "checkpoint_artifact_not_verified"]
    if quantity_rule_resolver is None:
        failures.append("quantity_rules_not_accepted")
    if ctx is None:
        failures.append("corporate_action_context_not_integrated")
    if any(not row["bar_present"] for row in exposed):
        failures.append("market_data_missing")
    if audit["exposure_unknown_count"]:
        failures.append("market_state_coverage_unknown")
    if ctx is not None and ctx.evidence()["incomplete"]:
        failures.append("corporate_action_exposure_incomplete")
    if any(row.get("rejected") not in (None, "no_next_execution_day") for row in audit["quantity_rule_usage"]):
        failures.append("quantity_rule_exposure_unknown")
    terminal = result.account_snapshots[-1]
    if any(p.shares > 0 for p in terminal.positions.values()):
        failures.append("buffer_residual_positions")
    if terminal.receivables_value:
        failures.append("outstanding_receivables")
    if terminal.unlisted_entitlements:
        failures.append("unlisted_entitlements")
    failures.extend(("execution_source_known_at_unknown", "ca_implementation_and_pit_unknown"))
    if prepared_inputs is not None:
        failures = [f for f in failures if f not in prepared_inputs.closed_gates]
    failures.extend(f"core_warning:{warning}" for warning in result.warnings)
    acceptance: Literal["INCOMPLETE", "BLOCKED"] = (
        "BLOCKED" if audit["exposure_unknown_count"] else "INCOMPLETE")
    effective = {
        "config": _plain(config), "mode": mode,
        "execution_config": _plain(execution_config),
        "portfolio_config": _plain(PortfolioConfig(top_n=10, lot_size=config.lot_size)),
        "signal_time_of_day": "15:00:00",
        "action_input_fingerprint": "none" if ctx is None else _config_hash({
            "files": dict(ctx.snapshot.file_sha256), "manifest": ctx.snapshot.manifest_sha256}),
        "quantity_rule_usage_sha256": _config_hash(audit["quantity_rule_usage"]),
        "prepared_manifest_sha256": getattr(prepared_inputs, "sources_sha256", None),
        "core_engine_version": result.engine_version, "core_policy_version": result.policy_version,
        "core_schema_version": result.schema_version, "methodology": _plain(result.methodology),
        "core_runner_sha256": hashlib.sha256(Path(inspect.getfile(run_account_backtest_from_orders)).read_bytes()).hexdigest(),
        "warnings": list(result.warnings), "static_cost": _plain(cost),
        "fee_table_sha256": _config_hash({"rows": fee_table}),
        "fee_table": fee_table if prepared_inputs is None else prepared_inputs.fee_source,
        "market_inputs_sha256": coverage.get("shared_sha256") or _config_hash(coverage),
        "e_boundary": "E-1订单可在E执行；E收盘与buffer不提交BUY",
    }
    config_hash = _config_hash({
        "effective": effective,
        "source_id": config.source_id,
        "signal_file_sha256": config.signal_file_sha256,
        "checkpoint_sha256": config.checkpoint_sha256,
        "policy": config.policy.value,
        "initial_capital": config.initial_capital,
        "tick_size": config.tick_size, "lot_size": config.lot_size,
        "tax_policy": config.tax_policy,
        "cost_config": cost.model_dump(),
        "anchor_date": window.anchor_date.isoformat(),
        "evaluation_end": window.evaluation_end.isoformat(),
        "execution_calendar": [d.isoformat()
                               for d in window.execution_calendar],
    })
    outcome = StagedWindowOutcome(
        config=config, window=window, result=result,
        provenance=prov, config_hash=config_hash,
        signal_file_sha256=signal_file_sha256,
        signal_content_sha256=content_sha,
        validation_failures=tuple(failures), production_acceptance=acceptance,
        mechanical_status=_mechanical_status(failures),
    )
    # 写出产物
    if out_path is not None:
        _write_outputs(out_path, result, prov, rank_summary, registry,
                       window, config, config_hash, signal_file_sha256,
                       recorder, strategy, effective, coverage, used_fees, tuple(failures), acceptance)
        outcome = StagedWindowOutcome(
            config=config, window=window, result=result,
            provenance=prov, config_hash=config_hash,
            signal_file_sha256=signal_file_sha256,
            signal_content_sha256=content_sha,
            validation_failures=tuple(failures), production_acceptance=acceptance,
            mechanical_status=outcome.mechanical_status,
            manifest_sha256=_compute_manifest_sha256(
                out_path / "manifest.json"),
        )
    return outcome


def _write_outputs(
    out_path: Path,
    result: EvaluationResult,
    provenance: dict[str, str],
    rank_summary: dict[str, list[dict]],
    registry: AllocationRegistry,
    window: WindowDefinition,
    config: StagedWindowConfig,
    config_hash: str,
    signal_file_sha256: str,
    recorder: _RecordingObserver,
    strategy: StagedOrderStrategy,
    effective: dict,
    coverage: dict,
    used_fees: list[dict],
    failures: tuple[str, ...],
    acceptance: Literal["INCOMPLETE", "BLOCKED"],
) -> None:
    """排他写入 manifest / daily_account / orders_fills / rank_summary / episode。"""
    # 1. manifest.json
    manifest = {
        "schema_version": "2.0",
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": provenance.get("run_id", ""),
        "source_id": config.source_id,
        "policy": config.policy.value,
        "initial_capital": config.initial_capital,
        "tranche_budget": budget_per_episode(config.initial_capital),
        "signal_file_sha256": signal_file_sha256,
        "signal_content_sha256": provenance.get("signal_content_sha256", ""),
        "checkpoint_sha256": config.checkpoint_sha256,
        "config_hash": config_hash,
        "anchor_date": window.anchor_date.isoformat(),
        "evaluation_end": window.evaluation_end.isoformat(),
        "execution_calendar": [d.isoformat()
                               for d in window.execution_calendar],
        "signal_dates": [d.isoformat() for d in window.signal_dates],
        "buffer_dates": [d.isoformat() for d in window.buffer_dates],
        "tax_policy": config.tax_policy,
        "tax_disclaimer": "cash_dividend_20pct_stress 是现金分红20%"
                          "压力测试，非实际个人税制",
        "lot_size": config.lot_size,
        "quantity_rule_status": provenance["quantity_rule_status"],
        "mode": provenance.get("mode", "reset"),
        "main_total_return": provenance.get("main_total_return", "N/A"),
        "main_nav_end": provenance.get("main_nav_end", "N/A"),
        "buffer_return": provenance.get("buffer_return", "N/A"),
        "buffer_nav_end": provenance.get("buffer_nav_end", "N/A"),
        "episode_count": provenance.get("episode_count", "0"),
        "provenance": provenance,
        "mechanical_status": _mechanical_status(failures),
        "actual_after_tax_target_eligible": False,
        "production_acceptance": acceptance,
        "validation_failures": list(failures),
        "effective_config": effective,
        "market_coverage": {k: v for k, v in coverage.items() if k != "rows"},
        "integration_gate": "接线结果待独立QA；实际税、实施与PIT资格仍未知",
        "warnings": list(result.warnings),
    }
    (out_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                   indent=2, default=str),
        encoding="utf-8",
    )
    # 2. daily_account.jsonl
    snap_rows = [
        {**_snapshot_to_row(s, window.anchor_date),
         "core_state": recorder.daily[s.date]["core_state"],
         "state_lineage": recorder.daily[s.date]["registry"]["core_snapshot_id"]}
        for s in result.account_snapshots
    ]
    _write_jsonl(out_path / "daily_account.jsonl", snap_rows)
    # 3. decisions_orders_fills.jsonl
    trade_rows = [_trade_to_row(t) for t in result.trades]
    _write_jsonl(out_path / "decisions_orders_fills.jsonl", trade_rows)
    _write_jsonl(out_path / "execution_updates.jsonl", recorder.updates)
    _write_jsonl(out_path / "registry_transitions.jsonl", recorder.transitions)
    _write_jsonl(out_path / "daily_registry.jsonl", [recorder.daily[d] for d in window.execution_calendar])
    _write_jsonl(out_path / "order_results.jsonl", [
        {**_plain(item), "remaining_shares": item.order.shares - item.filled_shares
         if item.order.shares is not None else None}
        for item in result.order_results])
    _write_jsonl(out_path / "strategy_rejections.jsonl", [{"reason": reason} for reason in strategy.rejection_log])
    _write_jsonl(out_path / "market_coverage.jsonl",
                 [{"shared_path": coverage["shared_path"], "sha256": coverage["shared_sha256"]}]
                 if "shared_path" in coverage else coverage["rows"])
    _write_jsonl(out_path / "actual_fee_usage.jsonl", used_fees)
    # 4. rank_summary.json
    (out_path / "rank_summary.json").write_text(
        json.dumps(rank_summary, sort_keys=True, ensure_ascii=False,
                   indent=2, default=str),
        encoding="utf-8",
    )
    # 5. episode_summary.json
    epi_rows = _episode_summary(registry)
    (out_path / "episode_summary.json").write_text(
        json.dumps(epi_rows, sort_keys=False, ensure_ascii=False,
                   indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("候选运行器输出已写入 %s: manifest, daily_account, "
                "orders_fills, rank_summary, episode_summary", out_path)


def _parse_calendar(path: str) -> list[date]:
    """从纯文本文件读日期列表，每行一个 YYYY-MM-DD。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"日历文件不存在: {p}")
    dates: list[date] = []
    for line in p.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        dates.append(date.fromisoformat(line))
    if not dates:
        raise ValueError(f"日历文件无有效日期: {p}")
    return dates


def main() -> None:
    """CLI：python -m backtest.cnn_adapter.staged_candidate_runner。"""
    import argparse
    parser = argparse.ArgumentParser(
        description="分批候选账户运行器（单窗 reset）")
    parser.add_argument("--signal-parquet", required=True,
                        help="冻结信号 Parquet 路径")
    parser.add_argument("--expected-sha256", required=True,
                        help="信号文件 SHA-256")
    parser.add_argument("--source-id", required=True,
                        help="来源标识")
    parser.add_argument("--checkpoint-sha256", required=True,
                        help="Checkpoint SHA-256")
    parser.add_argument("--anchor-date", required=True, type=date.fromisoformat,
                        help="锚点日期 (YYYY-MM-DD)")
    parser.add_argument("--evaluation-end", required=True,
                        type=date.fromisoformat,
                        help="E 日 (YYYY-MM-DD)")
    parser.add_argument("--execution-calendar", required=True,
                        help="日历文件路径，每行一个 YYYY-MM-DD")
    parser.add_argument("--policy", required=True,
                        choices=["B1", "S1", "S2", "C70"],
                        help="预算策略")
    parser.add_argument("--output-dir", required=True,
                        help="输出目录（必须不存在）")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0,
                        help="初始资金（默认 1,000,000）")
    parser.add_argument("--tax-policy", default="cash_dividend_20pct_stress",
                        choices=["pretax", "cash_dividend_20pct_stress"],
                        help="税务策略")
    parser.add_argument("--tick-size", type=float, default=0.01,
                        help="最小价格变动（默认 0.01）")
    parser.add_argument("--lot-size", type=int, default=100,
                        help="整手股数（默认 100）")
    parser.add_argument("--input-config", required=True, help="外部冻结输入配置")
    parser.add_argument("--prepared-manifest", help="复用已准备的共同只读输入")
    parser.add_argument("--research-mode", choices=["exploration", "strict"], default="exploration")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # 加载信号
    signal_rows, actual_sha = load_frozen_signal_parquet(
        args.signal_parquet, args.expected_sha256)
    logger.info("信号 Parquet 加载: %s, SHA=%s, 日期=%d",
                args.signal_parquet, actual_sha, len(signal_rows))
    # 读日历
    cal = _parse_calendar(args.execution_calendar)
    window = WindowDefinition(
        anchor_date=args.anchor_date,
        evaluation_end=args.evaluation_end,
        execution_calendar=tuple(cal),
    )
    window.date_type_check()
    logger.info("窗口: anchor=%s E=%s signals=%d buffers=%d",
                args.anchor_date, args.evaluation_end,
                len(window.signal_dates), len(window.buffer_dates))
    _cfg = StagedWindowConfig(
        source_id=args.source_id,
        signal_file_sha256=args.expected_sha256,
        checkpoint_sha256=args.checkpoint_sha256,
        initial_capital=args.initial_capital,
        policy=Policy(args.policy),
        tick_size=args.tick_size,
        lot_size=args.lot_size,
        tax_policy=args.tax_policy,
    )
    from backtest.cnn_adapter.staged_production_inputs import run_single_from_cli
    run_single_from_cli(args, window)


if __name__ == "__main__":
    main()
