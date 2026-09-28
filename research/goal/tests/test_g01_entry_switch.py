"""G01 TDD：goal 主入口切换契约（红→绿），零触库/零触网。

为什么做：阶段 3 直接切换要求 `backtest/engine.py` 默认走 adapter 订单
路径；旧 quintile 体显式隔离（opt-in 才可达），旧回归出口一律拒绝。
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import backtest.engine as entry
import goal_adapter.runner as runner_mod
from backtest.legacy import LegacyBacktestDisabledError
from goal_adapter.runner import run_goal_backtest


def _args(**over):
    base = {"pred": "p.parquet", "market": "m.parquet", "out": "o",
            "strategy": "daily", "top_n": None, "sell_buffer": None,
            "min_amount": 1e8, "capital": 1000.0, "model_name": "m",
            "model_artifact": "a", "feature_version": "f",
            "script_version": "s", "legacy": False}
    base.update(over)
    return SimpleNamespace(**base)


def _synthetic(tmpdir: str) -> tuple[str, str, list[date]]:
    """2 码 × 10 日确定性上涨合成双源（沿 C05 回归口径，全 mock/合成零触网）。"""
    days = [date(2025, 3, 3) + timedelta(days=i) for i in range(10)]
    mkt_rows, pred_rows = [], []
    for day_index, day in enumerate(days):
        for code_index, code in enumerate(("AAA.SZ", "BBB.SH")):
            price = round(10.0 + day_index * 0.5 + code_index, 2)
            mkt_rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": price,
                             "high": price, "low": price, "close": price,
                             "volume": 2_000_000.0, "amount": 2_000_000.0 * price,
                             "is_trading": True})
            pred_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                              "score": float(code_index), "future_ret_5d": 0.01, "q_true": 1})
    mkt_path = os.path.join(tmpdir, "mkt.parquet")
    pred_path = os.path.join(tmpdir, "pred.parquet")
    pd.DataFrame(mkt_rows).to_parquet(mkt_path, index=False)
    pd.DataFrame(pred_rows).to_parquet(pred_path, index=False)
    return mkt_path, pred_path, days


class TestG01AdapterDefault(unittest.TestCase):
    def test_default_marks_engine_and_nav(self):
        outcome = SimpleNamespace(account_metrics={"total_return": 0.1}, final_nav=1100.0,
                                  provenance={"top_n": "2"}, config_hash="h",
                                  data_fingerprint="f", manifest={})
        with (patch.object(runner_mod, "run_goal_backtest", return_value=outcome) as mocked,
              tempfile.TemporaryDirectory() as tmp):
            entry.run_adapter_default(_args(), tmp)
            with open(f"{tmp}/backtest.json", encoding="utf-8") as f:
                saved = json.load(f)
        mocked.assert_called_once()
        self.assertEqual(saved["engine"], "goal_adapter")
        self.assertNotIn("legacy", saved)
        self.assertAlmostEqual(saved["final_nav"], 1100.0)

    def test_runner_synthetic_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            mkt_path, pred_path, days = _synthetic(tmp)
            outcome = run_goal_backtest(
                pred_path=pred_path, market_path=mkt_path, strategy="daily",
                top_n=1, sell_buffer=0, min_amount_yuan=0.0, initial_capital=1000.0,
                model_name="g01", model_artifact="g01.pkl",
                feature_version="g01", script_version="g01")
        self.assertEqual(len(outcome.account_result.account_snapshots), len(days))
        self.assertGreater(outcome.final_nav, 0.0)
        self.assertEqual(outcome.provenance["order_entry"], "atomic_orders_cash_budget")
        for key in ("config_hash", "data_fingerprint", "order_entry", "provenance"):
            self.assertIn(key, outcome.manifest)


class TestG01LegacyIsolation(unittest.TestCase):
    def test_legacy_requires_opt_in(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(LegacyBacktestDisabledError):
            entry.run_legacy_quintile(_args(), "out")

    def test_legacy_regression_always_refuses(self):
        with patch.dict(os.environ, {"GOAL_ALLOW_LEGACY": "1"}), self.assertRaises(LegacyBacktestDisabledError):
            entry.run_legacy_regression()

    def test_old_engine_marked(self):
        self.assertTrue(entry.OLD_LOGIC)


class TestG01CliRouting(unittest.TestCase):
    def test_cli_default_routes_to_adapter(self):
        with (patch.object(entry, "run_adapter_default") as default,
              patch.object(entry, "run_legacy_quintile") as legacy,
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--pred", "p", "--market", "m", "--out", tmp])
        default.assert_called_once()
        legacy.assert_not_called()

    def test_cli_legacy_routes_with_opt_in(self):
        with (patch.object(entry, "run_adapter_default") as default,
              patch.object(entry, "run_legacy_quintile") as legacy,
              patch.dict(os.environ, {"GOAL_ALLOW_LEGACY": "1"}),
              tempfile.TemporaryDirectory() as tmp):
            entry.main(["--pred", "p", "--out", tmp, "--legacy"])
        legacy.assert_called_once()
        default.assert_not_called()


if __name__ == "__main__":
    unittest.main()
