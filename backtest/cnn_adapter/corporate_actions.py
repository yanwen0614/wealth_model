"""公司行动事件与权益投影；不持有可用现金或可交易账户股数。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from types import MappingProxyType
from typing import Literal
from zoneinfo import ZoneInfo

from backtest_core.contracts.account_actions import (
    CashPayment,
    CreateCashReceivable,
    CreateShareEntitlement,
    ListShareEntitlement,
    RecordPosition,
)

ActionKind = Literal["cash_dividend", "bonus", "capitalization", "rights_issue"]
TaxPolicy = Literal["pretax", "cash_dividend_20pct_stress"]


@dataclass(frozen=True)
class CorporateActionEvent:
    """保留来源身份与未知字段的规范化事件。"""

    event_id: str
    instrument_id: str
    kind: ActionKind
    source_table: str
    source_row_id: str
    source_snapshot_hash: str
    source_version: str
    record_date: date | None = None
    ex_date: date | None = None
    pay_date: date | None = None
    listing_date: date | None = None
    gross_cash_per_share: float | None = None
    share_ratio: float | None = None
    reference_price: float | None = None
    reference_source: str | None = None
    reference_version: str | None = None
    ratio_denominator: int | None = None
    rounding_rule: str | None = None
    fractional_cash_rule: str | None = None
    bonus_tax_rule: str | None = None
    announced_date: date | None = None
    known_at: date | datetime | None = None
    known_at_quality: Literal["verified_timestamp", "date_only", "unknown"] = "unknown"

    def __post_init__(self) -> None:
        for name in ("event_id", "instrument_id", "source_table", "source_row_id",
                     "source_snapshot_hash", "source_version"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if self.kind not in ("cash_dividend", "bonus", "capitalization", "rights_issue"):
            raise ValueError(f"unsupported corporate action kind: {self.kind!r}")
        for name in ("record_date", "ex_date", "pay_date", "listing_date", "announced_date"):
            value = getattr(self, name)
            if value is not None and (type(value) is not date or isinstance(value, datetime)):
                raise ValueError(f"{name} must be a pure date or None")
        if self.known_at_quality == "verified_timestamp":
            if (not isinstance(self.known_at, datetime) or self.known_at.tzinfo is None
                    or self.known_at.utcoffset() is None):
                raise ValueError("verified_timestamp requires timezone-aware known_at")
        elif self.known_at_quality == "date_only":
            if type(self.known_at) is not date:
                raise ValueError("date_only requires a pure date known_at")
        elif self.known_at_quality == "unknown" and self.known_at is not None:
            raise ValueError("unknown known_at_quality must not carry known_at")
        if self.ex_date is None:
            raise ValueError("ex_date is required")
        if self.record_date is not None and self.record_date > self.ex_date:
            raise ValueError("record_date must not follow ex_date")
        if self.pay_date is not None and self.pay_date < self.ex_date:
            raise ValueError("pay_date must not precede ex_date")
        for name in ("gross_cash_per_share", "share_ratio", "reference_price"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative")
        if self.reference_price is not None and not (self.reference_source and self.reference_version):
            raise ValueError("reference price requires source and version")
        if self.listing_date is not None and self.listing_date < self.ex_date:
            raise ValueError("listing_date must not precede ex_date")


@dataclass(frozen=True)
class CorporateActionProjection:
    """可重放日快照；现金转账消费者必须按事件ID幂等入账。"""

    date: date
    record_shares: Mapping[str, float]
    receivables_at_open: Mapping[str, float]
    receivables_at_close: Mapping[str, float]
    available_cash_transfers: Mapping[str, float]
    cash_tax_stress: Mapping[str, float]
    cash_available_at_open: Mapping[str, bool]
    listed_entitlements: Mapping[str, float]
    unlisted_shares: Mapping[str, float]
    share_rules_unknown: tuple[str, ...]
    bonus_tax_unknown: tuple[str, ...]
    entitlement_value: float
    rights_value_unknown: tuple[str, ...]
    order_rejections: Mapping[str, str]
    equity_value: float


class CorporateActionProvider:
    """由已完成血缘审计的规范事件提供按代码/除权日查询的不可变快照。"""

    def __init__(self, events: Sequence[CorporateActionEvent]) -> None:
        by_id: dict[str, CorporateActionEvent] = {}
        for event in events:
            if not isinstance(event, CorporateActionEvent):
                raise TypeError(f"events must contain CorporateActionEvent, got {event!r}")
            if event.event_id in by_id:
                raise ValueError(f"duplicate corporate action event_id: {event.event_id}")
            by_id[event.event_id] = event
        self._events = tuple(sorted(by_id.values(), key=lambda item: (item.ex_date, item.instrument_id, item.event_id)))

    @property
    def events(self) -> tuple[CorporateActionEvent, ...]:
        return self._events

    def events_for(self, instrument_id: str, effective_date: date) -> tuple[CorporateActionEvent, ...]:
        """返回该代码在指定除权日生效的事件，不进行未来字段推导。"""
        return tuple(event for event in self._events
                     if event.instrument_id == instrument_id and event.ex_date == effective_date)

    def events_known_as_of(self, signal_time: datetime) -> tuple[CorporateActionEvent, ...]:
        """只返能证明在收盘信号时已公开的事件；日期级公告当日不视为盘前可知。"""
        if (not isinstance(signal_time, datetime) or signal_time.tzinfo is None
                or signal_time.utcoffset() is None):
            raise ValueError("signal_time must be timezone-aware")
        market_date = signal_time.astimezone(ZoneInfo("Asia/Shanghai")).date()
        known: list[CorporateActionEvent] = []
        for event in self._events:
            if (event.known_at_quality == "verified_timestamp" and event.known_at is not None
                    and event.known_at <= signal_time):
                known.append(event)
            elif (event.known_at_quality == "date_only" and event.known_at is not None
                  and event.known_at < market_date):
                known.append(event)
        return tuple(known)

    def account_operations_for_day(self, day: date, *, period_id: str):
        """转换可严格表达的事件阶段；未知送转结算规则显式 fail closed。"""
        if type(day) is not date or not period_id.strip():
            raise ValueError("day must be a pure date and period_id must be non-empty")
        operations = []
        for event in self._events:
            prefix = f"{period_id}:{event.event_id}"
            actionable = event.kind != "rights_issue" and bool(event.gross_cash_per_share or event.share_ratio)
            if event.record_date == day and actionable:
                operations.append(RecordPosition(
                    f"{prefix}:record:{day.isoformat()}", event.event_id, event.instrument_id, day,
                ))
            if event.ex_date == day:
                if event.record_date is None and (event.gross_cash_per_share or event.share_ratio):
                    raise ValueError(f"{event.event_id}: record_date is required to book an entitlement")
                record_date = event.record_date
                if event.gross_cash_per_share or event.share_ratio:
                    if record_date is None:
                        raise ValueError(f"{event.event_id}: record_date is required to book an entitlement")
                    if event.gross_cash_per_share and event.pay_date is None:
                        raise ValueError(f"{event.event_id}: pay_date is required to book a cash receivable")
                    if event.gross_cash_per_share and event.pay_date is not None:
                        operations.append(CreateCashReceivable(
                            f"{prefix}:cash-ex:{day.isoformat()}", event.event_id, event.instrument_id,
                            f"{prefix}:record:{record_date.isoformat()}", event.gross_cash_per_share,
                            day, event.pay_date,
                        ))
                    if event.share_ratio:
                        if event.listing_date is None or event.ratio_denominator is None or event.rounding_rule is None:
                            raise ValueError(
                                f"{event.event_id}: share ratio denominator, rounding, and listing must be verified"
                            )
                        operations.append(CreateShareEntitlement(
                            f"{prefix}:share-ex:{day.isoformat()}", event.event_id, event.instrument_id,
                            f"{prefix}:record:{record_date.isoformat()}", event.share_ratio,
                            day, event.listing_date,
                        ))
            if event.pay_date == day and event.gross_cash_per_share:
                operations.append(CashPayment(f"{prefix}:cash-pay:{day.isoformat()}", event.event_id, day))
            if event.listing_date == day and event.share_ratio:
                operations.append(ListShareEntitlement(f"{prefix}:share-list:{day.isoformat()}", event.event_id, day))
        return tuple(operations)


class CorporateActionLedger:
    """只投影权益分项；现金实际入账和股份可卖性仍由core账户负责。"""

    def __init__(self, provider: CorporateActionProvider) -> None:
        if not isinstance(provider, CorporateActionProvider):
            raise TypeError("provider must be CorporateActionProvider")
        self.provider = provider
        self._record_shares: dict[str, float] = {}
        self._observed_pay_dates: set[str] = set()

    def project(self, day: date, *, positions: Mapping[str, int], raw_closes: Mapping[str, float],
                tax_policy: TaxPolicy = "pretax") -> CorporateActionProjection:
        """positions是core已登记股数；上市权益应先转入core，再用于下一交易日估值。"""
        if type(day) is not date or isinstance(day, datetime):
            raise ValueError("day must be a pure date")
        if tax_policy not in ("pretax", "cash_dividend_20pct_stress"):
            raise ValueError(f"unsupported tax_policy: {tax_policy!r}")
        for code, shares in positions.items():
            if isinstance(shares, bool) or not isinstance(shares, int) or shares < 0:
                raise ValueError(f"positions[{code!r}] must be a non-negative integer")
        for code, close in raw_closes.items():
            if not isfinite(float(close)) or float(close) <= 0:
                raise ValueError(f"raw_closes[{code!r}] must be positive and finite")
        record_shares: dict[str, float] = {}
        receivables_open: dict[str, float] = {}
        receivables_close: dict[str, float] = {}
        cash_transfers: dict[str, float] = {}
        cash_tax: dict[str, float] = {}
        cash_at_open: dict[str, bool] = {}
        listed: dict[str, float] = {}
        unlisted: dict[str, float] = {}
        share_rules_unknown: list[str] = []
        bonus_tax_unknown: list[str] = []
        unknown_rights: list[str] = []
        rejections: dict[str, str] = {}
        entitlement_value = 0.0
        receivable_value = 0.0
        for event in self.provider.events:
            if (event.pay_date is not None and event.pay_date < day
                    and event.gross_cash_per_share and event.event_id not in self._observed_pay_dates):
                raise ValueError(f"missed pay-date projection for {event.event_id}: {event.pay_date}")
            if event.pay_date == day and event.gross_cash_per_share:
                self._observed_pay_dates.add(event.event_id)
            if event.record_date == day:
                quantity = float(positions.get(event.instrument_id, 0))
                previous = self._record_shares.setdefault(event.event_id, quantity)
                if previous != quantity:
                    raise ValueError(f"record position changed on replay for {event.event_id}")
            quantity = self._record_shares.get(event.event_id)
            if quantity is not None:
                record_shares[event.event_id] = quantity
            if event.ex_date is None or day < event.ex_date:
                continue
            if event.reference_price is None and day == event.ex_date:
                rejections[event.instrument_id] = "corporate_action_unknown"
            if event.kind == "rights_issue":
                unknown_rights.append(event.event_id)
                continue
            if quantity is None:
                rejections.setdefault(event.instrument_id, "corporate_action_record_position_unknown")
                continue
            gross = quantity * float(event.gross_cash_per_share or 0.0)
            if gross > 0 and (event.pay_date is None or day <= event.pay_date):
                receivables_open[event.event_id] = gross
                cash_at_open[event.event_id] = False
                stress_tax = gross * 0.2 if tax_policy == "cash_dividend_20pct_stress" else 0.0
                cash_tax[event.event_id] = stress_tax
                if event.pay_date == day:
                    cash_transfers[event.event_id] = gross - stress_tax
                else:
                    receivables_close[event.event_id] = gross - stress_tax
                    receivable_value += gross - stress_tax
            if event.share_ratio is None or event.share_ratio == 0:
                if event.kind in ("bonus", "capitalization"):
                    share_rules_unknown.append(event.event_id)
                    bonus_tax_unknown.append(event.event_id)
                continue
            entitlement = quantity * event.share_ratio
            if entitlement == 0:
                continue
            if event.ratio_denominator is None or event.rounding_rule is None:
                share_rules_unknown.append(event.event_id)
            if event.bonus_tax_rule is None:
                bonus_tax_unknown.append(event.event_id)
            if event.listing_date is None or day <= event.listing_date:
                unlisted[event.event_id] = entitlement
                if event.listing_date is None:
                    share_rules_unknown.append(event.event_id)
            else:
                listed[event.event_id] = entitlement
            close = raw_closes.get(event.instrument_id)
            if close is None:
                raise ValueError(f"{day} {event.instrument_id}: raw close required to value share entitlement")
            if event.listing_date is None or day <= event.listing_date:
                entitlement_value += entitlement * float(close)
        raw_value = 0.0
        for code, shares in positions.items():
            if shares <= 0:
                continue
            close = raw_closes.get(code)
            if close is None:
                raise ValueError(f"{day} {code}: raw close required for held shares")
            raw_value += shares * float(close)
        total_entitlement = entitlement_value + receivable_value
        return CorporateActionProjection(
            date=day,
            record_shares=MappingProxyType(record_shares),
            receivables_at_open=MappingProxyType(receivables_open),
            receivables_at_close=MappingProxyType(receivables_close),
            available_cash_transfers=MappingProxyType(cash_transfers),
            cash_tax_stress=MappingProxyType(cash_tax),
            cash_available_at_open=MappingProxyType(cash_at_open),
            listed_entitlements=MappingProxyType(listed),
            unlisted_shares=MappingProxyType(unlisted),
            share_rules_unknown=tuple(sorted(set(share_rules_unknown))),
            bonus_tax_unknown=tuple(sorted(set(bonus_tax_unknown))),
            entitlement_value=entitlement_value,
            rights_value_unknown=tuple(sorted(set(unknown_rights))),
            order_rejections=MappingProxyType(rejections),
            equity_value=raw_value + total_entitlement,
        )
