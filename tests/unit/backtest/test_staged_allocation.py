"""分批预算登记与 core 成交反馈的合成回归测试。"""

import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import date
from math import inf, nan
from typing import Any, Literal, cast

from backtest.cnn_adapter.staged_allocation import (
    AllocationError,
    CoreAccountSnapshot,
    EpisodeStatus,
    ExecutionFeedback,
    Policy,
    StagedAllocationRegistry,
    budget_per_episode,
)
from backtest.cnn_adapter.staged_execution_bridge import cash_debit_from_transition

CALENDAR = [date(2021, 1, 4), date(2021, 1, 5)]


def registry(cash: float = 1000):
    return StagedAllocationRegistry(initial_cash=cash, calendar_days=CALENDAR)


def core_snapshot(
    snapshot_id: str,
    sequence: int,
    available_cash: float,
    positions: dict[str, int] | None = None,
    entitlements: frozenset[str] = frozenset(),
    orders: frozenset[str] = frozenset(),
    *,
    cash: float | None = None,
    locked: dict[str, int] | None = None,
):
    return CoreAccountSnapshot(
        snapshot_id, sequence, available_cash, positions or {}, entitlements, orders,
        cash=available_cash if cash is None else cash, locked=locked or {},
    )


def fill(episode: str = "e1", code: str = "AAA", *, fill_id: str = "f1",
         cash: float = 948, positions: dict[str, int] | None = None,
         entitlements: frozenset[str] = frozenset(), orders: frozenset[str] = frozenset(),
         amount: float = 50, fees: float = 2, debit: float = 52, shares: int = 2,
         side: Literal["buy", "sell"] = "buy", sequence=1):
    return ExecutionFeedback(
        episode_id=episode, order_id="o1", fill_id=fill_id, event="fill",
        side=side, amount=amount, fees=fees, cash_debit=debit,
        shares_delta=shares, available_cash=cash,
        core_snapshot_id=f"snapshot-{fill_id}",
        core_snapshot_sequence=sequence,
        positions=positions if positions is not None else {code: shares},
        unlisted_entitlement_codes=entitlements, active_order_codes=orders,
        cash=cash,
    )


class StagedAllocationTests(unittest.TestCase):
    def test_authoritative_snapshot_sync_updates_account_without_a_fill(self):
        book = registry()
        first = CoreAccountSnapshot(
            "s0", 0, 990, {"OLD": 3}, frozenset({"NEW"}), frozenset({"X"}),
            cash=1000, locked={"OLD": 2},
        )
        self.assertTrue(book.apply_core_snapshot(first))
        self.assertEqual(book.available_cash, 990)
        self.assertEqual(book.core_cash, 1000)
        self.assertEqual(dict(book.positions), {"OLD": 3})
        self.assertEqual(book.locked, {"OLD": 2})
        self.assertEqual(book.active_codes, frozenset({"OLD", "NEW", "X"}))
        self.assertEqual(book.fill_ledger, {})

    def test_nonfill_snapshot_replay_is_noop_and_cannot_roll_state_back(self):
        book = registry()
        old = core_snapshot("s0", 0, 1000)
        new = core_snapshot("s1", 1, 900, {"AAA": 2})
        self.assertTrue(book.apply_core_snapshot(old))
        self.assertTrue(book.apply_core_snapshot(new))
        self.assertFalse(book.apply_core_snapshot(old))
        self.assertEqual(book.available_cash, 900)
        self.assertEqual(dict(book.positions), {"AAA": 2})

    def test_nonfill_snapshot_conflicts_and_stale_ids_are_atomic(self):
        book = registry()
        first = core_snapshot("s0", 0, 1000)
        book.apply_core_snapshot(first)
        before = book.snapshot()
        conflict = core_snapshot("s0", 0, 900)
        with self.assertRaisesRegex(AllocationError, "snapshot_id"):
            book.apply_core_snapshot(conflict)
        stale = core_snapshot("s-old", 0, 800)
        with self.assertRaisesRegex(AllocationError, "sequence"):
            book.apply_core_snapshot(stale)
        self.assertEqual(book.snapshot(), before)

    def test_authoritative_snapshot_requires_actual_core_cash(self):
        book = registry()
        incomplete = CoreAccountSnapshot("missing-cash", 0, 900, {}, frozenset(), frozenset())
        with self.assertRaisesRegex(AllocationError, "缺少 cash"):
            book.apply_core_snapshot(incomplete)
        self.assertIsNone(book.snapshot().core_snapshot_id)

    def test_fill_feedback_requires_actual_core_cash_at_registry_boundary(self):
        book = registry()
        book.open_episode("e1", "AAA")
        before = book.snapshot()
        with self.assertRaisesRegex(AllocationError, "缺少 cash"):
            book.apply_feedback(replace(fill(), cash=None))
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(book.fill_ledger, {})

    def test_exit_confirmation_requires_fresh_snapshot_without_locked_entitlements_or_orders(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_core_snapshot(core_snapshot(
            "held", 1, 900, {"AAA": 2}, locked={"AAA": 2}
        ))
        book.mark_exit_pending("e1", CALENDAR[0])
        book.apply_core_snapshot(core_snapshot(
            "unlock-pending", 2, 900, locked={"AAA": 1}
        ))
        self.assertTrue(book.episodes["e1"].exit_pending)
        book.apply_core_snapshot(core_snapshot("ca-entitlement", 3, 900, entitlements=frozenset({"AAA"})))
        self.assertTrue(book.episodes["e1"].exit_pending)
        book.apply_core_snapshot(core_snapshot("cancel-pending", 4, 900, orders=frozenset({"AAA"})))
        self.assertTrue(book.episodes["e1"].exit_pending)
        book.apply_core_snapshot(core_snapshot("flat", 5, 900))
        self.assertIs(book.episodes["e1"].status, EpisodeStatus.CLOSED)

    def test_state_snapshot_does_not_consume_later_fill_and_fill_replay_is_noop(self):
        book = registry()
        book.open_episode("e1", "AAA")
        snap = core_snapshot("same", 1, 948, {"AAA": 2})
        self.assertTrue(book.apply_core_snapshot(snap))
        event = replace(fill(), core_snapshot_id="same", positions={"AAA": 2}, cash=948)
        self.assertTrue(book.apply_feedback(event))
        self.assertFalse(book.apply_core_snapshot(snap))
        self.assertFalse(book.apply_feedback(event))
        self.assertEqual(len(book.fill_ledger), 1)

    def test_only_unclosed_episodes_consume_slots_and_commitments(self):
        book = registry()
        for index in range(7):
            episode = book.open_episode(f"cycle-{index}", f"C{index}")
            self.assertEqual(book.snapshot().active_slots, 1)
            self.assertEqual(book.active_commitments, 200)
            book.cancel_episode(episode.episode_id)
            book.apply_core_snapshot(core_snapshot(f"flat-{index}", index, 1000))
            self.assertEqual(book.snapshot().active_slots, 0)
            self.assertEqual(book.active_commitments, 0)

    def test_empty_snapshot_does_not_end_active_cycle_before_final_plan_day(self):
        book = registry()
        episode = book.open_episode("planned", "AAA")
        book.set_episode_plan_end("planned", CALENDAR[1])
        book.apply_core_snapshot(core_snapshot("early-flat", 1, 1000))
        self.assertIs(book.episodes[episode.episode_id].status, EpisodeStatus.ACTIVE)
        self.assertEqual(book.snapshot().active_slots, 1)
        book.advance(CALENDAR[1])
        book.apply_core_snapshot(core_snapshot("mature-flat", 2, 1000))
        self.assertIs(book.episodes[episode.episode_id].status, EpisodeStatus.CLOSED)

    def test_cancelled_cycle_keeps_commitment_until_fresh_flat_core_snapshot(self):
        book = registry()
        book.open_episode("cancel-me", "AAA", Policy.C70)
        book.apply_feedback(fill(episode="cancel-me", cash=860, amount=138,
                                 fees=2, debit=140, positions={"AAA": 2}))
        book.cancel_episode("cancel-me")
        self.assertEqual(book.active_commitments, 60)
        self.assertEqual(book.snapshot().active_slots, 1)
        book.apply_core_snapshot(core_snapshot("cancel-flat", 2, 860))
        self.assertEqual(book.active_commitments, 0)
        self.assertEqual(book.snapshot().active_slots, 0)

    def test_loss_reducing_core_cash_below_fixed_budget_rejects_new_cycle(self):
        book = registry()
        book.apply_core_snapshot(core_snapshot("loss", 1, 199))
        with self.assertRaisesRegex(AllocationError, "free_cash"):
            book.open_episode("too-small", "AAA")
        self.assertEqual(book.available_cash, 199)

    def test_old_fill_replay_after_close_does_not_change_new_cycle(self):
        book = registry()
        book.open_episode("old", "AAA")
        old_fill = replace(fill(fill_id="old-fill"), episode_id="old")
        book.apply_feedback(old_fill)
        book.mark_exit_pending("old", CALENDAR[0])
        close = replace(fill(fill_id="old-close", side="sell", cash=996,
                             amount=50, fees=2, debit=0, positions={}, sequence=2),
                        episode_id="old")
        book.apply_feedback(close)
        new_episode = book.open_episode("new", "AAA")
        before = book.snapshot()
        self.assertFalse(book.apply_feedback(old_fill))
        self.assertEqual(book.snapshot(), before)
        self.assertIn(new_episode.episode_id, book.episodes)

    def test_cash_reconciliation_allows_only_tiny_absolute_float_tail(self):
        cash_before = 10_000_000.0
        book = registry(cash_before)
        book.open_episode("e1", "AAA")
        amount, fees = 10.125, 0.37
        cash_after = cash_before - amount - fees
        debit = cash_debit_from_transition(cash_before, cash_after, "buy")
        self.assertNotEqual(debit, amount + fees)
        self.assertLess(abs(debit - (amount + fees)), 1e-8)
        accepted = fill(amount=amount, fees=fees, debit=debit,
                        cash=cash_after, positions={"AAA": 1})
        accepted = replace(accepted, cash=cash_after)
        self.assertTrue(book.apply_feedback(accepted))
        self.assertEqual(book.fill_ledger["f1"].fees, fees)
        self.assertEqual(book.episodes["e1"].cumulative_cash_debit, debit)
        self.assertEqual(book.core_cash, cash_after)

    def test_sell_cash_credit_never_becomes_episode_cash_debit(self):
        self.assertEqual(cash_debit_from_transition(100, 150, "sell"), 0)

    def test_cash_reconciliation_rejects_one_cent_without_mutating_state(self):
        book = registry()
        book.open_episode("e1", "AAA")
        before = book.snapshot()
        invalid = fill(fill_id="cent", amount=10.125, fees=0.37,
                       debit=10.505, cash=989.495, positions={"AAA": 1})
        with self.assertRaisesRegex(AllocationError, "cash_debit"):
            book.apply_feedback(invalid)
        self.assertEqual(book.snapshot(), before)
        self.assertEqual(book.fill_ledger, {})

    def test_c70_rejects_float_tail_over_cap_without_negative_commitment(self):
        book = registry()
        book.open_episode("c70", "AAA", Policy.C70)
        invalid = fill(episode="c70", fill_id="over-tail", amount=138.00000000001,
                       fees=2, debit=140.00000000001, cash=859.99999999999,
                       positions={"AAA": 1})
        with self.assertRaisesRegex(AllocationError, "C70"):
            book.apply_feedback(invalid)
        self.assertEqual(book.episodes["c70"].commitment, 200)
        self.assertEqual(book.episodes["c70"].cumulative_cash_debit, 0)

    def test_only_feedback_is_the_real_fill_api_and_cash_is_named_available(self):
        book = registry()
        self.assertTrue(hasattr(book, "apply_feedback"))
        self.assertFalse(hasattr(book, "record_fill"))
        self.assertFalse(hasattr(book, "cash"))
        self.assertTrue(hasattr(book, "available_cash"))

    def test_budget_and_c70_commitment(self):
        self.assertEqual(budget_per_episode(1000), 200)
        for invalid_cash in (nan, inf, -1):
            with self.assertRaises(AllocationError):
                budget_per_episode(invalid_cash)
        book = registry()
        episode = book.open_episode("c70", "AAA", Policy.C70)
        self.assertEqual(episode.commitment, 200)
        self.assertEqual(book.free_cash, 800)

    def test_c70_single_and_cumulative_debit_cap_is_seventy_percent_of_b(self):
        book = registry()
        book.open_episode("c70", "AAA", Policy.C70)
        with self.assertRaisesRegex(AllocationError, "C70"):
            book.apply_feedback(fill(episode="c70", fill_id="over-one",
                                     amount=139, fees=2, debit=141,
                                     cash=859, positions={"AAA": 1}))
        self.assertEqual(len(book.fill_ledger), 0)
        self.assertTrue(book.apply_feedback(fill(episode="c70", fill_id="part-1",
                                                amount=98, fees=2, debit=100,
                                                cash=900, positions={"AAA": 1})))
        self.assertTrue(book.apply_feedback(fill(episode="c70", fill_id="part-2",
                                                amount=37, fees=3, debit=40,
                                                cash=860, positions={"AAA": 2},
                                                sequence=2)))
        with self.assertRaisesRegex(AllocationError, "C70"):
            book.apply_feedback(fill(episode="c70", fill_id="part-3",
                                     amount=0, fees=1, debit=1, cash=859,
                                     positions={"AAA": 2}, sequence=3))
        self.assertNotIn("part-3", book.fill_ledger)
        self.assertEqual(book.episodes["c70"].commitment, 60)
        self.assertEqual(book.episodes["c70"].cumulative_cash_debit, 140)

    def test_snapshot_sequence_rejects_stale_without_poisoning_fill_id(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_feedback(fill(fill_id="first", sequence=8))
        with self.assertRaisesRegex(AllocationError, "sequence"):
            book.apply_feedback(fill(fill_id="retry", sequence=7))
        with self.assertRaisesRegex(AllocationError, "sequence"):
            book.apply_feedback(fill(fill_id="retry", sequence=8))
        self.assertTrue(book.apply_feedback(fill(fill_id="retry", sequence=9,
                                                cash=900)))

    def test_snapshot_id_is_unique_and_cannot_describe_different_content(self):
        book = registry()
        book.open_episode("e1", "AAA")
        first = fill(fill_id="f1")
        book.apply_feedback(first)
        different_content = replace(first, fill_id="f2", available_cash=900,
                                    core_snapshot_sequence=2)
        with self.assertRaisesRegex(AllocationError, "snapshot_id"):
            book.apply_feedback(different_content)

    def test_snapshot_id_cannot_be_reused_even_with_same_snapshot_content(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_feedback(fill(fill_id="f1"))
        same_snapshot = replace(book.fill_ledger["f1"], fill_id="f2")
        with self.assertRaisesRegex(AllocationError, "snapshot_id"):
            book.apply_feedback(same_snapshot)
        self.assertEqual(tuple(book.fill_ledger), ("f1",))

    def test_cancelled_episode_rejects_buy_but_accepts_real_exit_sell(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_feedback(fill())
        book.cancel_episode("e1")
        cancelled_buy = fill(fill_id="cancel-buy", sequence=2,
                              cash=896, amount=50, fees=2, debit=52,
                              positions={"AAA": 4}, shares=2)
        with self.assertRaisesRegex(AllocationError, "CANCELLED"):
            book.apply_feedback(cancelled_buy)
        self.assertNotIn("cancel-buy", book.fill_ledger)
        exit_fill = fill(fill_id="exit", sequence=2, side="sell",
                         amount=50, fees=2, debit=0, cash=996,
                         positions={}, shares=2)
        self.assertTrue(book.apply_feedback(exit_fill))
        self.assertEqual(book.positions, {})
        self.assertIs(book.episodes["e1"].status, EpisodeStatus.CLOSED)
        with self.assertRaisesRegex(AllocationError, "CLOSED"):
            book.apply_feedback(fill(fill_id="late-buy", sequence=3))

    def test_closed_episode_rejects_new_fill_for_reconciliation(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_feedback(fill())
        book.mark_exit_pending("e1", CALENDAR[0])
        close = fill(fill_id="close", sequence=2, side="sell", amount=50,
                     fees=2, debit=0, cash=948, positions={}, shares=2)
        book.apply_feedback(close)
        late = fill(fill_id="late", sequence=3, cash=948)
        with self.assertRaisesRegex(AllocationError, "CLOSED.*对账"):
            book.apply_feedback(late)
        self.assertNotIn("late", book.fill_ledger)

    def test_five_slots_and_cancel_never_releases_budget(self):
        book = registry()
        first = book.open_episode("e0", "C0")
        book.cancel_episode(first.episode_id)
        for index in range(1, 5):
            book.open_episode(f"e{index}", f"C{index}")
        self.assertEqual(book.active_commitments, 1000)
        with self.assertRaises(AllocationError):
            book.open_episode("e5", "C5")

    def test_one_unique_code_from_positions_entitlements_and_orders(self):
        book = registry()
        book.open_episode("e1", "AAA")
        self.assertTrue(book.apply_feedback(fill(positions={"AAA": 2, "BBB": 1},
                                                entitlements=frozenset({"AAA", "CCC"}),
                                                orders=frozenset({"BBB", "DDD"}))))
        self.assertEqual(book.active_codes, frozenset({"AAA", "BBB", "CCC", "DDD"}))
        self.assertEqual(book.snapshot().active_slots, 1)
        for code in book.active_codes:
            with self.assertRaises(AllocationError):
                book.open_episode(f"new-{code}", code)

    def test_old_episode_blocks_same_code_even_after_empty_snapshot_until_exit(self):
        book = registry()
        book.open_episode("old", "AAA")
        book.apply_feedback(fill(episode="old"))
        with self.assertRaisesRegex(AllocationError, "旧 episode"):
            book.open_episode("again", "AAA")
        book.mark_exit_pending("old", CALENDAR[0])
        close = fill(episode="old", fill_id="close", cash=948,
                     positions={}, entitlements=frozenset(), orders=frozenset(),
                     shares=2, side="sell", sequence=2)
        book.apply_feedback(close)
        self.assertIs(book.episodes["old"].status, EpisodeStatus.CLOSED)
        book.open_episode("again", "AAA")

    def test_partial_fills_have_independent_fill_ids_and_order_may_repeat(self):
        book = registry()
        episode = book.open_episode("e1", "AAA")
        first = fill(fill_id="f1", cash=948, positions={"AAA": 2}, shares=99)
        second = fill(fill_id="f2", cash=777, amount=27, fees=3, debit=30,
                      positions={"AAA": 3}, shares=1, sequence=2)
        self.assertTrue(book.apply_feedback(first))
        self.assertTrue(book.apply_feedback(second))
        self.assertFalse(book.apply_feedback(first))
        self.assertEqual(book.available_cash, 777)
        self.assertEqual(dict(book.positions), {"AAA": 3})
        self.assertEqual(book.snapshot().core_snapshot_id, "snapshot-f2")
        self.assertEqual(book.snapshot().last_fill_id, "f2")
        self.assertEqual(book.snapshot().last_order_id, "o1")
        self.assertEqual(tuple(book.fill_ledger), ("f1", "f2"))
        with self.assertRaises(TypeError):
            cast(Any, book.fill_ledger)["f3"] = second
        self.assertEqual(book.episodes[episode.episode_id].commitment, 118)

    def test_failed_fill_validation_can_be_corrected_and_replayed(self):
        book = registry()
        book.open_episode("e1", "AAA")
        invalid = fill(fill_id="retry", cash=748, amount=250,
                       fees=0, debit=250)
        with self.assertRaises(AllocationError):
            book.apply_feedback(invalid)
        self.assertTrue(book.apply_feedback(fill(fill_id="retry")))
        self.assertEqual(book.available_cash, 948)

    def test_missing_order_or_fill_id_does_not_consume_dedupe_key(self):
        book = registry()
        book.open_episode("e1", "AAA")
        valid = fill(fill_id="retry-id")
        with self.assertRaises(AllocationError):
            book.apply_feedback(replace(valid, order_id=None))
        with self.assertRaises(AllocationError):
            book.apply_feedback(replace(valid, fill_id=None))
        with self.assertRaises(AllocationError):
            book.apply_feedback(replace(valid, core_snapshot_id=None))
        self.assertTrue(book.apply_feedback(valid))

    def test_snapshot_copy_isolated_from_mutable_input(self):
        book = registry()
        book.open_episode("e1", "AAA")
        source_positions = {"AAA": 2}
        source_locked = {"AAA": 2}
        feedback = replace(fill(positions=source_positions), locked=source_locked)
        book.apply_feedback(feedback)
        source_positions["EVIL"] = 1
        source_locked["EVIL"] = 1
        self.assertEqual(dict(book.positions), {"AAA": 2})
        self.assertEqual(dict(book.locked), {"AAA": 2})
        with self.assertRaises(AllocationError):
            book.apply_feedback(feedback)

    def test_invalid_fill_id_collision_does_not_replace_original(self):
        book = registry()
        book.open_episode("e1", "AAA")
        original = fill(fill_id="same")
        book.apply_feedback(original)
        with self.assertRaisesRegex(AllocationError, "fill_id"):
            book.apply_feedback(fill(fill_id="same", cash=900))
        self.assertEqual(book.available_cash, 948)

    def test_nonfill_events_and_calendar_advance_do_not_change_account_or_exit(self):
        book = registry()
        episode = book.open_episode("e1", "AAA")
        book.mark_exit_pending("e1", CALENDAR[0])
        before = book.snapshot()
        events: tuple[Literal["cancel", "reject", "failed"], ...] = (
            "cancel", "reject", "failed"
        )
        for event in events:
            feedback = ExecutionFeedback(
                "e1", "o1", None, event, "sell", 0, 0, 0, 0
            )
            self.assertFalse(book.apply_feedback(feedback))
        book.advance(CALENDAR[1])
        self.assertEqual(book.snapshot(), before)
        self.assertTrue(book.episodes[episode.episode_id].exit_pending)

    def test_exit_only_clears_on_fill_snapshot_without_any_active_code(self):
        book = registry()
        book.open_episode("e1", "AAA")
        book.apply_feedback(fill())
        book.mark_exit_pending("e1", CALENDAR[0])
        book.advance(CALENDAR[1])
        self.assertTrue(book.episodes["e1"].exit_pending)
        for fill_id, entitlements, orders in (
            ("f2", frozenset({"AAA"}), frozenset()),
            ("f3", frozenset(), frozenset({"AAA"})),
        ):
            book.apply_feedback(fill(fill_id=fill_id, cash=948, amount=0,
                                      fees=0, debit=0, positions={},
                                      entitlements=entitlements, orders=orders,
                                      shares=0, side="buy",
                                      sequence=int(fill_id[1:])))
            self.assertTrue(book.episodes["e1"].exit_pending)
        closing = fill(fill_id="f4", cash=948, amount=0, fees=0, debit=0,
                       positions={}, entitlements=frozenset(), orders=frozenset(),
                       shares=0, side="buy", sequence=4)
        book.apply_feedback(closing)
        self.assertFalse(book.episodes["e1"].exit_pending)
        self.assertIs(book.episodes["e1"].status, EpisodeStatus.CLOSED)
        self.assertEqual(book.episodes["e1"].commitment, 148)

    def test_external_episode_and_code_snapshot_mutation_is_blocked(self):
        book = registry()
        episode = book.open_episode("e1", "AAA")
        with self.assertRaises(TypeError):
            cast(Any, book.episodes)["e2"] = episode
        with self.assertRaises(FrozenInstanceError):
            cast(Any, episode).commitment = 0
        book.apply_feedback(fill())
        with self.assertRaises(AttributeError):
            cast(Any, book.active_codes).add("EVIL")
        self.assertNotIn("EVIL", book.active_codes)

    def test_fill_numeric_inputs_must_be_finite_nonnegative_and_integer_shares(self):
        book = registry()
        book.open_episode("e1", "AAA")
        valid = fill()
        cases = [(field, value) for field in
                 ("amount", "fees", "cash_debit", "available_cash")
                 for value in (nan, inf, -1)]
        cases.extend(("shares_delta", value) for value in (nan, inf, 1.5, -1))
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field, value=value):
                with self.assertRaises(AllocationError):
                    book.apply_feedback(replace(valid, **{field: value},
                                                fill_id=f"invalid-{index}"))
        self.assertEqual(len(book.fill_ledger), 0)

    def test_positions_snapshot_rejects_negative_or_noninteger_shares(self):
        book = registry()
        book.open_episode("e1", "AAA")
        for index, shares in enumerate((-1, 1.5, nan, inf)):
            with self.subTest(shares=shares):
                with self.assertRaises(AllocationError):
                    book.apply_feedback(fill(positions=cast(Any, {"AAA": shares}),
                                             fill_id=f"bad-position-{index}"))
        self.assertEqual(len(book.fill_ledger), 0)
