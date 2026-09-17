"""data/scaler.py PerCodeGroupedScaler（E1 静态 per-code robust）契约。"""
import os
import pickle
import tempfile
import unittest

import numpy as np
import pandas as pd

from data.scaler import SCALER_VERSION, PerCodeGroupedScaler, RelativeScaler
from data.schema import APPROVED_RAW_FEATURES

IQR_TO_SIGMA = 1.349
EPS = 1e-8


def _frame(close, **columns) -> pd.DataFrame:
    length = len(close)
    frame = pd.DataFrame({
        "code": ["A"] * length,
        "kline_time": pd.date_range("2020-01-01", periods=length),
        "close": close,
    })
    for name, values in columns.items():
        frame[name] = values
    return frame


class TestPerCodePRobust(unittest.TestCase):
    def test_p_relative_robust_formula(self):
        frame = _frame([10.0, 10.0, 10.0, 10.0], open=[10.0, 12.0, 14.0, 16.0])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        stats = scaler.per_code_stats["A"]["open"]
        self.assertAlmostEqual(stats["median"], 0.4, places=6)
        self.assertAlmostEqual(stats["iqr"], 0.2, places=6)
        out = scaler.transform_code("A", frame[["open"]].to_numpy(), ["open"], frame["close"].to_numpy())
        self.assertAlmostEqual(float(out[1, 0]), (0.2 - 0.4) / (0.2 / IQR_TO_SIGMA + EPS), places=5)

    def test_p_relative_first_row_and_missing_fill_zero(self):
        frame = _frame([10.0, 10.0, 10.0], open=[10.0, 12.0, np.nan])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        out = scaler.transform_code("A", frame[["open"]].to_numpy(), ["open"], frame["close"].to_numpy())
        self.assertEqual(float(out[0, 0]), 0.0)
        self.assertEqual(float(out[2, 0]), 0.0)

    def test_p_robust_clip_pm_five(self):
        frame = _frame([10.0, 10.0, 10.0], open=[10.0, 12.0, 14.0])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        out = scaler.transform_code("A", np.array([[10.0], [1e6]]), ["open"], np.array([10.0, 10.0]))
        self.assertAlmostEqual(float(out[1, 0]), 5.0, places=5)


class TestPerCodeRNG(unittest.TestCase):
    def test_r_asinh_scale_and_clip(self):
        frame = _frame([10.0, 10.0], amihud=[0.0, 1e-13], roe=[0.0, 100.0])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["amihud", "roe"])
        out = scaler.transform_code("A", frame[["amihud", "roe"]].to_numpy(), ["amihud", "roe"])
        self.assertAlmostEqual(float(out[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(out[1, 0]), float(np.arcsinh(1e-13 * 1e12)), places=6)
        self.assertAlmostEqual(float(out[1, 1]), 5.0, places=5)

    def test_n_clip01_and_missing_fill(self):
        frame = _frame([10.0] * 4, margin_balance_ratio_ts=[-0.5, 0.3, 1.7, np.nan])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["margin_balance_ratio_ts"])
        out = scaler.transform_code("A", frame[["margin_balance_ratio_ts"]].to_numpy(), ["margin_balance_ratio_ts"])
        np.testing.assert_allclose(out[:, 0], [0.0, 0.3, 1.0, 0.0], atol=1e-6)

    def test_g_fixed_clip_keeps_negative_value(self):
        frame = _frame([10.0] * 3, margin_net_buy_ratio_raw=[-3.0, 0.5, np.nan])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["margin_net_buy_ratio_raw"])
        out = scaler.transform_code("A", frame[["margin_net_buy_ratio_raw"]].to_numpy(), ["margin_net_buy_ratio_raw"])
        np.testing.assert_allclose(out[:, 0], [-1.0, 0.5, 0.0], atol=1e-6)


class TestMaskSchema(unittest.TestCase):
    def test_shared_mask_single_column_or_semantics(self):
        frame = _frame([10.0] * 3,
                       margin_balance_ratio=[np.nan, 0.5, np.nan],
                       margin_net_buy_ratio_raw=[np.nan, np.nan, 0.1])
        cols = ["margin_balance_ratio", "margin_net_buy_ratio_raw"]
        scaler = PerCodeGroupedScaler().fit(frame, cols)
        self.assertEqual(scaler.mask_cols, ["g9_observed_mask"])
        self.assertEqual(scaler.feature_cols_out, cols + ["g9_observed_mask"])
        out = scaler.transform_code("A", frame[cols].to_numpy(), cols)
        self.assertEqual(out.shape, (3, 3))
        np.testing.assert_array_equal(out[:, -1], np.array([0.0, 1.0, 1.0], dtype=np.float32))

    def test_add_mask_false_has_no_mask(self):
        frame = _frame([10.0, 10.0], margin_balance_ratio=[0.2, 0.3])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["margin_balance_ratio"])
        self.assertEqual(scaler.mask_cols, [])
        self.assertEqual(scaler.feature_cols_out, ["margin_balance_ratio"])

    def test_subset_without_g9_has_no_mask(self):
        frame = _frame([10.0, 10.0], open=[10.0, 11.0])
        scaler = PerCodeGroupedScaler().fit(frame, ["open"])
        self.assertEqual(scaler.mask_cols, [])
        self.assertEqual(scaler.feature_cols_out, ["open"])

    def test_full_default_schema_appends_one_mask(self):
        columns = {c: [0.1, 0.2] for c in APPROVED_RAW_FEATURES if c != "close"}
        frame = _frame([10.0, 11.0], **columns)
        scaler = PerCodeGroupedScaler().fit(frame, list(APPROVED_RAW_FEATURES))
        self.assertEqual(len(scaler.feature_cols_out), 53)
        self.assertEqual(scaler.feature_cols_out[-1], "g9_observed_mask")


class TestUnknownAndFallback(unittest.TestCase):
    def test_unknown_feature_col_raises_on_fit(self):
        frame = _frame([10.0, 10.0], open=[10.0, 11.0])
        with self.assertRaises(ValueError):
            PerCodeGroupedScaler(add_mask=False).fit(frame, ["not_a_feature"])

    def test_unknown_feature_col_raises_on_transform(self):
        frame = _frame([10.0, 10.0], open=[10.0, 11.0])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        with self.assertRaises(ValueError):
            scaler.transform_code("A", np.array([[1.0], [2.0]]), ["not_a_feature"])

    def test_unseen_code_falls_back_to_global_stats(self):
        frame = _frame([100.0] * 4, open=[100.0, 110.0, 120.0, 130.0])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        stats = scaler.global_stats["open"]
        out = scaler.transform_code("UNSEEN", np.array([[100.0], [150.0]]), ["open"], np.array([100.0, 100.0]))
        expected = (0.5 - stats["median"]) / (stats["iqr"] / IQR_TO_SIGMA + EPS)
        self.assertAlmostEqual(float(out[1, 0]), float(np.clip(expected, -5.0, 5.0)), places=5)

    def test_stats_only_required_for_p_group(self):
        frame = _frame([10.0] * 3, amihud=[1e-13, 2e-13, 3e-13])
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["amihud"])
        scaler.validate_requested_schema(["amihud"], add_mask=False)


class TestSchemaContractAndPersistence(unittest.TestCase):
    def test_validate_requested_schema_pass_and_mismatch(self):
        frame = _frame([10.0, 10.0], open=[10.0, 11.0])
        scaler = PerCodeGroupedScaler().fit(frame, ["open"])
        scaler.validate_requested_schema(["open"])
        with self.assertRaises(ValueError):
            scaler.validate_requested_schema(["open", "close"])
        with self.assertRaises(ValueError):
            scaler.validate_requested_schema(["open"], add_mask=False)

    def test_save_load_roundtrip_uses_v4_payload(self):
        frame = _frame([10.0, 11.0], open=[10.0, 11.0])
        scaler = PerCodeGroupedScaler().fit(frame, ["open"])
        scaler.set_identity({"dataset": "x"})
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "scaler.pkl")
            scaler.save(path)
            loaded = PerCodeGroupedScaler.load(path)
        self.assertEqual(loaded.feature_cols_out, scaler.feature_cols_out)
        np.testing.assert_allclose(
            loaded.transform_code("A", frame[["open"]].to_numpy(), ["open"], frame["close"].to_numpy()),
            scaler.transform_code("A", frame[["open"]].to_numpy(), ["open"], frame["close"].to_numpy()),
        )

    def test_old_v3_payload_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "old.pkl")
            with open(path, "wb") as file:
                pickle.dump({"version": "v3_per_code"}, file)
            with self.assertRaises(ValueError):
                PerCodeGroupedScaler.load(path)

    def test_versions_and_digest(self):
        self.assertEqual(SCALER_VERSION, "v4_per_code")
        digest = PerCodeGroupedScaler.transform_config_digest()
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, PerCodeGroupedScaler.transform_config_digest())
        self.assertNotEqual(digest, RelativeScaler.transform_config_digest())


if __name__ == "__main__":
    unittest.main()
