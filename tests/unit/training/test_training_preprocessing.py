"""training.preprocessing 统一装配契约（T08）。

覆盖：三入口矩阵一致 / eval 同 ckpt 同 scaler /
relative 无 state / per_code 复用 / rolling 异 scope 拒绝 /
multi_seed e4 显式对齐（禁静默默认）。
"""
import unittest

from training.preprocessing import (
    DEFAULT_ROLLING_SCOPE,
    PER_CODE_DEFAULT_SCALER_PATH,
    ROLLING_DEFAULT_SCALER_PATH,
    ROLLING_SCOPES,
    configure_preprocessing,
    default_scaler_path,
    resolve_eval_featurenum,
    resolve_eval_mode_scope,
    resolve_eval_scaler_path,
)


class TestConfigurePreprocessingMatrix(unittest.TestCase):
    def test_relative_is_stateless_and_isolated(self):
        cfg: dict = {}
        configure_preprocessing(cfg, "relative")
        self.assertEqual(cfg["NORMALIZE"], "relative")
        self.assertIsNone(cfg["SCALER_PATH"])
        self.assertEqual(cfg["LOG_DIR"], "./logs/relative")

    def test_per_code_reuses_single_path(self):
        cfg: dict = {}
        configure_preprocessing(cfg, "per_code")
        self.assertEqual(cfg["SCALER_PATH"], "logs/scaler_per_code.pkl")
        self.assertEqual(cfg["LOG_DIR"], "./logs")

    def test_rolling_scopes_are_isolated_e0_e5(self):
        self.assertEqual(DEFAULT_ROLLING_SCOPE, "e5")
        paths = set()
        for scope in ROLLING_SCOPES:
            cfg: dict = {}
            configure_preprocessing(cfg, "rolling", scope)
            self.assertIn(scope, cfg["SCALER_PATH"])
            self.assertIn(scope, cfg["LOG_DIR"])
            self.assertEqual(cfg["ROLLING_SCOPE"], scope)
            paths.add((cfg["SCALER_PATH"], cfg["LOG_DIR"]))
        self.assertEqual(len(paths), 6)

    def test_default_scope_is_e5_not_silent_e4(self):
        cfg: dict = {}
        configure_preprocessing(cfg, "rolling")
        self.assertEqual(cfg["ROLLING_SCOPE"], "e5")
        self.assertEqual(cfg["SCALER_PATH"], "logs/rolling_e5/scaler_rolling_e5.pkl")
        e4: dict = {}
        configure_preprocessing(e4, "rolling", "e4")
        self.assertNotEqual(cfg["SCALER_PATH"], e4["SCALER_PATH"])
        self.assertIn("rolling_e4", e4["SCALER_PATH"])

    def test_retail_namespace_is_isolated(self):
        cfg: dict = {}
        configure_preprocessing(cfg, "per_code", retail=True)
        self.assertEqual(cfg["LOG_DIR"], "./logs/retail_per_code")
        cfg2: dict = {}
        configure_preprocessing(cfg2, "rolling", "e5", retail=True)
        self.assertEqual(cfg2["LOG_DIR"], "./logs/retail_rolling_e5")
        cfg3: dict = {}
        configure_preprocessing(cfg3, "relative", retail=True)
        self.assertEqual(cfg3["LOG_DIR"], "./logs/retail_relative")

    def test_unknown_normalize_and_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "normalize"):
            configure_preprocessing({}, "bogus")
        with self.assertRaisesRegex(ValueError, "rolling_scope"):
            configure_preprocessing({}, "rolling", "e9")


class TestEvalResolution(unittest.TestCase):
    def test_default_scaler_paths(self):
        self.assertIsNone(default_scaler_path("relative"))
        self.assertEqual(default_scaler_path("rolling"), ROLLING_DEFAULT_SCALER_PATH)
        self.assertEqual(default_scaler_path("per_code"), PER_CODE_DEFAULT_SCALER_PATH)

    def test_same_ckpt_same_scaler_priority(self):
        run_cfg = {
            "SCALER_PATH": "/top/level.pkl",
            "preprocessing": {"mode": "rolling", "state_path": "custom/state.pkl"},
        }
        self.assertEqual(resolve_eval_scaler_path(run_cfg, "rolling"), "custom/state.pkl")
        self.assertEqual(
            resolve_eval_scaler_path(run_cfg, "rolling", cli_override="/cli/x.pkl"),
            "/cli/x.pkl",
        )
        self.assertIsNone(resolve_eval_scaler_path({"preprocessing": {"mode": "relative"}}))
        # CLI 可显式覆盖 relative（调试透传），其余情况恒 None
        self.assertEqual(
            resolve_eval_scaler_path({"preprocessing": {"mode": "relative"}}, cli_override="/c.pkl"),
            "/c.pkl",
        )


class TestEvalModeScopeFeaturenum(unittest.TestCase):
    def test_mode_scope_defaults_and_strictness(self):
        mode, scope = resolve_eval_mode_scope({"preprocessing": {"mode": "relative"}})
        self.assertEqual((mode, scope), ("relative", None))
        mode, scope = resolve_eval_mode_scope({"preprocessing": {"mode": "rolling"}})
        self.assertEqual((mode, scope), ("rolling", "e5"))
        mode, scope = resolve_eval_mode_scope(
            {"preprocessing": {"mode": "rolling", "scope": "e0"}}, "e0"
        )
        self.assertEqual(scope, "e0")
        with self.assertRaisesRegex(ValueError, "scope"):
            resolve_eval_mode_scope({"preprocessing": {"mode": "rolling", "scope": "e0"}}, "e5")
        with self.assertRaisesRegex(ValueError, "scope"):
            resolve_eval_mode_scope({"preprocessing": {"mode": "rolling"}}, "e9")
        with self.assertRaisesRegex(ValueError, "mode"):
            resolve_eval_mode_scope({"preprocessing": {"mode": "none"}})

    def test_featurenum_never_silent_45(self):
        with self.assertRaisesRegex(ValueError, "featurenum"):
            resolve_eval_featurenum({})
        with self.assertRaisesRegex(ValueError, "featurenum"):
            resolve_eval_featurenum({"preprocessing": {}})
        self.assertEqual(resolve_eval_featurenum({"preprocessing": {"featurenum": 53}}), 53)
        self.assertEqual(resolve_eval_featurenum({}, 53), 53)
        with self.assertRaisesRegex(ValueError, "featurenum"):
            resolve_eval_featurenum({"preprocessing": {"featurenum": 69}}, 53)
