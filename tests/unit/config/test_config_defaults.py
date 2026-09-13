"""共享默认配置的隔离契约。"""
import unittest

import train
from config.defaults import make_default_config


class TestConfigDefaults(unittest.TestCase):
    def test_each_call_has_independent_nested_values(self):
        first = make_default_config()
        second = make_default_config(dual_head=True)

        first["BINS"].append(99.0)
        first["EMLossConfig"]["p"] = 7
        first["CNNTransformerConfig"]["cnn_kernel_sizes"].append(11)

        self.assertTrue(second["DUAL_HEAD"])
        self.assertEqual(len(second["BINS"]), 51)
        self.assertEqual(second["EMLossConfig"]["p"], 2)
        self.assertEqual(second["CNNTransformerConfig"]["cnn_kernel_sizes"], [1, 3, 5, 7, 10])

    def test_model_class_count_tracks_bins(self):
        config = make_default_config()
        self.assertEqual(config["num_classes"], len(config["BINS"]) + 1)
        self.assertEqual(config["CNNTransformerConfig"]["num_classes"], 52)


class TestConfigCacheDefaults(unittest.TestCase):
    """T03: 训练入口默认开启缓存的配置键与隔离契约。"""

    def test_default_config_cache_keys(self):
        config = make_default_config()
        self.assertIs(config["CACHE_ENABLED"], True)
        self.assertIsNone(config["CACHE_DIR"])
        self.assertIs(config["REBUILD_CACHE"], False)

    def test_cache_keys_are_isolated_between_calls(self):
        first = make_default_config()
        second = make_default_config()
        first["CACHE_ENABLED"] = False
        first["CACHE_DIR"] = "/tmp/other"
        first["REBUILD_CACHE"] = True
        self.assertIs(second["CACHE_ENABLED"], True)
        self.assertIsNone(second["CACHE_DIR"])
        self.assertIs(second["REBUILD_CACHE"], False)


class TestTrainCacheArgs(unittest.TestCase):
    """T03: train.py CLI -> CACHE_* 装配透传。"""

    def test_default_cache_settings_enable_cache(self):
        settings = train.build_cache_settings(train.parse_args([]))
        self.assertIs(settings["CACHE_ENABLED"], True)
        self.assertIsNone(settings["CACHE_DIR"])
        self.assertIs(settings["REBUILD_CACHE"], False)

    def test_no_cache_flag_disables_cache(self):
        args = train.parse_args(["--no_cache"])
        settings = train.build_cache_settings(args)
        self.assertIs(settings["CACHE_ENABLED"], False)

    def test_cache_dir_and_rebuild_flags_pass_through(self):
        args = train.parse_args(["--cache_dir", "D:/tmp/cache", "--rebuild_cache"])
        settings = train.build_cache_settings(args)
        self.assertEqual(settings["CACHE_DIR"], "D:/tmp/cache")
        self.assertIs(settings["REBUILD_CACHE"], True)
        self.assertIs(settings["CACHE_ENABLED"], True)


if __name__ == "__main__":
    unittest.main()
