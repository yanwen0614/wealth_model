"""feature_cache 单测（T01 TDD Red-Green）。

覆盖：resolve_cache_root 跨平台默认；compute_cache_key 字段敏感；
FeatureCache save/load round-trip（features/小数组/index）；无 .ok 不可读、
异 key 隔离、重复 save 新 generation；_WindowIndex 语义；_FeatureView 语义与 pickle。

约束：全程 tempfile + monkeypatch env，绝不触碰真实用户缓存目录；不依赖真实 parquet。
Windows 下 np.memmap 持文件句柄，测试需显式关闭后再删除临时目录。
"""
import gc
import json
import os
import pickle
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from data import feature_cache
from data.feature_cache import (
    CACHE_FORMAT_VERSION,
    FeatureCache,
    _FeatureView,
    _WindowIndex,
    compute_bins_digest,
    compute_cache_key,
    resolve_cache_root,
)


def _key_kwargs(**over):
    base = {
        "base_identity": {"parquet_path": "x.parquet", "size": 1, "mtime_ns": 2},
        "role": "training",
        "rolling_scope": "e4",
        "scaler_identity_hash": "abc123",
        "seq_len": 60,
        "horizon": 5,
        "max_windows_per_code": None,
        "bins_digest": "deadbeef",
    }
    base.update(over)
    return base


def _make_groups():
    """构造 3 只假股票的小样本数据（不读 parquet）。"""
    rng = np.random.default_rng(0)
    groups = {}
    index = []
    codes = ["000001", "000002", "600000"]
    n_per_code = [7, 5, 6]
    num_features = 4
    for ci, (code, n) in enumerate(zip(codes, n_per_code)):
        feats = rng.standard_normal((n, num_features)).astype(np.float32)
        fret = (rng.standard_normal(n) * 0.01).astype(np.float32)
        disc = np.digitize(fret.astype(np.float64), np.linspace(-0.25, 0.25, 51)).astype(np.int64)
        op = (10.0 + np.arange(n) + ci).astype(np.float64)
        cl = (op + 0.5).astype(np.float64)
        kt = ((np.arange(n) + ci * 10) * 1_000_000_000).astype(np.int64)
        groups[code] = {
            "features": feats, "future_ret": fret, "discrete": disc,
            "open": op, "close": cl, "kline_time": kt, "n": n,
        }
        for s in range(max(0, n - 4)):
            index.append((code, s))
    return groups, index, codes, n_per_code, num_features


def _close_memmap(mem) -> None:
    inner = getattr(mem, "_mmap", None)
    if inner is not None and hasattr(inner, "close"):
        try:
            inner.close()
        except (ValueError, OSError):
            pass


class _CacheTestCase(unittest.TestCase):
    """公共夹具：临时根 + 小样本 + memmap 句柄回收。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "cache"
        self.groups, self.index, self.codes, self.n_per_code, self.num_features = _make_groups()
        self.cols = [f"f{i}" for i in range(self.num_features)]
        self.key = compute_cache_key(**_key_kwargs())
        self._loaded = []
        self.addCleanup(self._close_loaded)

    def _close_loaded(self):
        for data in self._loaded:
            _close_memmap(data.features._mmap)
        self._loaded = []
        gc.collect()

    def _load(self, key=None):
        data = FeatureCache.load(self.root, key or self.key)
        if data is not None:
            self._loaded.append(data)
        return data

    def _save(self, key=None, extra=None):
        return FeatureCache.save(
            self.root, key or self.key, self.groups, self.index,
            feature_cols=self.cols, feature_cols_out=self.cols,
            key_components={"role": "training"}, extra=extra,
        )

    def _expected(self, field):
        return np.concatenate([np.asarray(self.groups[c][field]) for c in self.codes])


class TestResolveCacheRoot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        home_patcher = mock.patch("pathlib.Path.home", return_value=self.home)
        home_patcher.start()
        self.addCleanup(home_patcher.stop)
        self._saved = {k: os.environ.get(k) for k in ("CNN_DATA_CACHE", "XDG_CACHE_HOME", "LOCALAPPDATA")}
        for key in self._saved:
            os.environ.pop(key, None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_explicit_param_over_env(self):
        os.environ["CNN_DATA_CACHE"] = str(Path(self.tmp.name) / "env")
        explicit = Path(self.tmp.name) / "explicit"
        got = resolve_cache_root(str(explicit))
        self.assertEqual(got, explicit)
        self.assertTrue(got.is_dir())

    def test_env_used_when_no_param(self):
        os.environ["CNN_DATA_CACHE"] = str(Path(self.tmp.name) / "env")
        self.assertEqual(resolve_cache_root(), Path(self.tmp.name) / "env")

    def test_linux_xdg_default(self):
        os.environ["XDG_CACHE_HOME"] = str(Path(self.tmp.name) / "xdg")
        with mock.patch.object(sys, "platform", "linux"):
            got = resolve_cache_root()
        self.assertEqual(got, Path(self.tmp.name) / "xdg" / "cnn")

    def test_linux_home_fallback(self):
        with mock.patch.object(sys, "platform", "linux"):
            got = resolve_cache_root()
        self.assertEqual(got, self.home / ".cache" / "cnn")

    def test_windows_localappdata_default(self):
        os.environ["LOCALAPPDATA"] = str(Path(self.tmp.name) / "la")
        with mock.patch.object(sys, "platform", "win32"):
            got = resolve_cache_root()
        self.assertEqual(got, Path(self.tmp.name) / "la" / "cnn" / "cache")

    def test_windows_home_fallback(self):
        with mock.patch.object(sys, "platform", "win32"):
            got = resolve_cache_root()
        self.assertEqual(got, self.home / "AppData" / "Local" / "cnn" / "cache")

    def test_no_drive_letter_hardcode(self):
        src = Path(feature_cache.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", src))


class TestComputeCacheKey(unittest.TestCase):
    def test_stable_hex16(self):
        first = compute_cache_key(**_key_kwargs())
        second = compute_cache_key(**_key_kwargs())
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{16}$")

    def test_each_field_changes_key(self):
        base = compute_cache_key(**_key_kwargs())
        variants = {
            "role": _key_kwargs(role="validation"),
            "rolling_scope": _key_kwargs(rolling_scope="e2"),
            "scaler_identity_hash": _key_kwargs(scaler_identity_hash="other"),
            "seq_len": _key_kwargs(seq_len=30),
            "horizon": _key_kwargs(horizon=10),
            "max_windows_per_code": _key_kwargs(max_windows_per_code=100),
            "bins_digest": _key_kwargs(bins_digest="cafebabe"),
            "base_identity": _key_kwargs(base_identity={"parquet_path": "y.parquet", "size": 1, "mtime_ns": 2}),
            "version": _key_kwargs(version="v9"),
        }
        for name, kwargs in variants.items():
            with self.subTest(field=name):
                self.assertNotEqual(base, compute_cache_key(**kwargs))
        self.assertNotEqual(CACHE_FORMAT_VERSION, "")

    def test_bins_digest_stable_and_sensitive(self):
        bins = list(np.linspace(-0.25, 0.25, 51))
        self.assertEqual(compute_bins_digest(bins), compute_bins_digest(list(bins)))
        self.assertEqual(compute_bins_digest(bins), compute_bins_digest([float(b) for b in bins]))
        self.assertNotEqual(compute_bins_digest(bins), compute_bins_digest(bins[:-1]))


class TestCacheFormatVersion(_CacheTestCase):
    """T02: warmup 语义变更必须使携带旧语义的 generation 失效。"""

    def test_current_version_is_v2_context_warmup(self):
        self.assertEqual(CACHE_FORMAT_VERSION, "v2_context_warmup")

    def test_legacy_version_meta_is_a_miss(self):
        path = self._save()
        self.assertIsNotNone(self._load())
        meta_path = path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["cache_format_version"] = "v1_memmap_cache"
        meta_path.write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True), encoding="utf-8"
        )
        self.assertIsNone(self._load())

    def test_warmup_semantics_changes_key(self):
        base = compute_cache_key(**_key_kwargs())
        legacy = compute_cache_key(**_key_kwargs(version="v1_memmap_cache"))
        self.assertNotEqual(base, legacy)


class TestFeatureCacheRoundTrip(_CacheTestCase):
    def test_round_trip_features_and_meta(self):
        path = self._save()
        self.assertEqual(path.name, f"{self.key}-g0")
        self.assertTrue((path / ".ok").exists())
        data = self._load()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data.codes, self.codes)
        self.assertEqual(data.offsets, [0, 7, 12])
        self.assertEqual(data.n_per_code, self.n_per_code)
        self.assertEqual(data.total_rows, 18)
        self.assertEqual(data.num_features, self.num_features)
        self.assertEqual(data.feature_cols, self.cols)
        self.assertEqual(data.feature_cols_out, self.cols)
        full = np.asarray(data.features)
        self.assertEqual(full.dtype, np.float32)
        np.testing.assert_array_equal(full, self._expected("features"))
        self.assertTrue(np.isfinite(full).all())

    def test_round_trip_small_arrays_and_dtypes(self):
        self._save()
        data = self._load()
        assert data is not None
        np.testing.assert_array_equal(data.future_ret, self._expected("future_ret"))
        np.testing.assert_array_equal(data.discrete, self._expected("discrete"))
        np.testing.assert_array_equal(data.open, self._expected("open"))
        np.testing.assert_array_equal(data.close, self._expected("close"))
        np.testing.assert_array_equal(data.kline_time, self._expected("kline_time"))
        self.assertEqual(data.future_ret.dtype, np.float32)
        self.assertEqual(data.discrete.dtype, np.int64)
        self.assertEqual(data.open.dtype, np.float64)
        self.assertEqual(data.close.dtype, np.float64)
        self.assertEqual(data.kline_time.dtype, np.int64)
        self.assertEqual(data.window_code_ids.dtype, np.int32)
        self.assertEqual(data.window_starts.dtype, np.int32)

    def test_round_trip_window_index(self):
        self._save()
        data = self._load()
        assert data is not None
        rebuilt = _WindowIndex(data.codes, data.window_code_ids, data.window_starts)
        self.assertEqual(list(rebuilt), self.index)
        self.assertEqual(len(rebuilt), len(self.index))
        self.assertEqual(rebuilt.index(self.index[-1]), len(self.index) - 1)

    def test_feature_view_subview_per_code(self):
        self._save()
        data = self._load()
        assert data is not None
        first = self.codes[0]
        view = data.features.subview(data.offsets[0], data.n_per_code[0])
        self.assertTrue(np.isfinite(np.asarray(view)).all())
        self.assertEqual(view.shape, (self.n_per_code[0], self.num_features))
        self.assertEqual(view.dtype, np.float32)
        np.testing.assert_array_equal(np.asarray(view), self.groups[first]["features"])
        np.testing.assert_array_equal(np.asarray(view.T), self.groups[first]["features"].T)

    def test_extra_round_trip(self):
        extra = {"rolling_audit": {"fallback_values": 3, "fallback_ratio": 0.25}, "note": "e2"}
        self._save(extra=extra)
        data = self._load()
        assert data is not None
        self.assertEqual(data.extra, extra)
        self.assertIsInstance(data.extra, dict)

    def test_extra_defaults_to_empty_for_legacy_meta(self):
        path = self._save()
        meta_path = path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("extra", None)  # 模拟旧版本 meta（无 extra 键）
        meta_path.write_text(
            json.dumps(meta, sort_keys=True, separators=(",", ":"), ensure_ascii=True), encoding="utf-8"
        )
        self.assertNotIn("extra", json.loads(meta_path.read_text(encoding="utf-8")))
        data = self._load()
        assert data is not None
        self.assertEqual(data.extra, {})


class TestFeatureCacheAtomicity(_CacheTestCase):
    def test_missing_ok_is_a_miss(self):
        path = self._save()
        self.assertIsNotNone(self._load())
        (path / ".ok").unlink()
        self.assertIsNone(self._load())

    def test_other_key_isolated(self):
        self._save()
        other = compute_cache_key(**_key_kwargs(role="validation"))
        self.assertIsNone(self._load(other))

    def test_repeat_save_new_generation_keeps_old(self):
        first = self._save()
        second = self._save()
        self.assertEqual(first.name, f"{self.key}-g0")
        self.assertEqual(second.name, f"{self.key}-g1")
        self.assertTrue((first / ".ok").exists())
        self.assertTrue((second / ".ok").exists())
        latest = self._load()
        assert latest is not None
        self.assertEqual(latest.path.name, f"{self.key}-g1")
        leftovers = [p.name for p in self.root.iterdir() if p.name.startswith("tmp-")]
        self.assertEqual(leftovers, [])


class TestWindowIndex(unittest.TestCase):
    def setUp(self):
        self.codes = ["a", "b", "c"]
        self.pairs = [("a", 0), ("a", 3), ("b", 1), ("c", 2), ("c", 5)]
        self.code_ids = np.array([0, 0, 1, 2, 2], dtype=np.int32)
        self.starts = np.array([0, 3, 1, 2, 5], dtype=np.int32)
        self.wi = _WindowIndex(self.codes, self.code_ids, self.starts)

    def test_len_getitem_negative(self):
        self.assertEqual(len(self.wi), 5)
        self.assertEqual(self.wi[0], ("a", 0))
        self.assertEqual(self.wi[-1], ("c", 5))
        self.assertEqual(self.wi[-2], ("c", 2))
        with self.assertRaises(IndexError):
            _ = self.wi[5]

    def test_iter_matches_list(self):
        self.assertEqual(list(self.wi), self.pairs)

    def test_index_lookup(self):
        self.assertEqual(self.wi.index(("a", 3)), 1)
        self.assertEqual(self.wi.index(("b", 1)), 2)
        with self.assertRaises(ValueError):
            self.wi.index(("z", 0))
        with self.assertRaises(ValueError):
            self.wi.index(("a", 99))

    def test_pickle_round_trip(self):
        obj = pickle.loads(pickle.dumps(self.wi))
        self.assertEqual(list(obj), self.pairs)
        self.assertEqual(obj.index(("c", 5)), 4)
        self.assertEqual(obj.code_ids.dtype, np.int32)


class TestFeatureView(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arr = np.arange(4000, dtype=np.float32).reshape(400, 10)
        self.path = Path(self.tmp.name) / "features.npy"
        np.save(self.path, self.arr)
        self.mmap = np.load(self.path, mmap_mode="r")
        self.addCleanup(_close_memmap, self.mmap)
        self.view = _FeatureView(self.mmap, 1, 200, 10)
        self._rows = self.arr[1:201]

    def test_shape_dtype_len(self):
        self.assertEqual(self.view.shape, (200, 10))
        self.assertEqual(self.view.dtype, np.float32)
        self.assertEqual(len(self.view), 200)

    def test_array_slice_and_transpose(self):
        np.testing.assert_array_equal(np.asarray(self.view), self._rows)
        self.assertTrue(np.isfinite(np.asarray(self.view)).all())
        np.testing.assert_array_equal(np.asarray(self.view[:1]), self._rows[:1])
        np.testing.assert_array_equal(np.asarray(self.view.T), self._rows.T)

    def test_pickle_is_reference_only(self):
        self.assertIn("path", self.view.__getstate__())
        self.assertNotIn("data", self.view.__getstate__())
        blob = pickle.dumps(self.view)
        obj = pickle.loads(blob)
        self.addCleanup(_close_memmap, obj._mmap)
        np.testing.assert_array_equal(np.asarray(obj), self._rows)
        self.assertIsInstance(obj._mmap, np.memmap)
        self.assertLess(len(blob), self.view.n * self.view.num_features * 4)  # 未复制 float32 数据


class TestFeatureViewSharedMmap(unittest.TestCase):
    """修复 WinError 1455：同路径 memmap 进程内共享，pickle 往返不再重复全量映射。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arr = np.arange(4000, dtype=np.float32).reshape(400, 10)
        self.path = Path(self.tmp.name) / "features.npy"
        np.save(self.path, self.arr)
        self.mmap = np.load(self.path, mmap_mode="r")
        self.addCleanup(_close_memmap, self.mmap)
        self.view = _FeatureView(self.mmap, 0, 400, 10)
        self.addCleanup(self._close_registry)
        self._close_registry()

    def _close_registry(self):
        registry = getattr(feature_cache, "_MMAP_REGISTRY", None)
        if not registry:
            return
        for mem in list(registry.values()):
            _close_memmap(mem)
        registry.clear()

    def test_subviews_share_one_mmap_after_pickle(self):
        a = self.view.subview(0, 150)
        b = self.view.subview(150, 150)
        a2 = pickle.loads(pickle.dumps(a))
        b2 = pickle.loads(pickle.dumps(b))
        self.assertIs(a2._mmap, b2._mmap)
        self.assertIsInstance(a2._mmap, np.memmap)

    def test_registry_loads_same_path_once(self):
        registry = getattr(feature_cache, "_MMAP_REGISTRY", None)
        if registry is not None:
            registry.clear()
        real_load = np.load
        calls = []

        def counting_load(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("file"))
            return real_load(*args, **kwargs)

        views = [self.view.subview(i, 1) for i in range(6)]
        with mock.patch.object(feature_cache.np, "load", side_effect=counting_load):
            loaded = [pickle.loads(pickle.dumps(v)) for v in views]
        self.assertEqual(len(calls), 1)
        for obj in loaded:
            self.assertIs(obj._mmap, loaded[0]._mmap)

    def test_round_trip_values_unchanged(self):
        view = self.view.subview(1, 200)
        obj = pickle.loads(pickle.dumps(view))
        expected = self.arr[1:201]
        np.testing.assert_array_equal(np.asarray(obj), expected)
        np.testing.assert_array_equal(np.asarray(obj[:3]), expected[:3])
        np.testing.assert_array_equal(np.asarray(obj.T), expected.T)
        self.assertEqual(obj.shape, (200, 10))
        self.assertEqual(obj.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
