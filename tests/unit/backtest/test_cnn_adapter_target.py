"""B04-target: CnnTargetOrderStrategy 单测（TDD，合成小缓存，零触网/cnn 无 DB）."""
import os
import shutil
import tempfile
import unittest
from datetime import date

import numpy as np

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache


def _synth_cache_arrays(codes, day="2025-03-03", scores=None):
    n = len(codes)
    exp_ret = np.asarray(scores if scores is not None else np.linspace(-0.04, 0.05, n),
                         dtype=np.float64)
    true_ret = np.linspace(0.01, 0.02, n)
    dates = np.array([day] * n, dtype="datetime64[D]")
    return exp_ret, true_ret, dates, np.asarray(codes)


def _make_pred_adapter(testcase, codes, **kwargs):
    from backtest.cnn_adapter.predictions import CnnPredictionAdapter

    arrays = _synth_cache_arrays(codes, scores=kwargs.pop("scores", None))
    path = os.path.join(testcase.tmp, "preds_target.npz")
    save_prediction_cache(path, *arrays)
    cache = load_prediction_cache(path)
    params = {"model_name": "cnn_transformer", "checkpoint": "logs/run_demo/best_model.pth",
              "bins_version": "BINS52_v1", "eval_script_version": "eval_bins_mapping@v1"}
    params.update(kwargs)
    return CnnPredictionAdapter(cache, **params)


def _make_target_strategy(testcase, codes, **kwargs):
    from backtest.cnn_adapter.target_strategy import CnnTargetOrderStrategy

    scores = kwargs.pop("scores", None)
    return CnnTargetOrderStrategy(_make_pred_adapter(testcase, codes, scores=scores), **kwargs)


class _FakePosition:
    def __init__(self, shares, price=None):
        self._shares = shares
        self._price = price

    @property
    def shares(self):
        return self._shares

    @property
    def cost(self):
        return 0.0

    @property
    def price(self):
        return self._price

    @property
    def market_value(self):
        return None if self._price is None else self._shares * self._price


class _FakeAccount:
    def __init__(self, cash=100000.0, positions=None):
        self._cash = cash
        self._positions = positions or {}

    @property
    def cash(self):
        return self._cash

    @property
    def available_cash(self):
        return self._cash

    @property
    def positions(self):
        return self._positions

    @property
    def locked(self):
        return {}

    @property
    def nav(self):
        return self._cash + sum((pos.market_value or 0.0) for pos in self._positions.values())


class _FakeMarket:
    """MarketView 形状替身：本策略不预判价格（`del market`），仅满足协议类型。"""

    def get_bars(self, instrument_ids, start, end, interval="1d"):
        ids = [instrument_ids] if isinstance(instrument_ids, str) else list(instrument_ids)
        return {code: [] for code in ids}


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b04t_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBuyBand(_TempDirMixin):
    def test_buy_band_picks_rank_within_target_size(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003", "000004"]
        strategy = _make_target_strategy(self, codes, scores=[0.01, 0.05, 0.03, 0.04],
                                         target_size=2, sell_buffer=500)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(), market=_FakeMarket())
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["000002", "000004"])

    def test_tie_breaks_by_code_ascending(self):
        from backtest_core.contracts import Side

        codes = ["000003", "000001", "000002"]
        strategy = _make_target_strategy(self, codes, scores=[0.02, 0.02, 0.02],
                                         target_size=2, sell_buffer=0)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(), market=_FakeMarket())
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["000001", "000002"])

    def test_budget_uses_actual_buy_count_and_held_target_skipped(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003", "000004"]
        strategy = _make_target_strategy(self, codes, scores=[0.01, 0.05, 0.03, 0.04],
                                         target_size=2, sell_buffer=500)
        held = {"000002": _FakePosition(300, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(cash=100000.0, positions=held),
                                     market=_FakeMarket())
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["000004"])
        self.assertIsNone(buys[0].shares)
        self.assertAlmostEqual(buys[0].cash_amount or 0.0, 100000.0)
        self.assertEqual([order for order in orders if order.side is Side.SELL], [])

    def test_zero_cash_produces_no_buys(self):
        from backtest_core.contracts import Side

        strategy = _make_target_strategy(self, ["000001", "000002"], target_size=1)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(cash=0.0), market=_FakeMarket())
        self.assertEqual([order for order in orders if order.side is Side.BUY], [])


class TestSellBuffer(_TempDirMixin):
    def test_holding_within_buffer_is_kept(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C", "D", "E"]
        strategy = _make_target_strategy(self, codes, scores=[0.05, 0.04, 0.03, 0.02, 0.01],
                                         target_size=1, sell_buffer=2)
        held = {"C": _FakePosition(100, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=_FakeMarket())
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual(sells, [])

    def test_holding_beyond_buffer_sold_in_full_sells_first(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C", "D", "E"]
        strategy = _make_target_strategy(self, codes, scores=[0.05, 0.04, 0.03, 0.02, 0.01],
                                         target_size=1, sell_buffer=1)
        held = {"C": _FakePosition(500, 10.0), "A": _FakePosition(200, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=_FakeMarket())
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual([(order.instrument_id, order.shares) for order in sells], [("C", 500)])
        self.assertEqual(orders[0].side, Side.SELL)

    def test_holding_without_prediction_is_kept(self):
        from backtest_core.contracts import Side

        strategy = _make_target_strategy(self, ["A", "B"], scores=[0.05, 0.04],
                                         target_size=1, sell_buffer=0)
        held = {"ZZZ": _FakePosition(100, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=_FakeMarket())
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual(sells, [])


class TestExitOnNonpositive(_TempDirMixin):
    def test_nonpositive_holding_sold_even_within_buffer(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C"]
        strategy = _make_target_strategy(self, codes, scores=[0.05, -0.01, 0.03],
                                         target_size=1, sell_buffer=500,
                                         exit_on_nonpositive=True, exit_threshold=0.0)
        held = {"B": _FakePosition(100, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=_FakeMarket())
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual([(order.instrument_id, order.shares) for order in sells], [("B", 100)])

    def test_positive_holding_kept_when_exit_enabled(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C"]
        strategy = _make_target_strategy(self, codes, scores=[0.05, 0.02, 0.03],
                                         target_size=1, sell_buffer=500,
                                         exit_on_nonpositive=True, exit_threshold=0.0)
        held = {"B": _FakePosition(100, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=_FakeMarket())
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual(sells, [])


class TestStrongBuy(_TempDirMixin):
    def test_below_threshold_skipped_without_refill_and_counted(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C"]
        strategy = _make_target_strategy(self, codes, scores=[0.05, 0.04, 0.03],
                                         target_size=2, sell_buffer=500,
                                         strong_buy_threshold=0.045)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(cash=100000.0), market=_FakeMarket())
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["A"])
        self.assertAlmostEqual(buys[0].cash_amount or 0.0, 100000.0)
        self.assertEqual(strategy.counters.skipped_strong_buy_count, 1)

    def test_zero_threshold_disables_gate(self):
        from backtest_core.contracts import Side

        codes = ["A", "B", "C"]
        strategy = _make_target_strategy(self, codes, scores=[-0.05, -0.04, -0.03],
                                         target_size=2, sell_buffer=500,
                                         strong_buy_threshold=0.0)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(), market=_FakeMarket())
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual(len(buys), 2)

    def test_negative_threshold_raises(self):
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A", "B"], target_size=1,
                                  strong_buy_threshold=-0.01)


class TestParamValidation(_TempDirMixin):
    def test_bad_params_raise(self):
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A"], target_size=0)
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A"], target_size=True)
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A"], target_size=1.5)
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A"], sell_buffer=-1)
        with self.assertRaises(ValueError):
            _make_target_strategy(self, ["A"], sell_buffer=1.5)
        with self.assertRaises(TypeError):
            _make_target_strategy(self, ["A"], exit_on_nonpositive="yes")
        with self.assertRaises(TypeError):
            _make_target_strategy(self, ["A"], exit_threshold="0.0")

    def test_bad_adapter_type_raises(self):
        from backtest.cnn_adapter.target_strategy import CnnTargetOrderStrategy

        with self.assertRaises(ValueError):
            CnnTargetOrderStrategy(object(), target_size=1)

    def test_no_top_n_attribute(self):
        strategy = _make_target_strategy(self, ["A", "B"], target_size=1)
        self.assertFalse(hasattr(strategy, "top_n"))
        self.assertEqual(strategy.target_size, 1)
        self.assertEqual(strategy.sell_buffer, 500)


class TestFailFastAndProtocol(_TempDirMixin):
    def test_unknown_date_raises(self):
        strategy = _make_target_strategy(self, ["000001", "000002"], target_size=1)
        with self.assertRaises(ValueError):
            strategy.orders_for(trading_date=date(2025, 4, 1),
                                signal_time=strategy.signal_time_for(date(2025, 4, 1)),
                                account=_FakeAccount(), market=_FakeMarket())

    def test_signal_time_mismatch_raises(self):
        import datetime

        from backtest.cnn_adapter.common import SHANGHAI_TZ

        strategy = _make_target_strategy(self, ["000001", "000002"], target_size=1)
        bad_time = datetime.datetime(2025, 3, 4, 15, 0, tzinfo=SHANGHAI_TZ)
        with self.assertRaises(ValueError):
            strategy.orders_for(trading_date=date(2025, 3, 3), signal_time=bad_time,
                                account=_FakeAccount(), market=_FakeMarket())

    def test_helpers_and_counters_shape(self):
        strategy = _make_target_strategy(self, ["000001", "000002"], target_size=1)
        self.assertEqual(list(strategy.available_dates), [date(2025, 3, 3)])
        summary = strategy.warnings_summary()
        self.assertIn("buy_order_count", summary)
        self.assertIn("sell_order_count", summary)
        self.assertTrue(all(isinstance(value, str) for value in summary.values()))


if __name__ == "__main__":
    unittest.main()
