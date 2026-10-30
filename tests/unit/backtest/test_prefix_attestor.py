"""独立子进程见证输入、八分支输出和只读访问记录。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory


class PrefixAttestorTests(unittest.TestCase):
    def test_fixed_source_inventory_accepts_exact_files_and_rejects_tampering(self) -> None:
        from backtest.cnn_adapter.w1_prefix.prefix_attestor import _check_fixed_paths, fixed_source_sha256

        inventory = fixed_source_sha256()
        self.assertEqual(len(inventory), 15)
        self.assertEqual(_check_fixed_paths(inventory, "source"), inventory)
        source = Path(next(path for path in inventory if path.endswith("fractional_scenarios.py")))
        with TemporaryDirectory() as temporary:
            changed = Path(temporary) / source.name
            changed.write_bytes(source.read_bytes() + b"\n# tampered\n")
            with self.assertRaisesRegex(ValueError, "source fixed SHA mismatch"):
                _check_fixed_paths({str(changed): inventory[str(source)]}, "source")

    def test_attestor_requires_complete_dual_core_experiment_identity(self) -> None:
        from backtest.cnn_adapter.w1_prefix.prefix_attestor import _validate_prefix_experiment_identity

        required = ("experiment_id", "prepared_manifest_sha256", "prepared_core_path",
                    "prepared_core_sha256", "runtime_core_path", "runtime_core_sha256",
                    "experiment_config_sha256")
        identity = {key: f"bound:{key}" for key in required}
        self.assertEqual(_validate_prefix_experiment_identity(identity), identity)
        for key in required:
            incomplete = {name: value for name, value in identity.items() if name != key}
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, "identity is incomplete"):
                _validate_prefix_experiment_identity(incomplete)

    def test_external_attestor_rejects_post_cutoff_quantity_state_lookup(self) -> None:
        from backtest.cnn_adapter.w1_prefix.prefix_attestor import _access_record

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "quantity_rule_usage.jsonl"
            path.write_text('{"rule_lookup_date":"2021-06-08"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "future access record"):
                _access_record(path, date(2021, 6, 7))

    def test_external_process_records_fixed_sources_outputs_and_readonly_access(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "outputs"
            output_root.mkdir()
            branch_names = [f"W1_{policy}_{scenario}"
                for policy in ("B1", "S1", "S2", "C70")
                for scenario in ("floor", "ceil")]
            for branch in branch_names:
                directory = output_root / branch
                directory.mkdir()
                (directory / "execution_updates.jsonl").write_text(
                    '{"date":"2021-06-07"}\n', encoding="utf-8")
                for name in ("prefix_market_access.jsonl", "prefix_ranking_access.jsonl",
                             "quantity_rule_usage.jsonl", "prefix_fee_policy.jsonl"):
                    (directory / name).write_bytes(b"")
            source = Path(__file__).resolve().parents[3] / "backtest/cnn_adapter/w1_prefix/prefix_attestor.py"
            input_path = root / "prepared.json"
            input_path.write_text("fixed", encoding="utf-8")
            plan = {"schema_version": "w1_prefix_attestation_test_plan_v1",
                "output_root": str(output_root), "cutoff": "2021-06-07",
                "sources": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
                "inputs": {str(input_path): hashlib.sha256(input_path.read_bytes()).hexdigest()},
                "branches": {name: str(output_root / name) for name in branch_names}}
            plan_path, attestation = root / "plan.json", root / "attestation.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            repo = Path(__file__).resolve().parents[3]
            process = subprocess.run([sys.executable, "-B", "-m",
                "backtest.cnn_adapter.w1_prefix.prefix_attestor", "--plan", str(plan_path),
                "--attestation", str(attestation)], cwd=repo, capture_output=True,
                text=True, check=True)
            record = json.loads(attestation.read_text(encoding="utf-8"))
            self.assertEqual(len(record["branches"]), 8)
            self.assertEqual(record["status"], "TEST_ONLY")
            self.assertEqual(len(process.stdout.strip()), 64)
            sample = record["read_only_access_records"][branch_names[0]]
            access = Path(sample["prefix_market_access.jsonl"]["external_path"])
            self.assertFalse(access.stat().st_mode & 0o200)
            output = output_root / branch_names[0] / "execution_updates.jsonl"
            pinned = record["branches"][branch_names[0]]["files"]["execution_updates.jsonl"]
            output.write_text('{"date":"2021-06-08"}\n', encoding="utf-8")
            self.assertNotEqual(hashlib.sha256(output.read_bytes()).hexdigest(), pinned)
            for path in root.rglob("*"):
                if path.is_file():
                    path.chmod(0o666)
