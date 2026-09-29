"""T16: pytest/CI 最小闭环门（identity/kernel/preprocessing/dataset-cache + 配置下限 + CI）。

全 Mock/轻量张量/mini parquet，不读真实大文件、不跑训练循环。"""
import shutil
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]


class TestIdentityGate(unittest.TestCase):
    def test_deterministic_key_order_free_and_numpy_parity(self):
        from data.identity import canonical_hash

        payload = {"b": 1.5, "a": [1, None], "n": None}
        shuffled = {"n": None, "a": [1, None], "b": 1.5}
        self.assertEqual(canonical_hash(payload), canonical_hash(shuffled))
        self.assertEqual(len(canonical_hash(payload)), 64)
        self.assertEqual(canonical_hash({"a": np.float64(1.5)}), canonical_hash({"a": 1.5}))


class TestKernelGate(unittest.TestCase):
    def test_relative_first_row_zero_and_shared_mask_or(self):
        from data.transform_kernel import append_shared_mask, apply_column_rule

        raw = np.array([10.0, 11.0, 12.0])
        close = np.array([10.0, 10.0, 11.0])
        rule = SimpleNamespace(transform="relative", clip=(-5.0, 5.0), robust=False, scale=1.0)
        out = apply_column_rule(raw, np.isfinite(raw), rule, close=close)
        np.testing.assert_allclose(out, np.array([0.0, 0.1, 12.0 / 10.0 - 1.0]))
        masked = append_shared_mask(np.zeros((3, 2)), np.array([True, False, True]))
        self.assertEqual(masked.shape, (3, 3))
        np.testing.assert_array_equal(masked[:, -1], np.array([1.0, 0.0, 1.0], dtype=np.float32))


class TestPreprocessingGate(unittest.TestCase):
    def test_relative_stateless_and_unknown_rejected(self):
        from training.preprocessing import configure_preprocessing

        cfg: dict = {}
        configure_preprocessing(cfg, "relative")
        self.assertEqual(cfg["NORMALIZE"], "relative")
        self.assertIsNone(cfg["SCALER_PATH"])
        self.assertEqual(cfg["LOG_DIR"], "./logs/relative")
        with self.assertRaises(ValueError):
            configure_preprocessing({}, "bogus")


class TestDatasetCacheGate(unittest.TestCase):
    def test_miss_then_hit_same_length(self):
        from data.dataset import ParquetDataConfig, ParquetDataset

        tmpdir = tempfile.mkdtemp(prefix="t16_gate_")
        try:
            rows = [
                {
                    "code": "000001", "is_trading": True,
                    "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=t),
                    "open": 10.0 + t, "high": 11.0 + t, "low": 9.0 + t, "close": 10.5 + t,
                }
                for t in range(45)
            ]
            parquet_path = str(Path(tmpdir) / "mini.parquet")
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False), parquet_path)
            base = {"parquet_path": parquet_path, "seq_len": 5, "horizon": 2,
                    "feature_cols": ["open", "high", "low"], "num_workers": 0}
            off = ParquetDataset(ParquetDataConfig(**base))
            on = ParquetDataset(ParquetDataConfig(**base, cache_enabled=True, cache_dir=str(Path(tmpdir) / "c")))
            hit = ParquetDataset(ParquetDataConfig(**base, cache_enabled=True, cache_dir=str(Path(tmpdir) / "c")))
            self.assertGreater(len(off), 0)
            self.assertEqual(len(off), len(on))
            self.assertEqual(len(off), len(hit))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestCIClosureGate(unittest.TestCase):
    def test_pytest_and_coverage_floor(self):
        cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("tests", str(cfg["tool"]["pytest"]["ini_options"].get("testpaths")))
        self.assertGreaterEqual(cfg["tool"]["coverage"]["report"].get("fail_under"), 50)

    def test_ci_workflow_runs_ruff_pytest_on_cpu(self):
        src = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("ruff", src)
        self.assertIn("pytest", src)
        self.assertIn("--num_workers 0", src)
        self.assertIn("CUDA_VISIBLE_DEVICES", src)


if __name__ == "__main__":
    unittest.main()
