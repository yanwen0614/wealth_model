"""N02 TDD：cnn 入口切换收口（红→绿），零触库/零触网。

为什么做：N01 遗留 + QG 2 Low 全部关闭——legacy 落盘带 engine 标记
（孤儿导出 consomme），默认路径 --ohlc 显式 WARNING，target 仅 legacy
决策锁定，默认 adapter 路径 CLI 端到端 smoke。
"""
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import scripts.run_backtest as entry
from backtest.legacy import LEGACY_ENGINE_NAME


def _args(**over):
    base = {"preds": ["p.npz"], "parquet": "q.parquet", "ohlc": None,
            "topn": [2], "initial_capital": 1000.0, "model_name": "m",
            "checkpoint": "c", "bins_version": "b", "eval_script_version": "e",
            "cost_rate": 0.0015, "horizon": 5}
    base.update(over)
    return SimpleNamespace(**base)


_FULL_METRICS = {"annual": 0.0, "sharpe": 0.0, "mdd": 0.0, "win_rate": 0.0}


class TestN02LegacyMetricsMarked(unittest.TestCase):
    def test_legacy_rolling_metrics_marked(self):
        import matplotlib
        matplotlib.use("Agg")
        ohlc = {"codes": np.array(["000001.SZ"]), "dates": np.array(["2026-01-01"]),
                "t_close": np.array([10.0]), "open_t1": np.array([10.0]),
                "open_t6": np.array([10.5])}
        preds = {"exp_ret": np.array([0.1]), "true_ret": np.array([0.01]),
                 "dates": np.array(["2026-01-01"]), "codes": np.array(["000001.SZ"])}
        res = SimpleNamespace(nav=np.array([1.0, 1.01]), holdings=np.array([]), skipped={})
        with (patch.object(entry, "load_ohlc", return_value=ohlc),
              patch.object(entry, "load_preds", return_value=preds),
              patch.object(entry, "benchmark_nav", return_value=np.array([1.0, 1.0])),
              patch.object(entry, "nav_metrics", return_value=dict(_FULL_METRICS)),
              patch.object(entry, "run_backtest", return_value=res),
              patch.object(entry, "save_holdings_csv"),
              patch.dict(os.environ, {"CNN_ALLOW_LEGACY": "1"}),
              tempfile.TemporaryDirectory() as tmp):
            entry.run_legacy_rolling(_args(ohlc="o.npz"), tmp)
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        self.assertTrue(saved["legacy"])
        self.assertEqual(saved["engine"], LEGACY_ENGINE_NAME)

    def test_target_metrics_marked(self):
        import matplotlib
        matplotlib.use("Agg")
        full = {"codes": np.array(["AAA"]), "dates": np.array(["2026-01-01"]),
                "open_m": np.array([[10.0]]), "close_m": np.array([[10.0]])}
        preds = {"exp_ret": np.array([0.1]), "true_ret": np.array([0.01]),
                 "dates": np.array(["2026-01-01"]), "codes": np.array(["AAA"])}
        res = SimpleNamespace(nav=np.array([1.0]), holdings=np.array([]), skipped={})
        args = _args(full_ohlc="f.npz", target_size=1, sell_buffer=0,
                     min_edge=0.01, edge_tail_pct=0.3, cost_rate=0.0015)
        with (patch.object(entry, "load_full_ohlc", return_value=full),
              patch.object(entry, "load_preds", return_value=preds),
              patch.object(entry, "run_backtest_target", return_value=res),
              patch.object(entry, "nav_metrics", return_value=dict(_FULL_METRICS)),
              patch.object(entry, "save_holdings_csv"),
              patch.dict(os.environ, {"CNN_ALLOW_LEGACY": "1"}),
              tempfile.TemporaryDirectory() as tmp):
            entry.run_target_mode(args, tmp)
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        self.assertTrue(saved["legacy"])
        self.assertEqual(saved["engine"], LEGACY_ENGINE_NAME)


class TestN02OhlcIgnoredWarning(unittest.TestCase):
    def test_default_path_warns_when_ohlc_given(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp,
              self.assertLogs(entry.logger, level="WARNING") as logs):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--ohlc", "o.npz", "--out_dir", tmp])
        default.assert_called_once()
        self.assertTrue(any("--ohlc" in m and "忽略" in m for m in logs.output))

    def test_default_path_no_warning_without_ohlc(self):
        with (patch.object(entry, "run_adapter_rolling") as default,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp,
              self.assertNoLogs(entry.logger, level="WARNING")):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--out_dir", tmp])
        default.assert_called_once()


class TestN02AdapterSmoke(unittest.TestCase):
    def test_cli_default_adapter_end_to_end(self):
        outcome = SimpleNamespace(account_evaluation={"total_return": 0.05, "sharpe": 0.8},
                                  provenance={}, config_hash="h", data_fingerprint="f")
        preds = {"exp_ret": [0.1], "true_ret": [0.01],
                 "dates": ["2026-01-01"], "codes": ["000001.SZ"]}
        with (patch.object(entry, "load_preds", return_value=preds),
              patch.object(entry, "run_cnn_backtest", return_value=outcome) as mocked,
              patch.dict(os.environ, {}, clear=True),
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--preds", "a.npz", "--parquet", "b.parquet",
                        "--topn", "2", "--out_dir", tmp])
            with open(f"{tmp}/metrics.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(saved["engine"], "cnn_adapter")
        self.assertNotIn("legacy", saved)
        self.assertAlmostEqual(saved["models"]["a"]["top2"]["final_nav"], 1050000.0)


if __name__ == "__main__":
    unittest.main()
