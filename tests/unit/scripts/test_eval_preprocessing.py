import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from data.dataset import _RollingDatasetState
from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import PerCodeGroupedScaler, RelativeScaler
from data.schema import APPROVED_RAW_FEATURES, G9_MASK_COLUMNS
from scripts import eval_bins_mapping as evaluation
from scripts import run_eval_pipeline as pipeline

FULL_FEATURE_COLS = list(APPROVED_RAW_FEATURES)
FULL_FEATURE_COLS_OUT = FULL_FEATURE_COLS + list(G9_MASK_COLUMNS)


def _checkpoint(config):
    directory = Path(tempfile.mkdtemp())
    checkpoint = directory / "best_model.pth"
    checkpoint.touch()
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return str(checkpoint)


def _relative_metadata(feature_cols=None, feature_cols_out=None):
    cols = list(FULL_FEATURE_COLS if feature_cols is None else feature_cols)
    scaler = RelativeScaler(cols)
    out = scaler.feature_cols_out if feature_cols_out is None else feature_cols_out
    return {
        "mode": "relative", "featurenum": len(scaler.feature_cols_out), "seq_len": 60,
        "num_classes": 52, "feature_cols": cols, "feature_cols_out": list(out),
    }


def _build_rolling_state(scope="e5", feature_cols=None):
    features = list(FULL_FEATURE_COLS if feature_cols is None else feature_cols)
    frame = pd.DataFrame({
        "code": ["x"] * 3,
        "kline_time": pd.date_range("2025-01-01", periods=3),
        "close": [1.0, 2.0, 3.0],
        **{column: [1.0, 2.0, 3.0] for column in features},
    })
    fallback = PerCodeGroupedScaler()
    fallback.fit(frame, features)
    fallback.set_identity({"dataset": "fallback", "feature_cols": features})
    normalizer = RollingNormalizer(RollingNormalizationConfig(scope=scope))
    return _RollingDatasetState(normalizer, {"dataset": "test"}, features, fallback)


class _EvalStateMixin:
    def _save_state(self, state):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = os.path.join(directory, "state.pkl")
        state.save(path)
        return path


class TestLoadEvalPreprocessing(_EvalStateMixin, unittest.TestCase):
    def test_old_config_defaults_to_per_code(self):
        checkpoint = _checkpoint({"CNNTransformerConfig": {"featurenum": 53}})
        result = evaluation.load_eval_preprocessing(checkpoint)
        self.assertEqual(result.mode, "per_code")

    def test_invalid_mode_raises(self):
        checkpoint = _checkpoint({"preprocessing": {"mode": "none"}})
        with self.assertRaisesRegex(ValueError, "mode"):
            evaluation.load_eval_preprocessing(checkpoint)

    def test_relative_mode_rebuilds_stateless_scaler(self):
        checkpoint = _checkpoint({"preprocessing": _relative_metadata()})
        result = evaluation.load_eval_preprocessing(checkpoint)
        self.assertEqual(result.mode, "relative")
        self.assertIsInstance(result.scaler_stats, RelativeScaler)
        self.assertEqual(result.feature_cols_out, FULL_FEATURE_COLS_OUT)
        self.assertIsNone(result.scaler_path)

    def test_relative_feature_cols_out_mismatch_raises(self):
        metadata = _relative_metadata(feature_cols_out=["open"])
        checkpoint = _checkpoint({"preprocessing": metadata})
        with self.assertRaisesRegex(ValueError, "feature_cols_out"):
            evaluation.load_eval_preprocessing(checkpoint)

    def test_relative_without_feature_cols_raises(self):
        checkpoint = _checkpoint({"preprocessing": {"mode": "relative"}})
        with self.assertRaisesRegex(ValueError, "feature_cols"):
            evaluation.load_eval_preprocessing(checkpoint)

    def test_rolling_metadata_loads_state(self):
        state = _build_rolling_state(scope="e1")
        path = self._save_state(state)
        checkpoint = _checkpoint({"preprocessing": {
            "mode": "rolling", "scope": "e1", "feature_cols": state.feature_cols,
            "schema_identity": state.identity_hash, "state_path": path,
        }})
        result = evaluation.load_eval_preprocessing(checkpoint)
        self.assertEqual(result.mode, "rolling")
        self.assertIsInstance(result.scaler_stats, _RollingDatasetState)
        self.assertEqual(
            result.feature_cols_out, state.normalizer.output_feature_cols(state.feature_cols)
        )

    def test_scope_choices_e0_to_e5_and_invalid_rejected(self):
        state = _build_rolling_state(scope="e5")
        path = self._save_state(state)
        checkpoint = _checkpoint({"preprocessing": {
            "mode": "rolling", "feature_cols": state.feature_cols,
            "schema_identity": state.identity_hash, "state_path": path,
        }})
        result = evaluation.load_eval_preprocessing(checkpoint, scope_override="e5")
        self.assertEqual(result.mode, "rolling")
        with self.assertRaisesRegex(ValueError, "scope"):
            evaluation.load_eval_preprocessing(checkpoint, scope_override="e0")
        with self.assertRaisesRegex(ValueError, "scope"):
            evaluation.load_eval_preprocessing(checkpoint, scope_override="e9")

    def test_rolling_schema_identity_and_feature_order_are_strict(self):
        state = _build_rolling_state(feature_cols=["open"])
        path = self._save_state(state)
        bad_identity = _checkpoint({"preprocessing": {
            "mode": "rolling", "schema_identity": "wrong", "state_path": path,
        }})
        with self.assertRaisesRegex(ValueError, "identity"):
            evaluation.load_eval_preprocessing(bad_identity)
        bad_order = _checkpoint({"preprocessing": {
            "mode": "rolling", "feature_cols": ["high"], "state_path": path,
        }})
        with self.assertRaisesRegex(ValueError, "feature"):
            evaluation.load_eval_preprocessing(bad_order)

    def test_per_code_rejects_rolling_state(self):
        state = _build_rolling_state(feature_cols=["open"])
        path = self._save_state(state)
        checkpoint = _checkpoint({"preprocessing": {"mode": "per_code", "state_path": path}})
        with patch("data.scaler.PerCodeGroupedScaler.load", return_value=state), \
                self.assertRaisesRegex(ValueError, "per_code"):
            evaluation.load_eval_preprocessing(checkpoint)

    def test_old_v3_scaler_payload_rejected(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = os.path.join(directory, "v3_scaler.pkl")
        with open(path, "wb") as handle:
            pickle.dump({"version": "v3_per_code", "feature_cols": ["open"]}, handle)
        checkpoint = _checkpoint({"preprocessing": {"mode": "per_code", "state_path": path}})
        with self.assertRaisesRegex(ValueError, "v4_per_code"):
            evaluation.load_eval_preprocessing(checkpoint)

    def test_metadata_scaler_path_takes_priority_over_top_level(self):
        state = _build_rolling_state(scope="e5")
        path = self._save_state(state)
        checkpoint = _checkpoint({
            "SCALER_PATH": "/nonexistent/top_level_scaler.pkl",
            "preprocessing": {"mode": "rolling", "feature_cols": state.feature_cols,
                              "schema_identity": state.identity_hash, "SCALER_PATH": path},
        })
        result = evaluation.load_eval_preprocessing(checkpoint)
        self.assertEqual(result.mode, "rolling")
        self.assertEqual(result.scaler_path, path)


class TestEvalFeaturenumResolution(unittest.TestCase):
    def test_missing_metadata_raises_instead_of_45(self):
        with self.assertRaisesRegex(ValueError, "featurenum"):
            evaluation.resolve_eval_featurenum({})
        with self.assertRaisesRegex(ValueError, "featurenum"):
            evaluation.resolve_eval_featurenum({"preprocessing": {}})

    def test_featurenum_from_metadata(self):
        self.assertEqual(
            evaluation.resolve_eval_featurenum({"preprocessing": {"featurenum": 53}}), 53
        )

    def test_featurenum_from_feature_cols_out(self):
        run_cfg = {"preprocessing": {"feature_cols_out": FULL_FEATURE_COLS_OUT}}
        self.assertEqual(evaluation.resolve_eval_featurenum(run_cfg), 53)

    def test_cli_featurenum_conflict_raises(self):
        with self.assertRaisesRegex(ValueError, "featurenum"):
            evaluation.resolve_eval_featurenum({"preprocessing": {"featurenum": 69}}, 53)

    def test_cli_featurenum_without_metadata(self):
        self.assertEqual(evaluation.resolve_eval_featurenum({}, 53), 53)


class TestEvalDimensions(unittest.TestCase):
    def test_per_code_dimensions_use_output_schema_and_remain_strict(self):
        scaler = PerCodeGroupedScaler()
        scaler.feature_cols = list(FULL_FEATURE_COLS)
        scaler.feature_cols_out = list(FULL_FEATURE_COLS_OUT)
        prep = evaluation.EvalPreprocessing(
            "per_code", scaler, list(FULL_FEATURE_COLS), "identity", {}, "scaler.pkl",
            list(FULL_FEATURE_COLS_OUT),
        )
        evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 53, "seq_len": 60}, 60, None)
        with self.assertRaisesRegex(ValueError, "feature schema"):
            evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 51, "seq_len": 60}, 60, None)
        with self.assertRaisesRegex(ValueError, "顺序"):
            evaluation.validate_preprocessing_dimensions(
                prep, {"featurenum": 53, "seq_len": 60}, 60, list(reversed(FULL_FEATURE_COLS))
            )

    def test_relative_dimensions_use_rules_output(self):
        scaler = RelativeScaler(FULL_FEATURE_COLS)
        prep = evaluation.EvalPreprocessing(
            "relative", scaler, list(FULL_FEATURE_COLS), None, {}, None, list(scaler.feature_cols_out)
        )
        evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 53, "seq_len": 60}, 60, None)
        with self.assertRaisesRegex(ValueError, "feature schema"):
            evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 69, "seq_len": 60}, 60, None)

    def test_relative_requires_relative_scaler(self):
        prep = evaluation.EvalPreprocessing(
            "relative", object(), list(FULL_FEATURE_COLS), None, {}, None, list(FULL_FEATURE_COLS_OUT)
        )
        with self.assertRaisesRegex(ValueError, "relative"):
            evaluation.validate_preprocessing_dimensions(prep, {"featurenum": 53, "seq_len": 60}, 60, None)


class TestScalerPathResolution(unittest.TestCase):
    def test_rolling_default_scope_path_is_e5(self):
        path = evaluation.resolve_scaler_path({"preprocessing": {"mode": "rolling"}}, "rolling")
        self.assertEqual(path, "logs/rolling_e5/scaler_rolling_e5.pkl")

    def test_relative_has_no_scaler_path(self):
        self.assertIsNone(evaluation.resolve_scaler_path({"preprocessing": {"mode": "relative"}}, "relative"))

    def test_metadata_state_path_beats_default(self):
        run_cfg = {"preprocessing": {"mode": "rolling", "state_path": "custom/state.pkl"}}
        self.assertEqual(evaluation.resolve_scaler_path(run_cfg, "rolling"), "custom/state.pkl")


class TestBuildValLoader(unittest.TestCase):
    def test_loader_relative_passes_stateless_scaler(self):
        args = SimpleNamespace(
            parquet="x", seq_len=60, horizon=5, batch_size=2, num_workers=0, max_codes=0,
            max_windows_per_code=None, val_start=None, val_end=None, feature_cols=None,
            scaler_path=None, allow_fit_scaler=False,
        )
        scaler = RelativeScaler(FULL_FEATURE_COLS)
        prep = evaluation.EvalPreprocessing(
            "relative", scaler, list(FULL_FEATURE_COLS), None, {}, None, list(scaler.feature_cols_out)
        )
        with patch.object(evaluation, "ParquetDataset") as dataset:
            dataset.return_value.num_features = 53
            evaluation.build_val_loader(args, prep)
            cfg = dataset.call_args.args[0]
            self.assertEqual(cfg.role, "evaluation")
            self.assertEqual(cfg.normalize, "relative")
            self.assertIs(dataset.call_args.kwargs["scaler_stats"], scaler)


class TestRunEvalPipelineResolution(unittest.TestCase):
    def test_mode_relative_and_default_scope_e5(self):
        mode, scope = pipeline.resolve_eval_mode_scope({"preprocessing": {"mode": "relative"}})
        self.assertEqual(mode, "relative")
        self.assertIsNone(scope)
        _, scope = pipeline.resolve_eval_mode_scope({"preprocessing": {"mode": "rolling"}})
        self.assertEqual(scope, "e5")

    def test_cli_scope_e0_e5_and_invalid(self):
        run_cfg = {"preprocessing": {"mode": "rolling", "scope": "e0"}}
        self.assertEqual(pipeline.resolve_eval_mode_scope(run_cfg, "e0")[1], "e0")
        with self.assertRaisesRegex(ValueError, "scope"):
            pipeline.resolve_eval_mode_scope(run_cfg, "e5")
        with self.assertRaisesRegex(ValueError, "scope"):
            pipeline.resolve_eval_mode_scope(run_cfg, "e9")

    def test_relative_scaler_path_is_none(self):
        self.assertIsNone(pipeline.resolve_eval_scaler_path({"preprocessing": {"mode": "relative"}}))

    def test_invalid_mode_rejected(self):
        with self.assertRaisesRegex(ValueError, "mode"):
            pipeline.resolve_eval_mode_scope({"preprocessing": {"mode": "none"}})

    def test_pipeline_featurenum_resolution(self):
        self.assertEqual(pipeline.resolve_eval_featurenum({"preprocessing": {"featurenum": 53}}), 53)


if __name__ == "__main__":
    unittest.main()
