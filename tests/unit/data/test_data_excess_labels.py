"""截面超额收益标签（`label_mode="excess"`）契约测试（TDD Red-Green）。

覆盖：
1. 纯函数 `_cross_sectional_excess`：按 kline_time 日期分组，逐日剔除截面均值；
   NaN 标签不参与均值且输出仍为 NaN。
2. `ParquetDataset` 默认 `label_mode="absolute"` 行为完全不变。
3. `label_mode="excess"` 时 groups["future_ret"]/["discrete"] 与手算一致。
4. `is_trading=False` 行被过滤后不污染当日截面均值。
5. context warmup 行绝不作为标签日（excess 模式同样成立）。
6. 缓存 key 对 label_mode 敏感，excess 标签可经缓存往返一致。

全部使用 tempfile 造 mini parquet 与临时 cache_dir，不污染真实用户数据/缓存。
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
from data.labels import _cross_sectional_excess

BINS = (np.linspace(-25, 25, 51) / 100).tolist()
CODES = {"A": 10.0, "B": 20.0, "C": 30.0}


def _row(code, day, price, trading):
    return {
        "code": code, "kline_time": day,
        "open": price, "high": price + 1.0, "low": price - 1.0, "close": price + 0.5,
        "is_trading": trading,
    }


def _multi_code_frame(*, z_untraded_on_date1: bool, n_rows: int = 10) -> pd.DataFrame:
    """A/B/C 三股同日历；可选 Z 股在交易日 1 放极端非交易行。"""
    dates = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    rows = []
    for code, base in CODES.items():
        for t, day in enumerate(dates):
            rows.append(_row(code, day, base + t, True))
    if z_untraded_on_date1:
        for t, day in enumerate(dates):
            price = 1000.0 if t == 1 else 50.0 + t
            rows.append(_row("Z", day, price, t != 1))
    return pd.DataFrame(rows)


def _expected_excess(t: int, code: str) -> float:
    """手算：future_ret = open[t+2]/open[t+1]-1（horizon=1），减去当日三股截面均值。"""
    rets = {c: (base + t + 2) / (base + t + 1) - 1.0 for c, base in CODES.items()}
    return rets[code] - sum(rets.values()) / len(rets)


def _config(path: str, **over) -> ParquetDataConfig:
    base: dict = {
        "parquet_path": path,
        "seq_len": 2,
        "horizon": 1,
        "bins": BINS,
        "feature_cols": ["open", "high", "low"],
        "normalize": "none",
        "num_workers": 0,
    }
    base.update(over)
    return ParquetDataConfig(**base)


class _parquet:
    def __init__(self, frame):
        self.frame = frame

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="excess_")
        self.path = os.path.join(self.dir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.path)
        return self.path

    def __exit__(self, *args):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestCrossSectionalExcess(unittest.TestCase):
    def test_hand_computed_two_days_three_stocks(self):
        d0 = np.array([np.datetime64("2024-01-01")] * 3)
        d1 = np.array([np.datetime64("2024-01-02")] * 3)
        dates = np.concatenate([d0, d1])
        rets = np.array([0.10, 0.20, 0.30, 0.40, 0.60, np.nan])
        out = _cross_sectional_excess(dates, rets)
        expected = [0.10 - 0.20, 0.20 - 0.20, 0.30 - 0.20, 0.40 - 0.50, 0.60 - 0.50, np.nan]
        for got, want in zip(out, expected):
            if np.isnan(want):
                self.assertTrue(np.isnan(got))
            else:
                self.assertAlmostEqual(float(got), want, places=12)

    def test_nan_labels_excluded_from_mean_but_stay_nan(self):
        dates = np.array([np.datetime64("2024-01-01")] * 2)
        rets = np.array([np.nan, 0.30])
        out = _cross_sectional_excess(dates, rets)
        self.assertTrue(np.isnan(out[0]))
        self.assertAlmostEqual(float(out[1]), 0.0, places=12)

    def test_min_count_marks_thin_cross_section_nan(self):
        d0 = np.datetime64("2024-01-01")
        d1 = np.datetime64("2024-01-02")
        dates = np.array([d0, d1, d1])
        rets = np.array([0.10, 0.20, 0.40])
        out = _cross_sectional_excess(dates, rets, min_count=2)
        self.assertTrue(np.isnan(out[0]))  # 当日仅 1 个有效标签 -> 不计截面均值
        self.assertAlmostEqual(float(out[1]), 0.20 - 0.30, places=12)
        self.assertAlmostEqual(float(out[2]), 0.40 - 0.30, places=12)

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            _cross_sectional_excess(np.array([1, 2]), np.array([0.1]))


class TestLabelModeDataset(unittest.TestCase):
    def test_default_label_mode_is_absolute_and_unchanged(self):
        self.assertEqual(ParquetDataConfig().label_mode, "absolute")
        with _parquet(_multi_code_frame(z_untraded_on_date1=False)) as path:
            default = ParquetDataset(_config(path))
            explicit = ParquetDataset(_config(path, label_mode="absolute"))
        for code in default.groups:
            np.testing.assert_array_equal(
                default.groups[code]["future_ret"], explicit.groups[code]["future_ret"]
            )
            np.testing.assert_array_equal(
                default.groups[code]["discrete"], explicit.groups[code]["discrete"]
            )
        # absolute 保留原始 future_ret：A 在 t=1 为 open[3]/open[2]-1 = 1/12
        self.assertAlmostEqual(float(default.groups["A"]["future_ret"][1]), 1.0 / 12.0, places=6)

    def test_excess_labels_match_hand_computation(self):
        with _parquet(_multi_code_frame(z_untraded_on_date1=False)) as path:
            ds = ParquetDataset(_config(path, label_mode="excess"))
        for code in CODES:
            group = ds.groups[code]
            self.assertAlmostEqual(
                float(group["future_ret"][1]), _expected_excess(1, code), places=6
            )
            self.assertEqual(
                int(group["discrete"][1]),
                int(np.digitize(_expected_excess(1, code), BINS)),
            )

    def test_untraded_row_excluded_from_cross_section(self):
        # Z 股交易日 1 的极端 open=1000 为 is_trading=False：过滤后不得进入当日均值
        with _parquet(_multi_code_frame(z_untraded_on_date1=True)) as path:
            ds = ParquetDataset(_config(path, label_mode="excess"))
        # Z 仍有其他交易日的行（group 存在），但交易日 1 的非交易行不参与均值
        self.assertIn("Z", ds.groups)
        for code in CODES:
            self.assertAlmostEqual(
                float(ds.groups[code]["future_ret"][1]), _expected_excess(1, code), places=6
            )

    def test_context_rows_never_labels_in_excess_mode(self):
        with _parquet(_multi_code_frame(z_untraded_on_date1=False)) as path:
            ds = ParquetDataset(_config(path, label_mode="excess", start_date="2024-01-05"))
        start = np.datetime64("2024-01-05")
        self.assertGreater(len(ds), 0)
        for code, s in ds.index:
            self.assertGreaterEqual(ds.groups[code]["kline_time"][s + 1], start)
            self.assertTrue(np.isfinite(float(ds.groups[code]["future_ret"][s + 1])))

    def test_excess_labels_round_trip_through_cache(self):
        with _parquet(_multi_code_frame(z_untraded_on_date1=False)) as path:
            cache_dir = tempfile.mkdtemp(prefix="excess_cache_")
            try:
                cfg = _config(path, label_mode="excess", cache_enabled=True, cache_dir=cache_dir)
                first = ParquetDataset(cfg)
                second = ParquetDataset(cfg)  # 二次构造命中缓存
                self.assertEqual(len(first), len(second))
                for code in first.groups:
                    np.testing.assert_array_equal(
                        first.groups[code]["future_ret"], second.groups[code]["future_ret"]
                    )
                    np.testing.assert_array_equal(
                        first.groups[code]["discrete"], second.groups[code]["discrete"]
                    )
            finally:
                # Windows 下命中缓存的 memmap 句柄在进程内惰性持有，清理失败可忽略
                del first, second
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)


class TestCacheKeyLabelMode(unittest.TestCase):
    @staticmethod
    def _kwargs() -> dict:
        return {
            "base_identity": {"parquet_path": "x", "size": 1, "mtime_ns": 2},
            "role": "training", "rolling_scope": None, "scaler_identity_hash": "h",
            "seq_len": 2, "horizon": 1, "max_windows_per_code": None, "bins_digest": "d",
        }

    def test_label_mode_sensitive_and_default_stable(self):
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), label_mode="excess"),
            compute_cache_key(**self._kwargs(), label_mode="absolute"),
        )
        # 默认（不传）与显式 absolute 同 key，避免既有缓存无谓失效
        self.assertEqual(
            compute_cache_key(**self._kwargs()),
            compute_cache_key(**self._kwargs(), label_mode="absolute"),
        )


if __name__ == "__main__":
    unittest.main()
