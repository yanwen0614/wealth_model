"""前缀账本 verifier 的字节、顺序与字段篡改测试。"""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from backtest.cnn_adapter.prefix_ledger_verifier import (
    W1_PREFIX_REQUIRED_LEDGERS,
    compare_jsonl,
    generate_prefix_proof,
    verify_ledger_directories,
    verify_machine_prefix_proof,
    write_blocked_prefix_record,
)


class PrefixLedgerVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.replay = self.root / "replay"
        self.baseline.mkdir()
        self.replay.mkdir()
        self.left = self.baseline / "ledger.jsonl"
        self.right = self.replay / "ledger.jsonl"

    def tearDown(self) -> None:
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
                path.chmod(0o666)
        self.temp.cleanup()

    def _write_pair(self, left: list[dict], right: list[dict]) -> None:
        for path, rows in ((self.left, left), (self.right, right)):
            path.write_bytes(b"".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                for row in rows
            ))

    def _write_required_pair(self, rows: list[dict]) -> None:
        payload = b"".join(json.dumps(row, sort_keys=True).encode() + b"\n" for row in rows)
        for name in W1_PREFIX_REQUIRED_LEDGERS:
            (self.baseline / name).write_bytes(payload)
            (self.replay / name).write_bytes(payload)

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _create_machine_proof_inputs(self):
        from backtest_core.engine import run_account_backtest_from_orders

        import backtest.cnn_adapter.prefix_ledger_verifier as verifier

        baseline_hashes, audit_hashes, artifacts_hashes = {}, {}, {}
        signal_path = self.root / "signal_W1.parquet"
        table = pa.table({"date": pa.array([date(2021, 6, 7)], type=pa.date32()),
            "code": ["300502.SZ"], "exp_ret": [0.1], "status": ["ok"],
            "buy_eligible": [True]})
        pq.write_table(table, signal_path)
        prepared_path, prereg_path = self.root / "prepared.json", self.root / "prereg.json"
        prereg_path.write_text("prereg", encoding="utf-8")
        input_config_path, pdf_path = self.root / "config.json", self.root / "official.pdf"
        config_body = {"windows": {"W1": {"source_id": "F4"}}}
        self._write_json(input_config_path, config_body)
        pdf_path.write_bytes(b"fixture-pdf")
        prepared_body = {"schema_version": "staged_prepared_v1", "config": config_body,
            "core_path": str(verifier.ORIGINAL_CORE_PATH.resolve()),
            "core_sha256": verifier.ORIGINAL_CORE_SHA256, "artifacts": {
            str(prereg_path.resolve()): self._sha(prereg_path),
            str(signal_path.resolve()): self._sha(signal_path)}}
        self._write_json(prepared_path, prepared_body)
        prepared_path.with_suffix(".sha256").write_text(
            self._sha(prepared_path), encoding="ascii")
        import backtest.cnn_adapter.prefix_attestor as attestor
        attestor.PREPARED_MANIFEST_SHA256 = self._sha(prepared_path)
        attestor.OFFICIAL_PDF_SHA256 = self._sha(pdf_path)
        signal_sha = self._sha(signal_path)
        source_manifest = {"core_sha256": verifier.ORIGINAL_CORE_SHA256,
            "artifacts": {str(signal_path): signal_sha}}
        source_sha = None
        for policy in verifier.POLICIES:
            directory = self.baseline / f"W1_{policy}"
            directory.mkdir()
            ledger_hashes = {}
            for name in W1_PREFIX_REQUIRED_LEDGERS:
                rows = [{"date": "2021-06-07", "policy": policy, "sequence_no": seq}
                        for seq in (1, 2)]
                (directory / name).write_text("".join(
                    json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
                ledger_hashes[name] = self._sha(directory / name)
            config = {"period_id": "W1", "policy": policy, "source_id": "F4",
                "signal_file_sha256": signal_sha, "checkpoint_sha256": "b" * 64}
            audit = {"mechanical_status": "INCOMPLETE", "config": config,
                "window": {"anchor_date": "2021-06-04", "evaluation_end": "2021-06-07",
                    "execution_calendar": ["2021-06-04", "2021-06-07"]},
                "error": {"reason": "dividend:27726: noninteger_or_unrepresentable_share_quantity"}}
            self._write_json(directory / "attempt_audit.json", audit)
            self._write_json(directory / "sources_manifest.json", source_manifest)
            artifacts = {path.name: self._sha(path) for path in directory.iterdir()}
            self._write_json(directory / "artifacts.json", artifacts)
            source_sha = self._sha(directory / "sources_manifest.json")
            baseline_hashes[policy] = ledger_hashes
            audit_hashes[policy] = self._sha(directory / "attempt_audit.json")
            artifacts_hashes[policy] = self._sha(directory / "artifacts.json")
        self._create_scenario_runs(verifier, inspect.getfile(run_account_backtest_from_orders),
            baseline_hashes, signal_path, prepared_path, prereg_path)
        attestation_path, attestation_sha, attestor_sha = self._write_external_attestation(
            verifier, signal_path, prepared_path, prereg_path)
        return (verifier, baseline_hashes, audit_hashes, artifacts_hashes, source_sha,
                self._sha(prepared_path), self._sha(prereg_path),
                attestation_path, attestation_sha, attestor_sha)

    def _write_external_attestation(self, verifier, signal_path: Path,
                                    prepared_path: Path, prereg_path: Path):
        import backtest.cnn_adapter.prefix_attestor as attestor
        source_hashes = attestor.fixed_source_sha256()
        config_path, pdf_path = self.root / "config.json", self.root / "official.pdf"
        input_hashes = {str(path.resolve()): self._sha(path) for path in
            (signal_path, prepared_path, prepared_path.with_suffix(".sha256"),
             prereg_path, config_path, pdf_path)}
        branches, access_records = {}, {}
        for policy in verifier.POLICIES:
            for scenario in verifier.SCENARIOS:
                branch = f"W1_{policy}_{scenario}"
                directory = self.replay / branch
                files = {path.relative_to(directory).as_posix(): self._sha(path)
                         for path in directory.iterdir() if path.is_file()}
                branches[branch] = {"path": str(directory.resolve()), "files": files}
                access_records[branch] = {}
                copy_root = self.root / "readonly_access" / branch
                copy_root.mkdir(parents=True)
                for name in verifier.ACCESS_FILES:
                    source = directory / name
                    copy = copy_root / name
                    copy.write_bytes(source.read_bytes())
                    copy.chmod(0o444)
                    access_records[branch][name] = {"sha256": self._sha(source),
                        "records": len(source.read_text(encoding="utf-8").splitlines()),
                        "read_only": True, "external_path": str(copy.resolve())}
        attestor_sha = self._sha(Path(attestor.__file__))
        experiment = json.loads((self.replay / "W1_B1_floor" / "prefix_experiment.json").read_text())
        root = {"schema_version": "w1_prefix_external_attestation_v1",
            "status": "PINNED", "attestor_sha256": attestor_sha,
            "trusted_attestor_sha256": attestor_sha,
            "plan_sha256": "e" * 64, "cutoff": "2021-06-07",
            "source_sha256": source_hashes, "input_sha256": input_hashes,
            "prefix_experiment_identity": experiment,
            "prepared_manifest_path": str(prepared_path.resolve()),
            "input_config_path": str(config_path.resolve()),
            "official_pdf_path": str(pdf_path.resolve()),
            "branches": branches, "read_only_access_records": access_records}
        path = self.root / "attestation.json"
        self._write_json(path, root)
        path.chmod(0o444)
        return path, self._sha(path), attestor_sha

    def _create_scenario_runs(self, verifier, core_path: str, baseline_hashes: dict,
                              signal_path: Path, prepared_path: Path, prereg_path: Path) -> None:
        core_sha = self._sha(Path(core_path))
        experiment = {"schema_version": "w1_dual_core_prefix_identity_v1",
            "experiment_id": "w1_dual_core_cutoff_2021-06-07_v1", "cutoff": "2021-06-07",
            "prepared_manifest_path": str(prepared_path.resolve()),
            "prepared_manifest_sha256": self._sha(prepared_path),
            "prepared_core_path": str(verifier.ORIGINAL_CORE_PATH.resolve()),
            "prepared_core_sha256": verifier.ORIGINAL_CORE_SHA256,
            "runtime_core_path": str(Path(core_path).resolve()),
            "runtime_core_sha256": core_sha, "runtime_import_path": str(Path(core_path).resolve()),
            "pit": "UNKNOWN", "actual_after_tax_target_eligible": False}
        experiment["experiment_config_sha256"] = verifier._canonical_sha(experiment)
        resolver_path = Path(verifier.__file__).with_name("historical_costs.py")
        resolver_sha = self._sha(resolver_path)
        from backtest.cnn_adapter.staged_candidate_runner import (
            _signal_content_fingerprint,
            load_frozen_signal_parquet,
        )
        signal_sha = self._sha(signal_path)
        signal_rows, _ = load_frozen_signal_parquet(signal_path, signal_sha)
        content_sha = _signal_content_fingerprint(signal_rows)
        for policy in verifier.POLICIES:
            config = {"period_id": "W1", "policy": policy, "source_id": "F4",
                "signal_file_sha256": signal_sha, "checkpoint_sha256": "b" * 64}
            scope_sha = verifier._canonical_sha({"source_id": "F4", "checkpoint_sha256": "b" * 64,
                "signal_sha256": signal_sha, "policy": policy})
            calendar_sha = verifier._canonical_sha(["2021-06-04", "2021-06-07"])
            universe_sha = verifier._canonical_sha(["300502.SZ"])
            for scenario in verifier.SCENARIOS:
                branch = f"W1_{policy}_{scenario}"
                directory = self.replay / branch
                directory.mkdir()
                identity = {"branch": branch, "output_dir": str(directory.resolve()),
                    "policy": policy, "scenario": scenario, "period_id": "W1",
                    "cutoff": "2021-06-07", "config_sha256": verifier._canonical_sha(config),
                    "signal_sha256": signal_sha, "signal_content_sha256": content_sha,
                    "signal_path": str(signal_path.resolve()), "checkpoint_sha256": "b" * 64,
                    "prepared_manifest_sha256": self._sha(prepared_path),
                    "prepared_manifest_path": str(prepared_path.resolve()),
                    "preregistration_sha256": self._sha(prereg_path),
                    "preregistration_path": str(prereg_path.resolve()), "scope_sha256": scope_sha,
                    "core_path": core_path, "core_sha256": core_sha,
                    "runtime_core_path": str(Path(core_path).resolve()),
                    "runtime_core_sha256": core_sha,
                    "prefix_experiment_id": experiment["experiment_id"],
                    "prepared_core_path": experiment["prepared_core_path"],
                    "prepared_core_sha256": experiment["prepared_core_sha256"],
                    "experiment_config_sha256": experiment["experiment_config_sha256"],
                    "calendar_sha256": calendar_sha, "universe_sha256": universe_sha,
                    "universe_codes": ["300502.SZ"],
                    "created_at_utc": "2026-10-28T00:00:00+00:00"}
                audit = {"mechanical_status": "PASS", "config": config,
                    "window": {"anchor_date": "2021-06-04", "evaluation_end": "2021-06-07",
                        "execution_calendar": ["2021-06-04", "2021-06-07"]},
                    "controlled_run_identity": identity}
                self._write_json(directory / "attempt_audit.json", audit)
                self._write_json(directory / "prefix_experiment.json", experiment)
                evidence = {"fractional_scenario": {"scenario": scenario,
                    "event_id": "dividend:27726:5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462"}}
                self._write_json(directory / "corporate_action_evidence.json", evidence)
                for name in W1_PREFIX_REQUIRED_LEDGERS:
                    (directory / name).write_bytes(
                        (self.baseline / f"W1_{policy}" / name).read_bytes())
                (directory / "prefix_market_access.jsonl").write_bytes(b"")
                (directory / "prefix_ranking_access.jsonl").write_bytes(b"")
                (directory / "quantity_rule_usage.jsonl").write_bytes(b"")
                bundle = {"schema_version": "cutoff_fee_bundle_v2",
                    "information_cutoff": "2021-06-07",
                    "generated_at_utc": "2026-10-28T00:00:00+00:00",
                    "preregistration_sha256": self._sha(prereg_path), "scope_sha256": scope_sha,
                    "calendar_sha256": calendar_sha, "universe_sha256": universe_sha,
                    "markets": {"SSE_A": {}, "SZSE_A": {}},
                    "resolver_source": {"path": str(resolver_path), "sha256": resolver_sha},
                    "knowledge": {"pit_evidence": "UNKNOWN",
                        "source_availability": "UNKNOWN", "actual_broker_fees": "UNKNOWN"}}
                bundle["sha256"] = verifier._canonical_sha(bundle)
                fee_row = {"information_cutoff": "2021-06-07",
                    "future_execution_fee_source": "static_config_asof_cutoff",
                    "cutoff_fee_bundle": bundle}
                (directory / "prefix_fee_policy.jsonl").write_text(
                    json.dumps(fee_row, sort_keys=True) + "\n", encoding="utf-8")
                artifacts = {path.name: self._sha(path) for path in directory.iterdir()}
                self._write_json(directory / "artifacts.json", artifacts)

    def test_identical_bytes_are_diagnostic_only(self) -> None:
        rows = [{"sequence_no": 1, "event_id": "a"}, {"sequence_no": 2, "event_id": "b"}]
        self._write_required_pair(rows)
        result = verify_ledger_directories(
            self.baseline, self.replay, W1_PREFIX_REQUIRED_LEDGERS)
        self.assertTrue(result["rows_identical"])
        self.assertNotIn("status", result)

    def test_reordered_rows_fail_without_sorting(self) -> None:
        first = {"sequence_no": 1, "event_id": "a"}
        second = {"sequence_no": 2, "event_id": "b"}
        self._write_pair([first, second], [second, first])
        result = compare_jsonl(self.left, self.right)
        self.assertFalse(result["raw_bytes_equal"])
        self.assertEqual([item["line"] for item in result["differences"]], [1, 1, 2, 2])

    def test_missing_row_fails(self) -> None:
        self._write_pair([{"sequence_no": 1}, {"sequence_no": 2}], [{"sequence_no": 1}])
        result = compare_jsonl(self.left, self.right)
        self.assertEqual(result["differences"][0]["kind"], "missing_or_extra_row")

    def test_changed_field_and_duplicate_json_key_fail(self) -> None:
        self._write_pair([{"event_id": "x", "shares": 100}], [{"event_id": "x", "shares": 99}])
        result = compare_jsonl(self.left, self.right)
        self.assertEqual(result["differences"][0]["pointer"], "/shares")
        self.right.write_text('{"event_id":"x","event_id":"y"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重复字段"):
            compare_jsonl(self.left, self.right)

    def test_empty_required_ledger_list_cannot_pass(self) -> None:
        with self.assertRaisesRegex(ValueError, "固定的五类"):
            verify_ledger_directories(self.baseline, self.replay, ())

    def test_five_simultaneously_empty_ledgers_fail(self) -> None:
        self._write_required_pair([])
        result = verify_ledger_directories(
            self.baseline, self.replay, W1_PREFIX_REQUIRED_LEDGERS)
        self.assertFalse(result["all_nonempty"])
        self.assertFalse(result["rows_identical"])

    def test_cutoff_ledger_rejects_2021_06_08_even_if_manifest_is_rehashed(self) -> None:
        import backtest.cnn_adapter.prefix_ledger_verifier as verifier

        rows = [{"date": "2021-06-07", "sequence_no": 1}]
        self._write_required_pair(rows)
        path = self.replay / W1_PREFIX_REQUIRED_LEDGERS[0]
        with path.open("ab") as stream:
            stream.write(b'{"date":"2021-06-08","sequence_no":2}\n')
        with self.assertRaisesRegex(ValueError, "after cutoff"):
            verifier._prefix_records(path)

    def test_cutoff_access_gate_rejects_2021_06_08_quantity_rule_read(self) -> None:
        import backtest.cnn_adapter.prefix_ledger_verifier as verifier

        branch = self.replay / "W1_B1_floor"
        branch.mkdir()
        for name in verifier.ACCESS_FILES:
            (branch / name).write_bytes(b"")
        (branch / "quantity_rule_usage.jsonl").write_text(
            '{"rule_lookup_date":"2021-06-08"}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "future information access"):
            verifier._assert_access_cutoff(branch)

    def test_same_directory_cannot_be_compared_as_two_runs(self) -> None:
        with self.assertRaisesRegex(ValueError, "独立目录"):
            verify_ledger_directories(
                self.baseline, self.baseline, W1_PREFIX_REQUIRED_LEDGERS)

    def test_blocked_record_is_not_gate_pass(self) -> None:
        from backtest.cnn_adapter.fractional_prefix_gate import TRUSTED_PREFIX_PROOF_SHA256

        record_path = self.root / "blocked.json"
        digest = write_blocked_prefix_record(record_path)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "BLOCKED")
        self.assertFalse(record["canonical_prefix_match"])
        self.assertFalse(record["floor_ceil_prefix_match"])
        self.assertEqual(len(record["required_runs"]), 12)
        self.assertIsNone(TRUSTED_PREFIX_PROOF_SHA256)
        self.assertEqual(len(digest), 64)

    def test_proof_generator_rejects_missing_controlled_12_run_outputs(self) -> None:
        proof_path = self.root / "proof.json"
        import backtest.cnn_adapter.prefix_ledger_verifier as verifier
        with (patch.object(verifier, "BASELINE_ROOT", self.baseline),
              patch.object(verifier, "PREFIX_OUTPUT_ROOT", self.replay),
              self.assertRaises(FileNotFoundError)):
            generate_prefix_proof(proof_path)
        self.assertFalse(proof_path.exists())

    def test_external_attestation_root_without_independent_pin_blocks_proof(self) -> None:
        verifier, ledgers, audits, artifacts, sources, prepared, prereg, attest_path, _, attestor_sha = self._create_machine_proof_inputs()
        with patch.multiple(verifier, BASELINE_ROOT=self.baseline,
                PREFIX_OUTPUT_ROOT=self.replay, PREFIX_ATTESTATION_ROOT=attest_path,
                BASELINE_LEDGER_SHA256=ledgers, BASELINE_AUDIT_SHA256=audits,
                BASELINE_ARTIFACTS_SHA256=artifacts, BASELINE_SOURCES_SHA256=sources,
                PREPARED_MANIFEST_SHA256=prepared, PREREGISTRATION_SHA256=prereg,
                TRUSTED_PREFIX_ATTESTATION_SHA256=None,
                TRUSTED_PREFIX_ATTESTATOR_SHA256=attestor_sha):
            with self.assertRaisesRegex(ValueError, "not independently pinned"):
                verifier._build_machine_proof(self.baseline, self.replay,
                    "2026-10-28T00:00:00+00:00")

    def test_machine_proof_recomputes_all_12_branches_and_stays_unpinned(self) -> None:
        verifier, ledgers, audits, artifacts, sources, prepared, prereg, attest_path, attest_sha, attestor_sha = self._create_machine_proof_inputs()
        with patch.multiple(verifier, BASELINE_ROOT=self.baseline,
                PREFIX_OUTPUT_ROOT=self.replay, BASELINE_LEDGER_SHA256=ledgers,
                BASELINE_AUDIT_SHA256=audits, BASELINE_ARTIFACTS_SHA256=artifacts,
                BASELINE_SOURCES_SHA256=sources, PREPARED_MANIFEST_SHA256=prepared,
                PREREGISTRATION_SHA256=prereg, PREFIX_ATTESTATION_ROOT=attest_path,
                TRUSTED_PREFIX_ATTESTATION_SHA256=attest_sha,
                TRUSTED_PREFIX_ATTESTATOR_SHA256=attestor_sha):
            proof_path = self.root / "machine-proof.json"
            digest = generate_prefix_proof(proof_path)
            proof = verify_machine_prefix_proof(proof_path)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(len(proof["required_runs"]), 12)
            self.assertIsNone(proof["trusted_prefix_proof_sha256"])
            self.assertEqual(proof["fee_knowledge"]["PIT"], "UNKNOWN")
            self.assertEqual(len(digest), 64)
            copied = self.root / "copied-branch"
            shutil.copytree(self.replay / "W1_B1_floor", copied)
            with self.assertRaisesRegex(ValueError, "controlled branch output"):
                verifier._scenario_identity("B1", "floor", copied)
            tampered = dict(proof)
            tampered["canonical_prefix_match"] = False
            tampered["proof_sha256"] = verifier._canonical_sha(
                {key: value for key, value in tampered.items() if key != "proof_sha256"})
            self._write_json(proof_path, tampered)
            with self.assertRaisesRegex(ValueError, "does not match current"):
                verify_machine_prefix_proof(proof_path)

    def test_dual_core_identity_rejects_prepared_runtime_and_config_tampering(self) -> None:
        verifier, _ledgers, _audits, _artifacts, _sources, prepared, _prereg, _, _, _ = (
            self._create_machine_proof_inputs())
        branch = self.replay / "W1_B1_floor"
        audit = json.loads((branch / "attempt_audit.json").read_text())
        control = audit["controlled_run_identity"]
        original = json.loads((branch / "prefix_experiment.json").read_text())
        mutations = (("prepared_core_sha256", "0" * 64),
            ("prepared_core_path", str(verifier.ISOLATED_CORE_PATH.resolve())),
            ("runtime_core_sha256", "0" * 64),
            ("runtime_core_path", str(self.root / "unknown_core.py")))
        with patch.object(verifier, "PREPARED_MANIFEST_SHA256", prepared):
            for key, value in mutations:
                changed = dict(original, **{key: value})
                body = {name: item for name, item in changed.items()
                        if name != "experiment_config_sha256"}
                changed["experiment_config_sha256"] = verifier._canonical_sha(body)
                with self.subTest(field=key), self.assertRaises(ValueError):
                    verifier._verify_dual_core_identity(branch, control, changed)

    def test_machine_proof_reports_row_reordering_and_missing_rows(self) -> None:
        verifier, ledgers, audits, artifacts, sources, prepared, prereg, attest_path, attest_sha, attestor_sha = self._create_machine_proof_inputs()
        with patch.multiple(verifier, BASELINE_ROOT=self.baseline,
                PREFIX_OUTPUT_ROOT=self.replay, BASELINE_LEDGER_SHA256=ledgers,
                BASELINE_AUDIT_SHA256=audits, BASELINE_ARTIFACTS_SHA256=artifacts,
                BASELINE_SOURCES_SHA256=sources, PREPARED_MANIFEST_SHA256=prepared,
                PREREGISTRATION_SHA256=prereg, PREFIX_ATTESTATION_ROOT=attest_path,
                TRUSTED_PREFIX_ATTESTATION_SHA256=attest_sha,
                TRUSTED_PREFIX_ATTESTATOR_SHA256=attestor_sha):
            branch = self.replay / "W1_B1_floor"
            ledger = branch / W1_PREFIX_REQUIRED_LEDGERS[0]
            records = ledger.read_bytes().splitlines(keepends=True)
            ledger.write_bytes(b"".join(reversed(records)))
            manifest = verifier._read_json(branch / "artifacts.json")
            manifest[ledger.name] = self._sha(ledger)
            self._write_json(branch / "artifacts.json", manifest)
            with self.assertRaisesRegex(ValueError, "external attestation output hashes"):
                verifier._build_machine_proof(self.baseline, self.replay,
                    "2026-10-28T00:00:00+00:00")

    def test_qa_forged_audit_rehashed_manifest_and_june_8_rows_fail(self) -> None:
        verifier, ledgers, audits, artifacts, sources, prepared, prereg, attest_path, attest_sha, attestor_sha = self._create_machine_proof_inputs()
        with patch.multiple(verifier, BASELINE_ROOT=self.baseline,
                PREFIX_OUTPUT_ROOT=self.replay, BASELINE_LEDGER_SHA256=ledgers,
                BASELINE_AUDIT_SHA256=audits, BASELINE_ARTIFACTS_SHA256=artifacts,
                BASELINE_SOURCES_SHA256=sources, PREPARED_MANIFEST_SHA256=prepared,
                PREREGISTRATION_SHA256=prereg, PREFIX_ATTESTATION_ROOT=attest_path,
                TRUSTED_PREFIX_ATTESTATION_SHA256=attest_sha,
                TRUSTED_PREFIX_ATTESTATOR_SHA256=attestor_sha):
            branch = self.replay / "W1_B1_floor"
            shutil.rmtree(branch)
            shutil.copytree(self.replay / "W1_B1_ceil", branch)
            audit_path = branch / "attempt_audit.json"
            audit = verifier._read_json(audit_path)
            audit["controlled_run_identity"].update(branch="W1_B1_floor",
                scenario="floor", output_dir=str(branch.resolve()))
            audit["forged_external_audit"] = True
            self._write_json(audit_path, audit)
            evidence_path = branch / "corporate_action_evidence.json"
            evidence = verifier._read_json(evidence_path)
            evidence["fractional_scenario"]["scenario"] = "floor"
            self._write_json(evidence_path, evidence)
            manifest = verifier._read_json(branch / "artifacts.json")
            for name in W1_PREFIX_REQUIRED_LEDGERS:
                ledger = branch / name
                with ledger.open("ab") as stream:
                    stream.write(b'{"date":"2021-06-08","sequence_no":999}\n')
                manifest[name] = self._sha(ledger)
            manifest["attempt_audit.json"] = self._sha(audit_path)
            manifest[evidence_path.name] = self._sha(evidence_path)
            self._write_json(branch / "artifacts.json", manifest)
            with self.assertRaisesRegex(ValueError, "external attestation output hashes"):
                generate_prefix_proof(self.root / "forged-proof.json")
