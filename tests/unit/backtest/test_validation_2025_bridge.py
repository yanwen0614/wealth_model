"""2025 NPZ 桥接与调度门禁的微型行为测试。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.contracts.config import CostConfig
from backtest_core.contracts.enums import Side
from backtest_core.testing.synthetic import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.staged_allocation import Policy
from backtest.cnn_adapter.staged_candidate_runner import (
    StagedWindowConfig,
    WindowDefinition,
    build_signal_ranking,
    load_frozen_signal_parquet,
    run_staged_window,
)
from backtest.cnn_adapter.validation_2025_bridge import (
    EligibilityDecision,
    FrozenParquetResult,
    NpzSignal,
    Validation2025Error,
    assert_ab_equivalent,
    convert_npz_to_frozen_parquet,
    derive_buy_eligibility,
    load_npz_signal,
)
from scripts.run_2025_ab_execution import (
    COMMON_ANCHOR,
    EVALUATION_END,
    FROZEN_PROTOCOL,
    _load_candidate_states,
    build_2025_window,
    load_prepared_manifest,
    prepare_ab_bridges,
    validate_prepared_manifest,
)
from scripts.run_2025_ab_execution import main as scheduler_main


def write_npz(path: Path, *, dates=None, codes=None, true_ret=None) -> str:
    day_values = np.asarray(dates or ["2025-01-02"], dtype="datetime64[us]")
    code_values = np.asarray(codes or ["000001.SZ"])
    true_values = np.asarray(true_ret if true_ret is not None else [0.01] * len(day_values),
                             dtype=np.float64)
    np.savez(path, dates=day_values, codes=code_values,
             exp_ret=np.full(len(day_values), 0.2), true_ret=true_values)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_source_report(path, npz_sha, checkpoint_sha, config_sha, produced_at):
    report = {"npz_sha256": npz_sha, "checkpoint_sha256": checkpoint_sha,
              "config_sha256": config_sha, "produced_at": produced_at,
              "model_horizon": 10}
    path.write_text(json.dumps(report), encoding="utf-8")


class NpzBridgeTests(unittest.TestCase):
    def test_npz_identity_and_first_signal_day_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "a.npz"
            digest = write_npz(source)
            signal = load_npz_signal(source, expected_sha256=digest)
            self.assertEqual(signal.dates, (date(2025, 1, 2),))
            self.assertEqual(signal.codes, ("000001.SZ",))
            self.assertEqual(signal.exp_ret, (0.2,))

    def test_bad_hash_schema_duplicates_nonfinite_and_order_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "a.npz"
            digest = write_npz(source)
            with self.assertRaises(Validation2025Error):
                load_npz_signal(source, expected_sha256="0" * 64)
            duplicate = root / "duplicate.npz"
            write_npz(duplicate, dates=["2025-01-02", "2025-01-02"],
                      codes=["000001.SZ", "000001.SZ"], true_ret=[0.01, 0.02])
            with self.assertRaises(Validation2025Error):
                load_npz_signal(duplicate, expected_sha256=hashlib.sha256(
                    duplicate.read_bytes()).hexdigest())
            b = root / "b.npz"
            write_npz(b, codes=["000002.SZ"])
            with self.assertRaises(Validation2025Error):
                assert_ab_equivalent(load_npz_signal(source, expected_sha256=digest),
                                     load_npz_signal(b, expected_sha256=hashlib.sha256(
                                         b.read_bytes()).hexdigest()))

    def test_ab_true_ret_and_row_order_are_exact_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            left, right = root / "a.npz", root / "b.npz"
            base = ["2025-01-02", "2025-01-03"]
            np.savez(left, dates=np.asarray(base, dtype="datetime64[us]"),
                     codes=np.asarray(["000001.SZ", "000002.SZ"]),
                     exp_ret=np.asarray([.2, .1]), true_ret=np.asarray([.01, -.02]))
            np.savez(right, dates=np.asarray(base, dtype="datetime64[us]"),
                     codes=np.asarray(["000001.SZ", "000002.SZ"]),
                     exp_ret=np.asarray([.8, -.1]), true_ret=np.asarray([.01, -.03]))
            load = lambda path: load_npz_signal(path, expected_sha256=hashlib.sha256(
                path.read_bytes()).hexdigest())
            with self.assertRaises(Validation2025Error):
                assert_ab_equivalent(load(left), load(right))
            reordered = root / "reordered.npz"
            np.savez(reordered, dates=np.asarray(base[::-1], dtype="datetime64[us]"),
                codes=np.asarray(["000002.SZ", "000001.SZ"]),
                exp_ret=np.asarray([.1, .2]), true_ret=np.asarray([-.02, .01]))
            with self.assertRaises(Validation2025Error):
                assert_ab_equivalent(load(left), load(reordered))

    def test_nonfinite_and_bad_npz_shape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.npz"
            np.savez(path, dates=np.asarray(["2025-01-02"], dtype="datetime64[us]"),
                     codes=np.asarray(["000001.SZ"]), exp_ret=np.asarray([np.inf]),
                     true_ret=np.asarray([0.01]))
            with self.assertRaises(Validation2025Error):
                load_npz_signal(path, expected_sha256=hashlib.sha256(
                    path.read_bytes()).hexdigest())

    def test_unknown_execution_state_is_explicitly_ineligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "signal.npz"
            digest = write_npz(path)
            signal = load_npz_signal(path, expected_sha256=digest)
            signal_day = date(2025, 1, 2)
            execution_day = date(2025, 1, 3)
            state = {"market_state": "unknown", "st_known": False,
                     "reference_known": True, "limit_known": False,
                     "limit_up": False, "limit_down": False,
                     "listing_known": True, "quantity_rule_known": True,
                     "corporate_action_known": True}
            decisions = derive_buy_eligibility(signal,
                (date(2024, 12, 31), date(2025, 1, 2), execution_day),
                {("000001.SZ", signal_day): state})
            decision = decisions[signal_day, "000001.SZ"]
            self.assertFalse(decision.buy_eligible)
            self.assertIn("market_state='unknown'", decision.reasons)
            self.assertIn("limit_known_unknown", decision.reasons)


class CoreMiniLedgerTests(unittest.TestCase):
    def test_parquet_write_failure_leaves_no_published_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "a.npz"
            source_sha = write_npz(source)
            checkpoint = root / "model.pth"
            checkpoint.write_bytes(b"mini-checkpoint")
            config = root / "config.json"
            config.write_text(json.dumps({"HORIZON": 10}), encoding="utf-8")
            report = root / "source-report.json"
            checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            produced_at = "2026-10-29T12:00:00+08:00"
            write_source_report(report, source_sha, checkpoint_sha, config_sha, produced_at)
            state_source = root / "state.parquet"
            state_source.write_bytes(b"mini state source")
            output = root / "signals"
            eligibility = {(date(2025, 1, 2), "000001.SZ"):
                           EligibilityDecision(True, "trading", ())}

            with patch("backtest.cnn_adapter.validation_2025_bridge.pq.ParquetWriter",
                       side_effect=OSError("simulated disk failure")):
                with self.assertRaisesRegex(OSError, "simulated disk failure"):
                    convert_npz_to_frozen_parquet(
                        source, expected_npz_sha256=source_sha,
                        checkpoint_path=checkpoint,
                        expected_checkpoint_sha256=checkpoint_sha,
                        config_path=config, expected_config_sha256=config_sha,
                        source_report_path=report,
                        expected_report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                        produced_at=produced_at, eligibility=eligibility,
                        state_source_path=state_source,
                        expected_state_source_sha256=hashlib.sha256(
                            state_source.read_bytes()).hexdigest(),
                        output_dir=output)

            self.assertFalse(output.exists())

    def test_second_ab_bridge_failure_publishes_no_partial_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = {}
            for name in ("A", "B"):
                npz = root / f"{name}.npz"
                npz_sha = write_npz(npz)
                files = {}
                for key in ("checkpoint", "config", "source_report"):
                    path = root / f"{name}_{key}.bin"
                    path.write_bytes(name.encode())
                    files[key] = str(path)
                sources[name] = {
                    "npz": str(npz), "npz_sha256": npz_sha,
                    "checkpoint": files["checkpoint"], "checkpoint_sha256": "a" * 64,
                    "config": files["config"], "config_sha256": "b" * 64,
                    "source_report": files["source_report"],
                    "source_report_sha256": "c" * 64,
                    "produced_at": "2026-10-29T12:00:00+08:00",
                }
            state_path = root / "states.parquet"
            state_path.write_bytes(b"states")
            signal_day = date(2025, 1, 2)
            verified = {
                "execution_calendar": (date(2024, 12, 31), signal_day, date(2025, 1, 3)),
                "benchmark_dates": (signal_day,),
                "artifacts": [{"role": "verified_states", "path": state_path,
                               "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest()}],
                "status": "READY_FOR_INDEPENDENT_QA", "manifest_sha256": "d" * 64,
                "coverage": {},
                "benchmark_closes": {date(2024, 12, 31): 100.0,
                                     EVALUATION_END: 110.0},
            }
            output = root / "ab-bridges"
            call_count = 0

            def fail_on_b(*args, output_dir, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("simulated B bridge failure")
                output_dir.mkdir(parents=True)
                signal_path = output_dir / "signals.parquet"
                signal_path.write_bytes(b"partial A")
                return FrozenParquetResult(signal_path, "e" * 64, "f" * 64, 1, "a" * 64)

            with (patch("scripts.run_2025_ab_execution.build_2025_window",
                        return_value=SimpleNamespace(signal_dates=(signal_day,))),
                  patch("scripts.run_2025_ab_execution._load_candidate_states",
                        return_value={("000001.SZ", signal_day): {}}),
                  patch("scripts.run_2025_ab_execution.derive_buy_eligibility",
                        return_value={(signal_day, "000001.SZ"):
                                      EligibilityDecision(True, "trading", ())}),
                  patch("scripts.run_2025_ab_execution.convert_npz_to_frozen_parquet",
                        side_effect=fail_on_b)):
                with self.assertRaisesRegex(OSError, "simulated B bridge failure"):
                    prepare_ab_bridges({"signal_sources": sources}, base_dir=root,
                                       verified=verified, output_dir=output)

            self.assertEqual(call_count, 2)
            self.assertFalse(output.exists())

    def test_bridge_drives_real_core_and_snapshots_balance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._run_core_fixture(root)

    def _run_core_fixture(self, root: Path) -> None:
        days = tuple(date.fromisoformat(value) for value in (
            "2024-12-31", "2025-01-02", "2025-01-03", "2025-01-06",
            "2025-01-07", "2025-01-08", "2025-01-09"))
        codes = tuple(f"00000{i}.SZ" for i in range(1, 6))
        signal_days = days[1:4]
        npz_path = root / "mini.npz"
        np.savez(npz_path, dates=np.asarray([d.isoformat() for d in signal_days
            for _ in codes], dtype="datetime64[us]"),
            codes=np.asarray(list(codes) * len(signal_days)),
            exp_ret=np.asarray([.05 - i * .01 for _ in signal_days for i in range(5)]),
            true_ret=np.asarray([.01] * (len(signal_days) * len(codes))))
        self._run_core_fixture_with_inputs(root, days, codes, npz_path)

    def _run_core_fixture_with_inputs(self, root, days, codes, npz_path):
        checkpoint = root / "weights.pth"
        checkpoint.write_bytes(b"fixture")
        config = root / "model.json"
        config.write_text('{"HORIZON":10}', encoding="utf-8")
        report = root / "source.json"
        source_sha = hashlib.sha256(npz_path.read_bytes()).hexdigest()
        checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
        produced_at = "2026-10-29T12:00:00+08:00"
        write_source_report(report, source_sha, checkpoint_sha, config_sha, produced_at)
        state_source = root / "states.parquet"
        state_source.write_bytes(b"mini state source")
        eligible = {(day, code): EligibilityDecision(True, "trading", ())
                    for day in days[1:4] for code in codes}
        result = convert_npz_to_frozen_parquet(
            npz_path, expected_npz_sha256=source_sha,
            checkpoint_path=checkpoint, expected_checkpoint_sha256=checkpoint_sha,
            config_path=config, expected_config_sha256=config_sha,
            source_report_path=report, expected_report_sha256=hashlib.sha256(
                report.read_bytes()).hexdigest(), produced_at=produced_at,
            eligibility=eligible, state_source_path=state_source,
            expected_state_source_sha256=hashlib.sha256(state_source.read_bytes()).hexdigest(),
            output_dir=root / "signals")
        bars = [make_bar(code, day, close=10., open_=10., high=10., low=10.,
                         volume=1_000_000, amount=10_000_000,
                         absolute_limit_up_price=20., absolute_limit_down_price=1.)
                for code in codes for day in days]
        window = WindowDefinition(days[0], days[3], days)
        cfg = StagedWindowConfig(source_id="mini_2025", signal_file_sha256=result.parquet_sha256,
            checkpoint_sha256=hashlib.sha256(b"fixture").hexdigest(),
            initial_capital=1_000_000, policy=Policy.B1, cost_config=CostConfig(),
            tax_policy="pretax", period_id="mini_2025")
        outcome = run_staged_window(window=window, config=cfg,
            signal_parquet_path=result.path, market=SyntheticMarketProvider(bars),
            output_dir=root / "core-output")
        self.assertEqual(outcome.config.policy, Policy.B1)
        self.assertEqual(outcome.window.buffer_dates, days[4:])
        self.assertTrue(outcome.result.account_snapshots)
        self.assertFalse(any(trade.side is Side.BUY and trade.execution_time.date() in days[4:]
                             for trade in outcome.result.trades))
        for snap in outcome.result.account_snapshots:
            self.assertLessEqual(len([p for p in snap.positions.values() if p.shares > 0]), 10)
            value = (snap.cash + snap.receivables_value
                     + sum(p.market_value or 0 for p in snap.positions.values())
                     + sum(e.market_value for e in snap.unlisted_entitlements.values()))
            self.assertAlmostEqual(value, snap.nav, places=6)


    def test_parquet_is_bound_to_npz_checkpoint_config_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "a.npz"
            source_sha = write_npz(source)
            checkpoint = root / "model.pth"
            checkpoint.write_bytes(b"mini-checkpoint")
            config = root / "config.json"
            config.write_text(json.dumps({"HORIZON": 10}), encoding="utf-8")
            report = root / "source-report.json"
            checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
            produced_at = "2026-10-29T12:00:00+08:00"
            write_source_report(report, source_sha, checkpoint_sha, config_sha, produced_at)
            state_source = root / "state.parquet"
            state_source.write_bytes(b"mini state source")
            eligibility = {(date(2025, 1, 2), "000001.SZ"):
                           EligibilityDecision(False, "unknown", ("limit_known_unknown",))}
            result = convert_npz_to_frozen_parquet(
                source, expected_npz_sha256=source_sha,
                checkpoint_path=checkpoint, expected_checkpoint_sha256=checkpoint_sha,
                config_path=config, expected_config_sha256=config_sha, source_report_path=report,
                expected_report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                produced_at=produced_at, eligibility=eligibility,
                state_source_path=state_source, expected_state_source_sha256=hashlib.sha256(
                    state_source.read_bytes()).hexdigest(),
                output_dir=root / "frozen")
            self.assertEqual(result.source_sha256, source_sha)
            self.assertEqual(result.row_count, 1)
            self.assertTrue((root / "frozen" / "signals.parquet").is_file())
            rows, parquet_sha = load_frozen_signal_parquet(
                result.path, expected_sha256=result.parquet_sha256)
            loaded = rows[date(2025, 1, 2)][0]
            self.assertEqual((loaded["exp_ret"], loaded["true_ret"]), (0.2, 0.01))
            self.assertFalse(loaded["buy_eligible"])
            ranking = build_signal_ranking("A", rows)[date(2025, 1, 2)]
            self.assertEqual(dict(ranking.ranks), {"000001.SZ": 1})
            self.assertFalse(ranking.buy_eligible["000001.SZ"])
            self.assertEqual(parquet_sha, result.parquet_sha256)
            local = convert_npz_to_frozen_parquet(
                source, expected_npz_sha256=source_sha, checkpoint_path=checkpoint,
                expected_checkpoint_sha256=checkpoint_sha, config_path=config,
                expected_config_sha256=config_sha, produced_at=produced_at,
                eligibility=eligibility, state_source_path=state_source,
                expected_state_source_sha256=hashlib.sha256(state_source.read_bytes()).hexdigest(),
                output_dir=root / "local-identity")
            local_rows, _ = load_frozen_signal_parquet(
                local.path, expected_sha256=local.parquet_sha256)
            self.assertEqual(local_rows[date(2025, 1, 2)][0]["identity_status"], "IDENTITY_LOCAL")

    def test_horizon_must_come_from_hashed_model_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "model.json"
            config.write_text('{"HORIZON":5}', encoding="utf-8")
            with self.assertRaisesRegex(Validation2025Error, "HORIZON=10"):
                from backtest.cnn_adapter.validation_2025_bridge import _validate_config
                _validate_config(config, hashlib.sha256(config.read_bytes()).hexdigest())

    def test_window_anchors_before_first_signal_and_uses_common_benchmark_days(self):
        calendar = tuple(date.fromisoformat(value) for value in (
            "2024-12-31", "2025-01-02", "2025-12-16", "2025-12-17",
            "2025-12-18", "2025-12-19"))
        window = build_2025_window(calendar)
        self.assertEqual(window.anchor_date, COMMON_ANCHOR)
        self.assertEqual(window.signal_dates[0], date(2025, 1, 2))
        self.assertEqual(window.evaluation_end, EVALUATION_END)
        self.assertEqual(window.buffer_dates, calendar[-3:])
        with self.assertRaises(Validation2025Error):
            build_2025_window((date(2025, 1, 2), *calendar[2:]))

    def test_missing_state_or_corporate_action_manifest_fails_with_missing_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {"schema_version": "validation_2025_prepared_v1",
                        "protocol": FROZEN_PROTOCOL,
                        "artifacts": [], "coverage": {}}
            with self.assertRaises(Validation2025Error) as error:
                validate_prepared_manifest(manifest, base_dir=root)
            self.assertIn("verified_states", str(error.exception))
            self.assertIn("corporate_actions", str(error.exception))

    def test_scheduler_rejects_policy_budget_or_slippage_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            altered = dict(FROZEN_PROTOCOL)
            altered["max_slots"] = 10
            manifest = {"schema_version": "validation_2025_prepared_v1",
                        "protocol": altered, "artifacts": [], "coverage": {}}
            with self.assertRaisesRegex(Validation2025Error, "冻结B1"):
                validate_prepared_manifest(manifest, base_dir=Path(temp))

    def test_cli_reports_missing_data_sources_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "prepared.json"
            manifest.write_text(json.dumps({"schema_version": "validation_2025_prepared_v1",
                "protocol": FROZEN_PROTOCOL, "artifacts": [], "coverage": {}}),
                encoding="utf-8")
            output = root / "should_not_exist"
            code = scheduler_main(["--prepared-manifest", str(manifest),
                "--expected-manifest-sha256", hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "--bridge-output-dir", str(output)])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_run_prepared_cli_dispatches_to_account_executor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prepared = root / "manifest.json"
            prepared.write_text("{}", encoding="utf-8")
            manifest, verified = {}, {"status": "INCOMPLETE", "artifacts": []}
            bridge = {"schema_version": "validation_2025_ab_bridge_v1"}
            execution = {"status": "COMPLETED"}
            with (patch("scripts.run_2025_ab_execution.load_prepared_manifest",
                        return_value=(manifest, "a" * 64)),
                  patch("scripts.run_2025_ab_execution.validate_prepared_manifest",
                        return_value=verified),
                  patch("scripts.run_2025_ab_execution.prepare_ab_bridges",
                        return_value=bridge) as prepare,
                  patch("scripts.run_2025_ab_execution.run_prepared_accounts",
                        return_value=execution) as run_accounts):
                code = scheduler_main(["--prepared-manifest", str(prepared),
                    "--expected-manifest-sha256", "a" * 64,
                    "--bridge-output-dir", str(root / "bridges"), "--run-prepared",
                    "--run-root", str(root / "runs")])
            self.assertEqual(code, 0)
            prepare.assert_called_once()
            run_accounts.assert_called_once()

    def test_manifest_mapping_cannot_substitute_for_actual_byte_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "prepared.json"
            path.write_text('{"schema_version":"validation_2025_prepared_v1"}',
                            encoding="utf-8")
            with self.assertRaises(Validation2025Error):
                load_prepared_manifest(path, expected_sha256="a" * 64)
            manifest, actual = load_prepared_manifest(
                path, expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(manifest["schema_version"], "validation_2025_prepared_v1")
            self.assertEqual(actual, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_state_parquet_missing_candidate_key_remains_ranked_but_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.parquet"
            pq.write_table(pa.Table.from_pylist([{"code": "000002.SZ",
                "date": date(2025, 1, 3), "market_state": "trading",
                 "st_known": True, "reference_known": True, "limit_known": True,
                 "limit_up": False, "limit_down": False, "listing_known": True,
                 "quantity_rule_known": True, "corporate_action_known": True,
                 "st_flag": False, "absolute_limit_up_price": 11.,
                 "absolute_limit_down_price": 9.}]), path)
            signal = NpzSignal((date(2025, 1, 2),), ("000001.SZ",),
                               (0.1,), (0.01,), "e" * 64)
            calendar = (date(2024, 12, 31), date(2025, 1, 2), date(2025, 1, 3))
            coverage = {}
            states = _load_candidate_states(path, signal, calendar, coverage=coverage)
            self.assertEqual(coverage["missing_signal_state_count"], 1)
            decision = derive_buy_eligibility(signal, calendar, states)
            self.assertFalse(decision[date(2025, 1, 2), "000001.SZ"].buy_eligible)


if __name__ == "__main__":
    unittest.main()
