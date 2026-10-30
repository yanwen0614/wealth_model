"""仅供 W1 300502.SZ 单事件 floor/ceil 条件账户的隔离适配器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from backtest_core.contracts.execution_feedback import ExecutionUpdate

from .corporate_action_context import CorporateActionContext
from .corporate_action_snapshot_loader import ActionDescriptor, CorporateActionSnapshot
from .fractional_prefix_gate import validate_prefix_proof

Scenario = Literal["floor", "ceil"]
EVENT_ID = "dividend:27726:5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462"
ROW_SHA256 = "5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462"
SOURCE_ROWS_SHA256 = "5ad5bfe8259b1a0075ebef0c731019c678a589a8f9d6b013bd46684edbe3168b"
OFFICIAL_PDF_SHA256 = "c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd"
ORIGINAL_RATIO = Decimal("0.4002532")
RECORD_DATE = date(2021, 6, 7)
EX_DATE = date(2021, 6, 8)
LISTING_DATE = date(2021, 6, 8)


@dataclass(frozen=True)
class EntitlementResolution:
    scenario: Scenario
    record_shares: int
    original_ratio: Decimal
    exact_entitlement: Decimal
    integer_shares: int
    remainder: Decimal
    effective_ratio: Decimal

    @property
    def basis_assumption(self) -> str:
        return "core 按 effective_ratio 将登记日成本basis同比例分配至条件整数股"

    @property
    def production_acceptance(self) -> str:
        return "BLOCKED"

    @property
    def actual_after_tax_target_eligible(self) -> bool:
        return False

    @property
    def tax_unknown(self) -> bool:
        return True


class W1FractionalScenarioContext(CorporateActionContext):
    """限定来源的单事件情景上下文；生产默认上下文完全不变。"""

    def __init__(self, snapshot: CorporateActionSnapshot, *, period_id: str,
                 reset_anchor: date, scenario: Scenario,
                 official_pdf_path: str | Path, source_rows_sha256: str,
                 delegate=None, window_end: date | None = None,
                 calendar_sha256: str | None = None,
                  prefix_proof_path: str | Path | None = None,
                  expected_prefix_proof_sha256: str | None = None,
                  prefix_only: bool = False, conditional_only: bool = False,
                  announcement_horizon: date | None = None) -> None:
        if scenario not in ("floor", "ceil"):
            raise ValueError("scenario must be floor or ceil")
        if not period_id.startswith("W1") or period_id.startswith("W2"):
            raise ValueError("fractional scenario is restricted to W1")
        if period_id != "W1":
            raise ValueError("mini context is only constructed inside the bounded mini runner")
        if prefix_only:
            if (window_end != date(2021, 6, 7) or prefix_proof_path is not None
                    or expected_prefix_proof_sha256 is not None):
                raise ValueError("prefix-only context must stop at the fixed cutoff")
        elif conditional_only:
            if (period_id != "W1" or reset_anchor != date(2020, 12, 31)
                    or window_end is None or window_end < LISTING_DATE
                    or announcement_horizon != date(2021, 6, 30)
                    or prefix_proof_path is not None
                    or expected_prefix_proof_sha256 is not None):
                raise ValueError("conditional mode requires frozen full W1 window and no proof")
            snapshot = replace(snapshot, descriptors=tuple(
                item for item in snapshot.descriptors if item.event is not None
                and item.event.announced_date is not None
                and item.event.announced_date <= announcement_horizon))
        else:
            validate_prefix_proof(Path(prefix_proof_path) if prefix_proof_path else None,
                                  expected_prefix_proof_sha256)
        matches = [item for item in snapshot.descriptors if item.event_id == EVENT_ID]
        if len(matches) != 1:
            raise ValueError("W1白名单事件必须恰好出现一次")
        pdf_path = Path(official_pdf_path)
        official_pdf_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        self.validate_descriptor(matches[0], official_pdf_sha256, source_rows_sha256)
        self.scenario: Scenario = cast(Scenario, scenario)
        self.official_pdf_sha256 = official_pdf_sha256
        self.source_rows_sha256 = source_rows_sha256
        self._resolution: EntitlementResolution | None = None
        super().__init__(snapshot, period_id=period_id, reset_anchor=reset_anchor,
                          empty_reset=True, strict_tax=False,
                          tax_policy="cash_dividend_20pct_stress", delegate=delegate,
                          window_end=window_end, calendar_sha256=calendar_sha256,
                          asof_announcement_dates=conditional_only)

    @staticmethod
    def validate_identity(*, event_id: str, source_file_sha256: str,
                           official_pdf_sha256: str, instrument_id: str,
                           record_date: date, ex_date: date, listing_date: date,
                           share_ratio: Decimal, row_sha256: str) -> None:
        """仅允许已固定的 W1 公司行动证据身份。"""
        expected = (EVENT_ID, SOURCE_ROWS_SHA256, OFFICIAL_PDF_SHA256,
                    "300502.SZ", RECORD_DATE, EX_DATE, LISTING_DATE,
                    ORIGINAL_RATIO, ROW_SHA256)
        actual = (event_id, source_file_sha256, official_pdf_sha256,
                  instrument_id, record_date, ex_date, listing_date,
                  share_ratio, row_sha256)
        if actual != expected:
            raise ValueError("W1 fraction scenario source identity mismatch")

    @classmethod
    def validate_descriptor(cls, item: ActionDescriptor, pdf_sha: str,
                            source_sha: str) -> None:
        event = item.event
        if event is None:
            raise ValueError("白名单事件缺少规范公司行动")
        if item.record_date != RECORD_DATE or event.ex_date != EX_DATE or event.listing_date != LISTING_DATE:
            raise ValueError("白名单公司行动日期不匹配")
        ratio = Decimal(str(item.raw_row.get("每股送转")))
        cls.validate_identity(
            event_id=item.event_id, source_file_sha256=item.file_sha256,
            official_pdf_sha256=pdf_sha, instrument_id=item.instrument_id,
            record_date=RECORD_DATE, ex_date=EX_DATE,
            listing_date=LISTING_DATE, share_ratio=ratio,
            row_sha256=str(item.raw_row.get("_row_hash")),
        )
        if source_sha != SOURCE_ROWS_SHA256 or event.source_snapshot_hash != source_sha:
            raise ValueError("原始公司行动快照 SHA256 不匹配")

    @staticmethod
    def resolve(record_shares: int, scenario: Scenario) -> EntitlementResolution:
        """以 Decimal 精确计算 q*r，再按明确分支取整。"""
        if type(record_shares) is not int or record_shares <= 0:
            raise ValueError("登记持仓必须是正整数股")
        if scenario not in ("floor", "ceil"):
            raise ValueError("scenario must be floor or ceil")
        exact = Decimal(record_shares) * ORIGINAL_RATIO
        rounding = ROUND_FLOOR if scenario == "floor" else ROUND_CEILING
        shares = int(exact.to_integral_value(rounding=rounding))
        effective = Decimal(shares) / Decimal(record_shares)
        core_ratio = float(effective)
        if record_shares * core_ratio != float(shares):
            raise ValueError("core float entitlement cannot represent scenario integer exactly")
        return EntitlementResolution(scenario, record_shares, ORIGINAL_RATIO,
                                     exact, shares, Decimal(shares) - exact, effective)

    def _target(self, item: ActionDescriptor) -> bool:
        return item.event_id == EVENT_ID

    def _validate_positive(self, item: ActionDescriptor, quantity: float) -> None:
        if not self._target(item):
            strict_tax = self.strict_tax
            self.strict_tax = True
            try:
                super()._validate_positive(item, quantity)
            finally:
                self.strict_tax = strict_tax
            return
        if not float(quantity).is_integer() or quantity <= 0:
            self._issue(item, "scenario_record_shares_must_be_positive_integer")
        self.validate_descriptor(item, self.official_pdf_sha256, self.source_rows_sha256)
        resolution = self.resolve(int(quantity), self.scenario)
        self._resolution = resolution
        assert item.event is not None
        event = replace(item.event, share_ratio=float(resolution.effective_ratio))
        raw = dict(item.raw_row)
        # 保留权威整数对；有限精度 Decimal 字符串会在 observer 的 Fraction
        # 校验中留下极小残差，而 core 机械执行仍使用上方已验证的 float 比例。
        raw["每股送转"] = (
            f"{resolution.integer_shares}/{resolution.record_shares}"
        )
        adjusted = replace(item, event=event, raw_row=MappingProxyType(raw))
        super()._validate_positive(adjusted, quantity)

    def _ex_actions(self, item: ActionDescriptor, day: date):
        if not self._target(item):
            return super()._ex_actions(item, day)
        resolution = self._resolution
        if resolution is None or item.event is None:
            self._issue(item, "scenario_resolution_missing")
            raise AssertionError("scenario resolution missing")
        adjusted = replace(item, event=replace(
            item.event, share_ratio=float(resolution.effective_ratio)))
        return super()._ex_actions(adjusted, day)

    def account_actions_for_day(self, day: date):
        if self.period_id.endswith("-mini") and self.window_end is not None and day > self.window_end:
            raise ValueError("fractional mini cannot run beyond its fixed window")
        if day == EX_DATE:
            target = next(item for item in self.snapshot.descriptors
                          if item.event_id == EVENT_ID)
            quantity = self._quantity(target)
            if quantity is None or quantity <= 0:
                self._issue(target, "scenario_requires_positive_record_position")
                raise AssertionError("positive record position required")
            self._validate_positive(target, quantity)
        return super().account_actions_for_day(day)

    def on_update(self, update: ExecutionUpdate) -> None:
        if (self.period_id.endswith("-mini") and self.window_end is not None
                and update.trading_date > self.window_end):
            raise ValueError("fractional mini cannot observe updates beyond its fixed window")
        super().on_update(update)

    def evidence(self):
        base = super().evidence()
        resolution = self._resolution
        base.update({
            "scenario_only": True,
            "conditional_only": self.asof_announcement_dates,
            "certification": ("NOT_CERTIFIED_CONDITIONAL" if self.asof_announcement_dates
                              else "NOT_CERTIFIED"),
            "pit": "UNKNOWN",
            "actual_allocation": "UNKNOWN",
            "tax": "UNKNOWN",
            "actual_unknown": True,
            "production_acceptance": "BLOCKED",
            "actual_after_tax_target_eligible": False,
            "tax_status": "unknown; cash_dividend_20pct_stress is only a stress assumption",
            "official_fractional_rule_exhaustiveness_proven": False,
            "fractional_scenario": None if resolution is None else {
                "event_id": EVENT_ID, "scenario": resolution.scenario,
                "source_rows_sha256": self.source_rows_sha256,
                "source_row_sha256": ROW_SHA256,
                "official_pdf_sha256": self.official_pdf_sha256,
                "record_shares": resolution.record_shares,
                "original_ratio": str(resolution.original_ratio),
                "exact_entitlement": str(resolution.exact_entitlement),
                "integer_shares": resolution.integer_shares,
                "scenario_minus_exact": str(resolution.remainder),
                "effective_ratio": str(resolution.effective_ratio),
                "basis_assumption": resolution.basis_assumption,
            },
        })
        return base
