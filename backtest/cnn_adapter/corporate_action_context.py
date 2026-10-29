"""组合 core 观察者与公司行动阶段钩子；只读真实账本，不复制账户。"""

from __future__ import annotations

from datetime import date
from fractions import Fraction
from typing import Any, Protocol

from backtest_core.contracts.account import AccountState
from backtest_core.contracts.account_actions import (
    CashPayment,
    CorporateActionOperation,
    CreateCashReceivable,
    CreateShareEntitlement,
    ListShareEntitlement,
    RecordPosition,
)
from backtest_core.contracts.execution_feedback import ExecutionUpdate

from .corporate_action_snapshot_loader import ActionDescriptor, CorporateActionSnapshot
from .corporate_actions import TaxPolicy


class UpdateDelegate(Protocol):
    def on_update(self, update: ExecutionUpdate) -> None: ...


class CorporateActionContext:
    """单窗空仓 reset；严格税务模式阻断实际暴露的未知税。"""

    def __init__(self, snapshot: CorporateActionSnapshot, *, period_id: str,
                 reset_anchor: date, empty_reset: bool,
                 strict_tax: bool = True, tax_policy: TaxPolicy = "pretax",
                 delegate: UpdateDelegate | None = None,
                 window_end: date | None = None, calendar_sha256: str | None = None) -> None:
        if not period_id.strip() or type(reset_anchor) is not date:
            raise ValueError("period_id 和纯日期 reset_anchor 必须明确")
        if tax_policy not in ("pretax", "cash_dividend_20pct_stress"):
            raise ValueError("税务策略无效")
        if window_end is not None and (type(window_end) is not date or window_end < reset_anchor):
            raise ValueError("window_end 必须是不早于 anchor 的纯日期")
        if calendar_sha256 is not None and (
                not isinstance(calendar_sha256, str) or len(calendar_sha256) != 64 or
                any(char not in "0123456789abcdef" for char in calendar_sha256)):
            raise ValueError("calendar_sha256 必须是调用者提供的 SHA256 小写十六进制")
        self.snapshot, self.period_id = snapshot, period_id
        self.reset_anchor, self.empty_reset = reset_anchor, empty_reset
        self.window_end, self.calendar_sha256 = window_end, calendar_sha256
        self.strict_tax, self.tax_policy, self.delegate = strict_tax, tax_policy, delegate
        self.post_state: AccountState | None = None
        self.last_update: ExecutionUpdate | None = None
        self._issues: dict[str, set[str]] = {}

    def _prefix(self, item: ActionDescriptor) -> str:
        return f"{self.period_id}:{item.event_id}"

    def _record_id(self, item: ActionDescriptor) -> str:
        return f"{self._prefix(item)}:record:{item.record_date}"

    def _issue(self, item: ActionDescriptor, reason: str, *, stop: bool = True) -> None:
        self._issues.setdefault(item.event_id, set()).add(reason)
        if stop:
            raise ValueError(f"{item.event_id}: {reason}; INCOMPLETE")

    def _quantity(self, item: ActionDescriptor) -> float | None:
        if self.post_state is None:
            return None
        return self.post_state.record_positions.get(self._record_id(item))

    def _validate_positive(self, item: ActionDescriptor, quantity: float) -> None:
        event = item.event
        if event is None:
            self._issue(item, "ex_date_missing")
            return
        if event.record_date == event.ex_date:
            self._issue(item, "same_day_record_ex_unsupported")
        if "total_ratio_missing" in item.unknown:
            self._issue(item, "total_ratio_missing")
        if event.gross_cash_per_share is None:
            self._issue(item, "cash_amount_unknown", stop=self.strict_tax)
        if event.gross_cash_per_share and event.pay_date is None:
            self._issue(item, "pay_date_missing")
        if event.share_ratio:
            if event.listing_date is None:
                self._issue(item, "listing_date_missing")
            # 十进制来源与 core 实际浮点乘积须同时精确为相同整数，不作 floor。
            total = item.raw_row.get("每股送转", event.share_ratio)
            exact = Fraction(str(quantity)) * Fraction(str(total))
            mechanical = quantity * event.share_ratio
            if exact.denominator != 1 or mechanical != exact.numerator:
                self._issue(item, "noninteger_or_unrepresentable_share_quantity")
        if event.gross_cash_per_share or event.share_ratio:
            self._issue(item, "tax_unknown", stop=self.strict_tax)

    def on_update(self, update: ExecutionUpdate) -> None:
        """先保存完整权威状态并透明转发，再暴露实际正登记的缺口。"""
        self.post_state, self.last_update = update.post_state, update
        if self.delegate is not None:
            try:
                self.delegate.on_update(update)
            except Exception as error:  # noqa: BLE001
                self._issues.setdefault("observer", set()).add(
                    f"delegate_failed:{type(error).__name__}:{update.event_id}")
                raise
        for item in self.snapshot.descriptors:
            quantity = self._quantity(item)
            if quantity is not None and quantity > 0:
                self._validate_positive(item, quantity)

    def account_actions_for_day(self, day: date) -> tuple[CorporateActionOperation, ...]:
        """core 开盘前请求操作，登记由 core 在开盘订单后执行。"""
        if type(day) is not date or day < self.reset_anchor:
            raise ValueError("操作日期必须为不早于 reset anchor 的纯日期")
        operations: list[CorporateActionOperation] = []
        for item in self.snapshot.descriptors:
            if item.source_table == "right_issue":
                continue
            event, record = item.event, item.record_date
            prefix = self._prefix(item)
            if record == day:
                operations.append(RecordPosition(self._record_id(item), item.event_id,
                                                 item.instrument_id, day))
            if record is not None and day <= record:
                continue
            stages = () if event is None else (event.ex_date, event.pay_date, event.listing_date)
            if day not in stages and not (event is None and record is not None and day > record):
                continue
            quantity = self._quantity(item)
            if quantity is None:
                if record is not None and record < self.reset_anchor and self.empty_reset:
                    continue
                # 没有登记日期时，无法证明无权益；只在该代码持仓时暴露缺口。
                if record is None and (self.post_state is None or
                                       not self.post_state.positions.get(item.instrument_id, 0)):
                    continue
                self._issue(item, "missing_record")
            if quantity is None or quantity == 0:
                continue
            self._validate_positive(item, quantity)
            assert event is not None
            if event.ex_date == day:
                if event.share_ratio and self.post_state is not None:
                    if self.post_state.positions.get(item.instrument_id, 0) != quantity:
                        self._issue(item, "core_share_holdings_changed_unsupported")
                operations.extend(self._ex_actions(item, day))
            if event.pay_date == day and event.gross_cash_per_share:
                if event.ex_date != day and self.post_state is not None and not any(
                        entry.event_id == item.event_id
                        for entry in self.post_state.cash_receivables.values()):
                    paid_id = f"{prefix}:cash-pay:{day}:{self.tax_policy}"
                    if paid_id not in self.post_state.processed_action_operations:
                        self._issue(item, "missing_cash_ex")
                operations.append(CashPayment(f"{prefix}:cash-pay:{day}:{self.tax_policy}",
                                               item.event_id, day))
            if event.listing_date == day and event.share_ratio:
                if event.ex_date != day and self.post_state is not None and not any(
                        entry.event_id == item.event_id
                        for entry in self.post_state.unlisted_entitlements.values()):
                    if f"{prefix}:share-list:{day}" not in self.post_state.processed_action_operations:
                        self._issue(item, "missing_share_ex")
                operations.append(ListShareEntitlement(f"{prefix}:share-list:{day}", item.event_id, day))
        return tuple(operations)

    def _ex_actions(self, item: ActionDescriptor, day: date) -> list[CorporateActionOperation]:
        event = item.event
        assert event is not None
        prefix = self._prefix(item)
        actions: list[CorporateActionOperation] = []
        if event.gross_cash_per_share:
            assert event.pay_date is not None
            withheld = event.gross_cash_per_share * 0.2 if (
                self.tax_policy == "cash_dividend_20pct_stress") else 0.0
            actions.append(CreateCashReceivable(
                f"{prefix}:cash-ex:{day}:{self.tax_policy}", item.event_id, item.instrument_id,
                self._record_id(item), event.gross_cash_per_share, day, event.pay_date,
                withheld_cash_per_share=withheld))
        if event.share_ratio:
            assert event.listing_date is not None
            actions.append(CreateShareEntitlement(
                f"{prefix}:share-ex:{day}", item.event_id, item.instrument_id,
                self._record_id(item), event.share_ratio, day, event.listing_date))
        return actions

    def evidence(self) -> dict[str, Any]:
        """机械账通过不能解释为实际税后目标；未知来源与实际阻断分别可追溯。"""
        return {**self.snapshot.evidence(), "scope": "single-window-reset",
                "period_id": self.period_id, "anchor": self.reset_anchor.isoformat(),
                "window_end": None if self.window_end is None else self.window_end.isoformat(),
                "calendar_sha256": self.calendar_sha256,
                "window_identity_validation": "pending_runner_validation",
                "reset_anchor": self.reset_anchor.isoformat(), "empty_reset": self.empty_reset,
                "status": "INCOMPLETE" if self._issues else "MECHANICAL_ONLY",
                "unknown": {key: sorted(value) for key, value in self._issues.items()},
                "incomplete": bool(self._issues), "actual_after_tax_target_eligible": False,
                "tax_policy": self.tax_policy, "cash_tax_is_actual": False,
                "strict_tax": self.strict_tax,
                "exact_integer_path_is_official_rounding_certificate": False,
                "last_core_update": None if self.last_update is None else self.last_update.event_id}
