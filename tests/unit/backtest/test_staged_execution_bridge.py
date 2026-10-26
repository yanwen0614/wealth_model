"""冻结 core observer 契约下的真实 runner-to-registry 端到端测试。"""

import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

from backtest_core.contracts import (
    AccountState,
    ActiveOrderSnapshot,
    CashPayment,
    CostConfig,
    CreateCashReceivable,
    EventStatus,
    ExecutionConfig,
    ExecutionPhase,
    ExecutionUpdate,
    OrderIntent,
    PortfolioConfig,
    RecordPosition,
    Side,
    TradeEvent,
)
from backtest_core.contracts.account_actions import CashReceivable, ShareEntitlement
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.testing import SyntheticMarketProvider, build_market

from backtest.cnn_adapter.staged_allocation import AllocationError, AllocationRegistry, Policy
from backtest.cnn_adapter.staged_execution_bridge import StagedExecutionBridge


class _ScriptedOrders:
    def __init__(self, entries: dict[date, tuple[OrderIntent, ...]], registry, exit_day: date,
                 cycle_start: date, cycle_end: date, partial_exit_day: date | None = None) -> None:
        self._entries = entries
        self._registry = registry
        self._exit_day = exit_day
        self._cycle_start = cycle_start
        self._cycle_end = cycle_end
        self._partial_exit_day = partial_exit_day

    def orders_for(self, *, trading_date, signal_time, account, market):
        if trading_date == self._exit_day:
            self._registry.mark_exit_pending("episode-buy", trading_date)
            self._registry.mark_exit_pending("episode-reject", trading_date)
        if trading_date == self._cycle_start:
            self._registry.open_episode("episode-buy-cycle2", "AAA", Policy.B1)
        if trading_date == self._cycle_end:
            self._registry.mark_exit_pending("episode-buy-cycle2", trading_date)
        if trading_date == self._partial_exit_day:
            self._registry.mark_exit_pending("episode-partial", trading_date)
        return self._entries.get(trading_date, ())


class _RecordingBridge(StagedExecutionBridge):
    def __init__(self, registry: AllocationRegistry) -> None:
        super().__init__(registry)
        self.updates = []

    def on_update(self, update) -> None:
        self.updates.append(update)
        super().on_update(update)


class StagedExecutionBridgeE2ETests(unittest.TestCase):
    evidence: dict[str, object]

    def test_identical_snapshot_event_replay_is_noop_and_payload_conflict_fails(self):
        day = date(2026, 3, 2)
        registry = AllocationRegistry(initial_cash=1000, calendar_days=[day])
        state = AccountState(1000, 1000, {}, {}, {}, {})
        update = ExecutionUpdate("snapshot-replay", 1, ExecutionPhase.SNAPSHOT, day, None, None,
                                 None, None, None, state, state, 0)
        bridge = StagedExecutionBridge(registry)
        self.assertTrue(bridge.consume(update))
        before = registry.snapshot()
        self.assertFalse(bridge.consume(update))
        self.assertEqual(registry.snapshot(), before)
        with self.assertRaisesRegex(AllocationError, "event_id"):
            bridge.consume(replace(update, reason="conflicting event payload"))
        self.assertEqual(registry.snapshot(), before)

    def test_actual_cash_delta_rejects_one_cent_fee_mismatch_atomically(self):
        day = date(2026, 3, 2)
        registry = AllocationRegistry(initial_cash=1000, calendar_days=[day])
        registry.open_episode("episode", "AAA")
        pre = AccountState(1000, 1000, {}, {}, {}, {})
        post = AccountState(984.98, 984.98, {"AAA": 1}, {"AAA": 1}, {"AAA": 10}, {"AAA": 10})
        trade = TradeEvent(
            datetime.combine(day, time(10), UTC), datetime.combine(day, time(10, 1), UTC),
            "AAA", Side.BUY, 1, 10, 10, 10, 5, 0, 0.01, 1.0, None,
            EventStatus.FILLED, None, episode_id="episode", order_id="o1", fill_id="f-cent",
        )
        update = ExecutionUpdate("fill-cent-mismatch", 1, ExecutionPhase.FILL, day, "episode", "o1",
                                 "a1", "f-cent", trade, pre, post, post.cash - pre.cash)
        bridge = StagedExecutionBridge(registry)
        before = registry.snapshot()
        with self.assertRaisesRegex(AllocationError, "三项现金费用不一致"):
            bridge.on_update(update)
        self.assertEqual(registry.snapshot(), before)
        self.assertEqual(registry.fill_ledger, {})

    def test_snapshot_keeps_core_order_and_action_objects_immutable_and_identified(self):
        day = date(2026, 3, 2)
        registry = AllocationRegistry(initial_cash=1000, calendar_days=[day, day + timedelta(days=1)])
        registry.open_episode("episode", "AAA")
        receivable = CashReceivable("r", "AAA", 2, day + timedelta(days=1))
        entitlement = ShareEntitlement("u", "NEW", 5, day + timedelta(days=2))
        state = AccountState(
            cash=1000, available_cash=900, positions={"AAA": 100}, locked={"AAA": 100},
            cost={"AAA": 10}, last_marks={"AAA": 10},
            cash_receivables={"r": receivable},
            unlisted_entitlements={"u": entitlement},
            pending_cash={"p": 2},
        )
        active = ActiveOrderSnapshot("sell", "episode", "AAA", Side.SELL, 100, day)
        update = ExecutionUpdate("snapshot-1", 1, ExecutionPhase.SNAPSHOT, day, None, None, None,
                                 None, None, state, state, 0, {"sell": active})
        StagedExecutionBridge(registry).on_update(update)
        self.assertIs(registry.active_order_snapshots["sell"], active)
        synced = registry.core_snapshot
        assert synced is not None
        self.assertIs(synced.cash_receivables["r"], receivable)
        self.assertIs(synced.unlisted_entitlements["u"], entitlement)
        self.assertEqual(synced.pending_cash["p"], 2)
        self.assertEqual(registry.active_codes, frozenset({"AAA", "NEW"}))

    def test_fill_without_episode_fails_closed_without_code_inference(self):
        day = date(2026, 3, 2)
        registry = AllocationRegistry(initial_cash=1000, calendar_days=[day])
        pre = AccountState(1000, 1000, {}, {}, {}, {})
        post = AccountState(984.99, 984.99, {"AAA": 1}, {"AAA": 1}, {"AAA": 10}, {"AAA": 10})
        trade = TradeEvent(
            datetime.combine(day, time(10), UTC), datetime.combine(day, time(10, 1), UTC),
            "AAA", Side.BUY, 1, 10, 10, 10, 5, 0, 0.01, 0.2, None,
            EventStatus.FILLED, None, order_id="o1", fill_id="f1",
        )
        update = ExecutionUpdate("fill-no-episode", 1, ExecutionPhase.FILL, day, None, "o1", "a1",
                                 "f1", trade, pre, post, post.cash - pre.cash)
        bridge = StagedExecutionBridge(registry)
        with self.assertRaisesRegex(AllocationError, "拒绝按代码猜测"):
            bridge.on_update(update)
        self.assertEqual(registry.positions, {})
        self.assertEqual(registry.fill_ledger, {})
        self.assertEqual(dict(bridge.seen_events), {})

    def _assert_real_partial_sell_is_not_carried_to_next_day(self):
        days = build_market("PART", start_date=date(2026, 1, 2), trading_days=24,
                            base_amount=30_000).trading_dates("PART")
        market = SyntheticMarketProvider(build_market(
            "PART", start_date=days[0], trading_days=len(days), base_amount=30_000
        ).bars_for("PART"))
        registry = AllocationRegistry(initial_cash=1_000_000, calendar_days=list(days))
        registry.open_episode("episode-partial", "PART", Policy.B1)
        bridge = _RecordingBridge(registry)
        strategy = _ScriptedOrders({
            days[0]: (OrderIntent("PART", Side.BUY, shares=5_000,
                                  episode_id="episode-partial", order_id="partial-buy"),),
            days[21]: (OrderIntent("PART", Side.SELL, shares=5_000,
                                   episode_id="episode-partial", order_id="partial-sell"),),
        }, registry, days[23], days[23], days[23], partial_exit_day=days[21])
        result = run_account_backtest_from_orders(
            execution_calendar=days, signal_dates=(days[0], days[21]), strategy=strategy, market=market,
            execution_config=ExecutionConfig(final_liquidation="mark"),
            portfolio_config=PortfolioConfig(lot_size=100), cost_config=CostConfig(),
            run_id="staged-partial-sell", model_id="synthetic", initial_capital=1_000_000,
            observer=bridge,
        )
        fills = [item for item in bridge.updates if item.phase is ExecutionPhase.FILL]
        for item in bridge.updates:
            self.assertEqual(item.cash_delta, item.post_state.cash - item.pre_state.cash)
        sell = next((item for item in fills if item.order_id == "partial-sell"), None)
        self.assertIsNotNone(sell, [(item.phase, item.order_id, item.order_status, item.reason)
                                    for item in bridge.updates
                                    if item.phase is not ExecutionPhase.SNAPSHOT])
        assert sell is not None
        assert sell.trade is not None
        assert sell.fill_id is not None
        self.assertGreater(sell.trade.shares, 0)
        self.assertLess(sell.trade.shares, 5_000)
        self.assertEqual(sell.cash_delta, sell.post_state.cash - sell.pre_state.cash)
        feedback = registry.fill_ledger[sell.fill_id]
        self.assertEqual(feedback.cash_debit, 0.0)
        self.assertEqual(feedback.fees, sell.trade.commission + sell.trade.stamp_tax
                         + sell.trade.transfer_fee)
        self.assertNotIn("partial-sell", sell.active_orders)
        terminal = next(item for item in bridge.updates if item.phase is ExecutionPhase.TERMINAL
                        and item.order_id == "partial-sell")
        self.assertEqual(terminal.order_status, "partial")
        next_day = next(item for item in bridge.updates if item.phase is ExecutionPhase.SNAPSHOT
                        and item.trading_date == days[23])
        self.assertNotIn("partial-sell", next_day.active_orders)
        self.assertEqual(sum(item.order_id == "partial-sell" for item in fills), 1)
        self.assertEqual(registry.positions["PART"], 5_000 - sell.trade.shares)
        self.assertEqual(registry.core_cash, result.account_snapshots[-1].cash)
        before_replay = registry.snapshot()
        for update in bridge.updates:
            self.assertFalse(bridge.consume(update))
        self.assertEqual(registry.snapshot(), before_replay)
        self.evidence["partial_sell"] = {
            "requested_shares": 5_000,
            "filled_shares": sell.trade.shares,
            "terminal_status": terminal.order_status,
            "next_day_active_order_ids": sorted(next_day.active_orders),
            "remaining_position": registry.positions["PART"],
            "cash_debit": feedback.cash_debit,
        }

    def test_real_runner_updates_registry_through_fill_ca_release_and_replay(self):
        days = build_market("AAA", start_date=date(2026, 2, 2), trading_days=7).trading_dates("AAA")
        market = SyntheticMarketProvider(
            bar for code in ("AAA", "BBB")
            for bar in build_market(
                code, start_date=days[0], trading_days=len(days), base_amount=100_000_000
            ).bars_for(code)
        )
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=list(days))
        registry.open_episode("episode-buy", "AAA", Policy.B1)
        registry.open_episode("episode-reject", "BBB", Policy.B1)
        bridge = _RecordingBridge(registry)
        actions = {
            days[2]: (RecordPosition("record-aaa", "div-aaa", "AAA", days[2]),),
            days[3]: (CreateCashReceivable(
                "receivable-aaa", "div-aaa", "AAA", "record-aaa", 0.025, days[3], days[4]
            ),),
            days[4]: (CashPayment("payment-aaa", "div-aaa", days[4]),),
        }
        strategy = _ScriptedOrders({
            days[0]: (
                OrderIntent("AAA", Side.BUY, shares=100, episode_id="episode-buy", order_id="buy-aaa"),
                OrderIntent("BBB", Side.BUY, shares=1_000_000, episode_id="episode-reject", order_id="reject-bbb"),
            ),
            days[2]: (
                OrderIntent("BBB", Side.SELL, shares=100, episode_id="episode-reject", order_id="sell-bbb-fail"),
                OrderIntent("AAA", Side.SELL, shares=100, episode_id="episode-buy", order_id="sell-aaa"),
            ),
            days[4]: (
                OrderIntent("AAA", Side.BUY, shares=50, episode_id="episode-buy-cycle2", order_id="buy-cycle2"),
            ),
            days[5]: (
                OrderIntent("AAA", Side.SELL, shares=50, episode_id="episode-buy-cycle2", order_id="sell-cycle2"),
            ),
        }, registry, days[2], days[4], days[5])
        result = run_account_backtest_from_orders(
            execution_calendar=days, signal_dates=(days[0], days[2], days[4], days[5]),
            strategy=strategy, market=market,
            execution_config=ExecutionConfig(final_liquidation="mark"),
            portfolio_config=PortfolioConfig(lot_size=1),
            cost_config=CostConfig(
                commission_rate_buy=0.0001, commission_rate_sell=0.0001,
                min_commission=5.0, stamp_tax_rate=0.001, transfer_fee_rate=0.001,
            ),
            account_actions_provider=lambda day: actions.get(day, ()),
            run_id="staged-observer-e2e", model_id="synthetic", initial_capital=100_000,
            observer=bridge,
        )
        updates = bridge.updates
        for item in updates:
            self.assertEqual(item.cash_delta, item.post_state.cash - item.pre_state.cash)
        submitted = [item for item in updates if item.phase is ExecutionPhase.SUBMITTED]
        first_batch = next(item for item in submitted if item.order_id == "buy-aaa")
        self.assertEqual(set(first_batch.active_orders), {"buy-aaa", "reject-bbb"})
        self.assertTrue(any(
            item.phase is ExecutionPhase.TERMINAL and item.order_id == "reject-bbb"
            and item.order_status == "rejected" for item in updates
        ))
        failed_sell = next(item for item in updates if item.phase is ExecutionPhase.TERMINAL
                           and item.order_id == "sell-bbb-fail")
        self.assertEqual(set(failed_sell.active_orders), {"sell-aaa"})
        fills = [item for item in updates if item.phase is ExecutionPhase.FILL]
        self.assertEqual({item.order_id for item in fills},
                         {"buy-aaa", "sell-aaa", "buy-cycle2", "sell-cycle2"})
        for item in fills:
            self.assertNotIn(item.order_id, item.active_orders)
            self.assertEqual(item.cash_delta, item.post_state.cash - item.pre_state.cash)
        first_buy = next(item for item in fills if item.order_id == "buy-aaa")
        self.assertIn("reject-bbb", first_buy.active_orders)
        self.assertTrue(any(item.post_state.cash_receivables for item in updates))
        self.assertTrue(any(item.post_state.pending_cash for item in updates))
        self.assertEqual(dict(registry.positions), {})
        self.assertEqual(registry.episodes["episode-buy"].status.value, "closed")
        self.assertEqual(registry.episodes["episode-reject"].status.value, "closed")
        self.assertEqual(registry.episodes["episode-buy-cycle2"].status.value, "closed")
        self.assertEqual(registry.snapshot().active_slots, 0)
        self.assertEqual(dict(registry.active_order_snapshots), {})
        self.assertEqual(registry.core_cash, result.account_snapshots[-1].cash)
        self.assertEqual(registry.available_cash, result.account_snapshots[-1].available_cash)
        payment = next(item for item in updates if item.trading_date == days[4]
                       and item.phase is ExecutionPhase.SNAPSHOT and item.post_state.pending_cash)
        released = next(item for item in updates if item.trading_date == days[5]
                        and item.phase is ExecutionPhase.SNAPSHOT)
        self.assertGreater(released.post_state.available_cash, payment.post_state.available_cash)
        self.assertFalse(released.post_state.pending_cash)
        for update in fills:
            trade = update.trade
            assert trade is not None
            assert trade.sequence_no is not None
            self.assertGreaterEqual(trade.sequence_no, 1)
            assert update.fill_id is not None
            feedback = registry.fill_ledger[update.fill_id]
            self.assertEqual(feedback.fees, trade.commission + trade.stamp_tax + trade.transfer_fee)
            self.assertEqual(feedback.cash_debit, update.pre_state.cash - update.post_state.cash
                             if trade.side is Side.BUY else 0)
            if trade.side is Side.BUY:
                self.assertEqual(trade.commission, 5.0)
                self.assertGreater(trade.transfer_fee, 0.0)
                self.assertLessEqual(abs(feedback.cash_debit - (trade.amount + feedback.fees)), 1e-8)
        sample_trade = fills[0].trade
        assert sample_trade is not None
        for invalid_sequence in (0, -1, 1.5, True):
            with self.assertRaisesRegex(ValueError, "sequence_no must be a positive int"):
                replace(sample_trade, sequence_no=invalid_sequence)
        before_replay = registry.snapshot()
        self.assertFalse(bridge.consume(fills[0]))
        for update in updates:
            self.assertFalse(bridge.consume(update))
        self.assertEqual(registry.snapshot(), before_replay)
        with self.assertRaisesRegex(AllocationError, "event_id"):
            bridge.consume(replace(fills[0], reason="different-payload"))
        missing_episode = replace(
            fills[0], event_id="manual-missing-episode", sequence_no=fills[0].sequence_no + 1,
            episode_id=None,
        )
        with self.assertRaisesRegex(AllocationError, "拒绝按代码猜测"):
            bridge.consume(missing_episode)
        self.assertEqual(registry.snapshot(), before_replay)
        snapshot_update = next(item for item in updates if item.phase is ExecutionPhase.SNAPSHOT)
        fractional_state = replace(
            snapshot_update.post_state,
            positions={"AAA": 1.5}, cost={"AAA": 10.0}, last_marks={"AAA": 10.0},
            locked={}, fractional=True,
        )
        fractional_update = replace(
            snapshot_update, event_id="fractional-shares", sequence_no=10_000,
            post_state=fractional_state,
            cash_delta=fractional_state.cash - snapshot_update.pre_state.cash,
        )
        with self.assertRaisesRegex(AllocationError, "不是非负整股数量"):
            bridge.consume(fractional_update)
        self.assertEqual(registry.snapshot(), before_replay)
        self.evidence = {
            "same_batch_active_order_ids": sorted(first_batch.active_orders),
            "fill_cash": [{
                "order_id": item.order_id,
                "pre_cash": item.pre_state.cash,
                "post_cash": item.post_state.cash,
                "cash_debit": registry.fill_ledger[item.fill_id].cash_debit,
                "amount": item.trade.amount,
                "commission": item.trade.commission,
                "stamp_tax": item.trade.stamp_tax,
                "transfer_fee": item.trade.transfer_fee,
                "slippage_cost": item.trade.slippage_cost,
                "cash_error": abs(
                    registry.fill_ledger[item.fill_id].cash_debit
                    - item.trade.amount - item.trade.commission
                    - item.trade.stamp_tax - item.trade.transfer_fee
                ) if item.trade.side is Side.BUY else 0.0,
            } for item in fills],
            "available_cash_release": {
                "before": payment.post_state.available_cash,
                "after": released.post_state.available_cash,
            },
            "ca_receivable_seen": any(item.post_state.cash_receivables for item in updates),
            "final_positions": dict(registry.positions),
            "final_active_order_ids": sorted(registry.active_order_snapshots),
        }
        self._assert_real_partial_sell_is_not_carried_to_next_day()
