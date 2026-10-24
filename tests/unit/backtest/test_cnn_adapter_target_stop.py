"""B04-target 两档止损单测（合成小缓存，零触网）。"""
import os
import shutil
import tempfile
import unittest
from datetime import date

import numpy as np

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache


def _synth(codes, scores):
    n = len(codes)
    exp = np.asarray(scores, dtype=np.float64)
    true = np.linspace(0.01, 0.02, n)
    dates = np.array(["2025-03-03"] * n, dtype="datetime64[D]")
    return exp, true, dates, np.asarray(codes)


def _adapter(tc, codes, scores):
    from backtest.cnn_adapter.predictions import CnnPredictionAdapter

    path = os.path.join(tc.tmp, "preds_stop.npz")
    save_prediction_cache(path, *_synth(codes, scores))
    params = {"model_name": "m", "checkpoint": "c",
              "bins_version": "b", "eval_script_version": "e"}
    return CnnPredictionAdapter(load_prediction_cache(path), **params)


class _Pos:
    def __init__(self, shares, cost, price, mv=None):
        self._s, self._c, self._p = shares, cost, price
        self._m = shares * price if mv is None and price is not None else mv

    @property
    def shares(self):
        return self._s

    @property
    def cost(self):
        return self._c

    @property
    def price(self):
        return self._p

    @property
    def market_value(self):
        return self._m


class _Acct:
    def __init__(self, positions, cash=100000.0, locked=None):
        self._p, self._c, self._l = positions, cash, locked or {}

    @property
    def cash(self):
        return self._c

    @property
    def available_cash(self):
        return self._c

    @property
    def positions(self):
        return self._p

    @property
    def locked(self):
        return self._l

    @property
    def nav(self):
        return self._c


class _Mkt:
    def get_bars(self, ids, start, end, interval="1d"):
        ids = [ids] if isinstance(ids, str) else list(ids)
        return {c: [] for c in ids}


class StopMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tstop_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _strat(self, codes, scores, **kw):
        from backtest.cnn_adapter.target_strategy import CnnTargetOrderStrategy

        return CnnTargetOrderStrategy(_adapter(self, codes, scores), **kw)

    def _orders(self, s, positions, locked=None):
        day = date(2025, 3, 3)
        return s.orders_for(trading_date=day, signal_time=s.signal_time_for(day),
                            account=_Acct(positions, locked=locked), market=_Mkt())


class TestStopLevels(StopMixin):
    def test_full_stop_sells_all(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B"], [0.09, 0.01], target_size=2, sell_buffer=500,
                        stop_half=0.03, stop_full=0.06)
        # A 在买入带内但浮亏 -10% → 全卖；B 无持仓 → 买入单
        acc = {"A": _Pos(200, 100.0, 90.0)}
        sells = [o for o in self._orders(s, acc) if o.side is Side.SELL]
        self.assertEqual([(o.instrument_id, o.shares) for o in sells], [("A", 200)])
        self.assertEqual(s.counters.stop_full_order_count, 1)

    def test_half_stop_sells_half(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B"], [0.09, 0.01], target_size=2, sell_buffer=500,
                        stop_half=0.03, stop_full=0.06)
        acc = {"A": _Pos(200, 100.0, 96.0)}  # -4% → 半仓
        sells = [o for o in self._orders(s, acc) if o.side is Side.SELL]
        self.assertEqual([(o.instrument_id, o.shares) for o in sells], [("A", 100)])
        self.assertEqual(s.counters.stop_half_order_count, 1)

    def test_no_stop_above_line(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B"], [0.09, 0.01], target_size=2, sell_buffer=500,
                        stop_half=0.03, stop_full=0.06)
        acc = {"A": _Pos(200, 100.0, 99.0)}  # -1% → 不动
        sells = [o for o in self._orders(s, acc) if o.side is Side.SELL]
        self.assertEqual(sells, [])

    def test_missing_price_and_zero_cost_skip(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B", "C"], [0.09, 0.05, 0.01], target_size=3,
                        sell_buffer=500, stop_half=0.03, stop_full=0.06)
        acc = {"A": _Pos(200, 0.0, 50.0),  # cost=0 → 跳过
               "B": _Pos(200, 100.0, None, mv=None)}  # 缺价 → 跳过
        sells = [o for o in self._orders(s, acc) if o.side is Side.SELL]
        self.assertEqual(sells, [])

    def test_locked_shares_excluded(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B"], [0.09, 0.01], target_size=2, sell_buffer=500,
                        stop_half=0.03, stop_full=0.06)
        acc = {"A": _Pos(200, 100.0, 90.0)}  # -10%，但锁定 200 → 无可卖
        sells = [o for o in self._orders(s, {"A": acc["A"]}, locked={"A": 200})
                 if o.side is Side.SELL]
        self.assertEqual(sells, [])

    def test_disabled_by_default(self):
        from backtest_core.contracts import Side

        s = self._strat(["A", "B"], [0.09, 0.01], target_size=2, sell_buffer=500)
        acc = {"A": _Pos(200, 100.0, 50.0)}  # -50% 但止损关闭 → 不卖
        sells = [o for o in self._orders(s, acc) if o.side is Side.SELL]
        self.assertEqual(sells, [])

    def test_bad_params_raise(self):
        with self.assertRaises(ValueError):
            self._strat(["A"], [0.01], stop_half=0.06, stop_full=0.03)
        with self.assertRaises(ValueError):
            self._strat(["A"], [0.01], stop_half=1.5)
        with self.assertRaises(TypeError):
            self._strat(["A"], [0.01], stop_half=True)


if __name__ == "__main__":
    unittest.main()
