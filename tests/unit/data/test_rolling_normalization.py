"""Synthetic contracts for the standalone rolling normalization kernel."""
import tempfile
import unittest
from typing import cast
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset, _RollingDatasetState
from data.rolling_scaler import (
    ROLLING_MODE,
    ROLLING_VERSION,
    RollingNormalizationConfig,
    RollingNormalizer,
)
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES, G9_MASK_COLUMNS


class TestRollingNormalization(unittest.TestCase):
    def setUp(self):
        self.config = RollingNormalizationConfig()
        self.normalizer = RollingNormalizer(self.config)

    def test_schema_and_identity_are_isolated_from_frozen_scaler(self):
        schema = self.normalizer.schema_manifest(APPROVED_RAW_FEATURES)
        self.assertEqual(ROLLING_MODE, "rolling")
        self.assertNotEqual(ROLLING_VERSION, "v3_per_code")
        self.assertEqual(self.config.window, 252)
        self.assertEqual(self.config.min_periods, 120)
        self.assertTrue(self.config.include_current_t)
        self.assertEqual(len(APPROVED_RAW_FEATURES), 51)
        self.assertEqual(len(G9_MASK_COLUMNS), 18)
        self.assertEqual(len(schema["output_feature_cols"]), 69)
        self.assertNotIn("close", schema["output_feature_cols"])
        self.assertEqual(schema["helper_cols"], ["close"])
        self.assertNotEqual(schema["transform_digest"], "per_code_transform_v3")
        first = self.normalizer.identity({"dataset": "synthetic"}, APPROVED_RAW_FEATURES)
        second = self.normalizer.identity({"dataset": "synthetic"}, APPROVED_RAW_FEATURES)
        changed = RollingNormalizer(RollingNormalizationConfig(window=251)).identity(
            {"dataset": "synthetic"}, APPROVED_RAW_FEATURES
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)

    def test_window_includes_current_and_future_changes_do_not_leak(self):
        values = np.arange(1.0, 131.0)[:, None]
        close = np.full(130, 10.0)
        baseline = self.normalizer.transform_code(values, ["volatility_5d"], close)
        perturbed = values.copy()
        perturbed[121:] = 1_000_000.0
        changed = self.normalizer.transform_code(perturbed, ["volatility_5d"], close)
        np.testing.assert_array_equal(baseline.values[:121], changed.values[:121])
        expected = np.percentile(values[0:120, 0], 99)
        self.assertAlmostEqual(baseline.values[119, 0], expected, places=5)
        self.assertFalse(baseline.fallback_mask[119, 0])

    def test_min_periods_boundary_uses_supplied_frozen_fallback(self):
        values = np.arange(1.0, 121.0)[:, None]
        frozen = np.full_like(values, -7.0)
        result = self.normalizer.transform_code(
            values, ["volatility_5d"], np.ones(120), frozen_fallback=frozen
        )
        self.assertTrue(result.fallback_mask[:119, 0].all())
        self.assertFalse(result.fallback_mask[119, 0])
        np.testing.assert_array_equal(result.values[:119, 0], frozen[:119, 0])
        self.assertEqual(result.audit.fallback_values, 119)
        self.assertEqual(result.audit.neutral_fallback_values, 0)

    def test_price_relative_robust_handles_constant_iqr_and_nan(self):
        close = np.full(122, 10.0)
        values = np.full((122, 1), 10.0)
        values[120, 0] = np.nan
        result = self.normalizer.transform_code(values, ["open"], close)
        self.assertTrue(np.isfinite(result.values).all())
        self.assertEqual(result.values[119, 0], 0.0)
        self.assertEqual(result.values[120, 0], 0.0)
        self.assertGreater(result.audit.constant_iqr_values, 0)
        self.assertEqual(result.audit.missing_values, 1)

    def test_window_is_capped_at_252_observations(self):
        values = np.ones((253, 1))
        values[0, 0] = 10_000.0
        result = self.normalizer.transform_code(values, ["volatility_5d"], np.ones(253))
        self.assertEqual(result.values[252, 0], 1.0)

    def test_nonrolling_columns_are_passthrough_and_g9_gets_masks(self):
        values = np.array(
            [
                [2.5, np.nan],
                [np.inf, 1.5],
                [-3.0, 0.25],
            ]
        )
        result = self.normalizer.transform_code(
            values,
            ["gross_margin", "margin_balance_ratio"],
            np.ones(3),
        )
        self.assertEqual(result.values.shape, (3, 3))
        np.testing.assert_array_equal(result.values[:, 0], [2.5, 0.0, -3.0])
        np.testing.assert_array_equal(result.values[:, 1], [0.0, 1.0, 0.25])
        np.testing.assert_array_equal(result.values[:, 2], [0.0, 1.0, 1.0])
        self.assertEqual(result.audit.passthrough_values, 6)
        self.assertTrue(np.isfinite(result.values).all())

    def test_missing_fallback_is_neutral_and_explicitly_marked(self):
        values = np.ones((3, 1))
        result = self.normalizer.transform_code(values, ["amihud"], np.ones(3))
        np.testing.assert_array_equal(result.values, np.zeros((3, 1)))
        self.assertTrue(result.fallback_mask.all())
        self.assertEqual(result.audit.neutral_fallback_values, 3)

    def test_rejects_close_as_an_output_and_bad_fallback_shape(self):
        with self.assertRaisesRegex(ValueError, "close"):
            self.normalizer.transform_code(np.ones((2, 1)), ["close"], np.ones(2))
        with self.assertRaisesRegex(ValueError, "frozen_fallback"):
            self.normalizer.transform_code(
                np.ones((2, 1)), ["open"], np.ones(2), frozen_fallback=np.ones((2, 2))
            )

    def test_accepts_frozen_fallback_with_appended_g9_masks(self):
        values = np.ones((3, 2))
        frozen = np.column_stack((np.full(3, -4.0), np.full(3, 0.5), np.ones(3)))
        result = self.normalizer.transform_code(
            values,
            ["open", "margin_balance_ratio"],
            np.ones(3),
            frozen_fallback=frozen,
        )
        np.testing.assert_array_equal(result.values[:, 0], np.full(3, -4.0))
        self.assertTrue(result.fallback_mask[:, 0].all())

    def test_rolling_state_round_trip_is_independent_and_validated(self):
        state = _rolling_state(self.normalizer, {"dataset": "synthetic"}, ["open"])
        with tempfile.NamedTemporaryFile(suffix=".pkl") as file:
            state.save(file.name)
            loaded = _RollingDatasetState.load(file.name)
            loaded.validate({"dataset": "synthetic"}, ["open"])
            with self.assertRaisesRegex(ValueError, "identity"):
                loaded.validate({"dataset": "changed"}, ["open"])

    def test_dataset_rolling_is_explicit_and_keeps_shape(self):
        frame = _dataset_frame(150)
        with _parquet(frame) as path:
            ds = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], num_workers=0,
            ))
        self.assertEqual(ds.num_features, 3)
        self.assertEqual(tuple(ds[0][0].shape), (3, 10))
        self.assertEqual(ds.config.normalize, "rolling")

    def test_rolling_validation_context_is_not_a_sample(self):
        frame = _dataset_frame(180)
        with _parquet(frame) as path:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], end_date="2025-04-30",
                num_workers=0,
            ))
            val = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], start_date="2025-05-01",
                role="validation", num_workers=0,
            ), scaler_stats=train.scaler_stats)
        self.assertTrue(all(s >= 0 for _, s in val.index))
        self.assertEqual(val.groups["000001"]["n"], 180 - 120)
        self.assertAlmostEqual(val.groups["000001"]["future_ret"][0], 124.0 / 122.0 - 1.0)

    def test_rolling_calls_frozen_only_for_element_fallback(self):
        frame = _dataset_frame(150)
        original_transform = PerCodeGroupedScaler.transform_code
        with patch.object(
            PerCodeGroupedScaler,
            "transform_code",
            autospec=True,
            side_effect=lambda scaler, *args, **kwargs: original_transform(scaler, *args, **kwargs),
        ) as transform, _parquet(frame) as path:
            ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], num_workers=0,
            ))
        self.assertEqual(transform.call_count, 1)

    def test_rolling_requires_matching_training_identity(self):
        frame = _dataset_frame(150)
        with _parquet(frame) as train_path, _parquet(frame) as other_path:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=train_path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], num_workers=0,
            ))
            with self.assertRaisesRegex(ValueError, "identity"):
                ParquetDataset(ParquetDataConfig(
                    parquet_path=other_path, seq_len=10, horizon=2, normalize="rolling",
                    feature_cols=["open", "high", "low"], role="validation", num_workers=0,
                ), scaler_stats=train.scaler_stats)

    def test_default_normalize_remains_frozen(self):
        self.assertEqual(ParquetDataConfig().normalize, "per_code")

    def test_default_dataset_uses_frozen_scaler_path(self):
        frame = _dataset_frame(150)
        with patch("data.dataset.RollingNormalizer") as rolling, _parquet(frame) as path:
            ds = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2,
                feature_cols=["open", "high", "low"], num_workers=0,
            ))
        self.assertEqual(ds.config.normalize, "per_code")
        rolling.assert_not_called()

    def test_training_fits_one_fallback_and_validation_reuses_it(self):
        frame = _dataset_frame(180)
        original_fit = PerCodeGroupedScaler.fit
        with patch.object(
            PerCodeGroupedScaler,
            "fit",
            autospec=True,
            side_effect=lambda scaler, *args, **kwargs: original_fit(scaler, *args, **kwargs),
        ) as fit, _parquet(frame) as path:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], end_date="2025-04-30", num_workers=0,
            ))
            val = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], start_date="2025-05-01",
                role="validation", num_workers=0,
            ), scaler_stats=train.scaler_stats)
        self.assertEqual(fit.call_count, 1)
        train_state = cast(_RollingDatasetState, train.scaler_stats)
        val_state = cast(_RollingDatasetState, val.scaler_stats)
        self.assertIs(val_state.fallback_scaler, train_state.fallback_scaler)

    def test_dataset_uses_frozen_warmup_then_rolling_values(self):
        frame = _dataset_frame(150)
        frame["volatility_5d"] = np.arange(1.0, 151.0)
        with _parquet(frame) as path:
            ds = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["volatility_5d"], num_workers=0,
            ))
        state = cast(_RollingDatasetState, ds.scaler_stats)
        fallback = state.fallback_scaler.transform_code(
            "000001", frame[["volatility_5d"]].to_numpy(), ["volatility_5d"], frame["close"].to_numpy()
        )
        np.testing.assert_array_equal(ds.groups["000001"]["features"][:119, 0], fallback[:119, 0])
        self.assertNotEqual(ds.groups["000001"]["features"][119, 0], fallback[119, 0])

    def test_state_round_trip_keeps_fallback_and_audit_is_split_local(self):
        frame = _dataset_frame(180)
        with _parquet(frame) as path, tempfile.NamedTemporaryFile(suffix=".pkl") as state_file:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], end_date="2025-04-30", num_workers=0,
            ))
            state = cast(_RollingDatasetState, train.scaler_stats)
            state.save(state_file.name)
            loaded = _RollingDatasetState.load(state_file.name)
            val = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], start_date="2025-05-01",
                role="validation", num_workers=0,
            ), scaler_stats=loaded)
        self.assertIsInstance(loaded.fallback_scaler, PerCodeGroupedScaler)
        self.assertEqual(
            loaded.schema_manifest["fallback"]["transform_digest"],
            PerCodeGroupedScaler.transform_config_digest(),
        )
        self.assertEqual(
            loaded.schema_manifest["fallback"]["identity_hash"],
            loaded.fallback_scaler.identity_hash,
        )
        self.assertGreater(train.rolling_audit["fallback_values"], 0)
        self.assertGreater(train.rolling_audit["fallback_ratio"], 0.0)
        self.assertEqual(train.rolling_audit["neutral_fallback_values"], 0)
        self.assertIsNot(train.rolling_audit, val.rolling_audit)


def _dataset_frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["000001"] * rows,
        "kline_time": pd.date_range("2025-01-01", periods=rows),
        "open": np.arange(1.0, rows + 1), "high": np.arange(2.0, rows + 2),
        "low": np.arange(0.5, rows + 0.5), "close": np.arange(1.5, rows + 1.5),
        "is_trading": True,
    })


def _rolling_state(normalizer, source, feature_cols):
    frame = _dataset_frame(5)
    fallback = PerCodeGroupedScaler()
    fallback.fit(frame, feature_cols)
    fallback.set_identity({"dataset": "fallback", "feature_cols": feature_cols})
    return _RollingDatasetState(normalizer, source, feature_cols, fallback)


class _parquet:
    def __init__(self, frame):
        self.frame = frame

    def __enter__(self):
        self.file = tempfile.NamedTemporaryFile(suffix=".parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.file.name)
        return self.file.name

    def __exit__(self, *args):
        self.file.close()


if __name__ == "__main__":
    unittest.main()
