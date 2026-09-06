"""共享默认配置的隔离契约。"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
