"""StagedOrderStrategy 的 RED/GREEN 合成契约测试。"""

import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

from backtest_core.contracts import (
    CostConfig,
    ExecutionConfig,
    ExecutionMode,
    ExecutionPhase,
    MarketBar,
    PortfolioConfig,
    Side,
)
from backtest_core.contracts.protocols import AccountView
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.testing import SyntheticMarketProvider

from backtest.cnn_adapter.quantity_rules import MappingQuantityRuleResolver, QuantityRule
from backtest.cnn_adapter.staged_allocation import (
    AllocationRegistry,
    CoreAccountSnapshot,
    EpisodeStatus,
    Policy,
    TrancheStatus,
)
from backtest.cnn_adapter.staged_execution_bridge import StagedExecutionBridge
from backtest.cnn_adapter.staged_order_strategy import (
    MappingRankingSource,
    RankingError,
    RankingSnapshot,
    StagedOrderStrategy,
)


class _Market:
    def __init__(self, bars):
        self.bars = bars

    def get_bars(self, instrument_ids, start, end, interval="1d"):
        codes = (instrument_ids,) if isinstance(instrument_ids, str) else instrument_ids
        return {code: tuple(bar for bar in self.bars.get(code, ())
                            if start <= bar.trading_date <= end) for code in codes}


def _account_view(available_cash: float, positions=None, locked=None) -> AccountView:
    return cast(AccountView, SimpleNamespace(
        cash=available_cash, available_cash=available_cash, positions=positions or {},
        locked=locked or {}, nav=available_cash,
    ))


def _tranche_id(order) -> str:
    assert order.order_id is not None
    return order.order_id.split(":")[-2]


def _ranked_day(day, source, code_rank, buy_eligible=True):
    ranks = {"AAA": code_rank}
    current = 1
    for index in range(1, 12):
        if current == code_rank:
            current += 1
        ranks[f"OTHER{index:02d}"] = current
        current += 1
    eligibility = {code: code == "AAA" and buy_eligible for code in ranks}
    return RankingSnapshot(day, source, ranks, True, eligibility)


class _RecordingBridge(StagedExecutionBridge):
    def __init__(self, registry):
        super().__init__(registry)
        self.updates = []

    def on_update(self, update):
        self.updates.append(update)
        super().on_update(update)


class StagedOrderStrategyTests(unittest.TestCase):
    def test_explicit_science_board_rule_rejects_100_and_accepts_200_or_300(self):
        day, next_day = date(2020, 1, 2), date(2020, 1, 3)
        rule = QuantityRule(200, 1, 100_000, "SSE-2019-23-20",
                            date(2019, 3, 1), date(2023, 2, 16))
        resolver = MappingQuantityRuleResolver({
            "688": (date(2019, 3, 1), date(2023, 2, 16), rule),
        })
        for initial_cash, expected in ((6_000, None), (12_000, 200), (18_000, 300)):
            with self.subTest(expected=expected):
                registry = AllocationRegistry(initial_cash=initial_cash, calendar_days=[day, next_day])
                registry.apply_core_snapshot(CoreAccountSnapshot(
                    "quantity-open", 1, initial_cash, {}, frozenset(), frozenset(),
                    cash=initial_cash, trading_date=day,
                ))
                ranks = RankingSnapshot(day, "quantity-ranks", {"688001.SH": 1}, True,
                                        {"688001.SH": True})
                strategy = StagedOrderStrategy(
                    registry, MappingRankingSource({day: ranks}), policy=Policy.B1,
                    execution_calendar=[day, next_day], worst_case_cost_config=CostConfig(),
                    tick_size=0.01, quantity_rule_resolver=resolver,
                )
                bar = MarketBar("688001.SH", day, 10, 10, 10, 10, 1000, 10000,
                                True, False, False)
                orders = strategy.orders_for(
                    trading_date=day, signal_time=strategy.signal_time_for(day),
                    account=_account_view(initial_cash), market=_Market({"688001.SH": (bar,)}),
                )
                if expected is None:
                    self.assertEqual(orders, ())
                    tranche = next(iter(registry.tranches.values()))
                    self.assertIs(tranche.status, TrancheStatus.REJECTED)
                    self.assertIsNone(tranche.order_id)
                    self.assertEqual(tranche.requested_shares, 0)
                    self.assertEqual(next(iter(registry.episodes.values())).commitment, 1200)
                else:
                    self.assertEqual(orders[0].shares, expected)

    def test_placeholder_source_ids_fail_at_snapshot_creation_without_registry_pollution(self):
        day = date(2026, 1, 5)
        invalid_source_ids = (
            "", "   ", "\t\n", "unknown", "UNKNOWN", " Unknown ", "unknown\n",
            "N/A", " null ", "PLACEHOLDER", "tBd", "<Unknown>", "not available",
        )
        for source_id in invalid_source_ids:
            with self.subTest(source_id=source_id):
                next_day = date(2026, 1, 6)
                registry = AllocationRegistry(initial_cash=100_000, calendar_days=[day, next_day])
                registry.apply_core_snapshot(CoreAccountSnapshot(
                    "source-test-open", 1, 100_000, {}, frozenset(), frozenset(),
                    cash=100_000, trading_date=day,
                ))
                before = registry.snapshot()
                orders = ()
                rejected_at_creation = False
                try:
                    snapshot = RankingSnapshot(
                        day, source_id, {"AAA": 1}, True, {"AAA": True},
                    )
                except RankingError:
                    rejected_at_creation = True
                else:
                    source = MappingRankingSource({day: snapshot})
                    strategy = StagedOrderStrategy(
                        registry, source, policy=Policy.B1,
                        execution_calendar=[day, next_day],
                        worst_case_cost_config=CostConfig(), tick_size=0.01,
                    )
                    orders = strategy.orders_for(
                        trading_date=day, signal_time=strategy.signal_time_for(day),
                        account=_account_view(100_000),
                        market=_Market({"AAA": (MarketBar(
                            "AAA", day, 10, 10, 10, 10, 1000, 10000, True, False, False,
                        ),)}),
                    )
                self.assertTrue(rejected_at_creation)
                self.assertEqual(orders, ())
                self.assertEqual(dict(registry.episodes), {})
                self.assertEqual(dict(registry.tranches), {})
                self.assertEqual(registry.snapshot(), before)

    def test_full_rank_is_score_descending_code_ascending_independent_of_buy_gate(self):
        day = date(2026, 1, 5)
        snapshot = RankingSnapshot.from_scores(day, "signal-v1", [
            {"instrument_id": "ZZZ", "status": "ready", "exp_ret": 0.2, "buy_eligible": False},
            {"instrument_id": "BBB", "status": "ready", "exp_ret": 0.1, "buy_eligible": True},
            {"instrument_id": "AAA", "status": "ready", "exp_ret": 0.1, "buy_eligible": True},
            {"instrument_id": "BAD", "status": "ready", "exp_ret": float("nan"), "buy_eligible": True},
            {"instrument_id": "OLD", "status": "missing", "exp_ret": 9.0, "buy_eligible": True},
        ], complete=True)
        self.assertEqual(dict(snapshot.ranks), {"ZZZ": 1, "AAA": 2, "BBB": 3})
        self.assertFalse(snapshot.buy_eligible["ZZZ"])

    def test_buy_gate_does_not_remove_ranked_code_before_candidate_ordering(self):
        day, next_day = date(2026, 1, 5), date(2026, 1, 6)
        snapshot = RankingSnapshot.from_scores(day, "signal-v1", [
            {"instrument_id": "ZZZ", "status": "ready", "exp_ret": 0.2, "buy_eligible": False},
            {"instrument_id": "AAA", "status": "ready", "exp_ret": 0.1, "buy_eligible": True},
        ], complete=True)
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=[day, next_day])
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "open-1", 1, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=day,
        ))
        bars = {code: (MarketBar(code, day, 10, 10, 10, 10, 1000, 10000, True, False, False,
                                 absolute_limit_up_price=11, absolute_limit_down_price=9),)
                for code in ("AAA", "ZZZ")}
        strategy = StagedOrderStrategy(registry, MappingRankingSource({day: snapshot}),
                                       policy=Policy.B1, execution_calendar=[day, next_day],
                                       worst_case_cost_config=CostConfig(), tick_size=0.01)
        orders = strategy.orders_for(
            trading_date=day, signal_time=datetime(2026, 1, 5, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            account=_account_view(100_000), market=_Market(bars),
        )
        self.assertEqual([order.instrument_id for order in orders], ["AAA"])

    def test_b1_uses_raw_close_inward_limit_fixed_lots_and_worst_case_fees(self):
        day = date(2026, 1, 5)
        ranks = RankingSnapshot(day, "fixture-ranks-v1", {"AAA": 1}, complete=True,
                                buy_eligible={"AAA": True})
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=[day, date(2026, 1, 6)])
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "open-1", 1, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=day,
        ))
        strategy = StagedOrderStrategy(
            registry, MappingRankingSource({day: ranks}), policy=Policy.B1,
            execution_calendar=[day, date(2026, 1, 6)],
            worst_case_cost_config=CostConfig(), tick_size=0.01, lot_size=100,
        )
        bar = MarketBar("AAA", day, 10, 10, 10, 10, 1_000, 10_000, True, False, False,
                        absolute_limit_up_price=10, absolute_limit_down_price=9)
        account = _account_view(100_000)
        orders = strategy.orders_for(
            trading_date=day, signal_time=datetime(2026, 1, 5, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
            account=account, market=_Market({"AAA": (bar,)}),
        )
        self.assertEqual(len(orders), 1)
        self.assertIs(orders[0].side, Side.BUY)
        self.assertIsNone(orders[0].cash_amount)
        self.assertEqual(orders[0].limit_price, 10.45)
        assert orders[0].shares is not None
        self.assertEqual(orders[0].shares % 100, 0)
        episode_id = orders[0].episode_id
        assert episode_id is not None
        tranche = registry.tranches[(episode_id, "t0")]
        self.assertEqual(tranche.limit_price, orders[0].limit_price)
        self.assertEqual(tranche.requested_shares, orders[0].shares)

    def test_fee_resolver_uses_execution_date_costs_for_fixed_share_budget(self):
        day, execution_day = date(2026, 1, 5), date(2026, 1, 6)
        snapshot = RankingSnapshot(day, "r", {"AAA": 1}, True, {"AAA": True})
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=[day, execution_day])
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "open", 1, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=day,
        ))
        resolved = []

        def resolver(cost_day, code):
            resolved.append((cost_day, code))
            return CostConfig(min_commission=200)

        strategy = StagedOrderStrategy(
            registry, MappingRankingSource({day: snapshot}), policy=Policy.B1,
            execution_calendar=[day, execution_day], worst_case_cost_config=CostConfig(),
            cost_config_resolver=resolver, tick_size=0.01,
        )
        bar = MarketBar("AAA", day, 10, 10, 10, 10, 1000, 10000, True, False, False)
        order = strategy.orders_for(
            trading_date=day, signal_time=strategy.signal_time_for(day),
            account=_account_view(100_000),
            market=_Market({"AAA": (bar,)}),
        )[0]
        self.assertEqual(resolved, [(execution_day, "AAA")])
        self.assertEqual(order.shares, 1800)

    def test_s1_tranche_clock_does_not_shift_after_t0_rejection(self):
        days = [date(2026, 1, 5) + timedelta(days=index) for index in range(8)]
        snapshots = {day: RankingSnapshot(day, f"r{index}", {"AAA": 1}, True, {"AAA": True})
                     for index, day in enumerate(days)}
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "snap-0", 1, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=days[0],
        ))
        strategy = StagedOrderStrategy(registry, MappingRankingSource(snapshots), policy=Policy.S1,
                                       execution_calendar=days, worst_case_cost_config=CostConfig(),
                                       tick_size=0.01)
        market = _Market({"AAA": tuple(MarketBar("AAA", day, 10, 10, 10, 10, 1000, 10000,
                                                 True, False, False, absolute_limit_up_price=11,
                                                 absolute_limit_down_price=9) for day in days)})
        account = _account_view(100_000)
        first = strategy.orders_for(trading_date=days[0], signal_time=strategy.signal_time_for(days[0]),
                                    account=account, market=market)
        assert first[0].order_id is not None and first[0].episode_id is not None
        self.assertIn("t0", first[0].order_id)
        registry.apply_order_update(first[0].order_id, first[0].episode_id, "submitted", None)
        registry.apply_order_update(first[0].order_id, first[0].episode_id, "terminal", "rejected")
        later_orders = {}
        for index in range(1, 7):
            registry.apply_core_snapshot(CoreAccountSnapshot(
                f"snap-{index}", index + 1, 100_000, {}, frozenset(), frozenset(),
                cash=100_000, trading_date=days[index],
            ))
            later_orders[index] = strategy.orders_for(
                trading_date=days[index], signal_time=strategy.signal_time_for(days[index]),
                account=account, market=market,
            )
        self.assertEqual([_tranche_id(order) for order in later_orders[3]], ["t3"])
        self.assertEqual([_tranche_id(order) for order in later_orders[6]], ["t6"])

    def test_s2_checks_t3_inclusive_then_t3_exclusive_and_keeps_ineligible_day_rank(self):
        days = [date(2026, 2, 2) + timedelta(days=index) for index in range(8)]
        ranks = [1, 2, 6, 4, 1, 5, 3, 3]
        snapshots = {
            day: _ranked_day(day, f"s{index}", rank, index != 5)
            for index, (day, rank) in enumerate(zip(days, ranks))
        }
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        strategy = StagedOrderStrategy(registry, MappingRankingSource(snapshots), policy=Policy.S2,
                                       execution_calendar=days, worst_case_cost_config=CostConfig(),
                                       tick_size=0.01)
        account = _account_view(100_000)
        market = _Market({"AAA": tuple(MarketBar("AAA", day, 10, 10, 10, 10, 1000, 10000,
                                                 True, False, False, absolute_limit_up_price=11,
                                                 absolute_limit_down_price=9) for day in days)})
        for index, day in enumerate(days[:7]):
            registry.apply_core_snapshot(CoreAccountSnapshot(
                f"snap-{index}", index + 1, 100_000, {}, frozenset(), frozenset(),
                cash=100_000, trading_date=day,
            ))
            orders = strategy.orders_for(trading_date=day, signal_time=strategy.signal_time_for(day),
                                         account=account, market=market)
            if index == 3:
                self.assertEqual(orders, ())
            if index == 6:
                self.assertEqual([_tranche_id(order) for order in orders], ["t6"])
        episode = next(iter(registry.episodes.values()))
        self.assertIs(registry.tranches[(episode.episode_id, "t3")].status, TrancheStatus.INELIGIBLE)
        self.assertIs(registry.tranches[(episode.episode_id, "t6")].status, TrancheStatus.SCHEDULED)

    def test_final_signal_day_sells_top_five_holding_for_first_buffer_open(self):
        days = [date(2026, 3, 2) + timedelta(days=index) for index in range(4)]
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        episode = registry.open_episode("held-cycle", "AAA", Policy.B1)
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "held-d2", 1, 90_000, {"AAA": 100}, frozenset(), frozenset(),
            cash=90_000, trading_date=days[2],
        ))
        strategy = StagedOrderStrategy(
            registry, MappingRankingSource({days[2]: _ranked_day(days[2], "rank-d2", 1)}),
            policy=Policy.B1, execution_calendar=days, worst_case_cost_config=CostConfig(),
            tick_size=0.01, buffer_start_date=days[3],
        )
        bar = MarketBar("AAA", days[2], 10, 10, 10, 10, 1000, 10000, True, False, False)
        orders = strategy.orders_for(
            trading_date=days[2], signal_time=strategy.signal_time_for(days[2]),
            account=_account_view(90_000, {"AAA": SimpleNamespace(shares=100)}),
            market=_Market({"AAA": (bar,)}),
        )
        self.assertEqual(len(orders), 1)
        self.assertIs(orders[0].side, Side.SELL)
        self.assertEqual(orders[0].shares, 100)
        self.assertEqual(orders[0].limit_price, 9.55)
        self.assertEqual(orders[0].episode_id, episode.episode_id)
        assert orders[0].order_id is not None
        self.assertIn(episode.episode_id, orders[0].order_id)
        self.assertEqual(strategy.position_usage.positive_position_codes, frozenset({"AAA"}))
        self.assertEqual(strategy.position_usage.occupied_codes, frozenset({"AAA"}))

    def test_rejected_t0_future_cycle_does_not_block_other_ranked_code(self):
        days = [date(2026, 3, 2) + timedelta(days=index) for index in range(4)]
        first = RankingSnapshot(days[0], "d0", {"AAA": 1, "BBB": 2}, True,
                                {"AAA": True, "BBB": False})
        second = RankingSnapshot(days[1], "d1", {"AAA": 1, "BBB": 2}, True,
                                 {"AAA": True, "BBB": True})
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "s0", 1, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=days[0],
        ))
        strategy = StagedOrderStrategy(
            registry, MappingRankingSource({days[0]: first, days[1]: second}),
            policy=Policy.S1, execution_calendar=days, worst_case_cost_config=CostConfig(),
            tick_size=0.01,
        )
        bars = _Market({code: tuple(MarketBar(code, day, 10, 10, 10, 10, 1000, 10000,
                                              True, False, False, absolute_limit_up_price=11,
                                              absolute_limit_down_price=9) for day in days)
                        for code in ("AAA", "BBB")})
        account = _account_view(100_000)
        first_order = strategy.orders_for(
            trading_date=days[0], signal_time=strategy.signal_time_for(days[0]),
            account=account, market=bars,
        )[0]
        assert first_order.order_id is not None and first_order.episode_id is not None
        registry.apply_order_update(first_order.order_id, first_order.episode_id, "submitted", None)
        registry.apply_order_update(first_order.order_id, first_order.episode_id, "terminal", "rejected")
        registry.apply_core_snapshot(CoreAccountSnapshot(
            "s1", 2, 100_000, {}, frozenset(), frozenset(), cash=100_000, trading_date=days[1],
        ))
        next_orders = strategy.orders_for(
            trading_date=days[1], signal_time=strategy.signal_time_for(days[1]),
            account=account, market=bars,
        )
        self.assertEqual([order.instrument_id for order in next_orders], ["BBB"])
        self.assertEqual({episode.code for episode in registry.episodes.values()}, {"AAA", "BBB"})

    def test_real_runner_executes_buy_then_final_signal_day_sell_with_observer_identity(self):
        days = [date(2026, 4, 6) + timedelta(days=index) for index in range(4)]
        cost = CostConfig()
        market = SyntheticMarketProvider(
            MarketBar("AAA", day, 10, 10.5, 9.5, 10, 100_000, 1_000_000, True, False, False,
                      absolute_limit_up_price=11, absolute_limit_down_price=9)
            for day in days
        )
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        ranks = {day: _ranked_day(day, f"ranking-{index}", 1) for index, day in enumerate(days)}
        strategy = StagedOrderStrategy(
            registry, MappingRankingSource(ranks), policy=Policy.B1, execution_calendar=days,
            worst_case_cost_config=cost, tick_size=0.01, buffer_start_date=days[3],
        )
        bridge = _RecordingBridge(registry)
        result = run_account_backtest_from_orders(
            execution_calendar=days, signal_dates=days, strategy=strategy, market=market,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN,
                                             final_liquidation="mark", initial_capital=100_000),
            portfolio_config=PortfolioConfig(lot_size=100), cost_config=cost,
            run_id="staged-strategy-e2e", model_id="synthetic", initial_capital=100_000,
            signal_timezone=ZoneInfo("Asia/Shanghai"), observer=bridge,
        )
        buys = [item for item in bridge.updates if item.phase is ExecutionPhase.FILL
                and item.trade is not None and item.trade.side is Side.BUY]
        sells = [item for item in bridge.updates if item.phase is ExecutionPhase.FILL
                 and item.trade is not None and item.trade.side is Side.SELL]
        self.assertEqual(len(buys), 1)
        self.assertEqual(len(sells), 1)
        self.assertEqual(buys[0].episode_id, sells[0].episode_id)
        assert sells[0].order_id is not None
        self.assertIn(":exit:", sells[0].order_id)
        self.assertIs(registry.episodes[buys[0].episode_id].status, EpisodeStatus.CLOSED)
        self.assertEqual(registry.snapshot().active_slots, 0)
        self.assertTrue(result.order_results)

    def test_buffer_maintenance_runs_without_rankings_retries_sells_and_reports_residual(self):
        days = [date(2026, 5, 4) + timedelta(days=index) for index in range(7)]
        cost = CostConfig()
        market = SyntheticMarketProvider(
            MarketBar("AAA", day, 10 if index < 3 else 9, 10, 8.5, 10, 100_000, 1_000_000,
                      True, False, False, absolute_limit_up_price=11, absolute_limit_down_price=8)
            for index, day in enumerate(days)
        )
        registry = AllocationRegistry(initial_cash=100_000, calendar_days=days)
        decision_ranks = {day: _ranked_day(day, f"decision-{i}", 1) for i, day in enumerate(days[:3])}
        source = MappingRankingSource(decision_ranks)
        strategy = StagedOrderStrategy(
            registry, source, policy=Policy.B1, execution_calendar=days,
            worst_case_cost_config=cost, tick_size=0.01, buffer_start_date=days[3],
        )
        bridge = _RecordingBridge(registry)
        result = run_account_backtest_from_orders(
            execution_calendar=days, signal_dates=days[:6], strategy=strategy, market=market,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN,
                                             final_liquidation="mark", initial_capital=100_000),
            portfolio_config=PortfolioConfig(lot_size=100), cost_config=cost,
            run_id="staged-buffer-no-ranks", model_id="synthetic", initial_capital=100_000,
            signal_timezone=ZoneInfo("Asia/Shanghai"), observer=bridge,
        )
        sell_terminals = [item for item in bridge.updates
                          if item.phase is ExecutionPhase.TERMINAL and item.order_id is not None
                          and ":exit:" in item.order_id]
        self.assertEqual(len(sell_terminals), 4)
        self.assertEqual([item.trading_date for item in sell_terminals], days[3:7])
        self.assertTrue(all(item.order_status == "rejected" for item in sell_terminals))
        assert sell_terminals[0].order_id is not None
        self.assertTrue(sell_terminals[0].order_id.endswith(days[2].isoformat()))
        self.assertEqual(len({item.order_id for item in sell_terminals}), 4)
        self.assertEqual(set(source._snapshots), set(days[:3]))
        self.assertGreater(registry.positions.get("AAA", 0), 0)
        self.assertIn("AAA", strategy.position_usage.positive_position_codes)
        self.assertEqual(registry.snapshot().active_slots, 1)
        self.assertTrue(result.order_results)
