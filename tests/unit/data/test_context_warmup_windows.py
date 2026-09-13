"""context warmup 窗口契约：start_date 前的历史行只作窗口输入，绝不作为标签日。

T01/T03 覆盖：
(a) start_date 首个真实交易日即产出标签，去重标签日数 == R-(horizon+1)；
(b) 遍历 index，标签日恒为非 context 行；
(c) 窗口末日 == 标签日，窗口内无未来泄露；
(d) 无 start_date 与 start_date==首日 逐元素一致（训练口径回归）；
(e) per_code / rolling 均通过，num_features=69、(69,60)，rolling 训练 state 只 fit 一次。
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset, _RollingDatasetState
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES


def _context_frame(pre: int, real: int, code: str = "000001", start: str = "2025-01-01") -> pd.DataFrame:
    """构造 pre 行 context（start 之前）+ real 行真实交易日，日期逐日递增。"""
    total = pre + real
    dates = pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=pre), periods=total, freq="D")
    base = np.arange(1.0, total + 1.0)
    rng = np.random.default_rng(7)
    frame = pd.DataFrame({
        "code": [code] * total,
        "kline_time": dates,
        "open": base + 10.0,
        "high": base + 11.0,
        "low": base + 9.0,
        "close": base + 10.5,
        "is_trading": True,
    })
    for column in APPROVED_RAW_FEATURES:
        if column in frame.columns:
            continue
        frame[column] = base * (1.0 + 0.01 * rng.standard_normal(total)) + 5.0
    return frame


class TestContextWarmupWindows(unittest.TestCase):
    @staticmethod
    def _config(path: str, **over) -> ParquetDataConfig:
        base: dict = {
            "parquet_path": path,
            "seq_len": 10,
            "horizon": 2,
            "feature_cols": list(APPROVED_RAW_FEATURES),
            "normalize": "per_code",
            "num_workers": 0,
        }
        base.update(over)
        return ParquetDataConfig(**base)

    def test_first_real_day_is_a_label_and_cover_count(self):
        seq_len, horizon, real = 10, 2, 160
        frame = _context_frame(seq_len - 1, real)
        with _parquet(frame) as path:
            ds = ParquetDataset(self._config(path, seq_len=seq_len, horizon=horizon, start_date="2025-01-01"))
        group = ds.groups["000001"]
        label_dates = {pd.Timestamp(group["kline_time"][s + seq_len - 1]) for _, s in ds.index}
        self.assertEqual(min(label_dates), pd.Timestamp("2025-01-01"))
        self.assertEqual(len(label_dates), real - (horizon + 1))

    def test_context_is_never_a_label_day(self):
        seq_len = 10
        frame = _context_frame(seq_len - 1, 120)
        start = np.datetime64("2025-01-01")
        with _parquet(frame) as path:
            ds = ParquetDataset(self._config(path, seq_len=seq_len, start_date="2025-01-01"))
        for code, s in ds.index:
            self.assertGreaterEqual(ds.groups[code]["kline_time"][s + seq_len - 1], start)

    def test_window_has_no_future_leak_and_ends_at_label_day(self):
        seq_len = 10
        frame = _context_frame(seq_len - 1, 120)
        with _parquet(frame) as path:
            ds = ParquetDataset(self._config(path, seq_len=seq_len, start_date="2025-01-01"))
        for code, s in ds.index:
            times = ds.groups[code]["kline_time"][s: s + seq_len]
            self.assertEqual(times[-1], times.max())
            self.assertEqual(times[-1], ds.groups[code]["kline_time"][s + seq_len - 1])

    def test_no_start_date_matches_first_day_bound_elementwise(self):
        frame = _context_frame(0, 80)
        with _parquet(frame) as path:
            plain = ParquetDataset(self._config(path, seq_len=60, horizon=5))
            bounded = ParquetDataset(
                self._config(path, seq_len=60, horizon=5, start_date="2025-01-01")
            )
        self.assertEqual(len(plain), len(bounded))
        self.assertEqual(list(plain.index), list(bounded.index))
        for code in plain.groups:
            np.testing.assert_array_equal(
                np.asarray(plain.groups[code]["features"]),
                np.asarray(bounded.groups[code]["features"]),
            )
            np.testing.assert_array_equal(
                plain.groups[code]["future_ret"], bounded.groups[code]["future_ret"]
            )
        self.assertEqual(plain.num_features, 69)
        self.assertEqual(tuple(plain[0][0].shape), (69, 60))

    def test_per_code_and_rolling_first_day_label(self):
        for normalize in ("per_code", "rolling"):
            with self.subTest(normalize=normalize):
                frame = _context_frame(59, 160)
                with _parquet(frame) as path:
                    ds = ParquetDataset(
                        self._config(
                            path, seq_len=60, horizon=5, normalize=normalize, start_date="2025-01-01"
                        )
                    )
                self.assertEqual(ds.num_features, 69)
                self.assertEqual(tuple(ds[0][0].shape), (69, 60))
                label_dates = {
                    pd.Timestamp(ds.groups["000001"]["kline_time"][s + 59]) for _, s in ds.index
                }
                self.assertEqual(min(label_dates), pd.Timestamp("2025-01-01"))
                self.assertEqual(len(label_dates), 160 - 6)

    def test_rolling_validation_reuses_state_and_labels_from_start(self):
        frame = _context_frame(120, 60, start="2025-05-01")
        original_fit = PerCodeGroupedScaler.fit
        start = np.datetime64("2025-05-01")
        with patch.object(
            PerCodeGroupedScaler,
            "fit",
            autospec=True,
            side_effect=lambda scaler, *args, **kwargs: original_fit(scaler, *args, **kwargs),
        ) as fit, _parquet(frame) as path:
            train = ParquetDataset(
                self._config(path, seq_len=10, horizon=2, normalize="rolling", end_date="2025-04-30")
            )
            val = ParquetDataset(
                self._config(
                    path, seq_len=10, horizon=2, normalize="rolling",
                    start_date="2025-05-01", role="validation",
                ),
                scaler_stats=train.scaler_stats,
            )
        self.assertEqual(fit.call_count, 1)
        self.assertIsInstance(train.scaler_stats, _RollingDatasetState)
        self.assertEqual(val.groups["000001"]["n"], 180)
        self.assertLess(val.groups["000001"]["kline_time"][0], start)
        label_days = [val.groups["000001"]["kline_time"][s + 9] for _, s in val.index]
        self.assertTrue(all(day >= start for day in label_days))
        self.assertEqual(min(label_days), start)

    def test_two_code_min_warmup_first_day_label(self):
        rows = []
        for code in ("A", "B"):
            for day in range(8):
                row = {col: 0.1 for col in APPROVED_RAW_FEATURES}
                price = 10.0 + day
                row.update({
                    "code": code,
                    "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=day),
                    "is_trading": True, "close": price, "open": price,
                    "high": price + 1.0, "low": price - 1.0,
                })
                rows.append(row)
        with _parquet(pd.DataFrame(rows)) as path:
            train = ParquetDataset(self._config(path, seq_len=2, horizon=1, end_date="2020-01-04"))
            valid = ParquetDataset(
                self._config(path, seq_len=2, horizon=1, start_date="2020-01-05", role="validation"),
                scaler_stats=train.scaler_stats,
            )
        for code in valid.groups:
            self.assertLess(valid.groups[code]["kline_time"][0], np.datetime64("2020-01-05"))
        for code, s in valid.index:
            self.assertGreaterEqual(valid.groups[code]["kline_time"][s + 1], np.datetime64("2020-01-05"))
        self.assertTrue(np.isfinite(np.asarray(valid.groups["A"]["features"])).all())


class _parquet:
    def __init__(self, frame):
        self.frame = frame

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="warmup_")
        self.path = os.path.join(self.dir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.path)
        return self.path

    def __exit__(self, *args):
        shutil.rmtree(self.dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()


