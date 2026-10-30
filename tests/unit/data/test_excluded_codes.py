"""代码级黑名单（`data/excluded_codes.json`）契约测试（TDD）。

覆盖：
1. 名单文件可加载、schema/条目校验、digest 与条目顺序无关；
2. 黑名单代码永不出现在 dataset 窗口（groups/index 均无、总行数减少）；
3. 正常股票不受影响（未排除时逐元素一致）；
4. exclude_codes=False 时不过滤（显式 opt-out 生效）；
5. identity 绑定：空名单不写入（旧 key 逐字节不变），非空名单写入 digest 并使 key 变化；
6. 缺文件/坏 schema 必须显式报错，不做静默空名单降级。

全部使用 tempfile 造 mini parquet / mini 黑名单，不读真实大文件、不碰任何 parquet 原文件。
"""
import gc
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset
from data.excluded_codes import (
    excluded_codes_digest,
    excluded_codes_identity,
    filter_excluded_codes,
    load_excluded_codes,
)
from data.schema import APPROVED_RAW_FEATURES

FEATURE_COLS = ["open", "high", "low"]
BLACK = "000002"
KEEP = "000001"


def _make_frame(codes: tuple[str, ...] = (KEEP, BLACK), rows: int = 45) -> pd.DataFrame:
    """两只股票、各 rows 行的 mini frame（价格随 t 变化，保证标签非 NaN）。"""
    records = []
    for code in codes:
        for t in range(rows):
            price = 10.0 + t
            row = {col: price * 0.5 for col in APPROVED_RAW_FEATURES}
            row.update({
                "code": code,
                "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=t),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.5,
                "is_trading": True,
            })
            records.append(row)
    return pd.DataFrame(records)


def _write_json(path: str, payload: dict) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


def _blacklist_payload(codes: list[str], schema_version: int = 1) -> dict:
    return {
        "schema_version": schema_version,
        "generated_at": "2026-10-30",
        "policy": "mini fixture",
        "excluded": [{"code": code, "reason": "mini fixture"} for code in codes],
    }


class _ExcludedCodesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="excluded_codes_")
        cls.parquet_path = os.path.join(cls.tmpdir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(_make_frame(), preserve_index=False), cls.parquet_path)
        cls.blacklist_path = _write_json(
            os.path.join(cls.tmpdir, "excluded_codes.json"), _blacklist_payload([BLACK])
        )
        cls.empty_blacklist_path = _write_json(
            os.path.join(cls.tmpdir, "excluded_empty.json"), _blacklist_payload([])
        )

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
            "excluded_codes_path": self.blacklist_path,
        }
        base.update(over)
        return ParquetDataConfig(**base)


class TestExcludedCodesLoading(_ExcludedCodesTestCase):
    def test_loads_codes_from_file(self):
        self.assertEqual(load_excluded_codes(self.blacklist_path), frozenset({BLACK}))

    def test_empty_list_loads_as_empty_frozenset(self):
        self.assertEqual(load_excluded_codes(self.empty_blacklist_path), frozenset())

    def test_digest_is_order_insensitive(self):
        self.assertEqual(
            excluded_codes_digest(frozenset({"a", "b", "c"})),
            excluded_codes_digest({"c", "a", "b"}),
        )
        self.assertNotEqual(
            excluded_codes_digest(frozenset({"a", "b"})), excluded_codes_digest(frozenset({"a"}))
        )

    def test_missing_file_raises(self):
        with self.assertRaises(OSError):
            load_excluded_codes(os.path.join(self.tmpdir, "nope.json"))

    def test_bad_schema_version_raises(self):
        path = _write_json(
            os.path.join(self.tmpdir, "bad_version.json"), _blacklist_payload([BLACK], schema_version=99)
        )
        with self.assertRaisesRegex(ValueError, "schema_version"):
            load_excluded_codes(path)

    def test_malformed_entry_raises(self):
        path = _write_json(
            os.path.join(self.tmpdir, "bad_entry.json"),
            {"schema_version": 1, "excluded": [{"reason": "no code"}]},
        )
        with self.assertRaisesRegex(TypeError, "code"):
            load_excluded_codes(path)


class TestFilterFunction(_ExcludedCodesTestCase):
    def test_drops_all_rows_of_blacklisted_code_only(self):
        df = pq.read_table(self.parquet_path).to_pandas()
        out = filter_excluded_codes(df, frozenset({BLACK}))
        self.assertEqual(set(out["code"]), {KEEP})
        self.assertEqual(len(out), len(df) // 2)

    def test_empty_codes_returns_same_content(self):
        df = pq.read_table(self.parquet_path).to_pandas()
        out = filter_excluded_codes(df, frozenset())
        pd.testing.assert_frame_equal(out, df)

    def test_logs_excluded_code_and_row_counts(self):
        df = pq.read_table(self.parquet_path).to_pandas()
        buf = StringIO()
        with redirect_stdout(buf):
            filter_excluded_codes(df, frozenset({BLACK}))
        log = buf.getvalue()
        self.assertIn("1 只", log)
        self.assertIn("drop", log)


class TestDatasetExcludesBlacklistedCode(_ExcludedCodesTestCase):
    def test_blacklisted_code_absent_from_groups_and_index(self):
        ds = ParquetDataset(self._config())
        self.assertNotIn(BLACK, ds.groups)
        self.assertTrue(all(code != BLACK for code, _ in ds.index))
        self.assertGreater(len(ds), 0)

    def test_all_labels_in_index_belong_to_kept_code(self):
        ds = ParquetDataset(self._config())
        self.assertEqual({code for code, _ in ds.index}, {KEEP})

    def test_normal_code_unaffected_vs_unfiltered_baseline(self):
        baseline = ParquetDataset(self._config(excluded_codes_path=self.empty_blacklist_path))
        filtered = ParquetDataset(self._config())
        self.assertIn(KEEP, baseline.groups)
        self.assertIn(KEEP, filtered.groups)
        np.testing.assert_array_equal(
            np.asarray(baseline.groups[KEEP]["features"]),
            np.asarray(filtered.groups[KEEP]["features"]),
        )
        self.assertEqual(len(baseline.groups[KEEP]["kline_time"]), len(filtered.groups[KEEP]["kline_time"]))
        keep_index = [pair for pair in filtered.index if pair[0] == KEEP]
        self.assertEqual(keep_index, [pair for pair in baseline.index if pair[0] == KEEP])

    def test_blacklisted_rows_removed_from_total_window_count(self):
        baseline = ParquetDataset(self._config(excluded_codes_path=self.empty_blacklist_path))
        filtered = ParquetDataset(self._config())
        black_windows = sum(1 for code, _ in baseline.index if code == BLACK)
        self.assertGreater(black_windows, 0)
        self.assertEqual(len(baseline) - len(filtered), black_windows)

    def test_exclude_codes_false_opts_out(self):
        ds = ParquetDataset(self._config(exclude_codes=False))
        self.assertIn(BLACK, ds.groups)
        self.assertTrue(any(code == BLACK for code, _ in ds.index))

    def test_filter_log_is_observable(self):
        buf = StringIO()
        with redirect_stdout(buf):
            ParquetDataset(self._config())
        self.assertIn("排除黑名单代码", buf.getvalue())


class TestIdentityBinding(_ExcludedCodesTestCase):
    def test_empty_list_does_not_change_identity(self):
        pf = pq.ParquetFile(self.parquet_path)
        feature_cols = list(FEATURE_COLS)
        with_empty = ParquetDataset._scaler_identity(
            self._config(excluded_codes_path=self.empty_blacklist_path), pf, feature_cols
        )
        disabled = ParquetDataset._scaler_identity(
            self._config(excluded_codes_path=self.empty_blacklist_path, exclude_codes=False), pf, feature_cols
        )
        self.assertEqual(with_empty, disabled)
        self.assertNotIn("excluded_codes_digest", with_empty)

    def test_non_empty_list_enters_identity(self):
        pf = pq.ParquetFile(self.parquet_path)
        feature_cols = list(FEATURE_COLS)
        identity = ParquetDataset._scaler_identity(self._config(), pf, feature_cols)
        self.assertEqual(identity["excluded_codes_count"], 1)
        self.assertEqual(identity["excluded_codes_digest"], excluded_codes_digest({BLACK}))

    def test_blacklist_change_changes_cache_key(self):
        pf = pq.ParquetFile(self.parquet_path)
        feature_cols = list(FEATURE_COLS)
        bins = np.array(self._config().bins, dtype=np.float64)
        keys = []
        for path in (self.empty_blacklist_path, self.blacklist_path):
            cfg = self._config(excluded_codes_path=path)
            identity = ParquetDataset._scaler_identity(cfg, pf, feature_cols)
            keys.append(ParquetDataset._cache_key(cfg, bins, identity, feature_cols))
        self.assertNotEqual(keys[0], keys[1])

    def test_identity_reports_absolute_path_and_count(self):
        identity = excluded_codes_identity(self.blacklist_path)
        self.assertEqual(identity["excluded_codes_count"], 1)
        self.assertTrue(os.path.isabs(identity["excluded_codes_path"]))


class TestDefaultBlacklistFile(unittest.TestCase):
    def test_repo_default_file_loads_and_has_provenance(self):
        from data.excluded_codes import DEFAULT_EXCLUDED_CODES_PATH

        self.assertTrue(os.path.exists(DEFAULT_EXCLUDED_CODES_PATH))
        with open(DEFAULT_EXCLUDED_CODES_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
        # 2026-10-30 审计结论：两个训练 parquet 中 0 只“零可用股”，故 excluded 当前为空。
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["excluded"], [])
        self.assertTrue(payload["sources"])
        self.assertEqual(load_excluded_codes(DEFAULT_EXCLUDED_CODES_PATH), frozenset())


if __name__ == "__main__":
    unittest.main()
