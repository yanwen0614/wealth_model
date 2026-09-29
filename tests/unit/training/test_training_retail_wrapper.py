"""T13 RED: train_retail thin wrapper + train.py reusable helpers (zero behavior change)."""
import os
import unittest


class TestTrainReusableHelpersExist(unittest.TestCase):
    def test_train_exports_apply_args_and_parquet_helper(self):
        import train as train_main

        self.assertTrue(callable(getattr(train_main, "apply_args_to_config", None)),
                        "train.apply_args_to_config 缺失（T13 复用出口）")
        self.assertTrue(callable(getattr(train_main, "build_parquet_data_config", None)),
                        "train.build_parquet_data_config 缺失（T13 复用出口）")

    def test_retail_wrapper_is_thin(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "train_retail.py")
        path = os.path.abspath(path)
        with open(path, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        self.assertLess(n, 120, f"train_retail.py 仍 {n} 行，需 <120（T13）")


class TestRetailCliCompat(unittest.TestCase):
    def test_retail_help_params_not_missing(self):
        import train_retail as retail

        args = retail.parse_args([])
        for key in ("gamma_neg", "lambda_reg", "default_threshold",
                    "target_precision", "normalize", "rolling_scope",
                    "smoke", "max_codes", "feature_cols", "featurenum",
                    "cache_dir", "no_cache", "rebuild_cache"):
            self.assertTrue(hasattr(args, key), f"retail CLI 参数缺失: --{key}")

    def test_retail_defaults_preserved(self):
        import train_retail as retail

        args = retail.parse_args([])
        self.assertAlmostEqual(float(args.lambda_reg), 0.3)
        self.assertAlmostEqual(float(args.default_threshold), 0.65)
        self.assertAlmostEqual(float(args.target_precision), 0.75)
        self.assertAlmostEqual(float(args.gamma_neg), 4.0)


class TestApplyArgsRetailNamespace(unittest.TestCase):
    def test_retail_config_uses_isolated_dirs_and_model(self):
        import train as train_main

        args = train_main.parse_args([], retail=True)
        cfg: dict = {}
        train_main.apply_args_to_config(cfg, args, retail=True)
        self.assertEqual(cfg["MODEL"], "retail_friendly")
        self.assertIn("retail", cfg["LOG_DIR"])
        self.assertAlmostEqual(float(cfg["RETAIL_LAMBDA_REG"]), 0.3)
        self.assertAlmostEqual(float(cfg["RETAIL_DEFAULT_THRESHOLD"]), 0.65)
        self.assertIn("RETAIL_GAMMA_NEG", cfg)

    def test_main_config_stays_cnn_by_default(self):
        import train as train_main

        args = train_main.parse_args([])
        cfg: dict = {}
        train_main.apply_args_to_config(cfg, args)
        self.assertEqual(cfg["MODEL"], "cnn_transformer")
        self.assertNotIn("retail", cfg["LOG_DIR"])

    def test_parquet_helper_passthrough(self):
        import train as train_main
        from config.defaults import make_default_config

        cfg = make_default_config()
        cfg["LABEL_MODE"] = "absolute"
        pc = train_main.build_parquet_data_config(cfg)
        self.assertEqual(pc.seq_len, cfg["SEQ_LEN"])
        self.assertEqual(pc.normalize, cfg["NORMALIZE"])
        self.assertFalse(pc.cs_rank)
        self.assertFalse(pc.mkt_factors)


class TestRetailFactoryDelegation(unittest.TestCase):
    def test_factory_retail_matches_direct(self):
        import train_retail as retail
        from config.defaults import make_default_config
        from models.retail_friendly.model import RetailFriendlyModel
        from training.factory import build_criterion, build_model

        args = retail.parse_args([])
        cfg = make_default_config()
        import train as train_main

        train_main.apply_args_to_config(cfg, args, retail=True)
        model, _ = build_model(cfg, actual_featurenum=53, mode="retail_friendly")
        self.assertIsInstance(model, RetailFriendlyModel)
        crit = build_criterion(cfg, mode="retail_friendly")
        self.assertTrue(hasattr(crit, "bce"))
        from typing import Any, cast

        self.assertAlmostEqual(float(cast(Any, crit).pos_weight), 2.0)


class TestRetailArtifactsContract(unittest.TestCase):
    def test_three_files_with_expected_keys(self):
        import tempfile

        import train_retail as retail

        tmp = tempfile.mkdtemp()
        hist = {"train_losses": [0.5], "val_losses": [0.4], "val_precisions": [0.8],
                "val_f1s": [0.7], "calibrated_threshold": 0.65,
                "calibration_report": {"precision": 0.8, "threshold": 0.65}}
        cfg = {"NORMALIZE": "relative", "EPOCHS": 1, "BATCH_SIZE": 256,
               "LEARNING_RATE": 3e-4, "MAX_CODES": 20}
        args = retail.parse_args([])
        retail.save_retail_artifacts(tmp, hist, cfg, args, 53)
        import json
        import os

        for name in ("calibration_report.json", "final_metrics.json", "inference_config.json"):
            self.assertTrue(os.path.exists(os.path.join(tmp, name)), name)
        with open(os.path.join(tmp, "final_metrics.json"), encoding="utf-8") as f:
            fm = json.load(f)
        for key in ("calibrated_threshold", "calibration", "final_train_loss",
                    "final_val_precision", "config"):
            self.assertIn(key, fm)
        self.assertEqual(fm["config"]["featurenum"], 53)


if __name__ == "__main__":
    unittest.main()
