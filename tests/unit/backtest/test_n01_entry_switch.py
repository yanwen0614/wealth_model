"""N01 TDD：cnn 主入口切换契约（红→绿），零触库/零触网。

为什么做：阶段 3 直接切换要求主入口默认走 adapter；旧 rolling/target
逻辑显式隔离（opt-in 才可达），旧回归出口一律拒绝。
"""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import scripts.run_backtest as entry
from backtest.legacy import LegacyBacktestDisabledError


def _args(**over):
    base = {"preds": ["p.npz"], "parquet": "q.parquet", "topn": [2],
            "initial_capital": 1000.0, "model_name": "m", "checkpoint": "c",
            "bins_version": "b", "eval_script_version": "e"}
    base.update(over)
    return SimpleNamespace(**base)


class TestN01AdapterDefault(unittest.TestCase):
    def test_rolling_uses_adapter_and_marks_engine(self):
        outcome = SimpleNamespace(account_evaluation={"total_return": 0.1, "sharpe": 1.0},
                                  provenance={}, config_hash="h", data_fingerprint="f")
        preds = {"exp_ret": [0.1], "true_ret": [0.01], "dates": ["2026-01-01"], "codes": ["000001.SZ"]}
        with (patch.object(entry, "load_preds", return_value=preds),
              patch.object(entry, "run_cnn_backtest", return_value=outcome) as mocked,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp):
            entry.run_adapter_rolling(_args(), tmp)
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(saved["engine"], "cnn_adapter")
        self.assertNotIn("legacy", saved)
        self.assertAlmostEqual(saved["models"]["p"]["top2"]["final_nav"], 1100.0)


class TestN01LegacyIsolation(unittest.TestCase):
    def test_legacy_rolling_requires_opt_in(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            entry.run_legacy_rolling(_args(), "out")

    def test_legacy_regression_always_refuses(self):
        with patch.dict(os.environ, {"CNN_ALLOW_LEGACY": "1"}), self.assertRaises(LegacyBacktestDisabledError):
            entry.run_legacy_regression()

    def test_old_engine_marked(self):
        import backtest.engine as old
        self.assertTrue(old.OLD_LOGIC)


class TestN01CliRouting(unittest.TestCase):
    def test_cli_default_routes_to_adapter(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              patch.object(entry, "run_legacy_rolling") as legacy,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet", "--out_dir", tmp])
        default.assert_called_once()
        legacy.assert_not_called()

    def test_cli_legacy_flag_guarded(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp,
              self.assertRaises(LegacyBacktestDisabledError)):
            entry.main(["--legacy", "--preds", "a.npz", "--ohlc", "o.npz",
                        "--out_dir", tmp])
        default.assert_not_called()

    def test_cli_target_default_refuses_without_adapter(self):
        with (patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp,
              self.assertRaises(LegacyBacktestDisabledError)):
            entry.main(["--mode", "target", "--preds", "a.npz",
                        "--full_ohlc", "f.npz", "--out_dir", tmp])


if __name__ == "__main__":
    unittest.main()
