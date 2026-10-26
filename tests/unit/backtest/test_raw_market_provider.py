"""raw provider 与 core unknown-state 拒单边界。"""

import tempfile
import unittest
from collections.abc import Mapping
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


class RawMarketProviderAbsoluteLimitTest(unittest.TestCase):
    """absolute_limit_up_price / absolute_limit_down_price 直接字段透传。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "raw.parquet"
        self.days = [date(2021, 3, 15) + timedelta(days=index) for index in range(4)]
        pd.DataFrame({
            "code": ["A.SZ"] * 4, "kline_time": pd.to_datetime(self.days),
            "open": [10.0] * 4, "high": [10.5] * 4, "low": [9.5] * 4,
            "close": [10.0] * 4, "volume": [100_000] * 4, "amount": [1_000_000_000] * 4,
        }).to_parquet(self.path, index=False)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _provider(self, state: Mapping[str, object] | None = None) -> CnnRawMarketDataProvider:
        key: tuple[str, date] = ("A.SZ", self.days[1])
        states: Mapping[tuple[str, date], Mapping[str, object]] = {}
        if state is not None:
            states = {key: state}
        return CnnRawMarketDataProvider(
            self.path, signal_start=self.days[0], signal_end=self.days[2],
            execution_end=self.days[3], verified_states=states,
        )

    def test_absent_keys_yield_none(self) -> None:
        """缺字段 None：verified_states 无 absolute_limit 键 → MarketBar 字段为 None。"""
        bar = self._provider({"market_state": "trading"}).get_bar("A.SZ", self.days[1])
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertIsNone(bar.absolute_limit_up_price)
        self.assertIsNone(bar.absolute_limit_down_price)

    def test_direct_passthrough(self) -> None:
        """直接原值：verified_states 中明确的价格原样传到 MarketBar。"""
        bar = self._provider({
            "market_state": "trading", "limit_known": True,
            "absolute_limit_up_price": 11.0, "absolute_limit_down_price": 9.0,
        }).get_bar("A.SZ", self.days[1])
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertEqual(bar.absolute_limit_up_price, 11.0)
        self.assertEqual(bar.absolute_limit_down_price, 9.0)

    def test_known_flag_not_forced_by_price(self) -> None:
        """known 标志不因有价变 True：价格存在但 limit_known=False → limit_state_known 仍为 False。"""
        bar = self._provider({
            "market_state": "trading", "limit_known": False,
            "absolute_limit_up_price": 11.0, "absolute_limit_down_price": 9.0,
        }).get_bar("A.SZ", self.days[1])
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertFalse(bar.limit_state_known)
        self.assertEqual(bar.absolute_limit_up_price, 11.0)
        self.assertEqual(bar.absolute_limit_down_price, 9.0)

    def test_single_boundary_missing(self) -> None:
        """单界缺失：只有 absolute_limit_up_price，down 为 None。"""
        bar = self._provider({
            "market_state": "trading", "limit_known": True,
            "absolute_limit_up_price": 11.0,
        }).get_bar("A.SZ", self.days[1])
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertEqual(bar.absolute_limit_up_price, 11.0)
        self.assertIsNone(bar.absolute_limit_down_price)

    def test_bool_rejected(self) -> None:
        """bool 类型被 adapter _to_float_price 明确拒绝，不默默变 None。"""
        with self.assertRaises(ValueError):
            self._provider({
                "market_state": "trading", "limit_known": True,
                "absolute_limit_up_price": True, "absolute_limit_down_price": 9.0,
            }).get_bar("A.SZ", self.days[1])

    def test_negative_rejected(self) -> None:
        """负值被 core MarketBar 明确拒绝。"""
        with self.assertRaises(ValueError):
            self._provider({
                "market_state": "trading", "limit_known": True,
                "absolute_limit_up_price": 11.0, "absolute_limit_down_price": -1.0,
            }).get_bar("A.SZ", self.days[1])

    def test_nan_rejected(self) -> None:
        """NaN 被 core MarketBar 明确拒绝。"""
        with self.assertRaises(ValueError):
            self._provider({
                "market_state": "trading", "limit_known": True,
                "absolute_limit_up_price": float("nan"), "absolute_limit_down_price": 9.0,
            }).get_bar("A.SZ", self.days[1])

    def test_reversed_order_rejected(self) -> None:
        """down > up 被 core MarketBar 明确拒绝。"""
        with self.assertRaises(ValueError):
            self._provider({
                "market_state": "trading", "limit_known": True,
                "absolute_limit_up_price": 9.0, "absolute_limit_down_price": 11.0,
            }).get_bar("A.SZ", self.days[1])
