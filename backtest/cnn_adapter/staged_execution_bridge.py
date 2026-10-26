"""冻结 backtest-core ExecutionUpdate 到分批 registry 的真实适配器。"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from types import MappingProxyType

from backtest_core.contracts import AccountState, ExecutionPhase, ExecutionUpdate, Side

from backtest.cnn_adapter.staged_allocation import (
    CASH_RECONCILIATION_ABS_TOLERANCE,
    AllocationError,
    AllocationRegistry,
    CoreAccountSnapshot,
    ExecutionFeedback,
)


def _integer_quantities(values: Mapping[str, float], label: str) -> dict[str, int]:
    """只把有限、非负且精确为整数的 core 数量转成 registry 整数股。"""
    converted: dict[str, int] = {}
    for code, value in values.items():
        if (not isinstance(code, str) or not code or isinstance(value, bool)
                or not isinstance(value, (int, float)) or not isfinite(value)
                or value < 0 or not float(value).is_integer()):
            raise AllocationError(f"core {label}[{code!r}] 不是非负整股数量")
        converted[code] = int(value)
    return converted


def cash_debit_from_transition(pre_cash: float, post_cash: float, side: Side | str) -> float:
    """按 core 前后现金差计算买入借记；卖出收入不会冲减 episode 承诺。"""
    for value in (pre_cash, post_cash):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise AllocationError("core cash 必须为有限非负数")
    normalized_side = Side(side)
    if normalized_side is Side.SELL:
        return 0.0
    debit = float(pre_cash) - float(post_cash)
    if debit < 0:
        raise AllocationError("买入后 core cash 不得增加")
    return debit


class StagedExecutionBridge:
    """ExecutionObserver：只消费冻结 core 契约，不推测 episode 或现金账。"""

    def __init__(self, registry: AllocationRegistry) -> None:
        self._registry = registry
        self._seen_events: dict[str, ExecutionUpdate] = {}

    @property
    def seen_events(self) -> Mapping[str, ExecutionUpdate]:
        return MappingProxyType(dict(self._seen_events))

    def on_update(self, update: ExecutionUpdate) -> None:
        """实现 core observer 回调；异常由 runner 传播并终止回测。"""
        self.consume(update)

    def consume(self, update: ExecutionUpdate) -> bool:
        """消费新事件；完全相同的 event_id 重放为 no-op，内容冲突立即失败。"""
        previous = self._seen_events.get(update.event_id)
        if previous is not None:
            if previous != update:
                raise AllocationError("event_id 重用且 ExecutionUpdate 内容不一致")
            return False
        snapshot = self._snapshot_from_update(update)
        if update.phase is ExecutionPhase.FILL:
            applied = self._apply_fill(update, snapshot)
        else:
            applied = self._registry.apply_core_snapshot(snapshot)
        self._seen_events[update.event_id] = update
        return applied

    @staticmethod
    def _snapshot_from_update(update: ExecutionUpdate) -> CoreAccountSnapshot:
        state: AccountState = update.post_state
        active_orders = update.active_orders
        return CoreAccountSnapshot(
            snapshot_id=update.event_id,
            sequence=update.sequence_no,
            available_cash=state.available_cash,
            positions=_integer_quantities(state.positions, "positions"),
            unlisted_entitlement_codes=frozenset(
                item.instrument_id for item in state.unlisted_entitlements.values()
            ),
            active_order_codes=frozenset(item.instrument_id for item in active_orders.values()),
            cash=state.cash,
            locked=_integer_quantities(state.locked, "locked"),
            cash_receivables=state.cash_receivables,
            unlisted_entitlements=state.unlisted_entitlements,
            pending_cash=state.pending_cash,
            active_orders=active_orders,
        )

    def _apply_fill(self, update: ExecutionUpdate, snapshot: CoreAccountSnapshot) -> bool:
        trade = update.trade
        if (trade is None or not update.episode_id or not update.order_id
                or not update.attempt_id or not update.fill_id):
            raise AllocationError("core fill 缺 episode/order/attempt/fill 身份，拒绝按代码猜测")
        if isinstance(trade.shares, bool) or not isinstance(trade.shares, int) or trade.shares <= 0:
            raise AllocationError("core fill shares 必须为正整数")
        expected_delta = update.post_state.cash - update.pre_state.cash
        if update.cash_delta != expected_delta:
            raise AllocationError("ExecutionUpdate cash_delta 与 AccountState 不一致")
        fees = trade.commission + trade.stamp_tax + trade.transfer_fee
        cash_debit = cash_debit_from_transition(update.pre_state.cash, update.post_state.cash, trade.side)
        if trade.side is Side.BUY and abs(cash_debit - (trade.amount + fees)) > CASH_RECONCILIATION_ABS_TOLERANCE:
            raise AllocationError("core pre/post cash 与成交额加三项现金费用不一致")
        feedback = ExecutionFeedback(
            episode_id=update.episode_id,
            order_id=update.order_id,
            fill_id=update.fill_id,
            event="fill",
            side=trade.side.value,
            amount=trade.amount,
            fees=fees,
            cash_debit=cash_debit,
            shares_delta=trade.shares,
            available_cash=snapshot.available_cash,
            core_snapshot_id=snapshot.snapshot_id,
            core_snapshot_sequence=snapshot.sequence,
            positions=snapshot.positions,
            unlisted_entitlement_codes=snapshot.unlisted_entitlement_codes,
            active_order_codes=snapshot.active_order_codes,
            cash=snapshot.cash,
            locked=snapshot.locked,
            core_snapshot=snapshot,
        )
        return self._registry.apply_feedback(feedback)
