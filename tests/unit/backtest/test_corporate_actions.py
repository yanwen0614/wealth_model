"""公司行动记账投影合成测试；不执行撮合或改写现金余额。"""

import unittest
from datetime import UTC, date, datetime

from backtest.cnn_adapter.corporate_actions import (
    CorporateActionEvent,
    CorporateActionLedger,
    CorporateActionProvider,
)


class CorporateActionsTest(unittest.TestCase):
    def test_same_event_adapts_independent_period_scoped_phases(self):
        event = CorporateActionEvent(
            event_id="cash-bonus", instrument_id="A.SZ", kind="capitalization",
            source_table="dividend", source_row_id="row-1", source_snapshot_hash="hash-1",
            source_version="fixture-v1", record_date=date(2021, 3, 15), ex_date=date(2021, 3, 16),
            pay_date=date(2021, 3, 18), listing_date=date(2021, 3, 19),
            gross_cash_per_share=0.18, share_ratio=0.8, ratio_denominator=10,
            rounding_rule="exact", reference_price=9.82, reference_source="fixture", reference_version="v1",
        )
        provider = CorporateActionProvider((event,))
        record = provider.account_operations_for_day(date(2021, 3, 15), period_id="W1")
        ex_date = provider.account_operations_for_day(date(2021, 3, 16), period_id="W1")
        pay_date = provider.account_operations_for_day(date(2021, 3, 18), period_id="W1")
        listing = provider.account_operations_for_day(date(2021, 3, 19), period_id="W1")
        self.assertEqual(len(record), 1)
        self.assertEqual(len(ex_date), 2)
        self.assertEqual(len(pay_date), 1)
        self.assertEqual(len(listing), 1)
        self.assertTrue(all("W1:" in item.operation_id for item in (*record, *ex_date, *pay_date, *listing)))

    def test_cash_dividend_record_ex_pay_projection_is_idempotent(self):
        event = CorporateActionEvent(
            event_id="cash-000001-20210514", instrument_id="000001.SZ", kind="cash_dividend",
            source_table="dividend", source_row_id="sample-1", source_snapshot_hash="abc",
            source_version="fixture-v1", record_date=date(2021, 5, 13), ex_date=date(2021, 5, 14),
            pay_date=date(2021, 5, 14), gross_cash_per_share=0.18,
            announced_date=date(2021, 5, 7), known_at=date(2021, 5, 7), known_at_quality="date_only",
        )
        ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        before = ledger.project(date(2021, 5, 13), positions={"000001.SZ": 100},
                                raw_closes={"000001.SZ": 23.07})
        projection = ledger.project(date(2021, 5, 14), positions={"000001.SZ": 100},
                                    raw_closes={"000001.SZ": 23.32})
        replay = ledger.project(date(2021, 5, 14), positions={"000001.SZ": 100},
                                raw_closes={"000001.SZ": 23.32})
        self.assertEqual(before.receivables_at_open, {})
        self.assertEqual(projection.receivables_at_open["cash-000001-20210514"], 18.0)
        self.assertEqual(projection.available_cash_transfers, {"cash-000001-20210514": 18.0})
        self.assertFalse(projection.cash_available_at_open["cash-000001-20210514"])
        self.assertEqual(projection.receivables_at_close, {})
        self.assertEqual(projection.receivables_at_open, replay.receivables_at_open)
        self.assertEqual(projection.available_cash_transfers, replay.available_cash_transfers)
        self.assertEqual(projection.equity_value, 2332.0)
        self.assertEqual(projection.equity_value + sum(projection.available_cash_transfers.values()), 2350.0)
        large_ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        large_ledger.project(date(2021, 5, 13), positions={"000001.SZ": 1000},
                             raw_closes={"000001.SZ": 23.07})
        large = large_ledger.project(date(2021, 5, 14), positions={"000001.SZ": 1000},
                                     raw_closes={"000001.SZ": 23.32})
        self.assertEqual(large.available_cash_transfers[event.event_id], 180.0)
        self.assertEqual(large.equity_value + sum(large.available_cash_transfers.values()), 23500.0)
        stress_ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        stress_ledger.project(date(2021, 5, 13), positions={"000001.SZ": 100},
                              raw_closes={"000001.SZ": 23.07})
        stress = stress_ledger.project(date(2021, 5, 14), positions={"000001.SZ": 100},
                                       raw_closes={"000001.SZ": 23.32},
                                       tax_policy="cash_dividend_20pct_stress")
        self.assertEqual(stress.cash_tax_stress[event.event_id], 3.6)
        self.assertEqual(stress.available_cash_transfers[event.event_id], 14.4)

    def test_bonus_entitlement_uses_record_shares_and_delays_listing(self):
        event = CorporateActionEvent(
            event_id="bonus-300896-20210316", instrument_id="300896.SZ", kind="capitalization",
            source_table="dividend", source_row_id="sample-2", source_snapshot_hash="def",
            source_version="fixture-v1", record_date=date(2021, 3, 15), ex_date=date(2021, 3, 16),
            pay_date=date(2021, 3, 16), listing_date=date(2021, 3, 16),
            gross_cash_per_share=3.5, share_ratio=0.8, announced_date=date(2021, 3, 9),
            known_at=date(2021, 3, 9),
            known_at_quality="date_only",
        )
        ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        record = ledger.project(date(2021, 3, 15), positions={"300896.SZ": 100},
                                raw_closes={"300896.SZ": 750.88})
        ex = ledger.project(date(2021, 3, 16), positions={"300896.SZ": 100},
                            raw_closes={"300896.SZ": 439.60})
        next_day = ledger.project(date(2021, 3, 17), positions={"300896.SZ": 180},
                                  raw_closes={"300896.SZ": 440.0})
        self.assertEqual(record.unlisted_shares, {})
        self.assertEqual(ex.unlisted_shares["bonus-300896-20210316"], 80.0)
        self.assertEqual(ex.share_rules_unknown, ("bonus-300896-20210316",))
        self.assertEqual(ex.bonus_tax_unknown, ("bonus-300896-20210316",))
        self.assertEqual(ex.listed_entitlements, {})
        self.assertEqual(ex.available_cash_transfers["bonus-300896-20210316"], 350.0)
        self.assertEqual(ex.equity_value + sum(ex.available_cash_transfers.values()),
                         100 * 439.60 + 80 * 439.60 + 350.0)
        self.assertEqual(next_day.listed_entitlements["bonus-300896-20210316"], 80.0)
        self.assertEqual(next_day.unlisted_shares, {})
        self.assertEqual(next_day.equity_value, 180 * 440.0)
        large_ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        large_ledger.project(date(2021, 3, 15), positions={"300896.SZ": 1000},
                             raw_closes={"300896.SZ": 750.88})
        large = large_ledger.project(date(2021, 3, 16), positions={"300896.SZ": 1000},
                                     raw_closes={"300896.SZ": 439.60})
        self.assertEqual(large.unlisted_shares[event.event_id], 800.0)
        self.assertEqual(large.equity_value + sum(large.available_cash_transfers.values()), 794780.0)

    def test_unknown_reference_blocks_orders_and_keeps_raw_holding(self):
        event = CorporateActionEvent(
            event_id="rights-unknown", instrument_id="A.SZ", kind="rights_issue",
            source_table="right_issue", source_row_id="sample-3", source_snapshot_hash="ghi",
            source_version="fixture-v1", record_date=date(2021, 3, 15), ex_date=date(2021, 3, 16),
            reference_price=None, share_ratio=None, known_at_quality="unknown",
        )
        ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        projection = ledger.project(date(2021, 3, 16), positions={"A.SZ": 100},
                                    raw_closes={"A.SZ": 9.5}, tax_policy="cash_dividend_20pct_stress")
        self.assertEqual(projection.order_rejections, {"A.SZ": "corporate_action_unknown"})
        self.assertEqual(projection.rights_value_unknown, ("rights-unknown",))
        self.assertEqual(projection.equity_value, 950.0)

    def test_rejects_unsupported_tax_policy_and_duplicate_event(self):
        event = CorporateActionEvent(
            event_id="event", instrument_id="A.SZ", kind="cash_dividend",
            source_table="dividend", source_row_id="row", source_snapshot_hash="hash",
            source_version="v1", record_date=date(2021, 1, 1), ex_date=date(2021, 1, 2),
            gross_cash_per_share=0.1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            CorporateActionProvider((event, event))
        ledger = CorporateActionLedger(CorporateActionProvider(()))
        with self.assertRaisesRegex(ValueError, "tax_policy"):
            ledger.project(date(2021, 1, 1), positions={}, raw_closes={}, tax_policy="true_fifo")

    def test_missed_pay_date_fails_instead_of_silently_dropping_receivable(self):
        event = CorporateActionEvent(
            event_id="late-cash", instrument_id="A.SZ", kind="cash_dividend",
            source_table="dividend", source_row_id="late", source_snapshot_hash="hash",
            source_version="v1", record_date=date(2021, 1, 1), ex_date=date(2021, 1, 2),
            pay_date=date(2021, 1, 3), gross_cash_per_share=0.1,
        )
        ledger = CorporateActionLedger(CorporateActionProvider((event,)))
        with self.assertRaisesRegex(ValueError, "missed pay-date"):
            ledger.project(date(2021, 1, 4), positions={"A.SZ": 100}, raw_closes={"A.SZ": 9.9})

    def test_known_at_timestamp_must_be_timezone_aware(self):
        event = CorporateActionEvent(
            event_id="known-at", instrument_id="A.SZ", kind="cash_dividend",
            source_table="dividend", source_row_id="known", source_snapshot_hash="hash",
            source_version="v1", ex_date=date(2021, 1, 2), known_at_quality="verified_timestamp",
            known_at=datetime(2021, 1, 1, 9, tzinfo=UTC),
        )
        self.assertEqual(event.known_at_quality, "verified_timestamp")
        provider = CorporateActionProvider((event,))
        self.assertEqual(provider.events_known_as_of(datetime(2021, 1, 1, 9, tzinfo=UTC)), (event,))
        self.assertEqual(provider.events_known_as_of(datetime(2021, 1, 1, 8, tzinfo=UTC)), ())
        date_event = CorporateActionEvent(
            event_id="date-only", instrument_id="A.SZ", kind="cash_dividend",
            source_table="dividend", source_row_id="date", source_snapshot_hash="hash",
            source_version="v1", ex_date=date(2021, 1, 4), known_at=date(2021, 1, 2),
            known_at_quality="date_only",
        )
        date_provider = CorporateActionProvider((date_event,))
        self.assertEqual(date_provider.events_known_as_of(datetime(2021, 1, 2, 15, 30, tzinfo=UTC)), ())
        self.assertEqual(date_provider.events_known_as_of(datetime(2021, 1, 2, 16, 30, tzinfo=UTC)),
                         (date_event,))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            CorporateActionEvent(
                event_id="naive", instrument_id="A.SZ", kind="cash_dividend",
                source_table="dividend", source_row_id="naive", source_snapshot_hash="hash",
                source_version="v1", ex_date=date(2021, 1, 2),
                known_at_quality="verified_timestamp", known_at=datetime.fromisoformat("2021-01-01T09:00:00"),
            )
