"""真实 core 账户与观察者上下文的增量 TDD。"""

import unittest
from datetime import date
from typing import Any

from backtest_core.contracts.account import AccountState
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import ExecutionMode, Side
from backtest_core.contracts.execution_feedback import ExecutionPhase, ExecutionUpdate
from backtest_core.contracts.order import OrderIntent
from backtest_core.engine.account import apply_account_actions
from backtest_core.engine.account_runner import run_account_backtest_from_orders
from backtest_core.testing import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.ca.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.ca.corporate_action_snapshot_loader import (
    CorporateActionSnapshot,
    descriptor_from_row,
)
from tests.unit.backtest.test_corporate_action_snapshot_loader import raw_row


def context(*, strict=False, empty=True, anchor=date(2021, 5, 10), delegate=None, **changes):
    item = descriptor_from_row(raw_row(**changes), table="dividend", file_sha256="fixture")
    snapshot = CorporateActionSnapshot((item,), {"fixture.json": "fixture"}, "manifest", {})
    return CorporateActionContext(snapshot, period_id="test", reset_anchor=anchor,
                                  empty_reset=empty, strict_tax=strict, delegate=delegate)


def state(shares=100, **changes):
    values: dict[str, Any] = {"cash": 10000., "available_cash": 10000.,
                              "positions": {"A.SZ": float(shares)}, "locked": {},
                              "cost": {"A.SZ": 10.}, "last_marks": {"A.SZ": 10.}}
    values.update(changes)
    return AccountState(**values)


def observe(ctx, account, day=date(2021, 5, 11)):
    update = ExecutionUpdate("u", 1, ExecutionPhase.SNAPSHOT, day, None, None,
                             None, None, None, account, account, 0.)
    ctx.on_update(update)
    return update


class ContextTest(unittest.TestCase):
    def test_missing_cash_zero_record_exploration_and_explicit_zero_are_distinct(self):
        for cash, shares, strict, incomplete in ((None, 0, True, False),
                                                  (None, 100, False, True),
                                                  (0, 100, True, False)):
            with self.subTest(cash=cash, shares=shares, strict=strict):
                ctx = context(strict=strict, 每股派息税前=cash, 每股送转=0,
                              每股送股比例=0, 每股转增比例=0)
                day = date(2021, 5, 11)
                recorded = apply_account_actions(state(shares), ctx.account_actions_for_day(day), day)
                observe(ctx, recorded)
                self.assertEqual(ctx.account_actions_for_day(date(2021, 5, 12)), ())
                self.assertEqual(ctx.evidence()["incomplete"], incomplete)
                self.assertEqual("cash_amount_unknown" in ctx.snapshot.descriptors[0].unknown,
                                 cash is None)
                self.assertFalse(recorded.cash_receivables or recorded.unlisted_entitlements)

    def test_evidence_window_identity_is_caller_supplied_and_unverified(self):
        snapshot = context().snapshot
        ctx = CorporateActionContext(
            snapshot, period_id="window-2021", reset_anchor=date(2021, 5, 10),
            empty_reset=True, window_end=date(2021, 5, 14), calendar_sha256="a" * 64)
        evidence = ctx.evidence()
        self.assertEqual(evidence["period_id"], "window-2021")
        self.assertEqual(evidence["anchor"], "2021-05-10")
        self.assertEqual(evidence["window_end"], "2021-05-14")
        self.assertEqual(evidence["calendar_sha256"], "a" * 64)
        self.assertEqual(evidence["window_identity_validation"], "pending_runner_validation")
        unspecified = context().evidence()
        self.assertIsNone(unspecified["window_end"])
        self.assertIsNone(unspecified["calendar_sha256"])

    def test_same_day_record_ex_keeps_record_and_only_blocks_positive_record(self):
        day = date(2021, 5, 12)
        for shares in (0, 100):
            with self.subTest(shares=shares):
                ctx = context(strict=True, 股权登记日=20210512, 除权除息日=20210512)
                observe(ctx, state(0))
                actions = ctx.account_actions_for_day(day)
                self.assertEqual(len(actions), 1)
                # 模拟 hook 之后 core 开盘买入，不能依据之前零持仓跳登记。
                recorded = apply_account_actions(state(shares), actions, day)
                self.assertEqual(next(iter(recorded.record_positions.values())), shares)
                if shares:
                    with self.assertRaisesRegex(ValueError, "same_day_record_ex_unsupported"):
                        observe(ctx, recorded, day)
                    self.assertTrue(ctx.evidence()["incomplete"])
                else:
                    observe(ctx, recorded, day)
                    self.assertFalse(ctx.evidence()["incomplete"])

    def test_positive_record_missing_cash_is_unknown_and_strictly_rejected(self):
        ctx = context(strict=True, 每股派息税前=None, 每股送转=0,
                      每股送股比例=0, 每股转增比例=0)
        record_day = date(2021, 5, 11)
        recorded = apply_account_actions(state(), ctx.account_actions_for_day(record_day), record_day)
        with self.assertRaisesRegex(ValueError, "cash_amount_unknown"):
            observe(ctx, recorded)
        evidence = ctx.evidence()
        self.assertTrue(evidence["incomplete"])
        self.assertIn("cash_amount_unknown", evidence["coverage"][0]["unknown"])
        self.assertIsNone(evidence["coverage"][0]["raw_row"]["每股派息税前"])

    def test_unrelated_unheld_unknown_descriptor_does_not_block_held_cash(self):
        held = descriptor_from_row(raw_row(每股送转=0, 每股送股比例=0, 每股转增比例=0),
                                   table="dividend", file_sha256="fixture")
        unheld = descriptor_from_row(raw_row(id=2, 证券代码="B.SZ", 除权除息日=None),
                                     table="dividend", file_sha256="fixture")
        snapshot = CorporateActionSnapshot((held, unheld), {}, "manifest", {})
        ctx = CorporateActionContext(snapshot, period_id="test", reset_anchor=date(2021, 5, 10),
                                     empty_reset=True, strict_tax=False)
        record = apply_account_actions(state(), ctx.account_actions_for_day(date(2021, 5, 11)),
                                       date(2021, 5, 11))
        observe(ctx, record)
        actions = ctx.account_actions_for_day(date(2021, 5, 12))
        self.assertEqual(len(actions), 1)
        self.assertNotIn(unheld.event_id, ctx.evidence()["unknown"])

    def test_cash_payment_core_replay_is_idempotent(self):
        first = context(每股送转=0, 每股送股比例=0, 每股转增比例=0)
        record = apply_account_actions(state(), first.account_actions_for_day(date(2021, 5, 11)),
                                       date(2021, 5, 11))
        observe(first, record)
        ex = apply_account_actions(record, first.account_actions_for_day(date(2021, 5, 12)),
                                   date(2021, 5, 12))
        observe(first, ex, date(2021, 5, 12))
        paid = apply_account_actions(ex, first.account_actions_for_day(date(2021, 5, 13)),
                                     date(2021, 5, 13))
        self.assertEqual(paid.gross_cash_dividends_paid, 18)
        observe(first, paid, date(2021, 5, 13))
        replay = apply_account_actions(paid, first.account_actions_for_day(date(2021, 5, 13)),
                                        date(2021, 5, 13))
        self.assertEqual(replay, paid)

    def test_zero_record_has_no_ghosts_or_unknown_block(self):
        ctx = context(strict=True, 派息日=None, 红股上市日=None)
        before = state(0)
        recorded = apply_account_actions(before, ctx.account_actions_for_day(date(2021, 5, 11)),
                                         date(2021, 5, 11))
        observe(ctx, recorded)
        self.assertEqual(ctx.account_actions_for_day(date(2021, 5, 12)), ())
        self.assertFalse(recorded.cash_receivables or recorded.unlisted_entitlements)

    def test_anchor_before_skip_and_anchor_on_or_after_missing_record_reject(self):
        ctx = context(anchor=date(2021, 5, 12))
        self.assertEqual(ctx.account_actions_for_day(date(2021, 5, 12)), ())
        for anchor, empty in ((date(2021, 5, 11), True),
                              (date(2021, 5, 10), True), (date(2021, 5, 12), False)):
            with self.subTest(anchor=anchor, empty=empty):
                ctx = context(anchor=anchor, empty=empty)
                with self.assertRaisesRegex(ValueError, "missing_record"):
                    ctx.account_actions_for_day(date(2021, 5, 12))
                self.assertEqual(ctx.evidence()["status"], "INCOMPLETE")


class CoreRunnerContextTest(unittest.TestCase):
    def test_real_core_same_day_ex_zero_passes_open_buy_records_then_blocks(self):
        for buy, strict in ((False, True), (True, True), (True, False)):
            with self.subTest(buy=buy, strict=strict):
                ctx = context(anchor=date(2021, 5, 7), strict=strict, 除权除息日=20210511)
                if buy:
                    with self.assertRaisesRegex(ValueError, "same_day_record_ex_unsupported"):
                        self.run_fixture(ctx, buy=True)
                else:
                    self.run_fixture(ctx, buy=False)
                assert ctx.post_state is not None
                self.assertEqual(next(iter(ctx.post_state.record_positions.values())), 100 if buy else 0)
                self.assertEqual(ctx.evidence()["incomplete"], buy)
                self.assertFalse(ctx.post_state.cash_receivables)
                self.assertFalse(ctx.post_state.unlisted_entitlements)

    def run_fixture(self, ctx, *, sell=False, buy=True):
        calendar = tuple(date(2021, 5, day) for day in (7, 10, 11, 12, 13, 14, 17))

        class Orders:
            def orders_for(self, *, trading_date, **kwargs):
                if buy and trading_date == date(2021, 5, 10):
                    return (OrderIntent("A.SZ", Side.BUY, shares=100),)
                if sell and trading_date == date(2021, 5, 11):
                    return (OrderIntent("A.SZ", Side.SELL, shares=100),)
                return ()

        market = SyntheticMarketProvider(make_bar("A.SZ", day, 10.) for day in calendar)
        return run_account_backtest_from_orders(
            execution_calendar=calendar, signal_dates=calendar[1:], anchor_date=calendar[0],
            strategy=Orders(), market=market, observer=ctx,
            account_actions_provider=ctx.account_actions_for_day,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN,
                                             final_liquidation="mark"),
            portfolio_config=PortfolioConfig(),
            cost_config=CostConfig(commission_rate=0., min_commission=0., stamp_tax_rate=0.,
                                   transfer_fee_rate=0.),
            run_id="context-real-core", model_id="fixture", initial_capital=10000.)

    def test_open_buy_then_record_and_cash_paid_after_sell_to_zero(self):
        ctx = context(anchor=date(2021, 5, 7), 每股送转=0, 每股送股比例=0, 每股转增比例=0)
        result = self.run_fixture(ctx, sell=True)
        assert ctx.post_state is not None
        recorded = result.account_snapshots[2]
        self.assertEqual(recorded.positions["A.SZ"].shares, 100)
        self.assertEqual(next(iter(ctx.post_state.record_positions.values())), 100)
        self.assertEqual(ctx.post_state.positions, {})
        self.assertEqual(ctx.post_state.gross_cash_dividends_paid, 18.)
        self.assertEqual(ctx.post_state.cash, result.account_snapshots[-1].cash)

    def test_missed_ex_payment_is_incomplete_before_core_error(self):
        ctx = context(每股送转=0, 每股送股比例=0, 每股转增比例=0)
        recorded = apply_account_actions(state(), ctx.account_actions_for_day(date(2021, 5, 11)),
                                         date(2021, 5, 11))
        observe(ctx, recorded)
        with self.assertRaisesRegex(ValueError, "missing_cash_ex"):
            ctx.account_actions_for_day(date(2021, 5, 13))

    def test_share_position_change_before_ex_is_incomplete(self):
        ctx = context()
        recorded = apply_account_actions(state(), ctx.account_actions_for_day(date(2021, 5, 11)),
                                         date(2021, 5, 11))
        changed = state(0, record_positions=recorded.record_positions,
                        record_costs=recorded.record_costs,
                        processed_action_operations=recorded.processed_action_operations)
        observe(ctx, changed)
        with self.assertRaisesRegex(ValueError, "core_share_holdings_changed"):
            ctx.account_actions_for_day(date(2021, 5, 12))

    def test_delegate_gets_original_and_errors_propagate(self):
        class Delegate:
            def __init__(self):
                self.updates = []

            def on_update(self, update):
                self.updates.append(update)
                raise RuntimeError("delegate failure")

        delegate = Delegate()
        ctx = context(delegate=delegate)
        account = state(0)
        with self.assertRaisesRegex(RuntimeError, "delegate failure"):
            observe(ctx, account)
        self.assertIs(ctx.post_state, account)
        self.assertIs(ctx.last_update, delegate.updates[0])
        self.assertEqual(ctx.evidence()["status"], "INCOMPLETE")

    def test_exact_integer_total_once_and_noninteger_rejected(self):
        ctx = context()
        recorded = apply_account_actions(state(), ctx.account_actions_for_day(date(2021, 5, 11)),
                                         date(2021, 5, 11))
        observe(ctx, recorded)
        actions = ctx.account_actions_for_day(date(2021, 5, 12))
        ex = apply_account_actions(recorded, actions, date(2021, 5, 12))
        self.assertEqual(len(ex.unlisted_entitlements), 1)
        self.assertEqual(next(iter(ex.unlisted_entitlements.values())).shares, 30)
        self.assertAlmostEqual(ex.cost["A.SZ"], 1000 / 130)
        bad = context(每股送转=0.333)
        recorded = apply_account_actions(state(), bad.account_actions_for_day(date(2021, 5, 11)),
                                         date(2021, 5, 11))
        with self.assertRaisesRegex(ValueError, "noninteger"):
            observe(bad, recorded)

    def test_positive_unresolved_dates_and_strict_tax_expose(self):
        cases: tuple[tuple[dict[str, Any], str], ...] = (({"除权除息日": None}, "ex_date_missing"),
                                ({"派息日": None}, "pay_date_missing"),
                                ({"红股上市日": None}, "listing_date_missing"),
                                ({}, "tax_unknown"))
        for changes, reason in cases:
            with self.subTest(changes=changes):
                ctx = context(strict=True, **changes)
                recorded = apply_account_actions(
                    state(), ctx.account_actions_for_day(date(2021, 5, 11)), date(2021, 5, 11))
                with self.assertRaisesRegex(ValueError, reason):
                    observe(ctx, recorded)
                self.assertIs(ctx.post_state, recorded)
                self.assertEqual(ctx.evidence()["status"], "INCOMPLETE")

    def test_real_core_composite_lists_once_and_cost_is_conserved(self):
        ctx = context(anchor=date(2021, 5, 7))
        result = self.run_fixture(ctx)
        assert ctx.post_state is not None
        self.assertEqual(ctx.post_state.positions["A.SZ"], 130)
        self.assertEqual(ctx.post_state.unlisted_entitlements, {})
        self.assertAlmostEqual(ctx.post_state.cost["A.SZ"] * 130,
                               result.account_snapshots[2].positions["A.SZ"].cost * 100)
        self.assertEqual(ctx.evidence()["status"], "INCOMPLETE")
        self.assertFalse(ctx.evidence()["actual_after_tax_target_eligible"])

    def test_real_core_zero_record_unknown_fields_no_ghosts(self):
        ctx = context(anchor=date(2021, 5, 7), strict=True, 派息日=None, 红股上市日=None)
        self.run_fixture(ctx, buy=False)
        assert ctx.post_state is not None
        self.assertEqual(next(iter(ctx.post_state.record_positions.values())), 0)
        self.assertFalse(ctx.post_state.cash_receivables)
        self.assertFalse(ctx.post_state.unlisted_entitlements)
        self.assertFalse(ctx.post_state.pending_cash)
        self.assertEqual(ctx.evidence()["status"], "MECHANICAL_ONLY")

    def test_real_core_cash_stress_is_only_cash_stress(self):
        item = descriptor_from_row(raw_row(每股送转=0, 每股送股比例=0, 每股转增比例=0),
                                   table="dividend", file_sha256="fixture")
        snapshot = CorporateActionSnapshot((item,), {}, "manifest", {})
        ctx = CorporateActionContext(snapshot, period_id="test", reset_anchor=date(2021, 5, 7),
                                     empty_reset=True, strict_tax=False,
                                     tax_policy="cash_dividend_20pct_stress")
        self.run_fixture(ctx)
        assert ctx.post_state is not None
        self.assertAlmostEqual(ctx.post_state.gross_cash_dividends_paid, 18)
        self.assertAlmostEqual(ctx.post_state.withheld_cash_dividends_paid, 3.6)
        self.assertFalse(ctx.evidence()["cash_tax_is_actual"])

    def test_all_real_core_updates_forwarded_without_projection(self):
        class Delegate:
            def __init__(self):
                self.updates = []

            def on_update(self, update):
                self.updates.append(update)

        delegate = Delegate()
        ctx = context(anchor=date(2021, 5, 7), delegate=delegate)
        self.run_fixture(ctx)
        self.assertIs(ctx.last_update, delegate.updates[-1])
        self.assertIs(ctx.post_state, delegate.updates[-1].post_state)
        self.assertEqual({item.phase for item in delegate.updates}, set(ExecutionPhase))
        sequences = [item.sequence_no for item in delegate.updates]
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))
