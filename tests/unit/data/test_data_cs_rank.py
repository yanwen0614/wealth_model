"""截面 rank（cs_rank）特征契约测试（TDD Red-Green）。

覆盖：
1. `DEFAULT_CS_RANK_FEATURES` 默认 16 个独立特征且全部属 FEATURE_GROUPS。
2. 配置默认关闭（cs_rank=False）时输出维度与现有行为一致。
3. cs_rank=True 时输出维度 = 归一化输出 + cs rank 列，列名 cs_<feature> 追加末尾。
4. 合成数据 2 天 × 3 股 × 1 特征手工验证 rank(pct) 值。
5. rank 在 max_codes 限制之前、全市场截面计算。
6. context warmup 行参与 rank 计算（真实历史截面）。
7. cs rank 列旁路归一化（relative 下保持 [0,1] 原始 rank，不被 x/close-1 污染）。
8. 非法/缺失 cs_rank_features 直接报错。
9. 缓存 key 对 cs_rank 敏感，默认关闭时 key 不变；cs rank 可经缓存往返一致。

全部使用 tempfile 造 mini parquet 与临时 cache_dir，不污染真实数据/缓存。
"""
import gc
import os
import shutil
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset
from data.feature_cache import compute_cache_key
from data.schema import APPROVED_RAW_FEATURES, DEFAULT_CS_RANK_FEATURES

BINS = (np.linspace(-25, 25, 51) / 100).tolist()
CODES = {"A": 1.0, "B": 2.0, "C": 3.0}


def _frame(n_days: int = 4) -> pd.DataFrame:
    """A/B/C 三股同日历；dmi 每日保持 A<B<C 顺序，价格水平随日递增。"""
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rows = []
    for code, base in CODES.items():
        for t, day in enumerate(dates):
            price = 10.0 + t
            rows.append({
                "code": code, "kline_time": day,
                "open": price, "high": price + 1.0, "low": price - 1.0, "close": price + 0.5,
                "is_trading": True, "dmi": base + t * 0.1,
            })
    return pd.DataFrame(rows)


def _config(path: str, **over) -> ParquetDataConfig:
    base: dict = {
        "parquet_path": path,
        "seq_len": 2,
        "horizon": 1,
        "bins": BINS,
        "feature_cols": ["dmi"],
        "normalize": "none",
        "num_workers": 0,
    }
    base.update(over)
    return ParquetDataConfig(**base)


class _parquet:
    def __init__(self, frame):
        self.frame = frame

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="csrank_")
        self.path = os.path.join(self.dir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.path)
        return self.path

    def __exit__(self, *args):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestCsRankConfig(unittest.TestCase):
    def test_default_list_is_16_approved_independent_features(self):
        features = list(DEFAULT_CS_RANK_FEATURES)
        self.assertEqual(len(features), 16)
        self.assertEqual(len(set(features)), 16)
        approved = set(APPROVED_RAW_FEATURES)
        self.assertTrue(set(features).issubset(approved), msg=f"非批准特征: {set(features) - approved}")

    def test_config_defaults_off(self):
        cfg = ParquetDataConfig()
        self.assertFalse(cfg.cs_rank)
        self.assertIsNone(cfg.cs_rank_features)

    def test_default_resolver_uses_builtin_list(self):
        resolved = ParquetDataset._resolve_cs_rank_features(list(APPROVED_RAW_FEATURES), None)
        self.assertEqual(resolved, list(DEFAULT_CS_RANK_FEATURES))

    def test_custom_resolver_dedups_and_rejects_unknown(self):
        resolved = ParquetDataset._resolve_cs_rank_features(["dmi", "roe", "dmi"], ["dmi", "roe", "dmi"])
        self.assertEqual(resolved, ["dmi", "roe"])
        with self.assertRaisesRegex(ValueError, "cs_rank_features"):
            ParquetDataset._resolve_cs_rank_features(["dmi"], ["macd"])


class TestCsRankOffUnchanged(unittest.TestCase):
    def test_default_off_matches_explicit_off_and_dimension(self):
        with _parquet(_frame()) as path:
            default = ParquetDataset(_config(path))
            explicit = ParquetDataset(_config(path, cs_rank=False, cs_rank_features=None))
        self.assertEqual(default.num_features, 1)
        self.assertEqual(default.feature_cols_out, ["dmi"])
        for code in default.groups:
            np.testing.assert_array_equal(
                default.groups[code]["features"], explicit.groups[code]["features"]
            )


class TestCsRankValues(unittest.TestCase):
    def test_hand_computed_ranks_two_days_three_stocks(self):
        # dmi: 每日 A<B<C -> rank(pct)=[1/3, 2/3, 1.0]
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(path, cs_rank=True, cs_rank_features=["dmi"]))
        self.assertEqual(ds.feature_cols_out, ["dmi", "cs_dmi"])
        self.assertEqual(ds.num_features, 2)
        expected = {"A": 1.0 / 3.0, "B": 2.0 / 3.0, "C": 1.0}
        for code, want in expected.items():
            rank_col = ds.groups[code]["features"][:, -1]
            np.testing.assert_allclose(rank_col, np.full(len(rank_col), want), rtol=0, atol=1e-6)

    def test_rank_computed_before_max_codes(self):
        # 若先按 max_codes 截断到 A/B，A 的 rank 会是 1/2；正确应在全 3 股截面得 1/3。
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(path, cs_rank=True, cs_rank_features=["dmi"], max_codes=2))
        self.assertIn("A", ds.groups)
        np.testing.assert_allclose(ds.groups["A"]["features"][:, -1], 1.0 / 3.0, rtol=0, atol=1e-6)

    def test_context_rows_participate_in_rank(self):
        frame = _frame(n_days=6)
        with _parquet(frame) as path:
            ds = ParquetDataset(_config(path, cs_rank=True, cs_rank_features=["dmi"], start_date="2024-01-03"))
        # context 保留 1 行（2024-01-02），其截面 rank 仍按 A<B<C 计算 -> 1/3
        self.assertEqual(int(ds.groups["A"]["n"]), 5)
        np.testing.assert_allclose(ds.groups["A"]["features"][0, -1], 1.0 / 3.0, rtol=0, atol=1e-6)

    def test_rank_bypasses_relative_normalization(self):
        # relative 会把 P 组 open 变换成 x/close[t-1]-1；cs_dmi 必须保持原始 rank ∈ [0,1]
        with _parquet(_frame()) as path:
            cfg = _config(path, cs_rank=True, cs_rank_features=["dmi"], normalize="relative",
                          feature_cols=["dmi", "open"])
            ds = ParquetDataset(cfg)
        self.assertEqual(ds.feature_cols_out, ["dmi", "open", "cs_dmi"])
        rank_col = ds.groups["A"]["features"][:, -1]
        np.testing.assert_allclose(rank_col, 1.0 / 3.0, rtol=0, atol=1e-6)
        self.assertTrue(np.all(rank_col >= 0.0) and np.all(rank_col <= 1.0))


class TestCsRankCache(unittest.TestCase):
    @staticmethod
    def _kwargs() -> dict:
        return {
            "base_identity": {"parquet_path": "x", "size": 1, "mtime_ns": 2},
            "role": "training", "rolling_scope": None, "scaler_identity_hash": "h",
            "seq_len": 2, "horizon": 1, "max_windows_per_code": None, "bins_digest": "d",
        }

    def test_cache_key_sensitive_and_default_stable(self):
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), cs_rank=True, cs_rank_features=["dmi"]),
            compute_cache_key(**self._kwargs()),
        )
        # 默认（不传）与显式关闭同 key
        self.assertEqual(compute_cache_key(**self._kwargs()), compute_cache_key(**self._kwargs(), cs_rank=False))
        # 启用时不同特征列表必须派生不同 key
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), cs_rank=True, cs_rank_features=["dmi"]),
            compute_cache_key(**self._kwargs(), cs_rank=True, cs_rank_features=["roe"]),
        )

    def test_round_trip_through_cache(self):
        with _parquet(_frame()) as path:
            cache_dir = tempfile.mkdtemp(prefix="csrank_cache_")
            try:
                cfg = _config(path, cs_rank=True, cs_rank_features=["dmi"], cache_enabled=True,
                              cache_dir=cache_dir)
                first = ParquetDataset(cfg)
                second = ParquetDataset(cfg)  # 二次构造命中缓存
                self.assertEqual(first.num_features, second.num_features)
                self.assertEqual(first.feature_cols_out, second.feature_cols_out)
                for code in first.groups:
                    np.testing.assert_array_equal(
                        first.groups[code]["features"], second.groups[code]["features"]
                    )
            finally:
                del first, second
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)

    def test_relative_cache_hit_accepts_appended_cs_columns(self):
        # relative 缓存命中路径按 COLUMN_RULES 重建 scaler，其 feature_cols_out 不含旁路 cs 列，
        # 必须补上 cs_rank_cols 再比对，否则带 cs_rank 的 relative 缓存命中会误报 schema 不匹配。
        with _parquet(_frame()) as path:
            cache_dir = tempfile.mkdtemp(prefix="csrank_rel_cache_")
            try:
                cfg = _config(path, cs_rank=True, cs_rank_features=["dmi"], normalize="relative",
                              feature_cols=["dmi", "open"], cache_enabled=True, cache_dir=cache_dir)
                first = ParquetDataset(cfg)
                second = ParquetDataset(cfg)  # 命中缓存，触发 _resolve_scaler_on_cache_hit
                self.assertEqual(second.feature_cols_out, ["dmi", "open", "cs_dmi"])
                self.assertEqual(first.num_features, second.num_features)
                for code in first.groups:
                    np.testing.assert_array_equal(
                        first.groups[code]["features"], second.groups[code]["features"]
                    )
            finally:
                del first, second
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
