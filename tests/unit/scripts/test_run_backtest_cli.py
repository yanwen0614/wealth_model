"""run_backtest CLI 参数默认值/废弃告警与 target metrics 单测（adapter 唯一路径）."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import scripts.run_backtest as entry_mod
from scripts.run_backtest import (
    default_index_dir,
    index_covers_trade_days,
    load_index_close,
    parse_args,
    run_adapter_target,
)


class TestRunBacktestCLI(unittest.TestCase):
    def _parse(self, argv):
        with mock.patch.object(sys, "argv", ["run_backtest", *argv]):
            return parse_args()

    def test_fee_defaults(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet"])
        self.assertEqual(a.capital, 1_000_000.0)
        self.assertEqual(a.buy_rate, 0.00025)
        self.assertEqual(a.sell_rate, 0.00025)
        self.assertEqual(a.stamp_rate, 0.00025)
        self.assertEqual(a.min_commission, 5.0)
        self.assertIsNone(a.cost_rate)

    def test_target_exit_defaults(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet", "--mode", "target"])
        self.assertEqual(a.sell_buffer, 500)
        self.assertFalse(a.exit_on_nonpositive)
        self.assertEqual(a.exit_threshold, 0.0)

    def test_cost_rate_deprecated_warning_and_ignored(self):
        with (mock.patch.object(entry_mod, "run_adapter_rolling") as default,
              tempfile.TemporaryDirectory() as tmp,
              self.assertLogs(entry_mod.logger, level="WARNING") as logs):
            entry_mod.main(["--preds", "x.npz", "--parquet", "q.parquet",
                            "--cost_rate", "0.0015", "--out_dir", tmp])
        default.assert_called_once()
        self.assertIsNone(default.call_args[0][0].cost_rate)
        self.assertTrue(any("cost_rate" in m for m in logs.output))

    def test_fee_overrides(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet", "--capital", "4e4",
                         "--buy_rate", "0.0003", "--min_commission", "1", "--exit-on-nonpositive",
                         "--exit_threshold", "0.01"])
        self.assertEqual(a.capital, 40000.0)
        self.assertEqual(a.buy_rate, 0.0003)
        self.assertEqual(a.min_commission, 1.0)
        self.assertTrue(a.exit_on_nonpositive)
        self.assertEqual(a.exit_threshold, 0.01)

    def test_benchmark_defaults(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet"])
        self.assertEqual(a.topn, [5, 10, 20])
        self.assertEqual(a.benchmark_index, "000300.SH")
        self.assertEqual(a.index_dir, default_index_dir())

    def test_benchmark_overrides(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet", "--benchmark_index", "000905.SH",
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


class TestStrongBuyThresholdCLI(unittest.TestCase):
    """--strong_buy_threshold CLI 参数（target 模式强买门槛）."""

    def _parse(self, argv):
        with mock.patch.object(sys, "argv", ["run_backtest", *argv]):
            return parse_args()

    def test_default_zero(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet", "--mode", "target"])
        self.assertEqual(a.strong_buy_threshold, 0.0)

    def test_override(self):
        a = self._parse(["--preds", "x.npz", "--parquet", "q.parquet", "--mode", "target",
                         "--strong_buy_threshold", "0.02"])
        self.assertEqual(a.strong_buy_threshold, 0.02)


class TestTargetMetricsStrongBuy(unittest.TestCase):
    """target metrics：adapter target 口径（final_nav/config_hash/data_fingerprint），打印含 strong_buy."""

    def _run(self, extra_argv, tmp, benchmark=None):
        with mock.patch.object(sys, "argv", ["run_backtest", "--preds", "x.npz", "--parquet", "q.parquet",
                                              "--mode", "target", *extra_argv]):
            args = parse_args()
        days = np.array(["2026-01-05", "2026-01-06"], dtype="datetime64[D]")
        preds = {"exp_ret": np.array([0.10]), "true_ret": np.array([0.10]),
                 "dates": days, "codes": np.array(["000001"])}
        outcome = SimpleNamespace(account_evaluation={"total_return": 0.05, "annualized_return": 0.06,
                                                      "sharpe": 0.8, "max_drawdown": 0.01},
                                  config_hash="h", data_fingerprint="f")
        mock_run = mock.Mock(return_value=outcome)
        buf = io.StringIO()
        with mock.patch.multiple("scripts.run_backtest",
                                 load_preds=mock.Mock(return_value=preds),
                                 _resolve_benchmark=mock.Mock(return_value=benchmark or (None, None)),
                                 run_cnn_backtest=mock_run), contextlib.redirect_stdout(buf):
            run_adapter_target(args, tmp)
        with open(os.path.join(tmp, "metrics.json"), encoding="utf-8") as f:
            return json.load(f), buf.getvalue(), mock_run

    def test_five_params_passthrough_and_target_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics, out, mock_run = self._run(["--strong_buy_threshold", "0.02", "--target_size", "7",
                                                "--sell_buffer", "9", "--exit-on-nonpositive",
                                                "--exit_threshold", "0.01"], tmp)
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(kwargs["mode"], "target")
        self.assertEqual(kwargs["target_size"], 7)
        self.assertEqual(kwargs["sell_buffer"], 9)
        self.assertTrue(kwargs["exit_on_nonpositive"])
        self.assertEqual(kwargs["exit_threshold"], 0.01)
        self.assertEqual(kwargs["strong_buy_threshold"], 0.02)
        self.assertEqual(metrics["strong_buy_threshold"], 0.02)
        self.assertEqual(metrics["target_size"], 7)
        self.assertEqual(metrics["sell_buffer"], 9)
        tm = metrics["models"]["x"]["target"]
        self.assertAlmostEqual(tm["final_nav"], 1050000.0)
        self.assertEqual(tm["config_hash"], "h")
        self.assertEqual(tm["data_fingerprint"], "f")
        self.assertNotIn("excess_annual", tm)
        self.assertIn("strong_buy=0.02", out)

    def test_default_threshold_zero_in_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics, out, mock_run = self._run([], tmp)
        self.assertEqual(mock_run.call_args.kwargs["strong_buy_threshold"], 0.0)
        self.assertEqual(metrics["strong_buy_threshold"], 0.0)
        self.assertIn("strong_buy=0.0", out)

    def test_excess_annual_when_benchmark_present(self):
        bench = (np.array([1.0, 1.02]),
                 {"annual": 0.01, "sharpe": 0.5, "mdd": 0.0, "win_rate": 0.5})
        with tempfile.TemporaryDirectory() as tmp:
            metrics, _, _ = self._run([], tmp, benchmark=bench)
        tm = metrics["models"]["x"]["target"]
        self.assertAlmostEqual(tm["excess_annual"], 0.05)
        self.assertIn("benchmark", metrics)


if __name__ == "__main__":
    unittest.main()
