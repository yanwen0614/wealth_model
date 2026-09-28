import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from models.daily_dataset import available_dates, iter_daily_records


class DailyDatasetTests(unittest.TestCase):
    @staticmethod
    def _write_sources(directory: Path, periods=12):
        dates = pd.bdate_range("2024-01-02", periods=periods)
        feature_columns = ["open", *[f"feature_{index}" for index in range(44)]]
        raw_rows = []
        feature_rows = []
        for code_index, code in enumerate(("A", "B")):
            for index, date in enumerate(dates):
                raw_rows.append(
                    {
                        "code": code,
                        "kline_time": date,
                        "close": 10 + code_index + index,
                        "open": 10.5 + code_index + index,
                        "amount": 1000 - code_index * 100,
                        "volume": 10000 - code_index * 1000,
                        "is_trading": True,
                    }
                )
                feature_rows.append(
                    {
                        "code": code,
                        "kline_time": date,
                        "open": 0.1 * index,
                        **{column: float(index + column_index) for column_index, column in enumerate(feature_columns[1:])},
                    }
                )
        raw_path = directory / "raw.parquet"
        feature_path = directory / "features.parquet"
        pd.DataFrame(raw_rows).to_parquet(raw_path)
        pd.DataFrame(feature_rows).to_parquet(feature_path)
        return raw_path, feature_path, feature_columns, dates

    def test_available_dates_reads_only_kline_time(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path, _, _, dates = self._write_sources(Path(directory))

            with patch("models.daily_dataset.pd.read_parquet", wraps=pd.read_parquet) as read:
                result = available_dates(raw_path)

            self.assertEqual(result.tolist(), dates.tolist())
            read.assert_called_once_with(raw_path, columns=["kline_time"])

    def test_iter_yields_one_record_at_a_time_and_keeps_split_end(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path, feature_path, feature_columns, dates = self._write_sources(Path(directory))
            split_end = dates[7]

            records = iter_daily_records(
                raw_path,
                feature_path,
                feature_columns,
                split_start=dates[3],
                split_end=split_end,
                warmup=3,
                horizon=2,
                stride=1,
                candidate_limit=1000,
            )
            first = next(records)
            self.assertIsInstance(first, tuple)
            record, metadata = first
            self.assertEqual(record.signal_date, dates[3])
            self.assertLessEqual(record.sell_date, split_end)
            self.assertEqual(record.features.shape, (1000, 49))
            self.assertEqual(record.feature_columns[0], "open_feature")
            self.assertEqual(metadata["split_end"], split_end)
            self.assertEqual(next(records)[0].signal_date, dates[4])
            self.assertEqual(next(records)[0].signal_date, dates[5])
            with self.assertRaises(StopIteration):
                next(records)

    def test_iter_reads_only_window_columns_and_filters_and_limits_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path, feature_path, feature_columns, dates = self._write_sources(Path(directory), periods=10)
            real_read = pd.read_parquet

            with patch("models.daily_dataset.pd.read_parquet", wraps=real_read) as read:
                list(
                    iter_daily_records(
                        raw_path,
                        feature_path,
                        feature_columns,
                        split_start=dates[3],
                        split_end=dates[5],
                        warmup=3,
                        horizon=2,
                        candidate_limit=1000,
                    )
                )

            self.assertGreaterEqual(read.call_count, 3)
            self.assertEqual(read.call_args_list[0].kwargs, {"columns": ["kline_time"]})
            for call in read.call_args_list[1:]:
                self.assertIn("columns", call.kwargs)
                self.assertIn("filters", call.kwargs)
                self.assertNotIn("filters", {"columns": call.kwargs["columns"]})
                self.assertEqual(len(call.kwargs["filters"]), 1)
                self.assertEqual(call.kwargs["filters"][0][0], "kline_time")
                self.assertEqual(call.kwargs["filters"][0][1], "in")
                self.assertLessEqual(len(call.kwargs["filters"][0][2]), 6)
            raw_calls = [call for call in read.call_args_list[1:] if call.args[0] == raw_path]
            self.assertTrue(raw_calls)
            self.assertEqual(
                raw_calls[0].kwargs["columns"],
                ["code", "kline_time", "close", "open", "amount", "is_trading", "volume"],
            )

    def test_iter_false_does_not_read_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path, feature_path, feature_columns, dates = self._write_sources(Path(directory), periods=10)
            real_read = pd.read_parquet

            with patch("models.daily_dataset.pd.read_parquet", wraps=real_read) as read:
                list(iter_daily_records(
                    raw_path, feature_path, feature_columns,
                    split_start=dates[3], split_end=dates[5], warmup=3, horizon=2,
                    include_execution_sidecar=False,
                ))

            raw_calls = [call for call in read.call_args_list[1:] if call.args[0] == raw_path]
            self.assertEqual(raw_calls[0].kwargs["columns"], [
                "code", "kline_time", "close", "open", "amount", "is_trading",
            ])

    def test_iter_true_reads_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            raw_path, feature_path, feature_columns, dates = self._write_sources(Path(directory), periods=10)
            real_read = pd.read_parquet

            with patch("models.daily_dataset.pd.read_parquet", wraps=real_read) as read:
                list(iter_daily_records(
                    raw_path, feature_path, feature_columns,
                    split_start=dates[3], split_end=dates[5], warmup=3, horizon=2,
                    include_execution_sidecar=True,
                ))

            raw_calls = [call for call in read.call_args_list[1:] if call.args[0] == raw_path]
            self.assertEqual(raw_calls[0].kwargs["columns"][-1], "volume")


if __name__ == "__main__":
    unittest.main()
