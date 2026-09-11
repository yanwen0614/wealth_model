"""B04: CnnOrderStrategy + runner 单测（TDD，合成小缓存+合成 parquet，零触网/cnn 无 DB）."""
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
    path = os.path.join(testcase.tmp, "preds.npz")
    save_prediction_cache(path, *arrays)
    cache = load_prediction_cache(path)
    params = {"model_name": "cnn_transformer", "checkpoint": "logs/run_demo/best_model.pth",
              "bins_version": "BINS52_v1", "eval_script_version": "eval_bins_mapping@v1"}
    params.update(kwargs)
    return CnnPredictionAdapter(cache, **params)


def _make_strategy(testcase, codes, **kwargs):
    from backtest.cnn_adapter.order_strategy import CnnOrderStrategy

    top_n = kwargs.pop("top_n", 2)
    return CnnOrderStrategy(_make_pred_adapter(testcase, codes, **kwargs), top_n=top_n)


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


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b04_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestTopNSelection(_TempDirMixin):
    def test_picks_highest_scores_descending(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003", "000004"]
        strategy = _make_strategy(self, codes, scores=[0.01, 0.05, 0.03, 0.04])
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(), market=None)
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["000002", "000004"])

    def test_tie_breaks_by_code_ascending_stably(self):
        from backtest_core.contracts import Side

        codes = ["000003", "000001", "000002"]
        strategy = _make_strategy(self, codes, scores=[0.02, 0.02, 0.02], top_n=2)
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(), market=None)
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual([order.instrument_id for order in buys], ["000001", "000002"])


class TestEqualWeightCash(_TempDirMixin):
    def test_budget_is_cash_divided_by_target_count(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003", "000004"]
        strategy = _make_strategy(self, codes, scores=[0.01, 0.05, 0.03, 0.04])
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(cash=100000.0), market=None)
        buys = [order for order in orders if order.side is Side.BUY]
        self.assertEqual(len(buys), 2)
        for order in buys:
            self.assertIsNone(order.shares)
            self.assertAlmostEqual(order.cash_amount or 0.0, 50000.0)

    def test_held_target_gets_no_order(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003", "000004"]
        strategy = _make_strategy(self, codes, scores=[0.01, 0.05, 0.03, 0.04])
        held = {"000002": _FakePosition(300, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=None)
        self.assertEqual([order.instrument_id for order in orders if order.side is Side.BUY], ["000004"])
        self.assertEqual([order for order in orders if order.side is Side.SELL], [])

    def test_zero_cash_produces_no_buys(self):
        from backtest_core.contracts import Side

        strategy = _make_strategy(self, ["000001", "000002"])
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(cash=0.0), market=None)
        self.assertEqual([order for order in orders if order.side is Side.BUY], [])


class TestExitSells(_TempDirMixin):
    def test_off_target_holding_sold_in_full(self):
        from backtest_core.contracts import Side

        codes = ["000001", "000002", "000003"]
        strategy = _make_strategy(self, codes, scores=[0.01, 0.05, 0.03], top_n=1)
        held = {"000001": _FakePosition(500, 10.0), "000002": _FakePosition(200, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=None)
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual([(order.instrument_id, order.shares) for order in sells], [("000001", 500)])
        self.assertEqual(orders[0].side, Side.SELL)

    def test_sells_sorted_by_code(self):
        from backtest_core.contracts import Side

        strategy = _make_strategy(self, ["000001"], scores=[0.09], top_n=1)
        held = {"000003": _FakePosition(100, 10.0), "000002": _FakePosition(100, 10.0)}
        orders = strategy.orders_for(trading_date=date(2025, 3, 3),
                                     signal_time=strategy.signal_time_for(date(2025, 3, 3)),
                                     account=_FakeAccount(positions=held), market=None)
        sells = [order for order in orders if order.side is Side.SELL]
        self.assertEqual([order.instrument_id for order in sells], ["000002", "000003"])


class TestFailFastDate(_TempDirMixin):
    def test_unknown_date_raises_without_empty_warning_path(self):
        strategy = _make_strategy(self, ["000001", "000002"])
        with self.assertRaises(ValueError):
            strategy.orders_for(trading_date=date(2025, 4, 1),
                                signal_time=strategy.signal_time_for(date(2025, 4, 1)),
                                account=_FakeAccount(), market=None)

    def test_signal_time_date_mismatch_raises(self):
        import datetime

        from backtest.cnn_adapter.common import SHANGHAI_TZ

        strategy = _make_strategy(self, ["000001", "000002"])
        bad_time = datetime.datetime(2025, 3, 4, 15, 0, tzinfo=SHANGHAI_TZ)
        with self.assertRaises(ValueError):
            strategy.orders_for(trading_date=date(2025, 3, 3), signal_time=bad_time,
                                account=_FakeAccount(), market=None)


class TestNoShadowAccount(_TempDirMixin):
    def test_double_run_identical_and_no_holding_state(self):
        import inspect

        import backtest.cnn_adapter.order_strategy as module

        codes = ["000001", "000002", "000003"]
        strategy = _make_strategy(self, codes)
        kwargs = {"trading_date": date(2025, 3, 3),
                  "signal_time": strategy.signal_time_for(date(2025, 3, 3)),
                  "account": _FakeAccount(), "market": None}
        first = strategy.orders_for(**kwargs)
        second = strategy.orders_for(**kwargs)
        self.assertEqual(first, second)
        for name in dir(strategy):
            if name.startswith("_"):
                continue
            self.assertNotIn("position", name.lower(), f"策略存在可疑持仓状态成员 {name!r}")
            self.assertNotIn("holding", name.lower(), f"策略存在可疑持仓状态成员 {name!r}")
            self.assertNotIn("cash", name.lower(), f"策略存在可疑资金状态成员 {name!r}")
        source = inspect.getsource(module).lower()
        self.assertNotIn("self._positions", source)
        self.assertNotIn("self._holdings", source)
        self.assertNotIn("self._cash", source)


_E2E_CODES = ["000001.SZ", "000002.SZ", "600000.SH", "600001.SH"]
_E2E_DAYS = ["2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10"]


def _e2e_cache():
    exp_ret, true_ret, dates, codes = [], [], [], []
    for day_index, day in enumerate(_E2E_DAYS):
        for code_index, code in enumerate(_E2E_CODES):
            exp_ret.append(0.01 * (code_index + 1) + 0.001 * day_index)
            true_ret.append(0.005)
            dates.append(day)
            codes.append(code)
    return (np.asarray(exp_ret), np.asarray(true_ret),
            np.asarray(dates, dtype="datetime64[D]"), np.asarray(codes))


def _e2e_parquet(path):
    import pandas as pd

    rows = []
    for day_index, day in enumerate(_E2E_DAYS):
        for code_index, code in enumerate(_E2E_CODES):
            price = 10.0 + code_index * 0.5 + day_index * 0.05
            rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": price,
                         "high": price + 0.1, "low": price - 0.1, "close": price + 0.02,
                         "volume": 2_000_000.0, "amount": price * 2_000_000.0, "is_trading": True})
    pd.DataFrame(rows).to_parquet(path, index=False)


def _e2e_kwargs(testcase):
    cache_path = os.path.join(testcase.tmp, "e2e_preds.npz")
    save_prediction_cache(cache_path, *_e2e_cache())
    parquet_path = os.path.join(testcase.tmp, "e2e.parquet")
    _e2e_parquet(parquet_path)
    return {"pred_cache": load_prediction_cache(cache_path), "parquet_path": parquet_path,
            "model_name": "cnn_transformer", "checkpoint": "logs/run_demo/best_model.pth",
            "bins_version": "BINS52_v1", "eval_script_version": "eval_bins_mapping@v1",
            "top_n": 2, "initial_capital": 200000.0}


class TestEndToEnd(_TempDirMixin):
    def test_orders_path_runs_with_verification_and_manifest(self):
        from backtest.cnn_adapter.runner import run_cnn_backtest

        outcome = run_cnn_backtest(**_e2e_kwargs(self))
        self.assertGreater(len(outcome.result.account_snapshots), 0)
        self.assertEqual(set(outcome.account_evaluation), set(outcome.result.account_metrics))
        for key, value in outcome.account_evaluation.items():
            self.assertAlmostEqual(value, outcome.result.account_metrics[key], places=9)
        self.assertTrue(outcome.manifest.config_hash)
        self.assertTrue(outcome.manifest.data_fingerprint)
        for key in ("order_entry", "model_name", "checkpoint", "run_id", "horizon", "label_formula"):
            self.assertIn(key, outcome.provenance)
        self.assertEqual(outcome.provenance["order_entry"], "atomic_orders_cash_budget")
        self.assertGreater(len(outcome.result.trades), 0)

    def test_same_input_double_run_is_deterministic(self):
        from backtest.cnn_adapter.runner import run_cnn_backtest

        first = run_cnn_backtest(**_e2e_kwargs(self))
        second = run_cnn_backtest(**_e2e_kwargs(self))
        self.assertEqual([snap.nav for snap in first.result.account_snapshots],
                         [snap.nav for snap in second.result.account_snapshots])
        self.assertEqual(first.account_evaluation, second.account_evaluation)
        self.assertEqual(first.manifest.config_hash, second.manifest.config_hash)
        self.assertEqual(first.manifest.data_fingerprint, second.manifest.data_fingerprint)

    def test_result_store_round_trip(self):
        from backtest_core.io import ResultStore

        from backtest.cnn_adapter.runner import run_cnn_backtest, write_cnn_result

        outcome = run_cnn_backtest(**_e2e_kwargs(self))
        out_dir = write_cnn_result(outcome, os.path.join(self.tmp, "runs", "b04"))
        reread = ResultStore(out_dir).read(out_dir)
        self.assertEqual(dict(reread.account_metrics), dict(outcome.result.account_metrics))
        self.assertEqual(reread.provenance["order_entry"], "atomic_orders_cash_budget")

    def test_bad_date_fails_fast(self):
        from backtest.cnn_adapter.runner import run_cnn_backtest

        kwargs = _e2e_kwargs(self)
        kwargs["dates"] = [date(2025, 3, 3), date(2025, 4, 1)]
        with self.assertRaises(ValueError):
            run_cnn_backtest(**kwargs)
