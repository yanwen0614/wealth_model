"""N02：cnn 入口切换收口（adapter 唯一路径），零触库/零触网。

为什么做：旧 rolling/target 体已删——默认路径 --ohlc 显式 WARNING 后走
adapter；target 经 adapter target（mode="target" + 五参透传）；默认
adapter 路径 CLI 端到端 smoke。
"""
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import scripts.run_backtest as entry


def _args(**over):
    base = {"preds": ["p.npz"], "parquet": "q.parquet",
            "capital": 1000.0, "buy_rate": 0.00025, "sell_rate": 0.00025,
            "stamp_rate": 0.00025, "min_commission": 5.0,
            "benchmark_index": "000300.SH", "index_dir": "idx_dir",
            "model_name": "m", "checkpoint": "c", "bins_version": "b",
            "topn": [2], "target_size": 7, "sell_buffer": 9,
            "exit_on_nonpositive": True, "exit_threshold": 0.01,
            "strong_buy_threshold": 0.02}
    base.update(over)
    return SimpleNamespace(**base)


def _preds():
    return {"exp_ret": [0.1], "true_ret": [0.01], "dates": ["2026-01-01"], "codes": ["000001.SZ"]}


def _outcome(total_return=0.05):
    return SimpleNamespace(account_evaluation={"total_return": total_return, "sharpe": 0.8},
                           config_hash="h", data_fingerprint="f")


class TestN02OhlcIgnoredWarning(unittest.TestCase):
    def test_default_path_warns_when_ohlc_given(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              tempfile.TemporaryDirectory() as tmp,
              self.assertLogs(entry.logger, level="WARNING") as logs):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--ohlc", "o.npz", "--out_dir", tmp])
        default.assert_called_once()
        self.assertTrue(any("--ohlc" in m and "忽略" in m for m in logs.output))

    def test_default_path_no_warning_without_ohlc(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              tempfile.TemporaryDirectory() as tmp,
              self.assertNoLogs(entry.logger, level="WARNING")):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--out_dir", tmp])
        default.assert_called_once()


class TestN02AdapterSmoke(unittest.TestCase):
    def test_cli_default_adapter_end_to_end(self):
        with (patch.object(entry, "load_preds", return_value=_preds()),
              patch.object(entry, "_resolve_benchmark", return_value=(None, None)),
              patch.object(entry, "run_cnn_backtest", return_value=_outcome(0.05)) as mocked,
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--topn", "2", "--out_dir", tmp])
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["mode"], "rolling")
        self.assertEqual(saved["engine"], "cnn_adapter")
        self.assertNotIn("legacy", saved)
        self.assertAlmostEqual(saved["models"]["a"]["top2"]["final_nav"], 1050000.0)


class TestN02AdapterTarget(unittest.TestCase):
    def test_target_passthrough_and_metrics(self):
        with (patch.object(entry, "load_preds", return_value=_preds()),
              patch.object(entry, "_resolve_benchmark", return_value=(None, None)),
              patch.object(entry, "run_cnn_backtest", return_value=_outcome(0.05)) as mocked,
              tempfile.TemporaryDirectory() as tmp):
            entry.run_adapter_target(_args(), tmp)
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["mode"], "target")
        self.assertEqual(kwargs["target_size"], 7)
        self.assertEqual(kwargs["sell_buffer"], 9)
        self.assertTrue(kwargs["exit_on_nonpositive"])
        self.assertEqual(kwargs["exit_threshold"], 0.01)
        self.assertEqual(kwargs["strong_buy_threshold"], 0.02)
        self.assertEqual(saved["engine"], "cnn_adapter")
        self.assertNotIn("legacy", saved)
        tm = saved["models"]["p"]["target"]
        self.assertAlmostEqual(tm["final_nav"], 1050.0)
        self.assertEqual(tm["config_hash"], "h")
        self.assertEqual(tm["data_fingerprint"], "f")

    def test_cli_target_routes_to_adapter_target(self):
        with (patch.object(entry, "load_preds", return_value=_preds()),
              patch.object(entry, "_resolve_benchmark", return_value=(None, None)),
              patch.object(entry, "run_cnn_backtest", return_value=_outcome(0.05)) as mocked,
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--mode", "target", "--preds", "a.npz", "--parquet", "b.parquet",
                        "--out_dir", tmp])
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["mode"], "target")
        self.assertIn("target", saved["models"]["a"])
        self.assertNotIn("legacy", saved)

    def test_cli_target_without_parquet_raises(self):
        with (tempfile.TemporaryDirectory() as tmp,
              self.assertRaises(ValueError)):
            entry.main(["--mode", "target", "--preds", "a.npz",
                        "--out_dir", tmp])


if __name__ == "__main__":
    unittest.main()
