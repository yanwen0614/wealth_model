"""N01：cnn 主入口切换契约（adapter 唯一路径），零触库/零触网。

为什么做：阶段 3 直接切换要求主入口默认走 adapter（rolling/target 均经
cnn_adapter）；旧 rolling/target 体已删，legacy 隔离只在库级保留
（backtest.legacy 守卫 + engine.OLD_LOGIC 标记）。
"""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import scripts.run_backtest as entry
from backtest.legacy import LegacyBacktestDisabledError, guard_legacy_disabled


def _args(**over):
    base = {"preds": ["p.npz"], "parquet": "q.parquet", "topn": [2],
            "capital": 1000.0, "buy_rate": 0.00025, "sell_rate": 0.00025,
            "stamp_rate": 0.00025, "min_commission": 5.0,
            "benchmark_index": "000300.SH", "index_dir": "idx_dir",
            "model_name": "m", "checkpoint": "c", "bins_version": "b"}
    base.update(over)
    return SimpleNamespace(**base)


class TestN01AdapterDefault(unittest.TestCase):
    def test_rolling_uses_adapter_and_marks_engine(self):
        outcome = SimpleNamespace(account_evaluation={"total_return": 0.1, "sharpe": 1.0},
                                  config_hash="h", data_fingerprint="f")
        preds = {"exp_ret": [0.1], "true_ret": [0.01], "dates": ["2026-01-01"], "codes": ["000001.SZ"]}
        with (patch.object(entry, "load_preds", return_value=preds),
              patch.object(entry, "_resolve_benchmark", return_value=(None, None)),
              patch.object(entry, "run_cnn_backtest", return_value=outcome) as mocked,
              tempfile.TemporaryDirectory() as tmp):
            entry.run_adapter_rolling(_args(), tmp)
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["mode"], "rolling")
        self.assertEqual(saved["engine"], "cnn_adapter")
        self.assertNotIn("legacy", saved)
        self.assertAlmostEqual(saved["models"]["p"]["top2"]["final_nav"], 1100.0)


class TestN01LegacyIsolation(unittest.TestCase):
    def test_guard_refuses_without_opt_in(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            guard_legacy_disabled("unit-test-caller")

    def test_guard_allows_explicit_opt_in(self):
        with patch.dict(os.environ, {"CNN_ALLOW_LEGACY": "1"}):
            self.assertIsNone(guard_legacy_disabled("unit-test-caller"))

    def test_old_engine_marked(self):
        import backtest.engine as old
        self.assertTrue(old.OLD_LOGIC)


class TestN01CliRouting(unittest.TestCase):
    def test_cli_default_routes_to_adapter(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet", "--out_dir", tmp])
        default.assert_called_once()

    def test_cli_target_routes_to_adapter_target(self):
        with (patch.object(entry, "run_adapter_target") as target,
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--mode", "target", "--preds", "a.npz", "--parquet", "b.parquet",
                        "--out_dir", tmp])
        target.assert_called_once()

    def test_cli_rolling_requires_parquet(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            entry.main(["--preds", "a.npz", "--out_dir", tmp])


if __name__ == "__main__":
    unittest.main()
