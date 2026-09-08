"""数据 schema、默认特征和标签纯函数契约。"""
import unittest

import numpy as np

from data import dataset
from data.labels import _future_ret_open_open
from data.schema import (
    APPROVED_RAW_FEATURES,
    BASE_COLUMNS,
    EXPORT_FACTORS,
    PREDICTION_CACHE_KEYS,
    PROHIBITED_COLUMNS,
    _default_feature_cols,
    validate_prediction_cache_arrays,
    validate_prediction_cache_keys,
)


class TestDataSchemaLabels(unittest.TestCase):
    def test_dataset_keeps_compatibility_aliases(self):
        self.assertIs(dataset.EXPORT_FACTORS, EXPORT_FACTORS)
        self.assertIs(dataset.BASE_COLUMNS, BASE_COLUMNS)
        self.assertIs(dataset._default_feature_cols, _default_feature_cols)
        self.assertIs(dataset._future_ret_open_open, _future_ret_open_open)

    def test_default_feature_columns_feed_45_dimensional_output(self):
        columns = BASE_COLUMNS + EXPORT_FACTORS
        selected = _default_feature_cols(columns)
        # 默认输入为 39 列，per_code scaler 追加 6 个 mask，输出为 F=45。
        self.assertEqual(len(selected), 39)
        self.assertNotIn("close", selected)
        self.assertNotIn("return_1d", selected)
        self.assertEqual(selected, APPROVED_RAW_FEATURES)
        self.assertTrue(PROHIBITED_COLUMNS.issuperset({"code", "kline_time", "is_trading", "close"}))

    def test_unknown_columns_warn_and_are_excluded(self):
        with self.assertWarnsRegex(UserWarning, "mystery_feature"):
            selected = _default_feature_cols(BASE_COLUMNS + APPROVED_RAW_FEATURES + ["mystery_feature"])
        self.assertEqual(selected, APPROVED_RAW_FEATURES)

    def test_missing_approved_column_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "open"):
            _default_feature_cols([c for c in APPROVED_RAW_FEATURES if c != "open"])

    def test_label_function_uses_open_open(self):
        opens = np.arange(10.0, 21.0)
        result = _future_ret_open_open(opens, horizon=2)
        self.assertAlmostEqual(result[0], opens[3] / opens[1] - 1.0)
        self.assertTrue(np.isnan(result[-3:]).all())

    def test_prediction_cache_requires_keys_and_equal_lengths(self):
        arrays = {key: np.arange(3) for key in PREDICTION_CACHE_KEYS}
        validate_prediction_cache_arrays(arrays)
        with self.assertRaisesRegex(ValueError, "缺少必需键"):
            validate_prediction_cache_keys(["exp_ret", "true_ret", "dates"])
        arrays["codes"] = np.arange(2)
        with self.assertRaisesRegex(ValueError, "长度不一致"):
            validate_prediction_cache_arrays(arrays)


if __name__ == "__main__":
    unittest.main()
