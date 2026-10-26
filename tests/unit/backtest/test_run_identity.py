"""运行身份采集与分支身份校验的合成测试。"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backtest.cnn_adapter.run_identity import (
    RunIdentity,
    _file_evidence,
    capture_run_identity,
    validate_branch_identities,
)


class RunIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.core_repo = self.root / "core"
        self.core_repo.mkdir()
        self.git_failure = False
        self.git_root_override: Path | None = None
        self.imported_path_override: Path | None = None
        self.files = {name: self.root / f"{name}.py" for name in (
            "historical_costs", "execution_audit", "run_identity",
            "cnn_runner", "core_runner", "core_cost", "core_account",
        )}
        for path in self.files.values():
            path.write_text("synthetic source\n", encoding="utf-8")
        self.artifacts = {name: self.root / f"{name}.bin" for name in (
            "data", "cache", "checkpoint",
        )}
        for path in self.artifacts.values():
            path.write_bytes(b"synthetic artifact")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, root: Path, *args: str) -> str:
        if self.git_failure:
            raise RuntimeError("git failed")
        if args == ("rev-parse", "--show-toplevel"):
            return str((self.git_root_override or root).resolve()) + "\n"
        if args == ("rev-parse", "HEAD"):
            return "a" * 40 + "\n"
        if args == ("branch", "--show-current"):
            return "synthetic\n"
        return "?? synthetic_untracked\0"

    def _capture(
        self, label: str = "candidate", repositories: dict[str, Path] | None = None,
    ) -> object:
        modules = {key: value for key, value in self.files.items()}
        modules["run_identity"] = Path(__file__).parents[3] / "backtest/cnn_adapter/run_identity.py"
        imported = {
            "backtest.cnn_adapter.historical_costs": self.imported_path_override or self.files["historical_costs"],
            "backtest.cnn_adapter.execution_audit": self.files["execution_audit"],
            "backtest.cnn_adapter.runner": self.files["cnn_runner"],
            "synthetic.account_runner": self.files["core_runner"],
            "synthetic.policies.cost": self.files["core_cost"],
            "synthetic.contracts.account": self.files["core_account"],
        }
        imported_modules = {
            name: type("SyntheticModule", (), {"__file__": str(path)})()
            for name, path in imported.items()
        }
        imported_modules["backtest.cnn_adapter.run_identity"] = sys.modules[
            "backtest.cnn_adapter.run_identity"
        ]
        with patch("backtest.cnn_adapter.run_identity._run_git", side_effect=self._git), patch(
            "backtest.cnn_adapter.run_identity._distribution_version", return_value="1.2.3"
        ), patch.dict(sys.modules, imported_modules, clear=False):
            return capture_run_identity(
                branch_label=label,
                repositories=repositories or {"cnn": self.repo, "core": self.core_repo},
                modules=modules,
                artifacts=self.artifacts,
                distributions=("backtest-core", "numpy", "pandas", "pydantic", "torch", "pyarrow"),
            )

    def test_identity_hash_is_canonical_and_records_file_hashes(self) -> None:
        identity = self._capture()
        payload = identity.to_dict()
        self.assertEqual(payload["branch_label"], "candidate")
        self.assertEqual(payload["repositories"]["cnn"]["dirty"], ["?? synthetic_untracked"])
        self.assertEqual(payload["files"]["data"]["sha256"], hashlib.sha256(b"synthetic artifact").hexdigest())
        material = dict(payload)
        recorded = material.pop("identity_hash")
        expected = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(recorded, expected)

    def test_missing_artifact_and_empty_label_fail(self) -> None:
        self.artifacts["data"] = self.root / "absent.bin"
        with self.assertRaises(ValueError):
            self._capture()
        self.artifacts["data"] = self.root / "data.bin"
        self.artifacts["data"].write_bytes(b"synthetic artifact")
        with self.assertRaises(TypeError):
            self._capture("")

    def test_branch_labels_must_be_unique(self) -> None:
        identity = self._capture()
        with self.assertRaises(ValueError):
            validate_branch_identities([identity, identity])

    def test_identical_evidence_with_distinct_capture_ids_is_valid(self) -> None:
        first = self._capture("first")
        second = self._capture("second")
        validate_branch_identities([first, second])
        self.assertEqual(first.to_dict()["repositories"], second.to_dict()["repositories"])
        self.assertNotEqual(first.to_dict()["capture_id"], second.to_dict()["capture_id"])

    def test_forged_label_with_reused_capture_id_is_rejected(self) -> None:
        identity = self._capture("first")
        changed = identity.to_dict()
        changed["branch_label"] = "second"
        forged = RunIdentity(changed)
        with self.assertRaises(ValueError):
            validate_branch_identities([identity, forged])

    def test_non_mapping_repository_and_file_evidence_are_rejected(self) -> None:
        identity = self._capture("candidate")
        for field, malformed in (("repositories", "invalid"), ("files", [])):
            with self.subTest(field=field):
                payload = identity.to_dict()
                payload[field] = malformed
                with self.assertRaises(ValueError):
                    validate_branch_identities([RunIdentity(payload)])

    def test_repository_root_mismatch_and_nested_roots_fail(self) -> None:
        wrong = self.root / "wrong"
        wrong.mkdir()
        self.git_root_override = self.repo
        with patch("backtest.cnn_adapter.run_identity._run_git", side_effect=self._git):
            with self.assertRaises(ValueError):
                self._capture(repositories={"cnn": wrong, "core": self.core_repo})
        self.git_root_override = None
        with patch("backtest.cnn_adapter.run_identity._run_git", side_effect=self._git):
            nested = self.repo / "nested_core"
            nested.mkdir()
            with self.assertRaises(ValueError):
                self._capture(repositories={"cnn": self.repo, "core": nested})
            with self.assertRaises(ValueError):
                self._capture(repositories={"cnn": self.repo, "core": self.repo})

    def test_file_stat_failures_before_and_after_hashing_are_value_errors(self) -> None:
        target = self.artifacts["data"]
        original_stat = Path.stat
        for failing_call in (2, 3):
            calls = 0

            def fail_stat(
                path: Path, *args: object, expected_call: int = failing_call,
                **kwargs: object,
            ) -> object:
                nonlocal calls
                if path == target:
                    calls += 1
                    if calls == expected_call:
                        raise OSError("synthetic stat failure")
                return original_stat(path, *args, **kwargs)

            with patch.object(Path, "stat", autospec=True, side_effect=fail_stat):
                with self.assertRaises(ValueError):
                    _file_evidence(target, "data")

    def test_supplied_role_path_cannot_fake_imported_module_path(self) -> None:
        wrong = self.root / "impostor.py"
        wrong.write_text("other source\n", encoding="utf-8")
        self.imported_path_override = wrong
        with self.assertRaises(ValueError):
            self._capture()

    def test_git_status_keeps_untracked_entries_and_git_error_fails(self) -> None:
        self.assertIsNotNone(self._capture())
        self.git_failure = True
        with self.assertRaises(ValueError):
            self._capture()


if __name__ == "__main__":
    unittest.main()
