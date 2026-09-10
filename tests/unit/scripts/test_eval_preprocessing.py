import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from data.dataset import _RollingDatasetState
from data.rolling_scaler import RollingNormalizer
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES, G9_MASK_COLUMNS
from scripts import eval_bins_mapping as evaluation


class TestEvalPreprocessing(unittest.TestCase):
    def _checkpoint(self, config):
        directory = Path(tempfile.mkdtemp())
        checkpoint = directory / "best_model.pth"
        checkpoint.touch()
        (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
        return str(checkpoint)

    def test_old_config_defaults_to_per_code(self):
        checkpoint = self._checkpoint({"CNNTransformerConfig": {"featurenum": 69}})
        result = evaluation.load_eval_preprocessing(checkpoint)
        self.assertEqual(result.mode, "per_code")

    def test_rolling_metadata_loads_rolling_state(self):
        with tempfile.NamedTemporaryFile(suffix=".pkl") as state_file:
            state = _rolling_state({"dataset": "x"}, ["open"])
            state.save(state_file.name)
            checkpoint = self._checkpoint({
                "CNNTransformerConfig": {"featurenum": 69, "seq_len": 60, "num_classes": 52},
                "preprocessing": {"mode": "rolling", "feature_cols": ["open"],
                                  "schema_manifest": state.schema_manifest,
                                  "schema_identity": state.identity_hash, "state_path": state_file.name},
            })
            result = evaluation.load_eval_preprocessing(checkpoint)
            self.assertEqual(result.mode, "rolling")
            self.assertIsInstance(result.scaler_stats, _RollingDatasetState)
            self.assertEqual(result.run_config["preprocessing"]["schema_manifest"], state.schema_manifest)

    def test_invalid_mode_and_frozen_rolling_mismatch_fail(self):
        checkpoint = self._checkpoint({"preprocessing": {"mode": "unknown"}})
        with self.assertRaisesRegex(ValueError, "mode"):
            evaluation.load_eval_preprocessing(checkpoint)
        with tempfile.NamedTemporaryFile(suffix=".pkl") as state_file:
            state = _rolling_state({}, ["open"])
            state.save(state_file.name)
            checkpoint = self._checkpoint({"preprocessing": {"mode": "per_code", "state_path": state_file.name}})
            with patch("data.scaler.PerCodeGroupedScaler.load", return_value=state), self.assertRaisesRegex(ValueError, "per_code"):
                evaluation.load_eval_preprocessing(checkpoint)

    def test_loader_uses_evaluation_role_and_metadata_mode(self):
        args = SimpleNamespace(parquet="x", seq_len=60, horizon=5, batch_size=2, num_workers=0,
                               max_codes=0, max_windows_per_code=None, val_start=None, val_end=None,
                               feature_cols=None, scaler_path=None, allow_fit_scaler=False)
        prep = evaluation.EvalPreprocessing("rolling", object(), ["open"], None, {}, None)
        with patch.object(evaluation, "ParquetDataset") as dataset:
            dataset.return_value.num_features = 69
            evaluation.build_val_loader(args, prep)
            cfg = dataset.call_args.args[0]
            self.assertEqual(cfg.role, "evaluation")
            self.assertEqual(cfg.normalize, "rolling")
            self.assertIs(dataset.call_args.kwargs["scaler_stats"], prep.scaler_stats)

    def test_rolling_schema_identity_and_feature_order_are_strict(self):
        with tempfile.NamedTemporaryFile(suffix=".pkl") as state_file:
            state = _rolling_state({"dataset": "x"}, ["open"])
            state.save(state_file.name)
            bad_identity = self._checkpoint({"preprocessing": {
                "mode": "rolling", "schema_identity": "wrong", "state_path": state_file.name,
            }})
            with self.assertRaisesRegex(ValueError, "identity"):
                evaluation.load_eval_preprocessing(bad_identity)
            bad_order = self._checkpoint({"preprocessing": {
                "mode": "rolling", "feature_cols": ["high"], "state_path": state_file.name,
            }})
            with self.assertRaisesRegex(ValueError, "feature"):
                evaluation.load_eval_preprocessing(bad_order)

    def test_per_code_dimensions_use_output_schema_and_remain_strict(self):
        scaler = PerCodeGroupedScaler()
        scaler.feature_cols = list(APPROVED_RAW_FEATURES)
        scaler.feature_cols_out = list(APPROVED_RAW_FEATURES) + list(G9_MASK_COLUMNS)
        prep = evaluation.EvalPreprocessing(
            "per_code", scaler, list(APPROVED_RAW_FEATURES), "identity", {}, "scaler.pkl"
        )
        evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 69, "seq_len": 60}, 60, None)
        with self.assertRaisesRegex(ValueError, "feature schema"):
            evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 51, "seq_len": 60}, 60, None)
        with self.assertRaisesRegex(ValueError, "顺序"):
            evaluation.validate_preprocessing_dimensions(
                prep, {"featurenum": 69, "seq_len": 60}, 60, list(reversed(APPROVED_RAW_FEATURES))
            )


if __name__ == "__main__":
    unittest.main()


def _rolling_state(source, feature_cols):
    frame = pd.DataFrame({
        "code": ["x"] * 3,
        "kline_time": pd.date_range("2025-01-01", periods=3),
        "close": [1.0, 2.0, 3.0],
        **{column: [1.0, 2.0, 3.0] for column in feature_cols},
    })
    fallback = PerCodeGroupedScaler()
    fallback.fit(frame, feature_cols)
    fallback.set_identity({"dataset": "fallback", "feature_cols": feature_cols})
    return _RollingDatasetState(RollingNormalizer(), source, feature_cols, fallback)
