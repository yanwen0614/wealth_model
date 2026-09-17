"""Synthetic contracts for the standalone rolling normalization kernel."""
import os
import tempfile
import unittest
from typing import ClassVar, cast
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset, _RollingDatasetState
from data.rolling_scaler import (
    ROLLING_FEATURES,
    ROLLING_MODE,
    ROLLING_PRICE_FEATURES,
    ROLLING_SCOPE_FEATURES,
    ROLLING_SCOPES,
    ROLLING_VERSION,
    ROLLING_VOLATILITY_FEATURES,
    RollingAudit,
    RollingNormalizationConfig,
    RollingNormalizer,
)
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES, FEATURE_GROUPS, G9_MASK_COLUMNS


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
        self.assertEqual(len(APPROVED_RAW_FEATURES), 52)
        self.assertEqual(len(G9_MASK_COLUMNS), 1)
        self.assertEqual(len(schema["output_feature_cols"]), 53)
        self.assertEqual(schema["output_feature_cols"][-1], "g9_observed_mask")
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

    def test_nonscope_columns_follow_column_rules_and_g9_shared_mask(self):
        values = np.array([[2.5, np.nan], [np.inf, 1.5], [-3.0, 0.25]])
        result = self.normalizer.transform_code(
            values, ["gross_margin", "margin_balance_ratio"], np.ones(3)
        )
        self.assertEqual(result.values.shape, (3, 3))
        expected_asinh = np.arcsinh(np.where(np.isfinite(values[:, 0]), values[:, 0], 0.0))
        np.testing.assert_allclose(result.values[:, 0], expected_asinh, rtol=0, atol=1e-6)
        np.testing.assert_array_equal(result.values[:, 1], [0.0, 1.0, 0.25])
        np.testing.assert_array_equal(result.values[:, 2], [0.0, 1.0, 1.0])
        self.assertTrue(np.isfinite(result.values).all())

    def test_missing_fallback_is_neutral_and_explicitly_marked(self):
        values = np.ones((3, 1))
        result = self.normalizer.transform_code(values, ["amihud"], np.ones(3))
        np.testing.assert_array_equal(result.values, np.zeros((3, 1)))
        self.assertTrue(result.fallback_mask.all())
        self.assertEqual(result.audit.neutral_fallback_values, 3)

    def test_close_is_allowed_and_bad_fallback_shape_is_rejected(self):
        close = np.array([10.0, 11.0, 12.0])
        result = self.normalizer.transform_code(close[:, None], ["close"], close)
        self.assertEqual(result.values.shape, (3, 1))
        with self.assertRaisesRegex(ValueError, "frozen_fallback"):
            self.normalizer.transform_code(
                np.ones((2, 1)), ["open"], np.ones(2), frozen_fallback=np.ones((2, 2))
            )
        with self.assertRaisesRegex(ValueError, "重复"):
            self.normalizer.transform_code(np.ones((2, 2)), ["open", "open"], np.ones(2))

    def test_accepts_frozen_fallback_with_appended_g9_mask(self):
        values = np.ones((3, 2))
        frozen = np.column_stack((np.full(3, -4.0), np.full(3, 0.5), np.ones(3)))
        result = self.normalizer.transform_code(
            values, ["open", "margin_balance_ratio"], np.ones(3), frozen_fallback=frozen
        )
        np.testing.assert_array_equal(result.values[:, 0], np.full(3, -4.0))
        self.assertTrue(result.fallback_mask[:, 0].all())

    def test_rolling_state_round_trip_is_independent_and_validated(self):
        state = _rolling_state(self.normalizer, {"dataset": "synthetic"}, ["open"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.pkl")
            state.save(path)
            loaded = _RollingDatasetState.load(path)
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

    def test_rolling_validation_context_is_warmup_not_a_label(self):
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
        # context 作为窗口 warmup 输入保留（combined 行数），可出现在窗口内。
        self.assertEqual(val.groups["000001"]["n"], 180)
        self.assertLess(val.groups["000001"]["kline_time"][0], np.datetime64("2025-05-01"))
        # 但 context 恒非标签日：所有标签日 >= start_date，最早标签日 == start_date。
        label_days = [val.groups["000001"]["kline_time"][s + 9] for _, s in val.index]
        self.assertTrue(all(day >= np.datetime64("2025-05-01") for day in label_days))
        self.assertEqual(min(label_days), np.datetime64("2025-05-01"))
        self.assertTrue(all(s >= 111 for _, s in val.index))

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
        with tempfile.TemporaryDirectory() as tmp, _parquet(frame) as path:
            state_path = os.path.join(tmp, "rolling_state.pkl")
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                feature_cols=["open", "high", "low"], end_date="2025-04-30", num_workers=0,
            ))
            state = cast(_RollingDatasetState, train.scaler_stats)
            state.save(state_path)
            loaded = _RollingDatasetState.load(state_path)
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
        self.assertEqual(_RollingDatasetState.PAYLOAD_VERSION, "v2_rolling_state")


class TestRollingScopeSubsets(unittest.TestCase):
    EXPECTED_COUNTS: ClassVar[dict[str, int]] = {"e0": 0, "e1": 18, "e2": 18, "e3": 21, "e4": 24, "e5": 30}

    def test_scopes_are_e0_through_e5(self):
        self.assertEqual(tuple(ROLLING_SCOPES), ("e0", "e1", "e2", "e3", "e4", "e5"))
        self.assertEqual(RollingNormalizationConfig().scope, "e5")

    def test_scope_feature_counts(self):
        self.assertEqual(
            {scope: len(cols) for scope, cols in ROLLING_SCOPE_FEATURES.items()},
            self.EXPECTED_COUNTS,
        )

    def test_scope_composition_from_feature_groups(self):
        price = tuple(FEATURE_GROUPS["P"])
        g9_raw = tuple(FEATURE_GROUPS["G"])
        self.assertEqual(ROLLING_SCOPE_FEATURES["e0"], ())
        self.assertEqual(tuple(ROLLING_SCOPE_FEATURES["e1"]), price)
        self.assertEqual(tuple(ROLLING_SCOPE_FEATURES["e2"]), price)
        self.assertEqual(
            tuple(ROLLING_SCOPE_FEATURES["e3"]), price + ROLLING_VOLATILITY_FEATURES
        )
        self.assertEqual(tuple(ROLLING_SCOPE_FEATURES["e4"]), tuple(ROLLING_FEATURES))
        self.assertEqual(tuple(ROLLING_SCOPE_FEATURES["e5"]), tuple(ROLLING_FEATURES) + g9_raw)
        self.assertEqual(tuple(ROLLING_PRICE_FEATURES), price)

    def test_invalid_scope_raises_value_error(self):
        with self.assertRaises(ValueError):
            RollingNormalizationConfig(scope="e6")

    def test_scope_digests_are_pairwise_different(self):
        digests = {
            scope: RollingNormalizer(RollingNormalizationConfig(scope=scope)).transform_config_digest()
            for scope in ROLLING_SCOPES
        }
        self.assertEqual(len(set(digests.values())), len(ROLLING_SCOPES))

    def test_output_feature_cols_len_matches_transform_for_all_scopes(self):
        for scope in ROLLING_SCOPES:
            with self.subTest(scope=scope):
                normalizer = RollingNormalizer(RollingNormalizationConfig(scope=scope))
                cols = list(APPROVED_RAW_FEATURES)
                out_cols = normalizer.output_feature_cols(cols)
                self.assertEqual(len(out_cols), 53)
                self.assertEqual(out_cols[-1], "g9_observed_mask")
                result = normalizer.transform_code(np.ones((5, len(cols))), cols, np.ones(5))
                self.assertEqual(result.values.shape[1], len(out_cols))

    def test_e0_nonscope_price_uses_relative_clip(self):
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope="e0"))
        close = np.array([10.0, 11.0, 12.0])
        result = normalizer.transform_code(close[:, None], ["close"], close)
        np.testing.assert_allclose(
            result.values[:, 0], [0.0, 1.0 / 10.0, 1.0 / 11.0], rtol=0, atol=1e-7
        )
        self.assertGreater(result.audit.passthrough_values, 0)


class TestRollingMaskRegression(unittest.TestCase):
    def test_g9_raw_in_scope_still_emits_shared_mask(self):
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope="e5"))
        cols = ["open", "margin_balance_ratio_raw"]
        out_cols = normalizer.output_feature_cols(cols)
        self.assertEqual(
            out_cols, ["open", "margin_balance_ratio_raw", "g9_observed_mask"]
        )
        values = np.array(
            [[10.0, 0.5], [11.0, np.nan], [12.0, np.inf], [13.0, -0.5]]
        )
        close = np.array([10.0, 10.0, 11.0, 12.0])
        result = normalizer.transform_code(values, cols, close)
        self.assertEqual(result.values.shape[1], len(out_cols))
        np.testing.assert_array_equal(result.values[:, -1], [1.0, 0.0, 0.0, 1.0])

    def test_nonscope_g_fixed_clip_preserves_negative(self):
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope="e0"))
        values = np.array([[-0.5], [0.5], [2.0], [np.nan]])
        result = normalizer.transform_code(
            values, ["margin_net_buy_ratio_raw"], np.ones(4)
        )
        np.testing.assert_array_equal(result.values[:, 0], [-0.5, 0.5, 1.0, 0.0])


class TestDatasetScope(unittest.TestCase):
    def test_mismatched_scope_state_raises_on_validate(self):
        frame = _dataset_frame(180)
        with _parquet(frame) as path:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                rolling_scope="e2", feature_cols=["open", "high", "low"],
                end_date="2025-04-30", num_workers=0,
            ))
            with self.assertRaises(ValueError):
                ParquetDataset(ParquetDataConfig(
                    parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                    rolling_scope="e3", feature_cols=["open", "high", "low"],
                    start_date="2025-05-01", role="validation", num_workers=0,
                ), scaler_stats=train.scaler_stats)

    def test_same_scope_reuse_passes_and_propagates_scope(self):
        frame = _dataset_frame(180)
        with _parquet(frame) as path:
            train = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                rolling_scope="e2", feature_cols=["open", "high", "low"],
                end_date="2025-04-30", num_workers=0,
            ))
            val = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                rolling_scope="e2", feature_cols=["open", "high", "low"],
                start_date="2025-05-01", role="validation", num_workers=0,
            ), scaler_stats=train.scaler_stats)
        train_state = cast(_RollingDatasetState, train.scaler_stats)
        self.assertEqual(train_state.normalizer.config.scope, "e2")
        self.assertEqual(train_state.schema_manifest["scope"], "e2")
        self.assertGreater(len(val), 0)

    def test_each_scope_output_num_features_53(self):
        for scope in ROLLING_SCOPES:
            with self.subTest(scope=scope):
                frame = _approved_frame(150)
                with _parquet(frame) as path:
                    ds = ParquetDataset(ParquetDataConfig(
                        parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                        rolling_scope=scope, feature_cols=list(APPROVED_RAW_FEATURES),
                        num_workers=0,
                    ))
                self.assertEqual(ds.num_features, 53)
                self.assertEqual(tuple(ds[0][0].shape), (53, 10))
                state = cast(_RollingDatasetState, ds.scaler_stats)
                self.assertEqual(state.normalizer.config.scope, scope)

    def test_invalid_scope_raises_value_error(self):
        frame = _dataset_frame(150)
        with _parquet(frame) as path, self.assertRaises(ValueError):
            ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2, normalize="rolling",
                rolling_scope="e6", feature_cols=["open", "high", "low"],
                num_workers=0,
            ))

    def test_per_code_ignores_rolling_scope(self):
        frame = _dataset_frame(150)
        with _parquet(frame) as path:
            ds = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=10, horizon=2,
                rolling_scope="e2", feature_cols=["open", "high", "low"], num_workers=0,
            ))
        self.assertEqual(ds.config.normalize, "per_code")


def _reference_rolling_column(
    config: RollingNormalizationConfig,
    values: np.ndarray,
    robust: bool,
    fallback: np.ndarray | None,
    fallback_mask: np.ndarray,
    audit: RollingAudit,
) -> np.ndarray:
    """逐行参考实现：向量化前 `_rolling_column` 的原始逻辑（保持逐字语义）。"""
    output = np.zeros(values.shape, dtype=np.float64)
    for current in range(len(values)):
        start = max(0, current - config.window + 1)
        window = values[start : current + 1]
        valid = window[np.isfinite(window)]
        if valid.size < config.min_periods:
            fallback_mask[current] = True
            audit.fallback_values += 1
            if fallback is not None and np.isfinite(fallback[current]):
                output[current] = fallback[current]
            else:
                audit.neutral_fallback_values += 1
            continue
        if not np.isfinite(values[current]):
            continue
        if robust:
            median = float(np.median(valid))
            q25, q75 = np.percentile(valid, [25, 75])
            iqr = float(q75 - q25)
            if iqr <= np.finfo(np.float64).eps:
                scale = 1.0
                audit.constant_iqr_values += 1
            else:
                scale = iqr / 1.349
            output[current] = np.clip(
                (values[current] - median) / scale,
                -config.robust_clip,
                config.robust_clip,
            )
        else:
            lower, upper = np.percentile(
                valid, [config.lower_percentile, config.upper_percentile]
            )
            output[current] = np.clip(values[current], lower, upper)
        audit.rolling_values += 1
    return output


class TestRollingColumnVectorizedEquivalence(unittest.TestCase):
    """向量化 `_rolling_column` 必须与逐行参考实现数值等价。"""

    WINDOW = 20
    MIN_PERIODS = 5

    def _compare(self, values, robust, fallback):
        config = RollingNormalizationConfig(window=self.WINDOW, min_periods=self.MIN_PERIODS)
        normalizer = RollingNormalizer(config)
        size = len(values)
        mask_vec = np.zeros(size, dtype=bool)
        mask_ref = np.zeros(size, dtype=bool)
        audit_vec = RollingAudit()
        audit_ref = RollingAudit()
        out_vec = normalizer._rolling_column(
            values.copy(), robust, fallback, mask_vec, audit_vec
        )
        out_ref = _reference_rolling_column(
            config, values.copy(), robust, fallback, mask_ref, audit_ref
        )
        self.assertEqual(out_vec.dtype, np.float64)
        np.testing.assert_array_equal(mask_vec, mask_ref)
        self.assertEqual(audit_vec, audit_ref)
        np.testing.assert_allclose(out_vec, out_ref, rtol=0, atol=1e-12)
        return float(np.max(np.abs(out_vec - out_ref))) if size else 0.0

    def _random_values(self, seed):
        rng = np.random.default_rng(seed)
        size = 137
        values = rng.standard_normal(size) * 10.0 + 5.0
        values[rng.random(size) < 0.15] = np.nan
        values[rng.random(size) < 0.05] = np.inf
        values[40:70] = 3.0  # 常数段：iqr=0 触发 constant_iqr_values
        values[100] = np.nan
        values[101] = 7.0
        return values

    def test_robust_matches_reference_with_nan_and_constant_segments(self):
        for seed in range(4):
            with self.subTest(seed=seed):
                values = self._random_values(seed)
                max_diff = self._compare(values, robust=True, fallback=None)
                self.assertLessEqual(max_diff, 1e-12)

    def test_winsor_matches_reference(self):
        for seed in range(4):
            with self.subTest(seed=seed):
                values = self._random_values(seed)
                max_diff = self._compare(values, robust=False, fallback=None)
                self.assertLessEqual(max_diff, 1e-12)

    def test_supplied_fallback_including_non_finite_entries(self):
        values = self._random_values(0)
        fallback = np.full(values.shape, -7.0)
        fallback[0:3] = np.nan
        fallback[10] = np.inf
        for robust in (True, False):
            with self.subTest(robust=robust):
                self._compare(values, robust=robust, fallback=fallback)

    def test_boundary_lengths_and_nan_current_row(self):
        for size in (self.MIN_PERIODS - 1, self.MIN_PERIODS, self.MIN_PERIODS + 1, 60):
            with self.subTest(size=size):
                values = np.arange(1.0, size + 1)
                if size > 2:
                    values[-1] = np.nan
                for robust in (True, False):
                    self._compare(values, robust=robust, fallback=None)

    def test_empty_and_all_nan(self):
        for values in (np.array([], dtype=np.float64), np.full(9, np.nan)):
            for robust in (True, False):
                with self.subTest(size=len(values), robust=robust):
                    self._compare(values, robust=robust, fallback=None)

    def test_rolling_column_is_vectorized(self):
        normalizer = RollingNormalizer(
            RollingNormalizationConfig(window=self.WINDOW, min_periods=self.MIN_PERIODS)
        )
        values = np.arange(1.0, 61.0)
        with patch("numpy.median") as median_call, patch("numpy.percentile") as percentile_call:
            normalizer._rolling_column(values, False, None, np.zeros(60, dtype=bool), RollingAudit())
        median_call.assert_not_called()
        percentile_call.assert_not_called()


def _dataset_frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({
        "code": ["000001"] * rows,
        "kline_time": pd.date_range("2025-01-01", periods=rows),
        "open": np.arange(1.0, rows + 1), "high": np.arange(2.0, rows + 2),
        "low": np.arange(0.5, rows + 0.5), "close": np.arange(1.5, rows + 1.5),
        "is_trading": True,
    })


def _approved_frame(rows: int) -> pd.DataFrame:
    frame = _dataset_frame(rows)
    rng = np.random.default_rng(42)
    base = np.arange(1.0, rows + 1)
    for column in APPROVED_RAW_FEATURES:
        if column in frame.columns:
            continue
        frame[column] = base * (1.0 + 0.01 * rng.standard_normal(rows)) + 5.0
    return frame


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
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "frame.parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.path)
        return self.path

    def __exit__(self, *args):
        self._dir.cleanup()


if __name__ == "__main__":
    unittest.main()
