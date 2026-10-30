"""300502 单事件 floor/ceil 条件账户测试。"""

import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.contracts.account import AccountState
from backtest_core.contracts.account_actions import CreateShareEntitlement, ListShareEntitlement
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import Side
from backtest_core.contracts.order import OrderIntent
from backtest_core.contracts.protocols import MarketDataProvider
from backtest_core.engine.account import apply_account_actions, apply_sell, unlock_shares
from backtest_core.engine.account_runner import run_account_backtest_from_orders
from backtest_core.testing import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.corporate_action_snapshot_loader import load_corporate_action_snapshot
from backtest.cnn_adapter.fractional_scenario_cli import execute, validate_prefix_proof
from backtest.cnn_adapter.fractional_scenarios import (
    EVENT_ID,
    OFFICIAL_PDF_SHA256,
    SOURCE_ROWS_SHA256,
    Scenario,
    W1FractionalScenarioContext,
)
from backtest.cnn_adapter.staged_allocation import Policy
from backtest.cnn_adapter.staged_candidate_runner import StagedWindowConfig, WindowDefinition, run_staged_window

SOURCE_ROOT = Path(r"C:\Users\yanwen\AppData\Local\Temp\opencode\staged_execution_input_snapshot_20261027_v1")
OFFICIAL_PDF = Path(r"C:\Users\yanwen\AppData\Local\Temp\opencode\ca_300502_official_search3_20261028\cninfo_2021-030_1210131886.PDF")
MANIFEST_SHA = "e7b1a533a6853a1b995d4a84c713acbb62943cc55f785c472020d2d492b86bcf"


class _Orders:
    def orders_for(self, *, trading_date, **kwargs):
        if trading_date == date(2021, 6, 4):
            return (OrderIntent("300502.SZ", Side.BUY, shares=100),)
        if trading_date == date(2021, 6, 7):
            return (OrderIntent("300502.SZ", Side.SELL, shares=100, limit_price=46.18),)
        return ()


class FractionalScenarioTests(unittest.TestCase):
    def snapshot(self):
        snapshot = load_corporate_action_snapshot(SOURCE_ROOT, expected_manifest_sha256=MANIFEST_SHA)
        return replace(snapshot, descriptors=tuple(
            item for item in snapshot.descriptors if item.event_id == EVENT_ID))

    def make_mini_context(self, scenario: Scenario, pdf_path: Path = OFFICIAL_PDF):
        calendar = tuple(date.fromisoformat(day) for day in (
            "2021-06-03", "2021-06-04", "2021-06-07", "2021-06-08",
            "2021-06-09", "2021-06-10", "2021-06-11"))
        context = W1FractionalScenarioContext.__new__(W1FractionalScenarioContext)
        from backtest.cnn_adapter.corporate_action_context import CorporateActionContext

        snapshot = self.snapshot()
        pdf_sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        W1FractionalScenarioContext.validate_descriptor(
            snapshot.descriptors[0], pdf_sha, SOURCE_ROWS_SHA256)
        context.scenario = scenario
        context.official_pdf_sha256 = pdf_sha
        context.source_rows_sha256 = SOURCE_ROWS_SHA256
        context._resolution = None
        CorporateActionContext.__init__(context, snapshot, period_id="W1-mini",
            reset_anchor=calendar[0], empty_reset=True, strict_tax=False,
            tax_policy="cash_dividend_20pct_stress", window_end=calendar[-1])
        return context

    def test_w1_cutoff_context_can_be_built_without_proof_but_full_context_cannot(self):
        from backtest.cnn_adapter.fractional_scenarios import W1FractionalScenarioContext

        snapshot = self.snapshot()
        args = {"period_id": "W1", "reset_anchor": date(2020, 12, 31),
            "scenario": "floor", "official_pdf_path": OFFICIAL_PDF,
            "source_rows_sha256": SOURCE_ROWS_SHA256,
            "window_end": date(2021, 6, 7)}
        context = W1FractionalScenarioContext(snapshot, prefix_only=True, **args)
        self.assertEqual(context.window_end, date(2021, 6, 7))
        with self.assertRaisesRegex(ValueError, "not independently pinned"):
            W1FractionalScenarioContext(snapshot, **args)

    def test_conditional_full_window_requires_explicit_mode_and_keeps_unknown_status(self):
        from backtest.cnn_adapter.fractional_scenarios import W1FractionalScenarioContext

        context = W1FractionalScenarioContext(self.snapshot(), period_id="W1",
            reset_anchor=date(2020, 12, 31), scenario="floor",
            official_pdf_path=OFFICIAL_PDF, source_rows_sha256=SOURCE_ROWS_SHA256,
            window_end=date(2021, 7, 5), conditional_only=True,
            announcement_horizon=date(2021, 6, 30))
        evidence = context.evidence()
        self.assertEqual(evidence["certification"], "NOT_CERTIFIED_CONDITIONAL")
        self.assertEqual(evidence["pit"], "UNKNOWN")
        self.assertEqual(evidence["announcement_visibility"], "conditional_date_only")

    @staticmethod
    def write_self_reported_proof(path: Path) -> str:
        path.write_text(json.dumps({
            "status": "PASS", "base_head": "ce7d1c6e0bd64136f10759412c55f6da410f128f",
            "through_date": "2021-06-07", "canonical_prefix_match": True,
            "floor_ceil_prefix_match": True,
        }), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def write_structural_candidate_proof(path: Path) -> str:
        branches = {f"{p}:{s}" for p in ("B1", "S1", "S2", "C70")
                    for s in ("floor", "ceil")}
        ledgers = ("execution_updates.jsonl", "daily_registry.jsonl",
            "strategy_decisions.jsonl", "registry_transitions.jsonl",
            "partial_account_states.jsonl")
        comparisons = {branch: {name: {"raw_prefix_equal": True, "differences": []}
            for name in ledgers} for branch in branches}
        proof = {"schema_version": "w1_prefix_machine_proof_v1", "status": "PASS",
            "base_head": "ce7d1c6e0bd64136f10759412c55f6da410f128f",
            "through_date": "2021-06-07", "canonical_prefix_match": True,
            "floor_ceil_prefix_match": True, "trusted_prefix_proof_sha256": None,
            "trusted_attestation_root_sha256": "d" * 64,
            "trusted_pin_state": "UNPINNED_AT_GENERATION", "comparisons": comparisons,
            "baseline_runs": {p: {} for p in ("B1", "S1", "S2", "C70")},
            "scenario_runs": {branch: {} for branch in branches},
            "fee_knowledge": {"PIT": "UNKNOWN", "source_availability": "UNKNOWN",
                              "actual_broker_fees": "UNKNOWN"},
            "required_runs": ([f"{p}:default" for p in ("B1", "S1", "S2", "C70")] +
                [f"{p}:{s}" for p in ("B1", "S1", "S2", "C70") for s in ("floor", "ceil")])}
        canonical = json.dumps(proof, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")
        proof["proof_sha256"] = hashlib.sha256(canonical).hexdigest()
        path.write_text(json.dumps(proof), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_eight_branch_executor_keeps_failed_and_incomplete_directories(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "runs"
            proof = Path(temporary) / "proof.json"
            digest = self.write_structural_candidate_proof(proof)
            commands = [{"branch": f"W1_P{i}_floor", "output_dir": str(root / f"W1_P{i}_floor"),
                         "argv": ["python", "-B"]} for i in range(8)]
            calls = 0

            def run(argv, **kwargs):
                nonlocal calls
                calls += 1
                code = 1 if calls % 2 else 0
                return subprocess.CompletedProcess(argv, code, "out", "err")

            with (patch("backtest.cnn_adapter.fractional_prefix_gate.TRUSTED_PREFIX_PROOF_SHA256", digest),
                  patch("backtest.cnn_adapter.fractional_scenario_cli.subprocess.run", side_effect=run)):
                results = execute(commands, root, proof, digest)
            self.assertEqual(len(results), 8)
            self.assertEqual([item["status"] for item in results],
                             ["FAILED", "INCOMPLETE"] * 4)
            self.assertTrue(all((root / str(item["branch"])).is_dir() for item in results))
            self.assertTrue((root / "branch_status.json").is_file())

    def test_direct_executor_rejects_before_output_or_subprocess(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "runs"
            proof = Path(temporary) / "proof.json"
            digest = self.write_self_reported_proof(proof)
            commands = [{"branch": "W1_B1_floor", "output_dir": str(root / "branch"),
                         "argv": ["python", "-B"]}]
            with patch("backtest.cnn_adapter.fractional_scenario_cli.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "prefix proof"):
                    execute(commands, root, proof, digest)
            run.assert_not_called()
            self.assertFalse(root.exists())

    def test_fractional_batch_cli_rejects_before_reading_inputs(self):
        from backtest.cnn_adapter import fractional_scenario_cli

        argv = ["fractional", "--prepared-manifest", "missing-manifest.json",
                "--input-config", "missing-config.json", "--official-pdf", "missing.pdf",
                "--output-root", "unused", "--execute"]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(ValueError, "prefix proof"):
                fractional_scenario_cli.main()

    def test_prefix_cli_runs_and_attests_without_preexisting_proof(self):
        from backtest.cnn_adapter import fractional_scenario_cli

        argv = ["fractional", "--prepared-manifest", "manifest.json", "--input-config", "config.json",
            "--official-pdf", "official.pdf", "--output-root", "outputs", "--run-prefixes",
            "--attestation-plan", "plan.json", "--attestation-root",
            "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_w1_prefix_fix5_attestation_20261028/attestation.json"]
        completed = [{"branch": f"W1_B{i}_floor", "status": "COMPLETE"} for i in range(8)]
        with (patch.object(sys, "argv", argv),
              patch.object(fractional_scenario_cli, "write_attestation_plan"),
              patch.object(fractional_scenario_cli, "build_commands", return_value=[]),
              patch.object(fractional_scenario_cli, "execute", return_value=completed) as execute_run,
              patch.object(fractional_scenario_cli.subprocess, "run",
                  return_value=subprocess.CompletedProcess([], 0, "a" * 64, "")) as attest):
            fractional_scenario_cli.main()
        self.assertTrue(execute_run.call_args.kwargs["prefix_only"])
        self.assertIn("prefix_attestor", attest.call_args.args[0][3])

    def test_cutoff_command_set_is_buildable_without_existing_proof(self):
        from backtest.cnn_adapter.fractional_scenario_cli import build_commands

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {"initial_capital": 1000000, "tax_policy": "pretax",
                "windows": {"W1": {"source_id": "F4", "signal_path": "signal.parquet",
                    "signal_sha256": "a" * 64, "checkpoint_sha256": "b" * 64,
                    "anchor": "2020-12-31", "evaluation_end": "2021-06-30"}}}
            prepared = root / "prepared.json"
            input_config = root / "config.json"
            prepared.write_text(json.dumps({"schema_version": "staged_prepared_v1",
                "config": config, "output_dir": str(root)}), encoding="utf-8")
            input_config.write_text(json.dumps(config), encoding="utf-8")
            with patch("backtest.cnn_adapter.fractional_scenario_cli.file_sha256",
                       return_value="a" * 64):
                commands = build_commands(prepared, input_config, OFFICIAL_PDF,
                    root / "outputs", prefix_only=True)
            self.assertEqual(len(commands), 8)
            for command in commands:
                argv = cast(list[str], command["argv"])
                self.assertIn("--prefix-stop-after-close", argv)
                self.assertIn("--information-cutoff", argv)
                self.assertIn("--prefix-experiment", argv)
                self.assertNotIn("--prefix-proof", argv)
                self.assertFalse(any(flag in argv for flag in
                    ("--prepared-core-path", "--prepared-core-sha256",
                     "--runtime-core-path", "--runtime-core-sha256")))
            with patch("backtest.cnn_adapter.fractional_scenario_cli.subprocess.run",
                       side_effect=lambda argv, **kwargs:
                           subprocess.CompletedProcess(argv, 0, "", "")):
                results = execute(commands, root / "outputs", prefix_only=True)
            self.assertEqual(len(results), 8)
            with patch("backtest.cnn_adapter.fractional_scenario_cli.file_sha256",
                       return_value="a" * 64):
                conditional = build_commands(prepared, input_config, OFFICIAL_PDF,
                    root / "conditional", conditional_only=True)
            self.assertEqual(len(conditional), 8)
            for command in conditional:
                argv = cast(list[str], command["argv"])
                self.assertIn("--conditional-simulation", argv)
                self.assertNotIn("--prefix-stop-after-close", argv)
                self.assertNotIn("--prefix-proof", argv)
            with patch("backtest.cnn_adapter.fractional_scenario_cli.subprocess.run",
                       side_effect=lambda argv, **kwargs:
                           subprocess.CompletedProcess(argv, 0, "", "")):
                results = execute(conditional, root / "conditional",
                                  conditional_only=True)
            self.assertTrue(all(row["certification"] == "NOT_CERTIFIED_CONDITIONAL"
                                for row in results))

    def test_direct_full_runner_rejects_before_output_input_or_core(self):
        anchor = date(2020, 12, 31)
        calendar = tuple(anchor + timedelta(days=i) for i in range(185))
        window = WindowDefinition(anchor, date(2021, 6, 30), calendar)
        config = StagedWindowConfig("W1", "a" * 64, "b" * 64, 100_000., Policy.B1,
                                    period_id="W1")
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            proof = Path(temporary) / "proof.json"
            digest = self.write_self_reported_proof(proof)
            with patch("backtest.cnn_adapter.staged_candidate_runner._run_staged_window_impl") as core:
                with self.assertRaisesRegex(ValueError, "prefix proof"):
                    run_staged_window(window=window, config=config,
                        signal_parquet_path=Path(temporary) / "heavy-missing.parquet",
                        market=SyntheticMarketProvider(()), fractional_scenario="floor",
                        official_pdf_path=OFFICIAL_PDF, corporate_action_snapshot=self.snapshot(),
                        prefix_proof_path=proof, expected_prefix_proof_sha256=digest,
                        output_dir=output)
            core.assert_not_called()
            self.assertFalse(output.exists())

    def test_mini_labels_cannot_disguise_a_full_window(self):
        anchor = date(2020, 12, 31)
        calendar = tuple(anchor + timedelta(days=i) for i in range(185))
        window = WindowDefinition(anchor, date(2021, 6, 30), calendar)
        config = StagedWindowConfig("w1-mini", "a" * 64, "b" * 64, 100_000., Policy.B1,
                                    period_id="W1-mini")
        with TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "prefix proof"):
                run_staged_window(window=window, config=config,
                    signal_parquet_path=Path(temporary) / "heavy-missing.parquet",
                    market=SyntheticMarketProvider(()), fractional_scenario="floor",
                    official_pdf_path=OFFICIAL_PDF, corporate_action_snapshot=self.snapshot())

    def test_runner_cli_rejects_before_loading_signal_or_calendar(self):
        from backtest.cnn_adapter import staged_candidate_runner

        argv = ["runner", "--signal-parquet", "missing.parquet", "--expected-sha256", "a" * 64,
                "--source-id", "W1", "--checkpoint-sha256", "b" * 64,
                "--anchor-date", "2020-12-31", "--evaluation-end", "2021-06-30",
                "--execution-calendar", "missing-calendar.txt", "--policy", "B1",
                "--output-dir", "unused", "--input-config", "missing-config.json",
                "--fractional-scenario", "floor"]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(ValueError, "prefix proof"):
                staged_candidate_runner.main()

    def test_runner_cli_prefix_mode_reaches_cutoff_inputs_without_proof(self):
        from backtest.cnn_adapter import staged_candidate_runner

        argv = ["runner", "--signal-parquet", "missing.parquet", "--expected-sha256", "a" * 64,
            "--source-id", "W1", "--checkpoint-sha256", "b" * 64,
            "--anchor-date", "2020-12-31", "--evaluation-end", "2021-06-30",
            "--execution-calendar", "missing-calendar.txt", "--policy", "B1",
            "--output-dir", "unused", "--input-config", "missing-config.json",
            "--fractional-scenario", "floor", "--prefix-stop-after-close", "2021-06-07",
            "--information-cutoff", "2021-06-07"]
        with patch.object(sys, "argv", argv):
            with self.assertRaisesRegex(FileNotFoundError, "日历文件不存在"):
                staged_candidate_runner.main()

    def test_single_runner_api_rejects_before_loading_config(self):
        from backtest.cnn_adapter.staged_production_inputs import run_single_from_cli

        anchor = date(2020, 12, 31)
        calendar = tuple(anchor + timedelta(days=i) for i in range(185))
        window = WindowDefinition(anchor, date(2021, 6, 30), calendar)
        args = SimpleNamespace(fractional_scenario="floor", prefix_proof=None,
                               expected_prefix_proof_sha256=None, input_config="missing.json")
        with self.assertRaisesRegex(ValueError, "prefix proof"):
            run_single_from_cli(args, window)

    def test_direct_full_context_requires_pin_before_reading_official_pdf(self):
        with self.assertRaisesRegex(ValueError, "prefix proof"):
            W1FractionalScenarioContext(
                self.snapshot(), period_id="W1", reset_anchor=date(2020, 12, 31),
                scenario="floor", official_pdf_path=Path("missing-official.pdf"),
                source_rows_sha256=SOURCE_ROWS_SHA256, window_end=date(2021, 7, 3),
            )

    def test_direct_mini_context_construction_requires_bounded_runner(self):
        with self.assertRaisesRegex(ValueError, "bounded mini runner"):
            W1FractionalScenarioContext(
                self.snapshot(), period_id="W1-mini", reset_anchor=date(2021, 6, 3),
                scenario="floor", official_pdf_path=OFFICIAL_PDF,
                source_rows_sha256=SOURCE_ROWS_SHA256, window_end=date(2021, 6, 11),
            )

    def test_staged_mini_runner_rejects_provider_with_forged_class_identity(self):
        calendar = tuple(date.fromisoformat(day) for day in (
            "2021-06-03", "2021-06-04", "2021-06-07", "2021-06-08",
            "2021-06-09", "2021-06-10", "2021-06-11"))
        window = WindowDefinition(calendar[0], calendar[3], calendar)
        fake_type = type("SyntheticMarketProvider", (), {
            "__module__": "backtest_core.testing.forged"})
        with TemporaryDirectory() as temporary:
            signal_path = Path(temporary) / "mini.parquet"
            rows = [{"date": day, "code": f"code{i}", "exp_ret": 1. - i * .1,
                     "status": "ready", "buy_eligible": True}
                    for day in window.signal_dates for i in range(5)]
            pq.write_table(pa.Table.from_pylist(rows), signal_path)
            digest = hashlib.sha256(signal_path.read_bytes()).hexdigest()
            config = StagedWindowConfig("w1-mini", digest, "b" * 64, 10_000., Policy.B1,
                                        period_id="W1-mini")
            output = Path(temporary) / "run"
            with self.assertRaisesRegex(ValueError, "prefix proof"):
                run_staged_window(window=window, config=config, signal_parquet_path=signal_path,
                    market=cast(MarketDataProvider, fake_type()),
                    corporate_action_snapshot=self.snapshot(), fractional_scenario="floor",
                    official_pdf_path=OFFICIAL_PDF, output_dir=output)
            self.assertFalse(output.exists())

    def test_no_publicly_callable_factory_returns_unbound_mini_context(self):
        self.assertFalse(hasattr(W1FractionalScenarioContext, "_from_bounded_mini_runner"))
        self.assertFalse(hasattr(
            W1FractionalScenarioContext,
            "_W1FractionalScenarioContext__initialize_context"))

    def test_self_supplied_prefix_hash_cannot_unlock_performance(self):
        with TemporaryDirectory() as temporary:
            proof = Path(temporary) / "proof.json"
            proof.write_text(json.dumps({
                "status": "PASS", "base_head": "ce7d1c6e0bd64136f10759412c55f6da410f128f",
                "through_date": "2021-06-07", "canonical_prefix_match": True,
                "floor_ceil_prefix_match": True,
            }), encoding="utf-8")
            digest = hashlib.sha256(proof.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "pinned"):
                validate_prefix_proof(proof, digest)

    def test_floor_and_ceil_use_decimal_and_disclose_unknowns(self):
        floor = W1FractionalScenarioContext.resolve(100, "floor")
        ceil = W1FractionalScenarioContext.resolve(100, "ceil")
        self.assertEqual(floor.exact_entitlement, Decimal("40.0253200"))
        self.assertEqual((floor.integer_shares, ceil.integer_shares), (40, 41))
        self.assertEqual(floor.original_ratio, Decimal("0.4002532"))
        self.assertEqual(floor.production_acceptance, "BLOCKED")
        self.assertFalse(floor.actual_after_tax_target_eligible)
        self.assertTrue(floor.tax_unknown)

    def test_registered_ceil_entitlements_use_authoritative_integer_bridge(self):
        target = self.snapshot().descriptors[0]
        for quantity, expected in ((1300, 521), (2800, 1121), (4000, 1602)):
            with self.subTest(quantity=quantity):
                context = self.make_mini_context("ceil")
                context._validate_positive(target, float(quantity))
                resolution = context._resolution
                self.assertIsNotNone(resolution)
                assert resolution is not None
                self.assertEqual(resolution.integer_shares, expected)
                self.assertEqual(quantity * float(resolution.effective_ratio), float(expected))

    def test_large_registration_floor_ceil_create_and_list_exact_integer_shares(self):
        for quantity in (1300, 2800, 4000):
            for scenario in ("floor", "ceil"):
                with self.subTest(quantity=quantity, scenario=scenario):
                    context = self.make_mini_context(scenario)
                    resolution = W1FractionalScenarioContext.resolve(quantity, scenario)
                    state = AccountState(
                        cash=quantity * 35., available_cash=quantity * 35.,
                        positions={"300502.SZ": float(quantity)},
                        locked={"300502.SZ": float(quantity)},
                        cost={"300502.SZ": 35.}, last_marks={"300502.SZ": 35.},
                    )
                    record_day = date(2021, 6, 7)
                    record_actions = context.account_actions_for_day(record_day)
                    state = apply_account_actions(state, record_actions, record_day)
                    context.post_state = state
                    ex_day = date(2021, 6, 8)
                    actions = context.account_actions_for_day(ex_day)
                    created = apply_account_actions(state, tuple(
                        action for action in actions if isinstance(action, CreateShareEntitlement)), ex_day)
                    listed = apply_account_actions(created, tuple(
                        action for action in actions if isinstance(action, ListShareEntitlement)), ex_day)
                    self.assertEqual(listed.positions["300502.SZ"], quantity + resolution.integer_shares)
                    self.assertAlmostEqual(
                        listed.cost["300502.SZ"] * (quantity + resolution.integer_shares),
                        quantity * 35., places=5)


    def test_only_bound_source_identity_can_enable_scenario(self):
        self.assertEqual(len(OFFICIAL_PDF_SHA256), 64)
        self.assertEqual(len(SOURCE_ROWS_SHA256), 64)
        with self.assertRaisesRegex(ValueError, "restricted to W1"):
            W1FractionalScenarioContext(
                self.snapshot(), period_id="W2", reset_anchor=date(2021, 6, 3),
                scenario="floor", official_pdf_path=OFFICIAL_PDF,
                source_rows_sha256=SOURCE_ROWS_SHA256,
            )
        with self.assertRaises(ValueError):
            W1FractionalScenarioContext.validate_identity(
                event_id="dividend:other", source_file_sha256=SOURCE_ROWS_SHA256,
                official_pdf_sha256=OFFICIAL_PDF_SHA256,
                instrument_id="300502.SZ", record_date=date(2021, 6, 7),
                ex_date=date(2021, 6, 8), listing_date=date(2021, 6, 8),
                share_ratio=Decimal("0.4002532"), row_sha256="bad",
            )
        with self.assertRaisesRegex(ValueError, "source identity"):
            W1FractionalScenarioContext.validate_descriptor(
                self.snapshot().descriptors[0], "0" * 64, SOURCE_ROWS_SHA256)
        for quantity in (0, -1):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                W1FractionalScenarioContext.resolve(quantity, "floor")

    def test_fractional_event_does_not_apply_to_altered_source_or_dates(self):
        base = {"event_id": EVENT_ID, "source_file_sha256": SOURCE_ROWS_SHA256,
                "official_pdf_sha256": OFFICIAL_PDF_SHA256, "instrument_id": "300502.SZ",
                "record_date": date(2021, 6, 7), "ex_date": date(2021, 6, 8),
                "listing_date": date(2021, 6, 8), "share_ratio": Decimal("0.4002532"),
                "row_sha256": "5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462"}
        for field, value in (("source_file_sha256", "a" * 64),
                             ("official_pdf_sha256", "b" * 64),
                             ("record_date", date(2021, 6, 8)),
                             ("share_ratio", Decimal("0.4"))):
            altered = {**base, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                W1FractionalScenarioContext.validate_identity(**altered)

    def test_zero_record_position_cannot_silently_skip_injection(self):
        ctx = self.make_mini_context("floor")
        ctx.post_state = AccountState(cash=1., available_cash=1., positions={}, locked={}, cost={}, last_marks={})
        with self.assertRaisesRegex(ValueError, "scenario_requires_positive_record_position"):
            ctx.account_actions_for_day(date(2021, 6, 8))
        with self.assertRaisesRegex(ValueError, "cannot run beyond its fixed window"):
            ctx.account_actions_for_day(date(2021, 6, 14))

    def test_missing_official_pdf_cannot_be_bypassed_by_supplied_hash(self):
        with self.assertRaises(FileNotFoundError):
            self.make_mini_context("floor", Path("missing-official.pdf"))

    def test_real_core_floor_and_ceil_registration_listing_and_limit_rejection(self):
        calendar = (date(2021, 6, 3), date(2021, 6, 4), date(2021, 6, 7),
                    date(2021, 6, 8), date(2021, 6, 9))
        cases: tuple[tuple[Scenario, int], ...] = (("floor", 140), ("ceil", 141))
        for scenario, expected in cases:
            ctx = self.make_mini_context(scenario)
            market = SyntheticMarketProvider(
                make_bar("300502.SZ", day, 35.0 if day < calendar[2] else 34.55,
                         high=35.0 if day < calendar[2] else 34.55)
                for day in calendar
            )
            result = run_account_backtest_from_orders(
                execution_calendar=calendar, signal_dates=calendar[1:-1], anchor_date=calendar[0],
                strategy=_Orders(), market=market, observer=ctx,
                account_actions_provider=ctx.account_actions_for_day,
                execution_config=ExecutionConfig(final_liquidation="mark"),
                portfolio_config=PortfolioConfig(top_n=10),
                cost_config=CostConfig(commission_rate=0., min_commission=0.,
                                       stamp_tax_rate=0., transfer_fee_rate=0.),
                run_id=f"w1-mini-{scenario}", model_id="mini", initial_capital=10000.,
            )
            self.assertEqual(result.account_snapshots[2].positions["300502.SZ"].shares, 100)
            self.assertEqual(result.account_snapshots[-1].positions["300502.SZ"].shares, expected)
            self.assertEqual(ctx.evidence()["fractional_scenario"]["integer_shares"], expected - 100)
            self.assertEqual(ctx.evidence()["production_acceptance"], "BLOCKED")
            self.assertTrue(ctx.evidence()["actual_unknown"])
            self.assertIn("tax_unknown", ctx.evidence()["unknown"][EVENT_ID])
            ex_snapshot = next(item for item in result.account_snapshots if item.date == date(2021, 6, 8))
            self.assertAlmostEqual(ex_snapshot.gross_cash_dividends_paid, 27.17082)
            self.assertAlmostEqual(ex_snapshot.withheld_cash_dividends_paid, 27.17082 * .2)
            self.assertAlmostEqual(
                result.account_snapshots[-1].positions["300502.SZ"].cost * expected,
                result.account_snapshots[2].positions["300502.SZ"].cost * 100,
                places=6,
            )
            self.assertTrue(any(
                item.order.limit_price == 46.18 and item.status.value == "rejected"
                for item in result.order_results
            ))
            class NoCost:
                def calculate(self, side, amount):
                    return (0.0, 0.0, 0.0)

            assert ctx.post_state is not None
            rejected = apply_sell(ctx.post_state, "300502.SZ", 50, 34.55, NoCost())
            self.assertFalse(rejected.filled)
            assert rejected.reason is not None
            self.assertEqual(rejected.reason.value, "zero_lot")
            closed = apply_sell(ctx.post_state, "300502.SZ", expected, 34.55, NoCost())
            self.assertTrue(closed.filled)
            self.assertEqual(closed.shares, expected)
            self.assertNotIn("300502.SZ", closed.state.positions)

    def test_default_context_still_rejects_noninteger_event(self):
        from backtest.cnn_adapter.corporate_action_context import CorporateActionContext

        context = CorporateActionContext(
            self.snapshot(), period_id="W1-production", reset_anchor=date(2021, 6, 3),
            empty_reset=True, strict_tax=False,
        )
        calendar = (date(2021, 6, 3), date(2021, 6, 4), date(2021, 6, 7), date(2021, 6, 8))
        market = SyntheticMarketProvider(make_bar("300502.SZ", day, 35.) for day in calendar)
        with self.assertRaisesRegex(ValueError, "noninteger_or_unrepresentable_share_quantity"):
            run_account_backtest_from_orders(
                execution_calendar=calendar, signal_dates=calendar[1:-1], anchor_date=calendar[0],
                strategy=_Orders(), market=market, observer=context,
                account_actions_provider=context.account_actions_for_day,
                execution_config=ExecutionConfig(final_liquidation="mark"),
                portfolio_config=PortfolioConfig(), cost_config=CostConfig(),
                run_id="w1-mini-production", model_id="mini", initial_capital=10000.,
            )

    def test_non_whitelisted_event_remains_strictly_fail_closed(self):
        snapshot = load_corporate_action_snapshot(SOURCE_ROOT, expected_manifest_sha256=MANIFEST_SHA)
        other = next(item for item in snapshot.descriptors
                     if item.event_id != EVENT_ID and item.event is not None
                     and (item.event.share_ratio or item.event.gross_cash_per_share))
        context = self.make_mini_context("floor")
        with self.assertRaises(ValueError):
            context._validate_positive(other, 100.)
        self.assertFalse(context.strict_tax)

    def test_core_unlisted_to_listed_transfer_conserves_basis(self):
        ctx = self.make_mini_context("floor")
        state = AccountState(cash=6500., available_cash=6500., positions={"300502.SZ": 100.},
                             locked={"300502.SZ": 100.},
                             cost={"300502.SZ": 35.}, last_marks={"300502.SZ": 35.})
        record_day = date(2021, 6, 7)
        state = apply_account_actions(state, ctx.account_actions_for_day(record_day), record_day)
        ctx.post_state = state
        ex_day = date(2021, 6, 8)
        actions = ctx.account_actions_for_day(ex_day)
        created = apply_account_actions(state, tuple(
            action for action in actions if isinstance(action, CreateShareEntitlement)), ex_day)
        self.assertEqual(next(iter(created.unlisted_entitlements.values())).shares, 40)
        entitlement_basis = next(iter(created.unlisted_entitlements.values())).cost_basis_total
        old_basis = created.positions["300502.SZ"] * created.cost["300502.SZ"]
        self.assertAlmostEqual(old_basis + entitlement_basis, 3500.)
        listed = apply_account_actions(created, tuple(
            action for action in actions if isinstance(action, ListShareEntitlement)), ex_day)
        self.assertEqual(listed.positions["300502.SZ"], 140)
        self.assertFalse(listed.unlisted_entitlements)
        self.assertAlmostEqual(listed.cost["300502.SZ"] * 140, 3500.)

        class NoCost:
            def calculate(self, side, amount):
                return (0.0, 0.0, 0.0)

        locked_sale = apply_sell(listed, "300502.SZ", 140, 35., NoCost())
        assert locked_sale.reason is not None
        self.assertEqual(locked_sale.reason.value, "locked_position")
        unlocked = unlock_shares(listed, "300502.SZ", 100)
        closed = apply_sell(unlocked, "300502.SZ", 140, 35., NoCost())
        self.assertTrue(closed.filled)
        self.assertEqual(closed.shares, 140)
        self.assertNotIn("300502.SZ", closed.state.positions)

    def test_staged_runner_uses_real_slot_bridge_with_scenario(self):
        calendar = tuple(date.fromisoformat(day) for day in (
            "2021-06-03", "2021-06-04", "2021-06-07", "2021-06-08",
            "2021-06-09", "2021-06-10", "2021-06-11"))
        window = WindowDefinition(anchor_date=calendar[0], evaluation_end=calendar[3],
                                  execution_calendar=calendar)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            signal_path = root / "signals.parquet"
            codes = ["300502.SZ", "000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
            rows = [{"date": day, "code": code, "exp_ret": 1.0 - index * .1,
                     "status": "ready", "buy_eligible": True}
                    for day in window.signal_dates for index, code in enumerate(codes)]
            pq.write_table(pa.Table.from_pylist(rows), signal_path)
            signal_sha = hashlib.sha256(signal_path.read_bytes()).hexdigest()
            bars = [make_bar(code, day, 35. if day < calendar[3] else 34.55,
                             high=35. if day < calendar[3] else 34.55,
                             absolute_limit_up_price=100., absolute_limit_down_price=1.)
                    for code in codes for day in calendar]
            cfg = StagedWindowConfig(
                source_id="w1-mini", signal_file_sha256=signal_sha,
                checkpoint_sha256="b" * 64, initial_capital=100_000., policy=Policy.B1,
                tax_policy="cash_dividend_20pct_stress",
                cost_config=CostConfig(commission_rate=0., min_commission=0.,
                                       stamp_tax_rate=0., transfer_fee_rate=0.),
                period_id="W1-mini",
            )
            outcome = run_staged_window(
                window=window, config=cfg, signal_parquet_path=signal_path,
                market=SyntheticMarketProvider(bars), corporate_action_snapshot=self.snapshot(),
                fractional_scenario="floor", official_pdf_path=OFFICIAL_PDF,
                output_dir=root / "run",
            )
            self.assertGreater(int(outcome.provenance["episode_count"]), 0)
            evidence = json.loads((root / "run" / "corporate_action_evidence.json").read_text())
            self.assertEqual(evidence["fractional_scenario"]["scenario"], "floor")
            daily = [json.loads(line) for line in
                     (root / "run" / "daily_registry.jsonl").read_text().splitlines()]
            record_state = next(row for row in daily if row["date"] == "2021-06-07")
            self.assertIn("300502.SZ", record_state["occupied_codes"])
            self.assertLessEqual(max(row["registry"]["active_slots"] for row in daily), 5)
