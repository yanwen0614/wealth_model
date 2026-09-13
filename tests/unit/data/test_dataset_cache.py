"""T02: ParquetDataset 接入 feature memmap 缓存的契约测试（TDD Red-Green）。

覆盖：
1. cache on/off 的 len/index/__getitem__ 逐元素一致
2. _WindowIndex 语义（index/负索引/迭代）
3. _FeatureView（np.isfinite 与切片 .T）
4. 首次 miss 自动落盘、二次构造命中
5. train/val 与不同 scope/seq_len/horizon/bins 的 key 互异
6. cache_enabled=False 保持 list index / ndarray features
7. validation 命中仍强制 scaler_stats 校验，绝不重 fit

全部使用 tempfile 造 mini parquet 与临时 cache_dir，不污染真实用户缓存。
"""
import gc
import io
import os
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset
from data.scaler import PerCodeGroupedScaler, RelativeScaler
from data.schema import APPROVED_RAW_FEATURES

FEATURE_COLS = ["open", "high", "low"]


def _make_frame(rows: int = 45) -> pd.DataFrame:
    records = []
    for t in range(rows):
        open_v = 10.0 + t
        records.append({
            "code": "000001",
            "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=t),
            "open": open_v,
            "high": open_v + 1.0,
            "low": open_v - 1.0,
            "close": open_v + 0.5,
            "is_trading": True,
        })
    return pd.DataFrame(records)


def _make_full_frame(rows: int = 45) -> pd.DataFrame:
    """含全部 APPROVED_RAW_FEATURES 的 mini frame（G9 源列存在 → shared mask）。"""
    records = []
    for t in range(rows):
        price = 10.0 + t
        row = {col: price * 0.5 for col in APPROVED_RAW_FEATURES}
        row.update({
            "code": "000001",
            "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=t),
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price + 0.5,
            "is_trading": True,
        })
        records.append(row)
    return pd.DataFrame(records)


class _DatasetCacheTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="t02_cache_")
        cls.parquet_path = os.path.join(cls.tmpdir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(_make_frame(), preserve_index=False), cls.parquet_path)

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _cache_dir(self, name: str) -> str:
        path = Path(self.tmpdir) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _config(self, **over) -> ParquetDataConfig:
        base: dict = {
            "parquet_path": self.parquet_path,
            "seq_len": 5,
            "horizon": 2,
            "feature_cols": list(FEATURE_COLS),
            "batch_size": 8,
            "num_workers": 0,
        }
        base.update(over)
        return ParquetDataConfig(**base)

    def _dataset(self, **over) -> ParquetDataset:
        return ParquetDataset(self._config(**over))


class TestCacheOnOffEquivalence(_DatasetCacheTestCase):
    def test_len_index_and_items_match(self):
        off = self._dataset()
        on = self._dataset(cache_enabled=True, cache_dir=self._cache_dir("eq"))
        self.assertEqual(len(off), len(on))
        self.assertEqual(list(off.index), list(on.index))
        self.assertGreater(len(off), 0)
        step = max(1, len(off) // 7)
        for idx in range(0, len(off), step):
            x_off, y_off, r_off = off[idx]
            x_on, y_on, r_on = on[idx]
            np.testing.assert_array_equal(x_off.numpy(), x_on.numpy())
            self.assertEqual(int(y_off), int(y_on))
            self.assertAlmostEqual(float(r_off), float(r_on), places=7)

    def test_group_features_match_elementwise(self):
        off = self._dataset()
        on = self._dataset(cache_enabled=True, cache_dir=self._cache_dir("eq_groups"))
        self.assertEqual(set(off.groups), set(on.groups))
        for code in off.groups:
            np.testing.assert_array_equal(off.groups[code]["features"], np.asarray(on.groups[code]["features"]))
            np.testing.assert_array_equal(off.groups[code]["future_ret"], on.groups[code]["future_ret"])
            np.testing.assert_array_equal(off.groups[code]["discrete"], on.groups[code]["discrete"])
            np.testing.assert_array_equal(off.groups[code]["open"], on.groups[code]["open"])
            np.testing.assert_array_equal(off.groups[code]["close"], on.groups[code]["close"])
            self.assertEqual(off.groups[code]["n"], on.groups[code]["n"])


class TestCacheAccessors(_DatasetCacheTestCase):
    def _hit_dataset(self, name: str) -> ParquetDataset:
        cfg = self._config(
            cache_enabled=True,
            cache_dir=self._cache_dir(name),
            scaler_path=os.path.join(self.tmpdir, f"{name}_scaler.pkl"),
        )
        ParquetDataset(cfg)  # 首次 miss 落盘（并保存 scaler）
        return ParquetDataset(cfg)  # 二次命中，index 切换为 _WindowIndex

    def test_window_index_semantics(self):
        ds = self._hit_dataset("acc")
        from data.feature_cache import _WindowIndex

        self.assertIsInstance(ds.index, _WindowIndex)
        code, start = ds.index[0]
        self.assertEqual(ds.index.index((code, start)), 0)
        self.assertEqual(ds.index[-1], list(ds.index)[-1])
        self.assertEqual(sum(1 for _ in ds.index), len(ds))
        with self.assertRaises((IndexError, ValueError)):
            _ = ds.index[len(ds)]

    def test_feature_view_finite_and_transpose(self):
        ds = self._hit_dataset("view")
        from data.feature_cache import _FeatureView

        for code in ds.groups:
            feat = ds.groups[code]["features"]
            self.assertIsInstance(feat, _FeatureView)
            self.assertTrue(np.isfinite(np.asarray(feat)).all())
            self.assertTrue(np.isfinite(feat[:2]).all())
            self.assertEqual(feat.T.shape, (feat.shape[1], feat.shape[0]))


class TestCacheDisabledKeepsFrozenPath(_DatasetCacheTestCase):
    def test_index_is_list_and_features_ndarray(self):
        ds = self._dataset()
        self.assertIsInstance(ds.index, list)
        for code in ds.groups:
            self.assertIsInstance(ds.groups[code]["features"], np.ndarray)


class TestCacheMissThenHit(_DatasetCacheTestCase):
    def test_first_miss_writes_cache_then_second_hits(self):
        root = Path(self._cache_dir("refill"))
        cfg = self._config(
            cache_enabled=True,
            cache_dir=str(root),
            scaler_path=os.path.join(self.tmpdir, "refill_scaler.pkl"),
        )
        first_log = io.StringIO()
        with redirect_stdout(first_log):
            first = ParquetDataset(cfg)
        self.assertNotIn("缓存命中", first_log.getvalue())
        self.assertTrue(list(root.glob("*-g0")))
        second_log = io.StringIO()
        with redirect_stdout(second_log):
            second = ParquetDataset(cfg)
        self.assertIn("缓存命中", second_log.getvalue())
        self.assertEqual(list(first.index), list(second.index))
        self.assertEqual(len(first), len(second))
        for code in first.groups:
            np.testing.assert_array_equal(first.groups[code]["features"], np.asarray(second.groups[code]["features"]))


class TestCacheKeyIsolation(_DatasetCacheTestCase):
    def _key(self, **over) -> str:
        cfg = self._config(**over)
        feature_cols = list(cfg.feature_cols or [])
        pf = pq.ParquetFile(self.parquet_path)
        identity = ParquetDataset._scaler_identity(cfg, pf, feature_cols)
        return ParquetDataset._cache_key(cfg, np.array(cfg.bins, dtype=np.float64), identity, feature_cols)

    def test_same_params_stable(self):
        self.assertEqual(self._key(), self._key())

    def test_role_and_index_params_change_key(self):
        base = self._key()
        self.assertNotEqual(base, self._key(role="validation"))
        self.assertNotEqual(base, self._key(seq_len=7))
        self.assertNotEqual(base, self._key(horizon=3))
        self.assertNotEqual(base, self._key(max_windows_per_code=10))
        self.assertNotEqual(base, self._key(bins=[-0.1, 0.0, 0.1]))

    def test_rolling_scope_changes_key(self):
        e2 = self._key(normalize="rolling", rolling_scope="e2")
        e3 = self._key(normalize="rolling", rolling_scope="e3")
        e4 = self._key(normalize="rolling", rolling_scope="e4")
        self.assertEqual(len({e2, e3, e4}), 3)

    def test_train_and_validation_land_in_distinct_generations(self):
        root = Path(self._cache_dir("roles"))
        train = ParquetDataset(self._config(cache_enabled=True, cache_dir=str(root)))
        ParquetDataset(self._config(role="validation", cache_enabled=True, cache_dir=str(root)), train.scaler_stats)
        prefixes = {p.name.rsplit("-g", 1)[0] for p in root.iterdir() if p.is_dir()}
        self.assertEqual(len(prefixes), 2)


class TestValidationScalerRedLine(_DatasetCacheTestCase):
    def test_cache_hit_still_requires_and_validates_scaler(self):
        root = Path(self._cache_dir("val_redline"))
        train = ParquetDataset(self._config(cache_enabled=True, cache_dir=str(root)))
        val_cfg = self._config(role="validation", cache_enabled=True, cache_dir=str(root))
        # 首次构造 validation 走 miss 并落盘
        val_first = ParquetDataset(val_cfg, train.scaler_stats)
        self.assertGreater(len(val_first), 0)
        # 二次构造命中，且带合法 scaler 时结果一致
        hit_log = io.StringIO()
        with redirect_stdout(hit_log):
            val_hit = ParquetDataset(val_cfg, train.scaler_stats)
        self.assertIn("缓存命中", hit_log.getvalue())
        self.assertEqual(list(val_first.index), list(val_hit.index))
        # 命中路径下缺 scaler 仍按既有语义报错
        with self.assertRaisesRegex(ValueError, "scaler"):
            ParquetDataset(val_cfg)
        # 命中路径下 schema 不匹配的 scaler 仍报错
        bad = PerCodeGroupedScaler().fit(_make_frame(), ["open"])
        bad.set_identity({"x": 1})
        with self.assertRaises(ValueError):
            ParquetDataset(val_cfg, bad)


class TestTrainingHitRequiresScaler(_DatasetCacheTestCase):
    def test_training_hit_without_scaler_raises(self):
        cfg = self._config(cache_enabled=True, cache_dir=self._cache_dir("train_no_scaler"))
        ParquetDataset(cfg)  # 首次 miss 现场拟合并落盘
        with self.assertRaisesRegex(ValueError, "scaler_path"):
            ParquetDataset(cfg)  # 二次命中但没有可用 scaler，必须显式失败

    def test_training_hit_with_scaler_path_loads(self):
        scaler_path = os.path.join(self.tmpdir, "hit_scaler.pkl")
        cfg = self._config(
            cache_enabled=True, cache_dir=self._cache_dir("train_with_scaler"), scaler_path=scaler_path
        )
        first = ParquetDataset(cfg)  # miss：拟合后保存 scaler
        self.assertTrue(os.path.exists(scaler_path))
        second = ParquetDataset(cfg)  # hit：从 scaler_path 加载，不重 fit
        self.assertIsInstance(second.scaler_stats, PerCodeGroupedScaler)
        self.assertEqual(first.num_features, second.num_features)
        self.assertEqual(list(first.index), list(second.index))


class TestRollingCacheHit(_DatasetCacheTestCase):
    def test_rolling_hit_reconstructs_features(self):
        root = self._cache_dir("rolling")
        off = self._dataset(normalize="rolling", rolling_scope="e2")
        cfg = self._config(normalize="rolling", rolling_scope="e2", cache_enabled=True, cache_dir=root)
        first = ParquetDataset(cfg)  # miss 落盘
        hit_log = io.StringIO()
        with redirect_stdout(hit_log):
            second = ParquetDataset(cfg)  # 命中
        self.assertIn("缓存命中", hit_log.getvalue())
        self.assertEqual(list(off.index), list(second.index))
        self.assertEqual(second.num_features, off.num_features)
        self.assertEqual(list(second.feature_cols_out), list(off.feature_cols_out))
        # 命中路径必须从 extra 恢复 rolling_audit，与 miss 路径一致
        self.assertEqual(second.rolling_audit, first.rolling_audit)
        self.assertGreater(second.rolling_audit["fallback_values"], 0)
        for code in off.groups:
            np.testing.assert_array_equal(off.groups[code]["features"], np.asarray(second.groups[code]["features"]))
            np.testing.assert_array_equal(off.groups[code]["future_ret"], second.groups[code]["future_ret"])
        self.assertEqual(first.num_features, second.num_features)


class TestRebuildCacheWriteNewGeneration(_DatasetCacheTestCase):
    """rebuild_cache=True 跳过命中、写新 generation 且不覆盖在用目录。"""

    def test_rebuild_skips_hit_and_publishes_new_generation(self):
        root = Path(self._cache_dir("rebuild"))
        scaler_path = os.path.join(self.tmpdir, "rebuild_scaler.pkl")
        cfg = self._config(cache_enabled=True, cache_dir=str(root), scaler_path=scaler_path)
        first = ParquetDataset(cfg)  # miss -> g0
        gens_before = sorted(p.name for p in root.glob("*-g*") if p.is_dir())
        self.assertEqual(len(gens_before), 1)

        rebuild_log = io.StringIO()
        with redirect_stdout(rebuild_log):
            rebuilt = ParquetDataset(replace(cfg, rebuild_cache=True))
        self.assertNotIn("缓存命中", rebuild_log.getvalue())
        gens_after = sorted(p.name for p in root.glob("*-g*") if p.is_dir())
        self.assertEqual(len(gens_after), 2)
        self.assertIn(gens_before[0], gens_after)  # 旧 generation 不被覆盖
        self.assertEqual(list(first.index), list(rebuilt.index))

        hit_log = io.StringIO()
        with redirect_stdout(hit_log):
            hit = ParquetDataset(cfg)  # 正常构造命中最新 generation
        self.assertIn("缓存命中", hit_log.getvalue())
        self.assertEqual(list(hit.index), list(first.index))


class TestMaxCodesWindowLimitCacheEquivalence(unittest.TestCase):
    """T04: max_codes / max_windows_per_code 小样本端到端（cache on 命中 == off）。"""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="t04_maxcodes_")
        cls.parquet_path = os.path.join(cls.tmpdir, "mini_multi.parquet")
        frame = _make_frame()
        extra = frame.copy()
        extra["code"] = "000002"
        extra["open"] = extra["open"] + 0.5
        extra["high"] = extra["high"] + 0.5
        extra["low"] = extra["low"] + 0.5
        extra["close"] = extra["close"] + 0.5
        combined = pd.concat([frame, extra], ignore_index=True)
        pq.write_table(pa.Table.from_pandas(combined, preserve_index=False), cls.parquet_path)

    @classmethod
    def tearDownClass(cls):
        gc.collect()
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _config(self, **over) -> ParquetDataConfig:
        base: dict = {
            "parquet_path": self.parquet_path,
            "seq_len": 5,
            "horizon": 2,
            "feature_cols": list(FEATURE_COLS),
            "batch_size": 8,
            "num_workers": 0,
            "max_codes": 2,
            "max_windows_per_code": 3,
        }
        base.update(over)
        return ParquetDataConfig(**base)

    def test_cache_hit_matches_off_under_limits(self):
        off = ParquetDataset(self._config())
        per_code = Counter(code for code, _ in off.index)
        self.assertEqual(set(per_code), {"000001", "000002"})
        self.assertTrue(all(n <= 3 for n in per_code.values()))
        self.assertGreater(len(off), 0)

        cache_root = Path(self.tmpdir) / "mc_cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        cfg = self._config(
            cache_enabled=True,
            cache_dir=str(cache_root),
            scaler_path=os.path.join(self.tmpdir, "mc_scaler.pkl"),
        )
        ParquetDataset(cfg)  # miss 落盘
        hit_log = io.StringIO()
        with redirect_stdout(hit_log):
            hit = ParquetDataset(cfg)  # 二次命中
        self.assertIn("缓存命中", hit_log.getvalue())
        self.assertEqual(len(off), len(hit))
        self.assertEqual(list(off.index), list(hit.index))
        for idx in range(len(off)):
            x_off, y_off, r_off = off[idx]
            x_hit, y_hit, r_hit = hit[idx]
            np.testing.assert_array_equal(x_off.numpy(), x_hit.numpy())
            self.assertEqual(int(y_off), int(y_hit))
            self.assertAlmostEqual(float(r_off), float(r_hit), places=7)


class TestRelativeMode(_DatasetCacheTestCase):
    """T05: relative 无状态归一化接入（feature_cols_out / cache key / 不重 fit）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.full_path = os.path.join(cls.tmpdir, "mini_full.parquet")
        pq.write_table(
            pa.Table.from_pandas(_make_full_frame(), preserve_index=False), cls.full_path
        )

    def _full_config(self, **over) -> ParquetDataConfig:
        base: dict = {
            "parquet_path": self.full_path,
            "seq_len": 5,
            "horizon": 2,
            "feature_cols": list(APPROVED_RAW_FEATURES),
            "normalize": "relative",
            "num_workers": 0,
        }
        base.update(over)
        return ParquetDataConfig(**base)

    def _key(self, **over) -> str:
        cfg = self._config(**over)
        feature_cols = list(cfg.feature_cols or [])
        pf = pq.ParquetFile(self.parquet_path)
        identity = ParquetDataset._scaler_identity(cfg, pf, feature_cols)
        return ParquetDataset._cache_key(cfg, np.array(cfg.bins, dtype=np.float64), identity, feature_cols)

    def test_num_features_and_shared_mask(self):
        ds = ParquetDataset(self._full_config())
        self.assertEqual(ds.num_features, 53)
        self.assertEqual(ds.feature_cols_out[-1], "g9_observed_mask")
        self.assertEqual(tuple(ds[0][0].shape), (53, 5))
        self.assertIsInstance(ds.scaler_stats, RelativeScaler)

    def test_subset_without_g9_has_no_mask(self):
        ds = ParquetDataset(self._config(normalize="relative"))
        self.assertEqual(ds.num_features, len(FEATURE_COLS))
        self.assertEqual(ds.feature_cols_out, list(FEATURE_COLS))

    def test_single_col_subset_output_one(self):
        ds = ParquetDataset(self._config(normalize="relative", feature_cols=["open"]))
        self.assertEqual(ds.num_features, 1)
        self.assertEqual(ds.feature_cols_out, ["open"])

    def test_cache_key_sensitive_to_relative_mode(self):
        per_code = self._key(normalize="per_code")
        relative = self._key(normalize="relative")
        rolling = self._key(normalize="rolling", rolling_scope="e5")
        self.assertEqual(len({per_code, relative, rolling}), 3)
        self.assertEqual(relative, self._key(normalize="relative"))

    def test_relative_never_fits(self):
        with patch.object(PerCodeGroupedScaler, "fit", autospec=True) as fit:
            ParquetDataset(self._full_config())
        fit.assert_not_called()

    def test_relative_validation_without_scaler_ok(self):
        train = ParquetDataset(self._full_config(role="training", end_date="2020-02-05"))
        val = ParquetDataset(self._full_config(role="validation", start_date="2020-02-06"))
        self.assertGreater(len(val), 0)
        self.assertEqual(val.num_features, train.num_features)
        self.assertIsInstance(val.scaler_stats, RelativeScaler)

    def test_cache_miss_then_hit_reconstructs_without_refit(self):
        root = Path(self._cache_dir("relative_cache"))
        cfg = self._full_config(cache_enabled=True, cache_dir=str(root))
        first = ParquetDataset(cfg)
        hit_log = io.StringIO()
        with patch.object(PerCodeGroupedScaler, "fit", autospec=True) as fit, redirect_stdout(hit_log):
            second = ParquetDataset(cfg)
        self.assertIn("缓存命中", hit_log.getvalue())
        fit.assert_not_called()
        self.assertEqual(first.num_features, second.num_features)
        self.assertEqual(list(first.feature_cols_out), list(second.feature_cols_out))
        self.assertEqual(list(first.index), list(second.index))
        self.assertIsInstance(second.scaler_stats, RelativeScaler)
        for code in first.groups:
            np.testing.assert_array_equal(
                np.asarray(first.groups[code]["features"]),
                np.asarray(second.groups[code]["features"]),
            )

    def test_validation_cache_hit_without_scaler_ok(self):
        root = Path(self._cache_dir("relative_val_hit"))
        cfg = self._full_config(role="validation", cache_enabled=True, cache_dir=str(root))
        ParquetDataset(cfg)
        hit_log = io.StringIO()
        with redirect_stdout(hit_log):
            hit = ParquetDataset(cfg)
        self.assertIn("缓存命中", hit_log.getvalue())
        self.assertIsInstance(hit.scaler_stats, RelativeScaler)


if __name__ == "__main__":
    unittest.main()
