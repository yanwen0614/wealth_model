"""T05: run_backtest CLI 参数默认值与 --cost_rate deprecation 单测."""
import contextlib
import io
import sys
import unittest
from unittest import mock

import numpy as np

from scripts.run_backtest import (
    default_index_dir,
    index_covers_trade_days,
    load_index_close,
    parse_args,
)


class TestRunBacktestCLI(unittest.TestCase):
    def _parse(self, argv):
        with mock.patch.object(sys, "argv", ["run_backtest", *argv]):
            return parse_args()

    def test_fee_defaults(self):
        a = self._parse(["--preds", "x.npz", "--ohlc", "o.npz"])
        self.assertEqual(a.capital, 1_000_000.0)
        self.assertEqual(a.buy_rate, 0.00025)
        self.assertEqual(a.sell_rate, 0.00025)
        self.assertEqual(a.stamp_rate, 0.00025)
        self.assertEqual(a.min_commission, 5.0)
        self.assertIsNone(a.cost_rate)

    def test_target_exit_defaults(self):
        a = self._parse(["--preds", "x.npz", "--mode", "target"])
        self.assertEqual(a.sell_buffer, 500)
        self.assertFalse(a.exit_on_nonpositive)
        self.assertEqual(a.exit_threshold, 0.0)

    def test_cost_rate_deprecated_warning_and_ignored(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            a = self._parse(["--preds", "x.npz", "--ohlc", "o.npz", "--cost_rate", "0.0015"])
        self.assertIn("cost_rate", buf.getvalue())
        self.assertIsNone(a.cost_rate)

    def test_fee_overrides(self):
        a = self._parse(["--preds", "x.npz", "--ohlc", "o.npz", "--capital", "4e4",
                         "--buy_rate", "0.0003", "--min_commission", "1", "--exit-on-nonpositive",
                         "--exit_threshold", "0.01"])
        self.assertEqual(a.capital, 40000.0)
        self.assertEqual(a.buy_rate, 0.0003)
        self.assertEqual(a.min_commission, 1.0)
        self.assertTrue(a.exit_on_nonpositive)
        self.assertEqual(a.exit_threshold, 0.01)

    def test_benchmark_defaults(self):
        a = self._parse(["--preds", "x.npz", "--ohlc", "o.npz"])
        self.assertEqual(a.topn, [5, 10, 20])
        self.assertEqual(a.benchmark_index, "000300.SH")
        self.assertEqual(a.index_dir, default_index_dir())

    def test_benchmark_overrides(self):
        a = self._parse(["--preds", "x.npz", "--ohlc", "o.npz", "--benchmark_index", "000905.SH",
                         "--index_dir", "D:/idx", "--topn", "5", "10"])
        self.assertEqual(a.benchmark_index, "000905.SH")
        self.assertEqual(a.index_dir, "D:/idx")
        self.assertEqual(a.topn, [5, 10])


class TestIndexBenchmarkHelpers(unittest.TestCase):
    def test_missing_index_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_index_close("D:/no/such/index/dir", "000300.SH")

    def test_coverage_false_when_no_overlap_true_when_overlap(self):
        idates = np.array(["2013-01-04", "2013-01-07"], dtype="datetime64[D]")
        self.assertFalse(index_covers_trade_days(idates, np.array(["2026-01-05"], dtype="datetime64[D]")))
        self.assertTrue(index_covers_trade_days(idates, np.array(["2013-01-04"], dtype="datetime64[D]")))


if __name__ == "__main__":
    unittest.main()
