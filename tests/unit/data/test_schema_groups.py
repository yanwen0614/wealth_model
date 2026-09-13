"""data/schema.py 分组注册表与共享 G9 mask 契约。"""
import unittest

import numpy as np
import pandas as pd

from data.schema import (
    APPROVED_RAW_FEATURES,
    FEATURE_GROUPS,
    G9_MASK_COLUMNS,
    G9_OBSERVATION_SOURCE,
    PROHIBITED_COLUMNS,
    column_group,
    default_feature_cols,
    g9_observed_mask,
)


class TestFeatureGroups(unittest.TestCase):
    def test_group_sizes_and_order_contract(self):
        self.assertEqual(list(FEATURE_GROUPS), ["P", "R", "N", "G"])
        self.assertEqual(
            {name: len(cols) for name, cols in FEATURE_GROUPS.items()},
            {"P": 18, "R": 16, "N": 12, "G": 6},
        )
        flattened = [col for cols in FEATURE_GROUPS.values() for col in cols]
        self.assertEqual(list(APPROVED_RAW_FEATURES), flattened)
        self.assertEqual(len(APPROVED_RAW_FEATURES), 52)

    def test_column_group_maps_and_rejects_unknown(self):
        self.assertEqual(column_group("close"), "P")
        self.assertEqual(column_group("amihud"), "R")
        self.assertEqual(column_group("roe"), "R")
        self.assertEqual(column_group("margin_balance_ratio_ts"), "N")
        self.assertEqual(column_group("short_sell_vol_ratio_raw"), "G")
        with self.assertRaises(ValueError):
            column_group("unknown")

    def test_close_unprohibited_and_single_mask(self):
        self.assertNotIn("close", PROHIBITED_COLUMNS)
        self.assertIn("code", PROHIBITED_COLUMNS)
        self.assertEqual(G9_MASK_COLUMNS, ("g9_observed_mask",))
        self.assertEqual(len(G9_OBSERVATION_SOURCE), 18)

    def test_default_feature_cols_validates_mode(self):
        for mode in ("relative", "per_code", "rolling", "none"):
            self.assertEqual(default_feature_cols(mode), list(APPROVED_RAW_FEATURES))
        with self.assertRaises(ValueError):
            default_feature_cols("bogus")

    def test_g9_observed_mask_or_semantics(self):
        cols = list(G9_OBSERVATION_SOURCE)
        frame = pd.DataFrame({col: [np.nan, np.nan, 1.0] for col in cols})
        mask = g9_observed_mask(frame)
        self.assertEqual(mask.dtype, np.float32)
        np.testing.assert_array_equal(mask, np.array([0, 0, 1], dtype=np.float32))
        frame.loc[0, cols[5]] = 2.0
        mask = g9_observed_mask(frame)
        np.testing.assert_array_equal(mask, np.array([1, 0, 1], dtype=np.float32))

    def test_g9_observed_mask_missing_column_raises(self):
        cols = list(G9_OBSERVATION_SOURCE)[:-1]
        frame = pd.DataFrame({col: [1.0] for col in cols})
        with self.assertRaises(ValueError):
            g9_observed_mask(frame)


if __name__ == "__main__":
    unittest.main()
