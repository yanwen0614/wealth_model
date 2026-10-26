"""raw provider 与 core unknown-state 拒单边界。"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

import pandas as pd
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import ExecutionMode, ReasonCode, Side
from backtest_core.contracts.order import OrderIntent
from backtest_core.engine.account_runner import run_account_backtest_from_orders

from backtest.cnn_adapter.raw_market_inputs import read_raw_market_inputs
from backtest.cnn_adapter.raw_market_provider import CnnRawMarketDataProvider


class _Buy:
    def orders_for(self, **kwargs):
        return (OrderIntent("A.SZ", Side.BUY, cash_amount=1_000.0),)


class RawMarketProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "raw.parquet"
        days = [date(2021, 3, 15) + timedelta(days=index) for index in range(4)]
        pd.DataFrame({
            "code": ["A.SZ"] * 4, "kline_time": pd.to_datetime(days),
            "open": [10.0] * 4, "high": [10.5] * 4, "low": [9.5] * 4,
            "close": [10.0] * 4, "volume": [100_000] * 4, "amount": [1_000_000_000] * 4,
        }).to_parquet(self.path, index=False)
        self.days = days

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_raw_price_units_and_missing_execution_state_remain_unknown(self) -> None:
        provider = CnnRawMarketDataProvider(
            self.path, signal_start=self.days[0], signal_end=self.days[2], execution_end=self.days[3],
            corporate_action_dates=frozenset({("A.SZ", self.days[1])}),
        )
        bar = provider.get_bar("A.SZ", self.days[1])
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertEqual((bar.open, bar.close, bar.volume, bar.amount), (10.0, 10.0, 1000, 10_000.0))
        self.assertFalse(bar.market_state_known)
        self.assertFalse(bar.st_state_known)
        self.assertFalse(bar.limit_state_known)
        self.assertTrue(bar.corporate_action_reference_required)

    def test_verified_execution_metadata_is_explicit_opt_in(self) -> None:
        key = ("A.SZ", self.days[1])
        provider = CnnRawMarketDataProvider(
            self.path, signal_start=self.days[0], signal_end=self.days[2], execution_end=self.days[3],
            verified_states={key: {
                "market_state": "trading", "st_known": True, "reference_known": True,
                "limit_known": True, "limit_up": False, "limit_down": False,
            }},
        )
        bar = provider.get_bar(*key)
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertTrue(bar.market_state_known and bar.st_state_known and bar.limit_state_known)
        self.assertTrue(bar.is_trading)

    def test_directory_resolves_only_the_requested_code_file(self) -> None:
        directory = Path(self.temp.name) / "per_code"
        directory.mkdir()
        target = directory / "A.SZ.parquet"
        copyfile(self.path, target)
        other = pd.read_parquet(self.path)
        other["code"] = "B.SZ"
        other.to_parquet(directory / "B.SZ.parquet", index=False)
        provider = CnnRawMarketDataProvider(
            directory, signal_start=self.days[0], signal_end=self.days[2], execution_end=self.days[3],
        )
        with patch(
            "backtest.cnn_adapter.raw_market_provider.read_raw_market_inputs",
            wraps=read_raw_market_inputs,
        ) as reader:
            self.assertIsNotNone(provider.get_bar("A.SZ", self.days[1]))
        reader.assert_called_once()
        self.assertEqual(Path(reader.call_args.args[0]), target)

    def test_directory_missing_code_fails_explicitly(self) -> None:
        directory = Path(self.temp.name) / "per_code"
        directory.mkdir()
        copyfile(self.path, directory / "A.SZ.parquet")
        provider = CnnRawMarketDataProvider(
            directory, signal_start=self.days[0], signal_end=self.days[2], execution_end=self.days[3],
        )
        with self.assertRaisesRegex(FileNotFoundError, "C.SZ"):
            provider.get_bar("C.SZ", self.days[1])

    def test_unknown_source_status_is_rejected_by_account_runner(self) -> None:
        provider = CnnRawMarketDataProvider(
            self.path, signal_start=self.days[0], signal_end=self.days[0], execution_end=self.days[1],
        )
        result = run_account_backtest_from_orders(
            execution_calendar=self.days[:2], signal_dates=self.days[:1], strategy=_Buy(), market=provider,
            execution_config=ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN),
            portfolio_config=PortfolioConfig(), cost_config=CostConfig(), run_id="unknown-source",
            model_id="synthetic", initial_capital=10_000.0,
        )
        self.assertEqual(result.order_results[0].reason, ReasonCode.MARKET_STATE_UNKNOWN)
        self.assertFalse(any(event.status.value == "filled" for event in result.trades))
