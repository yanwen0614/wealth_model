"""T02 engine真守卫 TDD：默认raise / opt-in放行且会计不变."""
import inspect
import os
import unittest
from unittest.mock import patch

import numpy as np


def _empty_rolling():
    exp = np.array([], dtype=np.float64)
    codes = np.array([], dtype="U6")
    dates = np.array([], dtype="datetime64[D]")
    ohlc = {"codes": np.array([], dtype="U6"), "dates": np.array([], dtype="datetime64[D]"),
            "t_close": np.array([], dtype=np.float64), "open_t1": np.array([], dtype=np.float64),
            "open_t6": np.array([], dtype=np.float64)}
    return exp, codes, dates, ohlc


def _empty_target():
    exp = np.array([], dtype=np.float64)
    codes = np.array([], dtype="U6")
    dates = np.array([], dtype="datetime64[D]")
    days = np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[D]")
    ohlc = {"codes": np.array(["000001"]), "dates": days,
            "open_m": np.full((1, 2), 10.0), "close_m": np.full((1, 2), 10.0)}
    return exp, codes, dates, ohlc


class TestEngineLegacyGuard(unittest.TestCase):
    def test_run_backtest_default_raises(self):
        from backtest.engine import run_backtest
        from backtest.legacy import LegacyBacktestDisabledError
        exp, codes, dates, ohlc = _empty_rolling()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            run_backtest(exp, codes, dates, ohlc, topn=1)

    def test_run_backtest_target_default_raises(self):
        from backtest.engine import run_backtest_target
        from backtest.legacy import LegacyBacktestDisabledError
        exp, codes, dates, ohlc = _empty_target()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            run_backtest_target(exp, codes, dates, ohlc, target_size=1)

    def test_guard_before_validation(self):
        from backtest.engine import run_backtest, run_backtest_target
        from backtest.legacy import LegacyBacktestDisabledError
        exp, codes, dates, ohlc = _empty_rolling()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            run_backtest(exp, codes, dates, ohlc, topn=0)
        exp2, c2, d2, o2 = _empty_target()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            run_backtest_target(exp2, c2, d2, o2, target_size=0)

    def test_engine_wires_guard(self):
        import backtest.engine as eng
        self.assertTrue(eng.OLD_LOGIC)
        for fn in (eng.run_backtest, eng.run_backtest_target):
            self.assertIn("guard_legacy_disabled", inspect.getsource(fn))

    def test_opt_in_allows_and_validates(self):
        from backtest.engine import run_backtest, run_backtest_target
        exp, codes, dates, ohlc = _empty_rolling()
        with patch.dict(os.environ, {"CNN_ALLOW_LEGACY": "1"}):
            res = run_backtest(exp, codes, dates, ohlc, topn=1)
            np.testing.assert_array_equal(res.nav, np.ones(1))
            with self.assertRaises(ValueError):
                run_backtest(exp, codes, dates, ohlc, topn=0)
            exp2, c2, d2, o2 = _empty_target()
            res2 = run_backtest_target(exp2, c2, d2, o2, target_size=1)
            self.assertEqual(len(res2.holdings), 0)


if __name__ == "__main__":
    unittest.main()
