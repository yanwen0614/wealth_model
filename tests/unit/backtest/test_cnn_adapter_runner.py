"""T04: runner 费用透传 + 策略选择（mock 隔离，零触网/零 parquet）。"""
import os
import shutil
import tempfile
import unittest
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from unittest import mock

import numpy as np

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache


@dataclass
class _FakeEngineResult:
    """最小引擎结果替身：须为 dataclass 以支持 runner 内 dataclasses.replace。"""

    trades: tuple = ()
    account_snapshots: tuple = ()
    methodology: object = None
    account_metrics: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    run_id: str = "fake"


def _make_pred_cache(testcase):

    codes = ["000001.SZ", "000002.SZ"]
    day = "2025-03-03"
    exp_ret = np.array([0.05, 0.02], dtype=np.float64)
    true_ret = np.array([0.01, 0.02], dtype=np.float64)
    dates = np.array([day] * 2, dtype="datetime64[D]")
    path = os.path.join(testcase.tmp, "preds_runner.npz")
    save_prediction_cache(path, exp_ret, true_ret, dates, np.asarray(codes))
    cache = load_prediction_cache(path)
    return cache


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t04r_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class _RunnerMixin(_TempDirMixin):
    def _run_with_capture(self, **kwargs):
        from backtest_core.contracts.result import MetricMethodology

        import backtest.cnn_adapter.runner as runner_mod

        captured = {}
        fake = _FakeEngineResult(methodology=MetricMethodology(), account_metrics={"m": 1.0},
                                 provenance={})

        def _fake_engine(*, dates, strategy, market, execution_config,
                         portfolio_config, cost_config, **rest):
            captured.update({"dates": dates, "strategy": strategy, "cost_config": cost_config,
                             "portfolio_config": portfolio_config, "rest": rest})
            fake.account_snapshots = tuple(SimpleNamespace(date=day, nav=1_000.0) for day in dates)
            return fake

        params = {"pred_cache": _make_pred_cache(self), "parquet_path": "dummy.parquet",
                  "model_name": "cnn_transformer", "checkpoint": "ckpt",
                  "bins_version": "BINS52_v1", "eval_script_version": "eval@v1",
                  "verify_account_metrics": False}
        params.update(kwargs)
        with mock.patch.object(runner_mod, "CnnMarketDataProvider",
                               lambda *a, **k: object()), \
            mock.patch.object(runner_mod, "CnnRawMarketDataProvider",
                              lambda *a, **k: object()), \
            mock.patch.object(runner_mod, "run_account_backtest_from_orders",
                              _fake_engine), \
            mock.patch.object(runner_mod, "evaluate_account",
                              lambda *a, **k: {"m": 1.0}):
            from backtest.cnn_adapter.runner import run_cnn_backtest

            outcome = run_cnn_backtest(**params)
        return outcome, captured


class TestRunnerDefaults(_RunnerMixin):
    def test_default_uses_cost_defaults_and_rolling_strategy(self):
        from backtest_core.contracts.config import CostConfig

        from backtest.cnn_adapter.order_strategy import CnnOrderStrategy

        outcome, captured = self._run_with_capture()
        self.assertEqual(captured["dates"], captured["rest"]["execution_calendar"])
        self.assertIsInstance(captured["strategy"], CnnOrderStrategy)
        default = CostConfig()
        got = captured["cost_config"]
        self.assertEqual(got.commission_rate_buy, default.commission_rate_buy)
        self.assertEqual(got.commission_rate_sell, default.commission_rate_sell)
        self.assertEqual(got.min_commission, default.min_commission)
        self.assertEqual(got.stamp_tax_rate, default.stamp_tax_rate)
        self.assertEqual(captured["portfolio_config"].top_n, 10)
        # hash 键集须含新参（直接断言源码 payload 含新键）。
        import inspect

        import backtest.cnn_adapter.runner as runner_mod

        source = inspect.getsource(runner_mod.run_cnn_backtest)
        for key in ("mode", "commission_rate_buy", "target_size", "strong_buy_threshold"):
            self.assertIn(key, source)
        self.assertEqual(len(outcome.config_hash), 40)
        self._default_hash = outcome.config_hash

    def test_tax_unknown_can_be_required_and_action_fingerprint_changes_hash(self):
        from datetime import date

        from backtest_core.contracts.config import ExecutionConfig
        from backtest_core.contracts.enums import ExecutionMode

        from backtest.cnn_adapter.ca.corporate_actions import CorporateActionEvent, CorporateActionProvider

        event = CorporateActionEvent(
            event_id="unknown-bonus", instrument_id="A.SZ", kind="bonus",
            source_table="dividend", source_row_id="row", source_snapshot_hash="hash-a",
            source_version="fixture", record_date=date(2025, 3, 3), ex_date=date(2025, 3, 4),
            pay_date=date(2025, 3, 5), listing_date=date(2025, 3, 6), share_ratio=0.1,
            ratio_denominator=10, rounding_rule="exact",
        )
        first_provider = CorporateActionProvider((event,))
        execution_calendar = tuple(date(2025, 3, day) for day in range(2, 7))
        base_params = {
            "corporate_action_provider": first_provider, "period_id": "W1",
            "execution_calendar": execution_calendar, "evaluation_end": date(2025, 3, 3),
            "raw_market_path": "raw.parquet",
            "execution_config": ExecutionConfig(execution_mode=ExecutionMode.T1_OPEN,
                                                 final_liquidation="mark"),
        }
        outcome, _ = self._run_with_capture(**base_params)
        self.assertEqual(outcome.provenance["corporate_action_share_tax_status"], "unknown")
        self.assertEqual(outcome.provenance["corporate_action_tax_completeness"],
                         "incomplete_unknown_share_tax")
        second_provider = CorporateActionProvider((replace(event, source_snapshot_hash="hash-b"),))
        changed_params = {**base_params, "corporate_action_provider": second_provider}
        changed, _ = self._run_with_capture(**changed_params)
        self.assertNotEqual(outcome.config_hash, changed.config_hash)
        self.assertNotEqual(outcome.provenance["corporate_action_fingerprint"],
                            changed.provenance["corporate_action_fingerprint"])
        with self.assertRaisesRegex(ValueError, "unknown share tax"):
            self._run_with_capture(
                **{**base_params, "require_known_share_tax": True},
            )

    def test_default_hash_stable_across_calls(self):
        first, _ = self._run_with_capture()
        second, _ = self._run_with_capture()
        self.assertEqual(first.config_hash, second.config_hash)


class TestRunnerPassthrough(_RunnerMixin):
    def test_explicit_fees_reach_cost_config(self):
        _, captured = self._run_with_capture(commission_rate_buy=0.0003,
                                             commission_rate_sell=0.0001,
                                             min_commission=1.0, stamp_tax_rate=0.001)
        got = captured["cost_config"]
        self.assertAlmostEqual(got.commission_rate_buy, 0.0003)
        self.assertAlmostEqual(got.commission_rate_sell, 0.0001)
        self.assertAlmostEqual(got.min_commission, 1.0)
        self.assertAlmostEqual(got.stamp_tax_rate, 0.001)

    def test_target_mode_builds_target_strategy_and_hash_changes(self):
        from backtest.cnn_adapter.target_strategy import CnnTargetOrderStrategy

        default_outcome, _ = self._run_with_capture()
        outcome, captured = self._run_with_capture(
            mode="target", top_n=10, target_size=5, sell_buffer=7,
            exit_on_nonpositive=True, exit_threshold=0.01, strong_buy_threshold=0.02)
        strategy = captured["strategy"]
        self.assertIsInstance(strategy, CnnTargetOrderStrategy)
        self.assertEqual(strategy.target_size, 5)
        self.assertEqual(strategy.sell_buffer, 7)
        self.assertTrue(strategy.exit_on_nonpositive)
        self.assertAlmostEqual(strategy.exit_threshold, 0.01)
        self.assertAlmostEqual(strategy.strong_buy_threshold, 0.02)
        self.assertEqual(captured["portfolio_config"].top_n, 5)
        self.assertNotEqual(outcome.config_hash, default_outcome.config_hash)

    def test_rolling_ignores_target_params(self):
        from backtest.cnn_adapter.order_strategy import CnnOrderStrategy

        _, captured = self._run_with_capture(mode="rolling", target_size=5)
        self.assertIsInstance(captured["strategy"], CnnOrderStrategy)
        self.assertEqual(captured["portfolio_config"].top_n, 10)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            self._run_with_capture(mode="bogus")

    def test_negative_strong_buy_raises_via_strategy(self):
        with self.assertRaises(ValueError):
            self._run_with_capture(mode="target", strong_buy_threshold=-0.01)


if __name__ == "__main__":
    unittest.main()
