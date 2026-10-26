"""终端退出计划与严格账户执行审计；不修改 core 的撮合结果或净值。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite

from backtest_core.contracts.config import ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import EventStatus, Side
from backtest_core.contracts.order import OrderIntent
from backtest_core.contracts.protocols import AccountView, MarketView, OrderStrategy
from backtest_core.contracts.result import EvaluationResult


@dataclass(frozen=True)
class TerminalPlan:
    calendar: tuple[date, ...]
    exit_signal_date: date
    evaluation_date: date
    buffer_dates: tuple[date, ...]

    @property
    def settlement_end(self) -> date:
        return self.buffer_dates[-1]


def build_terminal_plan(calendar: Sequence[date], evaluation_end: date, *, buffer_days: int = 1) -> TerminalPlan:
    """由显式交易日历生成 X/E/B；不补造自然日或交易日。"""
    days = tuple(calendar)
    if len(days) < 3 or any(type(day) is not date for day in days):
        raise ValueError("calendar must contain at least three pure date values")
    if days != tuple(sorted(set(days))):
        raise ValueError("calendar must be strictly increasing and unique")
    if isinstance(buffer_days, bool) or not isinstance(buffer_days, int) or buffer_days < 1:
        raise ValueError(f"buffer_days must be >= 1, got {buffer_days!r}")
    eligible = tuple(day for day in days if day <= evaluation_end)
    later = tuple(day for day in days if day > evaluation_end)
    if not eligible or len(later) < buffer_days:
        raise ValueError("calendar lacks exit-only date or requested settlement buffer")
    evaluation_date = eligible[-1]
    exit_signal_date = evaluation_date
    return TerminalPlan(days, exit_signal_date, evaluation_date, later[:buffer_days])


@dataclass(frozen=True)
class SuppressedOrder:
    signal_date: date
    execution_date: date
    order: OrderIntent
    reason: str


class ExitOnlyStrategy:
    """保留 E 收盘信号；E 日起只发实际持仓卖单，拦截执行日在 E 后的 BUY。"""

    def __init__(self, inner: OrderStrategy, plan: TerminalPlan) -> None:
        self.inner = inner
        self.plan = plan
        self._suppressed: list[SuppressedOrder] = []

    @property
    def suppressed_orders(self) -> tuple[SuppressedOrder, ...]:
        return tuple(self._suppressed)

    def orders_for(self, *, trading_date: date, signal_time: datetime,
                   account: AccountView, market: MarketView) -> Sequence[OrderIntent]:
        """终端包装器只读 core 账户；locked 保留在原持仓中交由 core 执行裁决。"""
        if trading_date not in self.plan.calendar:
            raise ValueError(f"trading_date outside terminal calendar: {trading_date!r}")
        if signal_time.date() != trading_date:
            raise ValueError(f"signal_time date does not match trading_date: {signal_time!r}")
        index = self.plan.calendar.index(trading_date)
        if trading_date >= self.plan.exit_signal_date:
            if trading_date >= self.plan.settlement_end or index + 1 >= len(self.plan.calendar):
                return ()
            next_date = self.plan.calendar[index + 1]
            if trading_date == self.plan.evaluation_date:
                orders = tuple(self.inner.orders_for(trading_date=trading_date, signal_time=signal_time,
                                                     account=account, market=market))
                self._suppressed.extend(
                    SuppressedOrder(trading_date, next_date, order, "execution_after_evaluation_end")
                    for order in orders if order.side is Side.BUY
                )
            return tuple(OrderIntent(code, Side.SELL, shares=position.shares)
                         for code, position in sorted(account.positions.items()) if position.shares > 0)
        orders = tuple(self.inner.orders_for(trading_date=trading_date, signal_time=signal_time,
                                             account=account, market=market))
        next_date = self.plan.calendar[index + 1]
        kept: list[OrderIntent] = []
        for order in orders:
            if order.side is Side.BUY and next_date > self.plan.evaluation_date:
                self._suppressed.append(SuppressedOrder(trading_date, next_date, order,
                                                        "execution_after_evaluation_end"))
            else:
                kept.append(order)
        return tuple(kept)


@dataclass(frozen=True)
class SnapshotMark:
    date: date
    cash: float
    available_cash: float
    blocked_cash: float
    receivables_value: float
    unlisted_value: float
    market_value: float
    nav: float
    positions: Mapping[str, tuple[int, float]]


@dataclass(frozen=True)
class ExecutionAuditReport:
    evaluation_mtm: SnapshotMark
    post_buffer: SnapshotMark
    filled_events: tuple[object, ...]
    locked_events: tuple[object, ...]
    unresolved_orders: tuple[object, ...]
    residual_positions: Mapping[str, tuple[int, float]]
    residual_entitlements: Mapping[str, float]
    residual_receivables: float
    cleared: bool


def validate_terminal_execution(execution_config: ExecutionConfig,
                                portfolio_config: PortfolioConfig) -> None:
    """逐日 T+1 + mark 是可审计执行 X/B 回调及期末估值的前置条件。"""
    if execution_config.execution_mode != "t1_open":
        raise ValueError("execution_config.execution_mode must be t1_open")
    if execution_config.final_liquidation != "mark":
        raise ValueError("execution_config.final_liquidation must be mark")
    if portfolio_config.rebalance_frequency != 1:
        raise ValueError("portfolio_config.rebalance_frequency must be 1")


def _snapshot_mark(snapshot, daily_closes: Mapping[date, Mapping[str, float]], max_positions: int) -> SnapshotMark:
    positions: dict[str, tuple[int, float]] = {}
    values: list[float] = []
    if len(snapshot.positions) > max_positions:
        raise ValueError(f"{snapshot.date}: positions exceed max_positions={max_positions}")
    for code, position in sorted(snapshot.positions.items()):
        if position.shares <= 0:
            continue
        close = daily_closes[snapshot.date].get(code)
        if close is None or not isfinite(float(close)) or float(close) <= 0:
            raise ValueError(f"{snapshot.date} {code}: missing or invalid same-day close")
        market_value = float(position.shares) * float(close)
        if not isclose(float(position.market_value or 0.0), market_value, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(f"{snapshot.date} {code}: snapshot market_value mismatch")
        positions[code] = (int(position.shares), market_value)
        values.append(market_value)
    market_value = sum(values)
    receivables = float(snapshot.receivables_value)
    available_cash = float(snapshot.available_cash)
    if available_cash < 0 or available_cash > float(snapshot.cash):
        raise ValueError(f"{snapshot.date}: available_cash must be between zero and cash")
    unlisted_value = 0.0
    for item in snapshot.unlisted_entitlements.values():
        close = daily_closes[snapshot.date].get(item.instrument_id)
        if close is None or not isfinite(float(close)) or float(close) <= 0:
            raise ValueError(f"{snapshot.date} {item.instrument_id}: missing close for unlisted entitlement")
        value = float(item.shares) * float(close)
        if not isclose(float(item.market_value), value, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(f"{snapshot.date} {item.instrument_id}: unlisted market_value mismatch")
        unlisted_value += value
    if not isclose(
        float(snapshot.nav), float(snapshot.cash) + receivables + unlisted_value + market_value,
        rel_tol=1e-9, abs_tol=1e-6
    ):
        raise ValueError(f"{snapshot.date}: cash + receivables + unlisted + market_value != NAV")
    return SnapshotMark(
        snapshot.date, float(snapshot.cash), available_cash, float(snapshot.cash) - available_cash,
        receivables, unlisted_value, market_value,
        float(snapshot.nav), positions,
    )


def audit_execution(result: EvaluationResult, plan: TerminalPlan, *,
                    daily_closes: Mapping[date, Mapping[str, float]], max_positions: int = 10) -> ExecutionAuditReport:
    """逐日严格核验当天报价、NAV 恒等式、持仓上限与成交时序；残仓如实报告。"""
    if isinstance(max_positions, bool) or not isinstance(max_positions, int) or not 1 <= max_positions <= 10:
        raise ValueError(f"max_positions must be in 1..10, got {max_positions!r}")
    snapshots = tuple(result.account_snapshots)
    dates = tuple(item.date for item in snapshots)
    if dates != plan.calendar or set(daily_closes) != set(plan.calendar):
        raise ValueError("snapshots and daily_closes must exactly cover terminal calendar in order")
    marks = tuple(_snapshot_mark(item, daily_closes, max_positions) for item in snapshots)
    for event in result.trades:
        if event.execution_time <= event.signal_time:
            raise ValueError(f"{event.instrument_id} {event.execution_time}: execution_time must follow signal_time")
        if event.side is Side.BUY and event.execution_time.date() > plan.exit_signal_date:
            raise ValueError(f"{event.instrument_id} {event.execution_time.date()}: BUY after exit-only boundary")
        if event.status is EventStatus.FORCED_EXIT:
            raise ValueError(f"{event.instrument_id}: forced liquidation is forbidden for mark audit")
    by_date = {item.date: item for item in marks}
    evaluation = by_date.get(plan.evaluation_date)
    final = by_date.get(plan.settlement_end)
    if evaluation is None or final is None:
        raise ValueError("evaluation_date and settlement_end snapshots are required")
    final_positions = dict(final.positions)
    final_snapshot = next(item for item in snapshots if item.date == plan.settlement_end)
    residual_entitlements = {
        key: float(value.shares) for key, value in final_snapshot.unlisted_entitlements.items()
    }
    filled = tuple(event for event in result.trades
                   if event.status in (EventStatus.FILLED, EventStatus.FORCED_EXIT))
    locked = tuple(event for event in result.trades if event.status is EventStatus.LOCKED)
    unresolved = tuple(order for order in result.order_results
                       if getattr(order.status, "value", order.status) in ("partial", "rejected"))
    return ExecutionAuditReport(
        evaluation_mtm=evaluation,
        post_buffer=final,
        filled_events=filled,
        locked_events=locked,
        unresolved_orders=unresolved,
        residual_positions=final_positions,
        residual_entitlements=residual_entitlements,
        residual_receivables=float(final_snapshot.receivables_value),
        cleared=not final_positions and not residual_entitlements and final_snapshot.receivables_value == 0,
    )
