"""Unit tests for training/sealed_eval.py — 封存逻辑全 Mock/mini 文件，不依赖真实 git 或 parquet。"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from training.sealed_eval import (
    SEALED_MANIFEST_FILENAME,
    SealedEvalError,
    SealedManifest,
    _compute_code_fingerprint,
    _compute_config_digest,
    _compute_file_sha1,
    create_sealed_manifest,
    guard_sealed,
    is_sealed,
)


class TestSealedEvalHelpers(unittest.TestCase):
    """Helper 函数基本功能验证（纯函数，不依赖 io/子进程）。"""

    def test_compute_config_digest_deterministic(self):
        cfg1 = {"TRAIN_START": "2013-01-01", "BINS": [0.1, 0.2, 0.3], "EPOCHS": 50}
        cfg2 = {"EPOCHS": 50, "BINS": [0.1, 0.2, 0.3], "TRAIN_START": "2013-01-01"}
        self.assertEqual(_compute_config_digest(cfg1), _compute_config_digest(cfg2))

    def test_compute_config_digest_excludes_run_log_dir(self):
        cfg_a = {"A": 1, "run_log_dir": "/tmp/run_20261023"}
        cfg_b = {"A": 1, "run_log_dir": "/tmp/run_20261024"}
        self.assertEqual(_compute_config_digest(cfg_a), _compute_config_digest(cfg_b))

    def test_compute_config_digest_differs_for_diff_config(self):
        cfg1 = {"EPOCHS": 50}
        cfg2 = {"EPOCHS": 100}
        self.assertNotEqual(_compute_config_digest(cfg1), _compute_config_digest(cfg2))

    def test_compute_config_digest_length(self):
        digest = _compute_config_digest({"a": 1})
        self.assertEqual(len(digest), 16)

    def test_compute_file_sha1_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            _compute_file_sha1("/nonexistent/file.parquet")

    def test_compute_file_sha1_known_content(self):
        import hashlib

        content = b"hello world\n"
        expected = hashlib.sha1(content).hexdigest()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmppath = f.name
        try:
            self.assertEqual(_compute_file_sha1(tmppath), expected)
        finally:
            os.unlink(tmppath)


@patch("training.sealed_eval.subprocess.run")
class TestCodeFingerprint(unittest.TestCase):
    """代码指纹函数测试（mock subprocess，不依赖真实 git 仓库）。"""

    def test_clean_repo(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="abc123def4567890abcdef1234567890abcdef12\n"),
            MagicMock(returncode=0),
        ]
        self.assertEqual(_compute_code_fingerprint(), "abc123def456")

    def test_dirty_repo(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="deadbeef1234567890abcdef1234567890abcdef12\n"),
            MagicMock(returncode=1),
        ]
        self.assertEqual(_compute_code_fingerprint(), "deadbeef1234-dirty")

    def test_git_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        with self.assertRaises(RuntimeError):
            _compute_code_fingerprint()

    def test_git_command_fails(self, mock_run):
        from subprocess import CalledProcessError

        mock_run.side_effect = CalledProcessError(128, "git")
        with self.assertRaises(RuntimeError):
            _compute_code_fingerprint()


class TestSealedManifest(unittest.TestCase):
    """SealedManifest 数据类核心功能测试。"""

    def setUp(self):
        self.manifest = SealedManifest(
            experiment_id="test-uuid",
            sealed_at="2026-10-23T12:00:00+00:00",
            config_hash="abc123def4567890",
            data_fingerprint="deadbeef",
            code_fingerprint="clean-commit",
            train_range=("2013-01-01", "2025-06-30"),
            val_range=("2025-07-01", "2025-12-31"),
            sealed_range=("2026-01-01", "2026-08-31"),
            metrics_snapshot={"final_val_loss": 1.5},
        )

    def test_frozen_dataclass(self):
        with self.assertRaises(AttributeError):
            self.manifest.experiment_id = "new-id"  # type: ignore[misc]

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sealed_manifest.json")
            self.manifest.save(path)
            self.assertTrue(os.path.isfile(path))
            loaded = SealedManifest.load(path)
            self.assertEqual(loaded.experiment_id, "test-uuid")
            self.assertEqual(loaded.config_hash, "abc123def4567890")
            self.assertEqual(loaded.train_range, ("2013-01-01", "2025-06-30"))
            self.assertEqual(loaded.sealed_range, ("2026-01-01", "2026-08-31"))
            self.assertEqual(loaded.metrics_snapshot["final_val_loss"], 1.5)

    def test_load_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            SealedManifest.load("/nonexistent/file.json")

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json}")
            tmppath = f.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                SealedManifest.load(tmppath)
        finally:
            os.unlink(tmppath)

    def test_load_converts_list_to_tuple(self):
        data = {
            "experiment_id": "x", "sealed_at": "2026-01-01T00:00:00+00:00",
            "config_hash": "h", "data_fingerprint": "d", "code_fingerprint": "c",
            "train_range": ["a", "b"], "val_range": ["c", "d"],
            "sealed_range": ["e", "f"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmppath = f.name
        try:
            manifest = SealedManifest.load(tmppath)
            self.assertIsInstance(manifest.train_range, tuple)
            self.assertIsInstance(manifest.val_range, tuple)
            self.assertIsInstance(manifest.sealed_range, tuple)
        finally:
            os.unlink(tmppath)

    @patch("training.sealed_eval._compute_config_digest")
    @patch("training.sealed_eval._compute_code_fingerprint")
    @patch("training.sealed_eval._compute_file_sha1")
    def test_verify_fingerprint_match(
        self, mock_file_sha1, mock_code_fp, mock_config_digest
    ):
        mock_config_digest.return_value = "abc123"
        mock_code_fp.return_value = "clean-commit"
        mock_file_sha1.return_value = "deadbeef"
        manifest = SealedManifest(
            experiment_id="x", sealed_at="now",
            config_hash="abc123", data_fingerprint="deadbeef",
            code_fingerprint="clean-commit",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        self.assertTrue(manifest.verify_fingerprint({"a": 1}, "/fake/path.parquet"))

    @patch("training.sealed_eval._compute_config_digest")
    def test_verify_fingerprint_config_mismatch(self, mock_config_digest):
        mock_config_digest.return_value = "different_hash"
        manifest = SealedManifest(
            experiment_id="x", sealed_at="now",
            config_hash="abc123", data_fingerprint="deadbeef",
            code_fingerprint="clean-commit",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        self.assertFalse(manifest.verify_fingerprint({"a": 1}))

    @patch("training.sealed_eval._compute_config_digest")
    @patch("training.sealed_eval._compute_code_fingerprint")
    def test_verify_fingerprint_code_mismatch(
        self, mock_code_fp, mock_config_digest
    ):
        mock_config_digest.return_value = "abc123"
        mock_code_fp.return_value = "different-commit"
        manifest = SealedManifest(
            experiment_id="x", sealed_at="now",
            config_hash="abc123", data_fingerprint="deadbeef",
            code_fingerprint="clean-commit",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        self.assertFalse(manifest.verify_fingerprint({"a": 1}))


class TestIsSealed(unittest.TestCase):
    """is_sealed 函数测试。"""

    def test_no_file_returns_false(self):
        self.assertFalse(is_sealed("/nonexistent/manifest.json"))

    def test_valid_manifest_returns_true(self):
        manifest = SealedManifest(
            experiment_id="x", sealed_at="now",
            config_hash="h", data_fingerprint="d", code_fingerprint="c",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manifest.json")
            manifest.save(path)
            self.assertTrue(is_sealed(path))

    def test_corrupted_manifest_returns_false(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{corrupted")
            tmppath = f.name
        try:
            self.assertFalse(is_sealed(tmppath))
        finally:
            os.unlink(tmppath)


class TestGuardSealed(unittest.TestCase):
    """guard_sealed 守卫函数测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="test_guard_")
        self.manifest_path = os.path.join(self.tmpdir, "sealed_manifest.json")
        # 创建有效 JSON 文件（内容不重要，os.path.isfile 检查用）
        with open(self.manifest_path, "w") as f:
            json.dump({"dummy": True}, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_manifest_passes(self):
        guard_sealed("/nonexistent/manifest.json", {"a": 1})
        # 无异常即通过

    @patch("training.sealed_eval.SealedManifest.load")
    @patch("training.sealed_eval.SealedManifest.verify_fingerprint")
    def test_matched_fingerprint_raises(self, mock_verify, mock_load):
        mock_verify.return_value = True
        mock_load.return_value = SealedManifest(
            experiment_id="sealed-run", sealed_at="now",
            config_hash="h", data_fingerprint="d", code_fingerprint="c",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        with self.assertRaises(SealedEvalError) as ctx:
            guard_sealed(self.manifest_path, {"a": 1})
        self.assertIn("sealed-run", str(ctx.exception))

    @patch("training.sealed_eval.SealedManifest.load")
    @patch("training.sealed_eval.SealedManifest.verify_fingerprint")
    def test_mismatched_fingerprint_passes(self, mock_verify, mock_load):
        mock_verify.return_value = False
        mock_load.return_value = SealedManifest(
            experiment_id="old-run", sealed_at="now",
            config_hash="h", data_fingerprint="d", code_fingerprint="c",
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        guard_sealed(self.manifest_path, {"a": 1})
        # 无异常即通过

    def test_corrupted_manifest_passes(self):
        # 覆盖 setUp 文件，写入非 json 内容
        with open(self.manifest_path, "w") as f:
            f.write("not json")
        guard_sealed(self.manifest_path, {"a": 1})  # 损坏视同未封存，通过


@patch("training.sealed_eval._compute_code_fingerprint")
@patch("training.sealed_eval._compute_file_sha1")
class TestCreateSealedManifest(unittest.TestCase):
    """create_sealed_manifest 集成测试（mock git 和数据文件）。"""

    def test_create_with_all_fields(self, mock_file_sha1, mock_code_fp):
        mock_file_sha1.return_value = "data_sha1_hash"
        mock_code_fp.return_value = "abc123-clean"
        with tempfile.TemporaryDirectory() as tmp:
            parquet_path = os.path.join(tmp, "data.parquet")
            with open(parquet_path, "w") as f:
                f.write("fake parquet content")

            manifest = create_sealed_manifest(
                config={"EPOCHS": 50, "TRAIN_START": "2013-01-01", "BINS": [0.1, 0.2]},
                train_range=("2013-01-01", "2025-06-30"),
                val_range=("2025-07-01", "2025-12-31"),
                sealed_range=("2026-01-01", "2026-08-31"),
                metrics_snapshot={"final_val_loss": 1.23},
                parquet_path=parquet_path,
                output_dir=tmp,
            )
            self.assertEqual(manifest.data_fingerprint, "data_sha1_hash")
            self.assertEqual(manifest.code_fingerprint, "abc123-clean")
            self.assertEqual(manifest.metrics_snapshot["final_val_loss"], 1.23)
            self.assertEqual(manifest.train_range, ("2013-01-01", "2025-06-30"))
            self.assertEqual(manifest.sealed_range, ("2026-01-01", "2026-08-31"))
            # 检查文件持久化
            saved_path = os.path.join(tmp, SEALED_MANIFEST_FILENAME)
            self.assertTrue(os.path.isfile(saved_path))
            loaded = SealedManifest.load(saved_path)
            self.assertEqual(loaded.experiment_id, manifest.experiment_id)

    def test_create_without_data_file(self, mock_file_sha1, mock_code_fp):
        mock_code_fp.return_value = "abc123-clean"
        manifest = create_sealed_manifest(
            config={"EPOCHS": 50},
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
            parquet_path="/nonexistent/file.parquet",
        )
        self.assertEqual(manifest.data_fingerprint, "no_data_file")

    def test_create_without_output_dir_no_save(self, mock_file_sha1, mock_code_fp):
        mock_file_sha1.return_value = "data_hash"
        mock_code_fp.return_value = "abc123-clean"
        manifest = create_sealed_manifest(
            config={"EPOCHS": 50},
            train_range=("a", "b"), val_range=("c", "d"),
            sealed_range=("e", "f"),
        )
        self.assertIsNotNone(manifest.experiment_id)


class TestSealedEvalError(unittest.TestCase):
    def test_exception_message_contains_manifest_path_and_id(self):
        err = SealedEvalError("/path/manifest.json", "exp-123")
        self.assertIn("/path/manifest.json", str(err))
        self.assertIn("exp-123", str(err))
        self.assertIsInstance(err, RuntimeError)


class TestSealedManifestConstant(unittest.TestCase):
    def test_manifest_filename_is_defined(self):
        self.assertEqual(SEALED_MANIFEST_FILENAME, "sealed_manifest.json")


if __name__ == "__main__":
    unittest.main()
