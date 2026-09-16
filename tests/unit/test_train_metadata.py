import json
import sys
import unittest
from unittest.mock import patch

import pandas as pd

import train
from config.defaults import make_default_config
from data.dataset import _RollingDatasetState
from data.rolling_scaler import RollingNormalizer
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES
from train import build_preprocessing_metadata, configure_preprocessing, parse_args


class TestTrainMetadata(unittest.TestCase):
    def test_default_normalization_is_per_code(self):
        with patch.object(sys, "argv", ["train.py"]):
            args = parse_args()
        self.assertEqual(args.normalize, "per_code")
        config = make_default_config()
        configure_preprocessing(config, args.normalize)
        self.assertEqual(config["NORMALIZE"], "per_code")
        self.assertEqual(config["SCALER_PATH"], "logs/scaler_per_code.pkl")

    def test_rolling_is_explicit_and_isolated(self):
        with patch.object(sys, "argv", ["train.py", "--normalize", "rolling"]):
            args = parse_args()
        config = make_default_config()
        configure_preprocessing(config, args.normalize)
        self.assertEqual(args.normalize, "rolling")
        self.assertEqual(config["NORMALIZE"], "rolling")
        self.assertNotEqual(config["SCALER_PATH"], "logs/scaler_per_code.pkl")
        self.assertIn("rolling", config["SCALER_PATH"])
        self.assertIn("rolling", config["LOG_DIR"])

    def test_metadata_records_schema_identity_and_rejects_old_dimension(self):
        state = _rolling_state()
        metadata = build_preprocessing_metadata(
            "rolling", state, state.feature_cols, 69, 60, 52
        )
        self.assertEqual(metadata["mode"], "rolling")
        self.assertEqual(metadata["featurenum"], 69)
        self.assertEqual(metadata["schema_identity"], state.identity_hash)
        self.assertEqual(metadata["schema_manifest"], state.schema_manifest)
        with self.assertRaisesRegex(ValueError, "featurenum"):
            build_preprocessing_metadata("rolling", state, state.feature_cols, 45, 60, 52)

    def test_metadata_is_json_serializable(self):
        metadata = build_preprocessing_metadata(
            "per_code", None, ["open"], 69, 60, 52
        )
        json.dumps(metadata)
        train.json.dumps(metadata)


class TestTrainRollingScopeT03(unittest.TestCase):
    """T03: train.py CLI seed/scope 隔离（e4 路径迁移至 logs/rolling_e4/ 有意为之，见 PLAN）。"""

    def test_default_rolling_scope_is_e4_and_paths_match(self):
        with patch.object(sys, "argv", ["train.py", "--normalize", "rolling"]):
            args = parse_args()
        self.assertEqual(args.rolling_scope, "e4")
        self.assertEqual(args.seed, 42)
        implicit = make_default_config()
        configure_preprocessing(implicit, args.normalize)
        explicit = make_default_config()
        configure_preprocessing(explicit, "rolling", "e4")
        self.assertEqual(implicit["SCALER_PATH"], explicit["SCALER_PATH"])
        self.assertEqual(implicit["LOG_DIR"], explicit["LOG_DIR"])
        self.assertEqual(explicit["SCALER_PATH"], "logs/rolling_e4/scaler_rolling_e4.pkl")
        self.assertEqual(explicit["LOG_DIR"], "./logs/rolling_e4")

    def test_rolling_scopes_are_isolated(self):
        paths = set()
        for scope in ("e2", "e3", "e4"):
            config = make_default_config()
            configure_preprocessing(config, "rolling", scope)
            self.assertIn(scope, config["SCALER_PATH"])
            self.assertIn(scope, config["LOG_DIR"])
            paths.add((config["SCALER_PATH"], config["LOG_DIR"]))
        self.assertEqual(len(paths), 3)

    def test_per_code_ignores_rolling_scope(self):
        config = make_default_config()
        configure_preprocessing(config, "per_code", "e2")
        self.assertEqual(config["NORMALIZE"], "per_code")
        self.assertEqual(config["SCALER_PATH"], "logs/scaler_per_code.pkl")
        self.assertNotIn("rolling", config["LOG_DIR"])

    def test_load_rolling_state_rejects_foreign_scope(self):
        import os
        import tempfile

        from train import load_rolling_state

        state = _rolling_state_t03(scope="e2")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scaler_rolling_e2.pkl")
            state.save(path)
            loaded = load_rolling_state(path, expected_scope="e2")
            self.assertEqual(loaded.normalizer.config.scope, "e2")
            with self.assertRaisesRegex(ValueError, "scope"):
                load_rolling_state(path, expected_scope="e3")

    def test_metadata_records_scope_seed_digest_identity(self):
        state = _rolling_state_t03(scope="e2")
        metadata = build_preprocessing_metadata(
            "rolling", state, state.feature_cols, 69, 60, 52, scope="e2", seed=42
        )
        self.assertEqual(metadata["scope"], "e2")
        self.assertEqual(metadata["seed"], 42)
        self.assertEqual(metadata["identity"], state.identity_hash)
        self.assertEqual(metadata["digest"], state.normalizer.transform_config_digest())
        json.dumps(metadata)

    def test_set_all_seeds_reproducible(self):
        import random

        import numpy as np
        import torch

        from train import set_all_seeds

        set_all_seeds(42)
        expected_torch = torch.rand(8)
        expected_np = np.random.rand(8)
        expected_py = [random.random() for _ in range(8)]
        set_all_seeds(42)
        torch.testing.assert_close(torch.rand(8), expected_torch)
        np.testing.assert_allclose(np.random.rand(8), expected_np)
        self.assertEqual([random.random() for _ in range(8)], expected_py)


def _rolling_state_t03(scope="e4"):
    from data.rolling_scaler import RollingNormalizationConfig

    features = list(APPROVED_RAW_FEATURES)
    frame = pd.DataFrame({
        "code": ["x"] * 3,
        "kline_time": pd.date_range("2025-01-01", periods=3),
        "close": [1.0, 2.0, 3.0],
        **{column: [1.0, 2.0, 3.0] for column in features},
    })
    fallback = PerCodeGroupedScaler()
    fallback.fit(frame, features)
    fallback.set_identity({"dataset": "fallback", "feature_cols": features})
    return _RollingDatasetState(
        RollingNormalizer(RollingNormalizationConfig(scope=scope)), {"dataset": "test"}, features, fallback
    )


if __name__ == "__main__":
    unittest.main()


def _rolling_state():
    features = list(APPROVED_RAW_FEATURES)
    frame = pd.DataFrame({
        "code": ["x"] * 3,
        "kline_time": pd.date_range("2025-01-01", periods=3),
        "close": [1.0, 2.0, 3.0],
        **{column: [1.0, 2.0, 3.0] for column in features},
    })
    fallback = PerCodeGroupedScaler()
    fallback.fit(frame, features)
    fallback.set_identity({"dataset": "fallback", "feature_cols": features})
    return _RollingDatasetState(RollingNormalizer(), {"dataset": "test"}, features, fallback)
