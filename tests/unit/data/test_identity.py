"""T06: data/identity.py 统一 hash 对照单测（TDD Red-Green）。

锁定旧 digest 向量逐位一致：
- scaler identity（PerCodeGroupedScaler.identity_hash_for 旧逻辑）
- cache key（feature_cache._canonical_digest 旧逻辑，default=str）
- rolling state（RollingNormalizer._canonical_hash / dataset _identity_hash 旧逻辑）

新 data.identity.canonical_hash 对纯 JSON payload 必须与旧逻辑逐位一致；
numpy 标量/ndarray 归一为 Python 等价值后确定性一致；e1/e2 同列集异语义
靠 scope 入 digest 保持互异；CACHE_FORMAT_VERSION 语义不变。
"""
import hashlib
import json
import unittest

import numpy as np

from data.identity import canonical_hash


# 旧逻辑 inline（T06 替换前四处实现的字面复制，用于对照，不导入旧包装）。
def _legacy_digest(payload, with_default_str=False):
    kwargs = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": True}
    if with_default_str:
        kwargs["default"] = str
    return hashlib.sha256(json.dumps(payload, **kwargs).encode("utf-8")).hexdigest()


SCALER_MANIFEST = {
    "dataset": "x",
    "feature_cols": ["open", "close"],
    "normalize": "per_code",
    "f": 1.5,
    "n": None,
}
# 2026-09-28 实测旧 scaler 逻辑向量（json sort_keys+separators+sha256）。
SCALER_VECTOR = "238a92c970816d98164537e2565ad1a26122e33268dae6b1a5398a3aa6eed023"

CACHE_PAYLOAD = {
    "cache_format_version": "v3_relative_groups",
    "base_identity": {"parquet_path": "x.parquet", "size": 1, "mtime_ns": 2},
    "role": "training",
    "rolling_scope": "e4",
    "scaler_identity_hash": "abc123",
    "seq_len": 60,
    "horizon": 5,
    "max_windows_per_code": None,
    "bins_digest": "deadbeef",
}
CACHE_VECTOR_FULL = "23c2d7ffa0238bf43c10010398054c96ae5e08519b0895f3f4b0f365b74e496e"
CACHE_VECTOR_SHORT = "23c2d7ffa0238bf4"


class TestCanonicalVectors(unittest.TestCase):
    def test_scaler_identity_vector(self):
        self.assertEqual(_legacy_digest(SCALER_MANIFEST), SCALER_VECTOR)
        self.assertEqual(canonical_hash(SCALER_MANIFEST), SCALER_VECTOR)

    def test_cache_key_vector(self):
        self.assertEqual(_legacy_digest(CACHE_PAYLOAD, True), CACHE_VECTOR_FULL)
        self.assertEqual(canonical_hash(CACHE_PAYLOAD), CACHE_VECTOR_FULL)
        self.assertEqual(canonical_hash(CACHE_PAYLOAD)[:16], CACHE_VECTOR_SHORT)

    def test_key_order_independent(self):
        shuffled = {
            "n": None, "f": 1.5, "normalize": "per_code",
            "feature_cols": ["open", "close"], "dataset": "x",
        }
        self.assertEqual(canonical_hash(shuffled), SCALER_VECTOR)

    def test_bins_vector_stable(self):
        from data.feature_cache import compute_bins_digest
        bins = [float(b) for b in np.linspace(-0.38, 0.38, 51)]
        self.assertEqual(compute_bins_digest(bins), "930a144e107e8c93")
        self.assertEqual(canonical_hash(bins)[:16], "930a144e107e8c93")


class TestNumpyDeterminism(unittest.TestCase):
    def test_numpy_scalars_equal_python(self):
        pure = {"a": 1.5, "b": 3, "c": None}
        mixed = {"a": np.float64(1.5), "b": np.int64(3), "c": None}
        self.assertEqual(canonical_hash(mixed), canonical_hash(pure))

    def test_ndarray_equals_list(self):
        arr = np.array([1.0, 2.0, 3.0])
        self.assertEqual(canonical_hash({"v": arr}), canonical_hash({"v": [1.0, 2.0, 3.0]}))
        self.assertEqual(
            canonical_hash(np.array([[1, 2], [3, 4]])),
            canonical_hash([[1, 2], [3, 4]]),
        )

    def test_tuple_equals_list_and_none_float(self):
        self.assertEqual(canonical_hash((1, None, 2.5)), canonical_hash([1, None, 2.5]))
        self.assertEqual(canonical_hash({"x": (1.0, None)}), canonical_hash({"x": [1.0, None]}))


class TestScopeSemantics(unittest.TestCase):
    def test_e1_e2_same_cols_but_digests_differ(self):
        from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
        e1 = RollingNormalizer(RollingNormalizationConfig(scope="e1")).transform_config_digest()
        e2 = RollingNormalizer(RollingNormalizationConfig(scope="e2")).transform_config_digest()
        self.assertEqual(e1, "8dac9bf7d3c4d620e1a9b369f5dfd8edf72433c2bca2b7d74a4f3d11efbaf89a")
        self.assertEqual(e2, "a7234227f5f1e07738cbf1ead02adbf77420f948ebf0f5e3e12fc135b2717c8e")
        self.assertNotEqual(e1, e2)

    def test_cache_format_version_unchanged(self):
        from data.feature_cache import CACHE_FORMAT_VERSION
        self.assertEqual(CACHE_FORMAT_VERSION, "v3_relative_groups")


class TestWrapperParity(unittest.TestCase):
    def test_all_four_wrappers_delegate(self):
        from data.dataset import _RollingDatasetState
        from data.feature_cache import _canonical_digest
        from data.rolling_scaler import RollingNormalizer
        from data.scaler import PerCodeGroupedScaler
        self.assertEqual(PerCodeGroupedScaler.identity_hash_for(SCALER_MANIFEST), SCALER_VECTOR)
        self.assertEqual(_canonical_digest(CACHE_PAYLOAD), CACHE_VECTOR_FULL)
        self.assertEqual(RollingNormalizer._canonical_hash(dict(SCALER_MANIFEST)), SCALER_VECTOR)
        self.assertEqual(_RollingDatasetState._identity_hash(dict(SCALER_MANIFEST)), SCALER_VECTOR)

    def test_zero_dependency_no_data_imports(self):
        import re
        from pathlib import Path
        src = Path("data/identity.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?m)^\s*(from|import)\s+data\b", src))
        self.assertNotIn("from data.scaler", src)
        self.assertNotIn("from data.rolling_scaler", src)


if __name__ == "__main__":
    unittest.main()
