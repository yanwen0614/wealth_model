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
