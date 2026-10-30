"""raw 市场、公司行动账本、E signal 边界与 buffer 清算的合成端到端。"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import ExecutionMode, ReasonCode, Side
from backtest_core.contracts.order import OrderIntent, OrderStatus
from backtest_core.engine.account_runner import run_account_backtest_from_orders
from backtest_core.testing import build_market

from backtest.cnn_adapter.ca.corporate_actions import CorporateActionEvent, CorporateActionProvider
from backtest.cnn_adapter.ca.raw_market_provider import CnnRawMarketDataProvider
from backtest.cnn_adapter.execution_audit import ExitOnlyStrategy, audit_execution, build_terminal_plan
from backtest.cnn_adapter.order_strategy import CnnOrderStrategy
from backtest.cnn_adapter.predictions import CnnPredictionAdapter
from backtest.cnn_adapter.runner import run_cnn_backtest
from scripts.generate_walkforward_signals import _signal_record, prediction_cache_arrays


class _DateOrders:
    def __init__(self, orders: dict[date, tuple[OrderIntent, ...]]) -> None:
        self.orders = orders
        self.available_cash: dict[date, float] = {}

    def orders_for(self, *, trading_date, account, **kwargs):
        self.available_cash[trading_date] = account.available_cash
        return self.orders.get(trading_date, ())


class _MixedOrders:
    def __init__(self, fixed_orders, cnn_strategy, cnn_date):
        self.fixed_orders = fixed_orders
        self.cnn_strategy = cnn_strategy
        self.cnn_date = cnn_date

    def orders_for(self, *, trading_date, signal_time, account, market):
        if trading_date == self.cnn_date:
            return self.cnn_strategy.orders_for(
                trading_date=trading_date, signal_time=signal_time, account=account, market=market,
            )
        return self.fixed_orders.orders_for(trading_date=trading_date, account=account)


class CorporateActionRunnerE2ETest(unittest.TestCase):
    def test_cash_tax_stress_flows_through_runner_snapshot_and_provenance(self) -> None:
        calendar = tuple(build_market("A.SZ", start_date=date(2021, 5, 10), trading_days=11).trading_dates("A.SZ"))
        entry, record, ex_date, _, pay_date, e_date = calendar[1:7]
        action = CorporateActionEvent(
            event_id="cash-tax-stress", instrument_id="A.SZ", kind="cash_dividend",
            source_table="synthetic", source_row_id="tax-row", source_snapshot_hash="hash",
            source_version="fixture", record_date=record, ex_date=ex_date, pay_date=pay_date,
            gross_cash_per_share=0.18,
        )
        raw_path = self._write_raw(calendar)
        verified = {
            (code, day): {"market_state": "trading", "st_known": True, "reference_known": True,
                          "limit_known": True, "limit_up": False, "limit_down": False}
            for code in ("A.SZ", "B.SZ", "C.SZ") for day in calendar
        }
        cache = {"exp_ret": np.asarray([1.0, 1.0]), "true_ret": np.full(2, np.nan),
                 "dates": np.asarray([entry, e_date], dtype="datetime64[D]"),
                 "codes": np.asarray(["A.SZ", "A.SZ"])}
        outcome = run_cnn_backtest(
            pred_cache=cache, parquet_path=str(raw_path), dates=(entry, e_date), top_n=1,
            initial_capital=100_000.0, run_id="cash-tax-stress", corporate_action_provider=CorporateActionProvider((action,)),
            period_id="tax-fixture", execution_calendar=calendar, evaluation_end=e_date, raw_market_path=raw_path,
            verified_execution_states=verified, corporate_action_tax_policy="cash_dividend_20pct_stress",
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN, final_liquidation="mark"),
            commission_rate_buy=0.0, commission_rate_sell=0.0, min_commission=0.0,
            stamp_tax_rate=0.0, transfer_fee_rate=0.0,
        )
        ex = next(item for item in outcome.result.account_snapshots if item.date == ex_date)
        gross_receivable = cast(float, ex.gross_receivables_value)
        withholding_payable = cast(float, ex.withholding_payable_value)
        self.assertEqual(outcome.provenance["corporate_action_tax_policy"], "cash_dividend_20pct_stress")
        self.assertEqual(outcome.provenance["corporate_action_cash_tax_is_actual"], "false")
        self.assertAlmostEqual(ex.receivables_value, gross_receivable * 0.8)
        self.assertAlmostEqual(withholding_payable, gross_receivable * 0.2)
        self.assertEqual(ex.nav, ex.cash + ex.receivables_value + sum(
            float(position.market_value or 0.0) for position in ex.positions.values()
        ))
        pay_index = next(index for index, item in enumerate(outcome.result.account_snapshots)
                         if item.date == pay_date)
        paid, released = outcome.result.account_snapshots[pay_index:pay_index + 2]
        self.assertAlmostEqual(paid.cash - ex.cash, gross_receivable * 0.8)
        self.assertAlmostEqual(paid.gross_cash_dividends_paid, gross_receivable)
        self.assertAlmostEqual(paid.withheld_cash_dividends_paid, withholding_payable)
        self.assertAlmostEqual(paid.blocked_cash, gross_receivable * 0.8)
        self.assertAlmostEqual(cast(float, released.available_cash), cast(float, paid.cash))

    def test_cnn_runner_fails_closed_on_ex_date_without_raw_close(self) -> None:
        calendar = tuple(build_market("A.SZ", start_date=date(2021, 3, 15), trading_days=9).trading_dates("A.SZ"))
        entry, record, ex_date, _, e_date = calendar[1:6]
        action = CorporateActionEvent(
            event_id="missing-ex-close-cash", instrument_id="A.SZ", kind="cash_dividend",
            source_table="synthetic", source_row_id="missing-ex-row", source_snapshot_hash="sha256-test",
            source_version="fixture-v1", record_date=record, ex_date=ex_date,
            pay_date=calendar[6], gross_cash_per_share=0.18,
        )
        raw_path = self._write_raw(calendar, missing=frozenset({("A.SZ", ex_date)}))
        cache = {
            "exp_ret": np.asarray([1.0, 1.0]), "true_ret": np.full(2, np.nan),
            "dates": np.asarray([entry, e_date], dtype="datetime64[D]"),
            "codes": np.asarray(["A.SZ", "A.SZ"]),
        }
        verified = {
            ("A.SZ", day): {"market_state": "trading", "st_known": True,
                            "reference_known": True, "limit_known": True,
                            "limit_up": False, "limit_down": False}
            for day in calendar if day != ex_date
        }
        with self.assertRaisesRegex(
            ValueError,
            "event_id='missing-ex-close-cash'.*date=" + ex_date.isoformat()
            + ".*missing_or_nontrading_raw_close.*stale mark plus accrued entitlement",
        ):
            run_cnn_backtest(
                pred_cache=cache, parquet_path=str(raw_path), dates=(entry, e_date), top_n=1,
                initial_capital=100_000.0, run_id="missing-ex-close-e2e",
                commission_rate_buy=0.0, commission_rate_sell=0.0, min_commission=0.0,
                stamp_tax_rate=0.0, transfer_fee_rate=0.0,
                execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN, final_liquidation="mark"),
                execution_calendar=calendar, evaluation_end=e_date, raw_market_path=raw_path,
                corporate_action_provider=CorporateActionProvider((action,)), period_id="2021-H1",
                verified_execution_states=verified,
            )

    def test_cnn_runner_wires_raw_actions_and_terminal_period(self) -> None:
        calendar = tuple(build_market("A.SZ", start_date=date(2021, 3, 15), trading_days=11).trading_dates("A.SZ"))
        entry, record, ex_date, sell_signal, listing, pay_date, e_date = calendar[1:8]
        action = CorporateActionEvent(
            event_id="runner-cash-bonus", instrument_id="A.SZ", kind="capitalization",
            source_table="synthetic", source_row_id="runner-row", source_snapshot_hash="sha256-test",
            source_version="fixture-v1", record_date=record, ex_date=ex_date, pay_date=pay_date,
            listing_date=listing, gross_cash_per_share=0.18, share_ratio=0.8,
            ratio_denominator=10, rounding_rule="exact", reference_price=5.38,
            reference_source="synthetic-reference", reference_version="v1",
        )
        raw_path = self._write_raw(calendar)
        verified = {
            (code, day): {"market_state": "trading", "st_known": True, "reference_known": True,
                          "limit_known": True, "limit_up": False, "limit_down": False}
            for code in ("A.SZ", "B.SZ", "C.SZ") for day in calendar
        }
        verified[("B.SZ", listing)] = {
            "market_state": "unknown", "st_known": False, "reference_known": False,
            "limit_known": False,
        }
        signal_dates = np.asarray([entry, sell_signal, pay_date, e_date] * 3, dtype="datetime64[D]")
        codes = np.asarray(["A.SZ"] * 4 + ["B.SZ"] * 4 + ["C.SZ"] * 4)
        scores = np.asarray([1.0, 0.0, 0.0, 0.0,
                             0.0, 1.0, 0.0, 1.0,
                             0.0, 0.0, 1.0, 0.0])
        signals = pd.DataFrame([
            _signal_record(code, cast(pd.Timestamp, pd.Timestamp(str(day))), float(score), "ready", True)
            for code, day, score in zip(codes, signal_dates, scores)
        ])
        cache = prediction_cache_arrays(signals)
        cache["label_availability"] = signals["label_availability"].to_numpy(dtype=str)
        self.assertTrue(np.isnan(cache["true_ret"]).all())
        self.assertTrue((cache["label_availability"] == "not_loaded").all())
        c_pre_e = signals.loc[(signals["code"] == "C.SZ") & (signals["date"] == pd.Timestamp(pay_date))].iloc[0]
        self.assertEqual(c_pre_e["status"], "ready")
        self.assertTrue(bool(c_pre_e["buy_eligible"]) and np.isfinite(c_pre_e["exp_ret"]))
        outcome = run_cnn_backtest(
            pred_cache=cache, parquet_path=str(raw_path), dates=(entry, sell_signal, pay_date, e_date), top_n=1,
            initial_capital=100_000.0, run_id="cnn-runner-e2e", mode="rolling",
            commission_rate_buy=0.0, commission_rate_sell=0.0, min_commission=0.0,
            stamp_tax_rate=0.0, transfer_fee_rate=0.0,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN, final_liquidation="mark"),
            execution_calendar=calendar, evaluation_end=e_date, raw_market_path=raw_path,
            corporate_action_provider=CorporateActionProvider((action,)), period_id="2021-H1",
            verified_execution_states=verified,
        )
        self.assertEqual(outcome.evaluation_date, e_date)
        self.assertEqual(outcome.settlement_end, calendar[-1])
        self.assertIsNotNone(outcome.buffer_evaluation)
        self.assertEqual(outcome.provenance["label_availability"], "not_loaded")
        self.assertEqual(outcome.provenance["labeled_rows"], "0")
        self.assertEqual(outcome.provenance["quality_metrics_status"], "not_available")
        self.assertEqual(outcome.provenance["rank_ic"], "not_available")
        self.assertEqual(outcome.provenance["corporate_action_tax_policy"], "pretax")
        self.assertEqual(outcome.provenance["corporate_action_share_tax_status"], "unknown")
        self.assertTrue(any(item.date == e_date for item in outcome.result.account_snapshots))
        e_day_scores = {code: float(score) for code, score, day in zip(codes, cache["exp_ret"], signal_dates)
                        if pd.Timestamp(day).date() == e_date}
        self.assertEqual(max(e_day_scores, key=lambda code: e_day_scores[code]), "B.SZ")
        self.assertTrue(any(
            item.signal_date == e_date and item.execution_date == calendar[8]
            and item.order.instrument_id == "B.SZ" and item.order.side is Side.BUY
            and item.reason == "execution_after_evaluation_end"
            for item in outcome.suppressed_orders
        ), repr((outcome.suppressed_orders, outcome.result.order_results,
                 [(item.date, item.cash, list(item.positions)) for item in outcome.result.account_snapshots])))
        self.assertTrue(any(
            result.order.instrument_id == "B.SZ" and result.status is OrderStatus.REJECTED
            and result.reason == ReasonCode.MARKET_STATE_UNKNOWN.value
            for result in outcome.result.order_results
        ))
        self.assertTrue(any(
            result.order.instrument_id == "A.SZ" and result.order.side is Side.BUY
            and result.status is OrderStatus.FILLED
            for result in outcome.result.order_results
        ))
        self.assertTrue(any(
            trade.instrument_id == "C.SZ" and trade.side is Side.BUY
            and trade.execution_time.date() == e_date and trade.status.value == "filled"
            for trade in outcome.result.trades
        ), repr([(trade.instrument_id, trade.side, trade.execution_time, trade.status)
                 for trade in outcome.result.trades]))
        for snapshot in outcome.result.account_snapshots:
            raw_market_value = sum(float(position.market_value or 0.0)
                                   for position in snapshot.positions.values())
            unlisted_value = sum(float(item.market_value)
                                 for item in snapshot.unlisted_entitlements.values())
            liabilities = 0.0
            self.assertAlmostEqual(
                snapshot.cash + raw_market_value + snapshot.receivables_value + unlisted_value - liabilities,
                snapshot.nav,
                places=6,
                msg=f"snapshot NAV mismatch on {snapshot.date}",
            )
        self.assertFalse(any(
            trade.instrument_id == "B.SZ" and trade.side is Side.BUY
            and trade.execution_time.date() > e_date and trade.status == "filled"
            for trade in outcome.result.trades
        ))
        self.assertTrue(any(
            trade.instrument_id == "C.SZ" and trade.side is Side.SELL
            and trade.execution_time.date() > e_date and trade.status == "filled"
            for trade in outcome.result.trades
        ))

    def test_raw_cash_bonus_terminal_e2e_preserves_period_ledger(self) -> None:
        calendar = tuple(build_market("A.SZ", start_date=date(2021, 3, 15), trading_days=11).trading_dates("A.SZ"))
        anchor, entry, record, ex_date, sell_signal, listing, pay_date, e_date = calendar[:8]
        plan = build_terminal_plan(calendar, e_date, buffer_days=3)
        action = CorporateActionEvent(
            event_id="cash-bonus-e2e", instrument_id="A.SZ", kind="capitalization",
            source_table="synthetic", source_row_id="row-1", source_snapshot_hash="sha256-test",
            source_version="fixture-v1", record_date=record, ex_date=ex_date, pay_date=pay_date,
            listing_date=listing, gross_cash_per_share=0.18, share_ratio=0.8,
            ratio_denominator=10, rounding_rule="exact", reference_price=5.38,
            reference_source="synthetic-reference", reference_version="v1",
        )
        event_provider = CorporateActionProvider((action,))
        raw_path = self._write_raw(calendar)
        verified = {
            (code, day): {"market_state": "trading", "st_known": True, "reference_known": True,
                          "limit_known": True, "limit_up": False, "limit_down": False}
            for code in ("A.SZ", "B.SZ") for day in calendar
        }
        market = CnnRawMarketDataProvider(
            raw_path, signal_start=entry, signal_end=e_date, execution_end=plan.settlement_end,
            corporate_action_dates=frozenset({("A.SZ", ex_date)}), verified_states=verified,
        )
        e_buy = OrderIntent("B.SZ", Side.BUY, cash_amount=1_000.0)
        fixed = _DateOrders({
            entry: (OrderIntent("A.SZ", Side.BUY, shares=100),),
            sell_signal: (OrderIntent("A.SZ", Side.SELL, shares=100),),
        })
        predictions = CnnPredictionAdapter(
            {"exp_ret": np.asarray([-0.1, 0.5]), "true_ret": np.asarray([np.nan, np.nan]),
             "dates": np.asarray([e_date, e_date], dtype="datetime64[D]"),
             "codes": np.asarray(["A.SZ", "B.SZ"])},
            model_name="synthetic-cnn", checkpoint="synthetic-checkpoint", bins_version="synthetic",
            eval_script_version="synthetic",
        )
        cnn_strategy = CnnOrderStrategy(predictions, top_n=1)
        inner = _MixedOrders(fixed, cnn_strategy, e_date)
        strategy = ExitOnlyStrategy(inner, plan)
        def repeated_hook(day: date):
            operations = event_provider.account_operations_for_day(day, period_id="2021-H1")
            return operations + operations

        result = run_account_backtest_from_orders(
            execution_calendar=calendar, signal_dates=(entry, sell_signal, e_date),
            maintenance_dates=plan.buffer_dates, anchor_date=anchor, evaluation_end=e_date,
            account_actions_provider=repeated_hook, strategy=strategy, market=market,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN, final_liquidation="mark"),
            portfolio_config=PortfolioConfig(),
            cost_config=CostConfig(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0,
                                   transfer_fee_rate=0.0),
            run_id="corporate-action-e2e", model_id="synthetic", initial_capital=100_000.0,
        )
        record_snapshot, ex_snapshot = result.account_snapshots[2:4]
        self.assertEqual(record_snapshot.positions["A.SZ"].shares, 100)
        self.assertEqual(ex_snapshot.receivables_value, 18.0)
        self.assertEqual(sum(item.shares for item in ex_snapshot.unlisted_entitlements.values()), 80.0)
        self.assertEqual(result.account_snapshots[5].positions["A.SZ"].shares, 80)
        pay_eod, released = result.account_snapshots[6:8]
        self.assertEqual(pay_eod.blocked_cash, 18.0)
        self.assertEqual(released.blocked_cash, 0.0)
        self.assertEqual(pay_eod.cash, released.cash)
        self.assertEqual(pay_eod.nav, released.nav)
        self.assertEqual(strategy.suppressed_orders[0].order.instrument_id, e_buy.instrument_id)
        self.assertFalse(any(event.instrument_id == "B.SZ" for event in result.trades))
        self.assertTrue(any(event.instrument_id == "A.SZ" and event.side is Side.BUY
                            and event.execution_time.date() == record for event in result.trades))
        self.assertTrue(any(event.instrument_id == "A.SZ" and event.side is Side.SELL
                            and event.execution_time.date() == listing for event in result.trades))
        closes = {
            day: {"A.SZ": 10.0 if day < ex_date else 5.5, "B.SZ": 20.0}
            for day in calendar
        }
        report = audit_execution(result, plan, daily_closes=closes)
        self.assertTrue(report.cleared)
        self.assertEqual(report.residual_receivables, 0.0)
        self.assertEqual(result.account_snapshots[-1].positions, {})
        self.assertAlmostEqual(
            result.account_metrics["total_return"], result.account_snapshots[7].nav / 100_000.0 - 1.0,
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_raw(
        self, calendar: tuple[date, ...], *, missing: frozenset[tuple[str, date]] = frozenset(),
    ) -> Path:
        rows = []
        for code in ("A.SZ", "B.SZ", "C.SZ"):
            for index, day in enumerate(calendar):
                if (code, day) in missing:
                    continue
                price = (10.0 if index < 3 else 5.5) if code == "A.SZ" else 20.0
                rows.append({
                    "code": code, "kline_time": pd.Timestamp(day), "open": price,
                    "high": price * 1.02, "low": price * 0.98, "close": price,
                    "volume": 1_000_000, "amount": price * 10_000 * 100_000,
                })
        path = Path(self.temp.name) / "raw.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        return path
