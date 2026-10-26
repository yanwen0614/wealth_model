"""历史费用规则必须使用实际成交日，并交由 backtest-core 计算。"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from backtest_core.contracts.config import CostConfig, ExecutionConfig
from backtest_core.contracts.enums import EventStatus, Side

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.historical_costs import (
    calculate_historical_costs,
    resolve_historical_costs,
)
from backtest.cnn_adapter.runner import run_cnn_backtest


class HistoricalCostsTest(unittest.TestCase):
    def test_policy_breakpoints_and_commission_assumptions(self) -> None:
        base = CostConfig(commission_rate_buy=0.00025, commission_rate_sell=0.0003,
                          min_commission=5, stamp_tax_rate=0.9, transfer_fee_rate=0.9,
                          impact_coefficient=1.2)
        cases = ((date(2022, 4, 28), 0.00002), (date(2022, 4, 29), 0.00001))
        for day, transfer in cases:
            resolved = resolve_historical_costs(execution_date=day, market="SSE_A", commission=base)
            self.assertEqual(resolved.transfer_fee_rate, transfer)
            self.assertEqual(resolved.impact_coefficient, 1.2)
        # 手算：10万元卖出，卖佣万3=30元；stamp 断点前 0.001=100、2023-08-28 起 0.0005=50；
        # transfer 断点前 0.00002=2、2022-04-29 起 0.00001=1（均双边）
        old = calculate_historical_costs(execution_date=date(2022, 4, 28), market="SZSE_A",
                                         side=Side.SELL, amount=100_000, commission=base)
        mid = calculate_historical_costs(execution_date=date(2023, 8, 25), market="SZSE_A",
                                         side=Side.SELL, amount=100_000, commission=base)
        new = calculate_historical_costs(execution_date=date(2023, 8, 28), market="SZSE_A",
                                         side=Side.SELL, amount=100_000, commission=base)
        for got, want in zip(old, (30.0, 100.0, 2.0)):
            self.assertAlmostEqual(got, want, places=9)
        for got, want in zip(mid, (30.0, 100.0, 1.0)):
            self.assertAlmostEqual(got, want, places=9)
        for got, want in zip(new, (30.0, 50.0, 1.0)):
            self.assertAlmostEqual(got, want, places=9)

    def test_rejects_invalid_inputs(self) -> None:
        base = CostConfig()
        bad_dates = (datetime(2022, 4, 29), "2022-04-29", date(2020, 12, 31))  # noqa: DTZ001
        for bad in bad_dates:
            with self.assertRaises(ValueError):
                resolve_historical_costs(execution_date=bad, market="SSE_A", commission=base)
        for bad_market in ("BJ_A", "SSE_ETF", "", "sse_a"):
            with self.assertRaises(ValueError):
                resolve_historical_costs(execution_date=date(2022, 4, 29), market=bad_market, commission=base)
        with self.assertRaises(ValueError):
            resolve_historical_costs(execution_date=date(2022, 4, 29), market="SSE_A", commission=None)

    def test_buy_has_no_stamp_and_min_commission_applies(self) -> None:
        base = CostConfig(commission_rate_buy=0.00025, commission_rate_sell=0.0003,
                          min_commission=5, stamp_tax_rate=0.9, transfer_fee_rate=0.9)
        buy = calculate_historical_costs(execution_date=date(2023, 8, 28), market="SSE_A",
                                         side=Side.BUY, amount=10_000, commission=base)
        # 手算：买佣 max(10000×0.00025, 5)=5（最低佣金生效）；买方无印花税；过户费 0.1
        for got, want in zip(buy, (5.0, 0.0, 0.1)):
            self.assertAlmostEqual(got, want, places=9)
        small_sell = calculate_historical_costs(execution_date=date(2021, 6, 1), market="SZSE_A",
                                                side=Side.SELL, amount=5_000, commission=base)
        # 手算：卖佣 max(5000×0.0003, 5)=5；旧印花 0.001=5；旧过户 0.00002=0.1
        for got, want in zip(small_sell, (5.0, 5.0, 0.1)):
            self.assertAlmostEqual(got, want, places=9)

    def test_cnn_runner_charges_execution_day_costs_and_writes_synthetic_evidence(self) -> None:
        """cnn runner→core 订单→现金扣费：跨两个断点，最低佣金与净额均按手算核对。"""
        from backtest_core.contracts.config import CostConfig

        codes = ("000001.SZ", "000002.SZ", "600000.SH")
        signal_days = (date(2022, 4, 27), date(2022, 4, 28), date(2022, 4, 29),
                       date(2023, 8, 25), date(2023, 8, 28))
        history_days = []
        current = date(2022, 3, 1)
        while current < signal_days[0]:
            if current.weekday() < 5:
                history_days.append(current)
            current += timedelta(days=1)
        all_market_days = tuple(history_days) + signal_days
        rows = [{"code": code, "kline_time": pd.Timestamp(day), "open": 20.0, "high": 20.0,
                 "low": 20.0, "close": 20.0, "volume": 5_000_000.0,
                 "amount": 100_000_000.0, "is_trading": True}
                for code in codes for day in all_market_days]
        approved = Path("C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness")
        self.assertTrue(approved.is_dir())
        evidence_dir = Path(tempfile.mkdtemp(prefix="cnn_fee_e2e_", dir=approved))
        parquet = evidence_dir / "synthetic_market.parquet"
        cache_path = evidence_dir / "synthetic_predictions.npz"
        pd.DataFrame(rows).to_parquet(parquet, index=False)
        rankings = ((codes[0], codes[1]), (codes[0], codes[2]), (codes[1], codes[2]),
                    (codes[0], codes[2]), (codes[0], codes[2]))
        scores = {day: ranking for day, ranking in zip(signal_days, rankings)}
        exp = [0.06 if code == scores[day][0] else 0.04 if code == scores[day][1] else 0.01
               for day in signal_days for code in codes]
        true = [0.0] * len(exp)
        sample_dates = np.asarray([day.isoformat() for day in signal_days for _ in codes], dtype="datetime64[D]")
        sample_codes = np.asarray(codes * len(signal_days))
        save_prediction_cache(str(cache_path), np.asarray(exp), np.asarray(true), sample_dates, sample_codes)
        prediction_cache = load_prediction_cache(str(cache_path))
        base = CostConfig(commission_rate_buy=0.00025, commission_rate_sell=0.0003,
                          min_commission=5.0, impact_coefficient=1.0)
        market_by_code = {codes[0]: "SZSE_A", codes[1]: "SZSE_A", codes[2]: "SSE_A"}

        def resolver(execution_date: date, instrument_id: str) -> CostConfig:
            return resolve_historical_costs(execution_date=execution_date,
                                            market=market_by_code[instrument_id], commission=base)

        outcome = run_cnn_backtest(
            pred_cache=prediction_cache, parquet_path=str(parquet), dates=signal_days, top_n=2,
            initial_capital=22_000.0, mode="rolling", commission_rate_buy=0.00025,
            commission_rate_sell=0.0003, min_commission=5.0, cost_config_resolver=resolver,
            execution_config=ExecutionConfig(final_liquidation="mark"),
            run_id="synthetic-historical-cost-e2e", verify_account_metrics=True,
        )
        fills = [event for event in outcome.result.trades if event.status is EventStatus.FILLED]
        self.assertTrue(fills)
        self.assertTrue(all(event.execution_time > event.signal_time for event in fills))
        self.assertTrue(any(event.execution_time.date() == date(2022, 4, 28)
                            and event.transfer_fee == event.amount * 0.00002 for event in fills))
        old_stamp = [event for event in fills if event.side is Side.SELL
                     and event.execution_time.date() == date(2022, 4, 29)]
        new_stamp = [event for event in fills if event.side is Side.SELL
                     and event.execution_time.date() == date(2023, 8, 25)]
        self.assertTrue(old_stamp and new_stamp)
        for event in old_stamp:
            self.assertAlmostEqual(event.stamp_tax, event.amount * 0.001, places=8)
            self.assertEqual(event.commission, 5.0)
        for event in new_stamp:
            self.assertAlmostEqual(event.stamp_tax, event.amount * 0.001, places=8)
        self.assertTrue(any(event.side is Side.SELL and event.execution_time.date() == date(2023, 8, 28)
                            and abs(event.stamp_tax - event.amount * 0.0005) < 1e-8 for event in fills),
                        [(event.side.value, event.execution_time.date(), event.amount, event.stamp_tax)
                         for event in fills])
        self.assertTrue(any(event.side is Side.BUY and event.commission == 5.0 for event in fills))
        final = outcome.result.account_snapshots[-1]
        self.assertAlmostEqual(final.nav, final.cash + sum(
            item.market_value or 0.0 for item in final.positions.values()), places=6)
        self.assertAlmostEqual(final.cash, 11_908.23085, places=5)
        self.assertAlmostEqual(final.nav, 21_908.23085, places=5)
        records = {
            "accounts": [{"date": item.date.isoformat(), "cash": item.cash, "nav": item.nav}
                         for item in outcome.result.account_snapshots],
            "orders": [{"status": item.status.value, "filled_shares": item.filled_shares,
                        "reason": None if item.reason is None else item.reason.value}
                       for item in outcome.result.order_results],
            "trades": [{"instrument_id": item.instrument_id, "side": item.side.value,
                        "status": item.status.value, "shares": item.shares, "amount": item.amount,
                        "commission": item.commission, "stamp_tax": item.stamp_tax,
                        "transfer_fee": item.transfer_fee, "signal_time": item.signal_time.isoformat(),
                        "execution_time": item.execution_time.isoformat()}
                       for item in outcome.result.trades],
        }
        for name, content in records.items():
            with (evidence_dir / f"{name}.jsonl").open("x", encoding="utf-8") as stream:
                for record in content:
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        with (evidence_dir / "audit.jsonl").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps({"evaluation_mtm_date": final.date.isoformat(),
                                     "cash": final.cash, "nav": final.nav,
                                     "positions": {code: item.shares for code, item in final.positions.items()},
                                     "locked_events": sum(event.status.value == "locked"
                                                          for event in outcome.result.trades),
                                     "cleared": not bool(final.positions),
                                     "mark_mode_lock_evidence": "not_exposed_by_snapshot"},
                                    sort_keys=True) + "\n")


if __name__ == "__main__":
    unittest.main()
