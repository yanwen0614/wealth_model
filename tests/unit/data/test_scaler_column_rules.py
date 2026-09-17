"""data/scaler.py ColumnRule 注册表与 RelativeScaler（E0）契约。"""
import unittest
from unittest import mock

import numpy as np

from data.scaler import (
    AMIHUD_SCALE,
    COLUMN_RULES,
    ColumnRule,
    RelativeScaler,
    _relative_transform,
    column_rule,
)
from data.schema import APPROVED_RAW_FEATURES


class TestColumnRuleRegistry(unittest.TestCase):
    def test_rules_cover_all_approved_features(self):
        self.assertEqual(len(COLUMN_RULES), 52)
        self.assertEqual(set(COLUMN_RULES), set(APPROVED_RAW_FEATURES))
        self.assertTrue(all(isinstance(rule, ColumnRule) for rule in COLUMN_RULES.values()))

    def test_group_specific_rules(self):
        self.assertEqual(COLUMN_RULES["close"].group, "P")
        self.assertEqual(COLUMN_RULES["close"].transform, "relative")
        self.assertEqual(COLUMN_RULES["close"].relative_denominator, "close")
        self.assertEqual(COLUMN_RULES["amihud"].scale, AMIHUD_SCALE)
        self.assertEqual(COLUMN_RULES["amihud"].transform, "asinh")
        self.assertEqual(COLUMN_RULES["roe"].scale, 1.0)
        self.assertEqual(COLUMN_RULES["margin_balance_ratio"].transform, "clip01")
        self.assertEqual(COLUMN_RULES["margin_net_buy_ratio_raw"].transform, "fixed_clip")
        self.assertEqual(COLUMN_RULES["margin_net_buy_ratio_raw"].clip, (-1.0, 1.0))

    def test_p_and_n_groups_use_expected_transforms(self):
        expected = {"P": "relative", "N": "clip01", "G": "fixed_clip"}
        for column, rule in COLUMN_RULES.items():
            if rule.group in expected:
                self.assertEqual(rule.transform, expected[rule.group], column)

    def test_column_rule_rejects_unknown(self):
        with self.assertRaises(ValueError):
            column_rule("unknown")


class TestRelativeScalerSchema(unittest.TestCase):
    def test_has_no_fit(self):
        scaler = RelativeScaler(list(APPROVED_RAW_FEATURES))
        self.assertFalse(hasattr(scaler, "fit"))

    def test_default_schema_appends_single_shared_mask(self):
        scaler = RelativeScaler(list(APPROVED_RAW_FEATURES))
        self.assertEqual(scaler.feature_cols, list(APPROVED_RAW_FEATURES))
        self.assertEqual(len(scaler.feature_cols_out), 53)
        self.assertEqual(scaler.feature_cols_out[-1], "g9_observed_mask")
        self.assertEqual(scaler.mask_cols, ["g9_observed_mask"])

    def test_subset_without_g9_has_no_mask(self):
        scaler = RelativeScaler(["open", "ma_5", "amihud"])
        self.assertEqual(scaler.mask_cols, [])
        self.assertEqual(scaler.feature_cols_out, ["open", "ma_5", "amihud"])

    def test_transform_config_digest_is_stable(self):
        digest = RelativeScaler.transform_config_digest()
        self.assertIsInstance(digest, str)
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, RelativeScaler.transform_config_digest())

    def test_transform_config_digest_tracks_mask_columns(self):
        baseline = RelativeScaler.transform_config_digest()
        with mock.patch("data.scaler.G9_MASK_COLUMNS", ("other_mask",)):
            self.assertNotEqual(RelativeScaler.transform_config_digest(), baseline)


class TestRelativeTransform(unittest.TestCase):
    def test_p_relative_formula_and_first_row_fill(self):
        scaler = RelativeScaler(["open"])
        close = np.array([10.0, 11.0, 12.0])
        feats = np.array([[10.0], [10.0], [11.0]])
        out = scaler.transform_code("000001", feats, ["open"], close=close)
        np.testing.assert_allclose(out[:, 0], [0.0, 0.0, 0.0], atol=1e-6)

    def test_p_relative_clip(self):
        scaler = RelativeScaler(["open"])
        close = np.array([10.0, 10.0])
        feats = np.array([[10.0], [100.0]])
        out = scaler.transform_code("000001", feats, ["open"], close=close)
        self.assertAlmostEqual(float(out[1, 0]), 5.0, places=5)

    def test_p_relative_rejects_non_finite_and_zero_denominator(self):
        vals = np.array([1.0, 1.0, 1.0])
        close = np.array([np.inf, 0.0, 10.0])
        # prev_close = [head(nan), inf, 0]；非有限/0 分母必须产出 NaN（不得退化成 -1）
        out = _relative_transform(vals, close)
        self.assertTrue(np.isnan(out).all(), out)

    def test_r_asinh_keeps_sign_and_amihud_scale(self):
        scaler = RelativeScaler(["amihud", "roe"])
        feats = np.array([[1e-13, 1.0]])
        out = scaler.transform_code("000001", feats, ["amihud", "roe"])
        self.assertGreater(float(out[0, 0]), 0.09)
        self.assertAlmostEqual(float(out[0, 1]), float(np.arcsinh(1.0)), places=6)

    def test_r_asinh_clipped_at_pm_five(self):
        scaler = RelativeScaler(["roe"])
        feats = np.array([[100.0], [-100.0]])
        out = scaler.transform_code("000001", feats, ["roe"])
        np.testing.assert_allclose(out[:, 0], [5.0, -5.0], atol=1e-6)

    def test_n_clip01_and_missing_fill(self):
        scaler = RelativeScaler(["margin_balance_ratio_ts"])
        feats = np.array([[-0.5], [0.3], [1.7], [np.nan]])
        out = scaler.transform_code("000001", feats, ["margin_balance_ratio_ts"])
        np.testing.assert_allclose(out[:, 0], [0.0, 0.3, 1.0, 0.0], atol=1e-6)

    def test_g_fixed_clip_and_missing_fill(self):
        scaler = RelativeScaler(["margin_net_buy_ratio_raw"])
        feats = np.array([[-3.0], [0.5], [np.nan]])
        out = scaler.transform_code("000001", feats, ["margin_net_buy_ratio_raw"])
        np.testing.assert_allclose(out[:, 0], [-1.0, 0.5, 0.0], atol=1e-6)


class TestRelativeMaskAndFiniteness(unittest.TestCase):
    def test_shared_mask_or_semantics_and_dtype(self):
        feature_cols = list(APPROVED_RAW_FEATURES)
        scaler = RelativeScaler(feature_cols)
        feats = np.full((3, len(feature_cols)), np.nan, dtype=np.float64)
        feats[1, feature_cols.index("margin_balance_ratio")] = 0.5
        feats[2, :] = 1.0
        out = scaler.transform_code("000001", feats, feature_cols, close=np.full(3, 10.0))
        self.assertEqual(out[:, -1].dtype, np.float32)
        np.testing.assert_array_equal(out[:, -1], np.array([0.0, 1.0, 1.0], dtype=np.float32))

    def test_output_is_finite_float32(self):
        feature_cols = list(APPROVED_RAW_FEATURES)
        scaler = RelativeScaler(feature_cols)
        feats = np.full((2, len(feature_cols)), np.nan, dtype=np.float64)
        feats[0, :] = np.inf
        feats[1, :] = -np.inf
        out = scaler.transform_code("000001", feats, feature_cols, close=np.zeros(2))
        self.assertEqual(out.dtype, np.float32)
        self.assertTrue(bool(np.isfinite(out).all()))


if __name__ == "__main__":
    unittest.main()
