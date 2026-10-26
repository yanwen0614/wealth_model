"""终端退出包装与严格账户审计的 CPU 合成闭环。"""

import unittest
from datetime import UTC, date, datetime, time
from types import SimpleNamespace

from backtest_core.contracts import EventStatus, OrderIntent, Side
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.testing import SyntheticMarketProvider, build_market, make_bar

from backtest.cnn_adapter.execution_audit import (
    ExitOnlyStrategy,
    audit_execution,
    build_terminal_plan,
    validate_terminal_execution,
)


class _Inner:
    def __init__(self, orders):
        self.orders = orders
        self.calls = 0

    def orders_for(self, **kwargs):
        self.calls += 1
        day = kwargs["trading_date"]
        return self.orders.get(day, ()) if isinstance(self.orders, dict) else self.orders


class ExecutionAuditTest(unittest.TestCase):
    def test_e_prediction_buy_is_suppressed_but_prior_signal_buy_executes_on_e(self):
        market = build_market("A.SZ", start_date=date(2026, 1, 5), trading_days=5, volatility=0.0)
        days = market.trading_dates("A.SZ")
        plan = build_terminal_plan(days, days[2], buffer_days=2)
        e_buy = OrderIntent("B.SZ", Side.BUY, cash_amount=1_000.0)
        inner = _Inner({days[1]: (OrderIntent("A.SZ", Side.BUY, cash_amount=1_000.0),), days[2]: (e_buy,)})
        strategy = ExitOnlyStrategy(inner, plan)
        market = SyntheticMarketProvider(
            make_bar(code, day, 10.0, open_=10.0) for code in ("A.SZ", "B.SZ") for day in days
        )
        result = run_account_backtest_from_orders(
            execution_calendar=days, signal_dates=days[1:3], maintenance_dates=plan.buffer_dates,
            anchor_date=days[0], evaluation_end=days[2], strategy=strategy, market=market,
            execution_config=ExecutionConfig(final_liquidation="mark"), portfolio_config=PortfolioConfig(),
            cost_config=CostConfig(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0,
                                   transfer_fee_rate=0.0), run_id="E-boundary", model_id="synthetic",
            initial_capital=100_000.0, signal_timezone=UTC,
        )
        prior_buy = next(event for event in result.trades if event.side is Side.BUY and event.instrument_id == "A.SZ")
        self.assertEqual(prior_buy.execution_time.date(), days[2])
        self.assertEqual(strategy.suppressed_orders[0].order, e_buy)
        self.assertFalse(any(event.instrument_id == "B.SZ" for event in result.trades))
        evaluation_nav = result.account_snapshots[2].nav
        self.assertAlmostEqual(result.account_metrics["total_return"], evaluation_nav / 100_000.0 - 1.0)

    def test_evaluation_day_signal_is_kept_but_buys_are_suppressed_and_holding_retried(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7),
                date(2026, 1, 8), date(2026, 1, 9))
        plan = build_terminal_plan(days, days[2], buffer_days=2)
        inner = _Inner((OrderIntent("A.SZ", Side.BUY, cash_amount=1000),))
        strategy = ExitOnlyStrategy(inner, plan)
        account = SimpleNamespace(positions={"LOCK.SZ": SimpleNamespace(shares=100)})
        market = SimpleNamespace()
        allowed = strategy.orders_for(trading_date=days[1],
                                      signal_time=datetime.combine(days[1], time(15), tzinfo=UTC),
                                      account=account, market=market)
        self.assertEqual(allowed, inner.orders)
        self.assertEqual(inner.calls, 1)
        self.assertEqual(strategy.suppressed_orders, ())
        exit_orders = strategy.orders_for(trading_date=days[2],
                                          signal_time=datetime.combine(days[2], time(15), tzinfo=UTC),
                                          account=account, market=market)
        self.assertEqual([(item.instrument_id, item.shares) for item in exit_orders], [("LOCK.SZ", 100)])
        self.assertEqual(inner.calls, 2)
        self.assertEqual(strategy.suppressed_orders[0].execution_date, days[3])
        self.assertEqual(strategy.suppressed_orders[0].reason, "execution_after_evaluation_end")
        retry = strategy.orders_for(trading_date=days[3],
                                    signal_time=datetime.combine(days[3], time(15), tzinfo=UTC),
                                    account=account, market=market)
        self.assertEqual([(item.instrument_id, item.shares) for item in retry], [("LOCK.SZ", 100)])
        self.assertEqual(inner.calls, 2)
        self.assertEqual(strategy.orders_for(
            trading_date=days[4], signal_time=datetime.combine(days[4], time(15), tzinfo=UTC),
            account=account, market=market,
        ), ())

    def test_plan_and_configuration_fail_closed(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
        plan = build_terminal_plan(days, days[2])
        self.assertEqual((plan.exit_signal_date, plan.evaluation_date, plan.buffer_dates),
                         (days[2], days[2], (days[3],)))
        validate_terminal_execution(ExecutionConfig(final_liquidation="mark"), PortfolioConfig())
        with self.assertRaises(ValueError):
            validate_terminal_execution(ExecutionConfig(final_liquidation="force"), PortfolioConfig())
        with self.assertRaises(ValueError):
            build_terminal_plan(days[:3], days[2])

    def test_nontrading_evaluation_end_keeps_last_signal_and_allows_buy_into_e(self):
        days = (date(2026, 1, 8), date(2026, 1, 9), date(2026, 1, 12), date(2026, 1, 13))
        plan = build_terminal_plan(days, date(2026, 1, 10))
        self.assertEqual((plan.exit_signal_date, plan.evaluation_date, plan.buffer_dates),
                         (days[1], days[1], (days[2],)))
        inner = _Inner((OrderIntent("A.SZ", Side.BUY, cash_amount=1000),))
        strategy = ExitOnlyStrategy(inner, plan)
        account = SimpleNamespace(positions={})
        orders = strategy.orders_for(
            trading_date=days[0], signal_time=datetime.combine(days[0], time(15), tzinfo=UTC),
            account=account, market=SimpleNamespace(),
        )
        self.assertEqual(orders, inner.orders)
        self.assertEqual(inner.calls, 1)
        final_signal_orders = strategy.orders_for(
            trading_date=days[1], signal_time=datetime.combine(days[1], time(15), tzinfo=UTC),
            account=account, market=SimpleNamespace(),
        )
        self.assertEqual(final_signal_orders, ())
        self.assertEqual(inner.calls, 2)
        self.assertEqual(strategy.suppressed_orders[0].execution_date, days[2])

    def test_audit_separates_evaluation_and_buffer_and_keeps_residual(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
        plan = build_terminal_plan(days, days[2])
        snapshots = tuple(SimpleNamespace(date=day, cash=100.0, available_cash=100.0,
                         receivables_value=0.0, unlisted_entitlements={},
                         positions={"A.SZ": SimpleNamespace(shares=10, market_value=100.0)},
                         nav=200.0) for day in days)
        result = SimpleNamespace(account_snapshots=snapshots, trades=(), order_results=())
        closes = {day: {"A.SZ": 10.0} for day in days}
        report = audit_execution(result, plan, daily_closes=closes)
        self.assertEqual(report.evaluation_mtm.date, days[2])
        self.assertEqual(report.post_buffer.date, days[3])
        self.assertFalse(report.cleared)
        self.assertEqual(report.residual_positions, {"A.SZ": (10, 100.0)})

    def test_audit_rejects_missing_same_day_close_and_bad_nav(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
        plan = build_terminal_plan(days, days[2])
        snapshots = tuple(SimpleNamespace(date=day, cash=100.0, available_cash=100.0,
                         receivables_value=0.0, unlisted_entitlements={},
                         positions={"A.SZ": SimpleNamespace(shares=10, market_value=100.0)},
                         nav=201.0 if day == days[0] else 200.0) for day in days)
        result = SimpleNamespace(account_snapshots=snapshots, trades=(), order_results=())
        with self.assertRaisesRegex(ValueError, "NAV"):
            audit_execution(result, plan, daily_closes={day: {"A.SZ": 10.0} for day in days})
        with self.assertRaisesRegex(ValueError, "same-day close"):
            audit_execution(result, plan, daily_closes={day: {} for day in days})

    def test_audit_includes_cash_receivables_in_nav(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
        plan = build_terminal_plan(days, days[2])
        snapshots = tuple(SimpleNamespace(
            date=day, cash=100.0, available_cash=80.0, receivables_value=20.0, unlisted_entitlements={},
            positions={"A.SZ": SimpleNamespace(shares=10, market_value=100.0)}, nav=220.0,
        ) for day in days)
        result = SimpleNamespace(account_snapshots=snapshots, trades=(), order_results=())
        closes = {day: {"A.SZ": 10.0} for day in days}
        report = audit_execution(result, plan, daily_closes=closes)
        self.assertEqual(report.evaluation_mtm.receivables_value, 20.0)
        self.assertEqual(report.evaluation_mtm.available_cash, 80.0)
        self.assertEqual(report.evaluation_mtm.blocked_cash, 20.0)
        self.assertEqual(report.evaluation_mtm.nav, 220.0)

    def test_core_runner_terminal_exit_and_audit_end_to_end(self):
        market = build_market("A.SZ", start_date=date(2026, 1, 5), trading_days=4,
                              volatility=0.0, base_amount=1_000_000.0)
        days = market.trading_dates("A.SZ")
        plan = build_terminal_plan(days, days[2])
        inner = _Inner((OrderIntent("A.SZ", Side.BUY, shares=100),))
        strategy = ExitOnlyStrategy(inner, plan)
        validate_terminal_execution(ExecutionConfig(final_liquidation="mark"), PortfolioConfig())
        result = run_account_backtest_from_orders(
            dates=days, strategy=strategy, market=market,
            execution_config=ExecutionConfig(final_liquidation="mark"),
            portfolio_config=PortfolioConfig(), cost_config=CostConfig(
                commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0,
                spread_floor=0.0002), run_id="terminal-synthetic", model_id="synthetic",
            initial_capital=100_000.0,
        )
        closes = {day: {"A.SZ": bar.close} for day, bar in zip(days, market.bars_for("A.SZ"))}
        report = audit_execution(result, plan, daily_closes=closes)
        self.assertEqual(report.evaluation_mtm.date, days[2])
        self.assertTrue(any(event.status is EventStatus.FILLED and event.side is Side.SELL
                            for event in result.trades))
        self.assertTrue(all(event.execution_time > event.signal_time for event in result.trades))

    def test_audit_rejects_buy_executed_after_exit_boundary(self):
        days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
        plan = build_terminal_plan(days, days[2])
        snapshots = tuple(SimpleNamespace(
            date=day, cash=100.0, available_cash=100.0, receivables_value=0.0,
            unlisted_entitlements={}, positions={}, nav=100.0,
        ) for day in days)
        event = SimpleNamespace(signal_time=datetime(2026, 1, 7, 15, tzinfo=UTC),
                                execution_time=datetime(2026, 1, 8, 9, tzinfo=UTC), instrument_id="A.SZ",
                                side=Side.BUY, status=EventStatus.FILLED)
        result = SimpleNamespace(account_snapshots=snapshots, trades=(event,), order_results=())
        closes = {day: {} for day in days}
        with self.assertRaisesRegex(ValueError, "BUY after exit-only"):
            audit_execution(result, plan, daily_closes=closes)


if __name__ == "__main__":
    unittest.main()
