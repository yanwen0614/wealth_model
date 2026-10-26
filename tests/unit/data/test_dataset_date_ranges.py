"""数据工厂日期契约：先验证标签区间，再构建数据集。"""

import unittest
from unittest.mock import MagicMock, patch

from data.dataset import ParquetDataConfig, ParquetDataset


class TestDatasetDateRanges(unittest.TestCase):
    def test_invalid_splits_are_rejected_before_construction(self):
        valid = {"train_start": "2020-01-01", "train_end": "2020-12-31",
                 "val_start": "2021-01-01", "val_end": "2021-06-30"}
        cases = [
            ({"val_start": "2020-12-31"}, "train_end"),
            ({"val_start": "2020-06-01"}, "train_end"),
            ({"val_start": "2019-01-01", "val_end": "2022-01-01"}, "train_end"),
            ({"val_start": "2019-01-01", "val_end": "2019-06-01"}, "train_end"),
            ({"train_start": "2021-01-01"}, "train_start"),
            ({"val_end": "2020-12-01"}, "val_start"),
            ({"train_end": None}, "train_end"),
            ({"train_start": None, "train_end": None}, "train_end"),
            ({"val_start": None}, "val_start"),
        ]
        for field in valid:
            for value in ("非法日期", "NaT", "", "2021-02-30"):
                cases.append(({field: value}, field))
        for changes, message in cases:
            dates = {**valid, **changes}
            with self.subTest(dates=dates), \
                    patch.object(ParquetDataset, "__init__", return_value=None) as constructor, \
                    patch.object(ParquetDataset, "__len__", return_value=0), \
                    patch.object(ParquetDataset, "num_features", 53, create=True), \
                    patch.object(ParquetDataset, "scaler_stats", None, create=True), \
                    patch.object(ParquetDataset, "_load_and_prepare") as reader, \
                    patch("data.dataset.PerCodeGroupedScaler.fit") as fit, \
                    patch("data.dataset.DataLoader") as loader:
                with self.assertRaisesRegex(ValueError, message):
                    ParquetDataset.create_dataloaders(ParquetDataConfig(num_workers=0), **dates)
                constructor.assert_not_called()
                reader.assert_not_called()
                fit.assert_not_called()
                loader.assert_not_called()

    def test_valid_ranges_preserve_dates_and_share_training_scaler(self):
        cases = (
            (None, "2020-12-31", "2021-01-01", None),
            ("2020-12-31", "2020-12-31", "2021-01-01", "2021-01-01"),
            (None, None, None, None),
            ("2020-01-01", None, None, None),
            (None, "2020-12-31", None, None),
        )
        for dates in cases:
            with self.subTest(dates=dates):
                train_dataset = MagicMock(num_features=53)
                val_dataset = MagicMock(num_features=53)
                # 用子类替身捕获工厂构造行为，不读取 parquet。
                class CapturedDataset(ParquetDataset):
                    pass

                with patch.object(CapturedDataset, "__new__",
                                  side_effect=[train_dataset, val_dataset]) as constructor, \
                        patch("data.dataset.DataLoader") as loader:
                    _, validation, scaler = CapturedDataset.create_dataloaders(
                        ParquetDataConfig(num_workers=0), *dates,
                    )
                train_cfg = constructor.call_args_list[0].args[1]
                self.assertEqual((train_cfg.start_date, train_cfg.end_date), dates[:2])
                self.assertEqual(train_cfg.role, "training")
                self.assertIs(scaler, train_dataset.scaler_stats)
                has_validation = dates[2] is not None
                self.assertEqual(constructor.call_count, 2 if has_validation else 1)
                self.assertEqual(loader.call_count, constructor.call_count)
                if has_validation:
                    call = constructor.call_args_list[1]
                    self.assertIs(call.kwargs["scaler_stats"], scaler)
                    self.assertEqual(call.args[1].role, "validation")
                    self.assertEqual((call.args[1].start_date, call.args[1].end_date), dates[2:])
                else:
                    self.assertIsNone(validation)


if __name__ == "__main__":
    unittest.main()
