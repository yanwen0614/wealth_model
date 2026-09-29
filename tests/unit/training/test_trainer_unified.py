"""T12 RED: 统一 Trainer 零售能力 + factory mode 参数 + validate dict 兼容解包。"""
import os
import tempfile
import unittest
from typing import Any, cast

import torch

from training.factory import build_criterion, build_model
from training.trainer import Trainer


def _loader(n=16, f=8, t=32, ncls=52, retail=False):
    data = torch.randn(n, f, t)
    y = torch.randint(0, ncls, (n,))
    if retail:
        r = torch.randn(n)
        ds = torch.utils.data.TensorDataset(data, y, r)
    else:
        ds = torch.utils.data.TensorDataset(data, y)
    return torch.utils.data.DataLoader(ds, batch_size=8)


class TestTrainerUnified(unittest.TestCase):
    def test_binarize_labels_prefers_y_ret(self):
        y_cls = torch.tensor([0, 51])
        y_ret = torch.tensor([0.05, -0.02])
        out = Trainer.binarize_labels(y_cls, y_ret)
        self.assertEqual(out.tolist(), [1.0, 0.0])

    def test_binarize_labels_falls_back_to_half(self):
        y_cls = torch.tensor([25, 26])
        out = Trainer.binarize_labels(y_cls, None)
        self.assertEqual(out.tolist(), [0.0, 1.0])

    def test_validate_epoch_dict_with_tuple_unpack(self):
        model = torch.nn.Sequential(torch.nn.Flatten(), torch.nn.Linear(8 * 32, 52))
        crit = torch.nn.CrossEntropyLoss()
        tmp = tempfile.mkdtemp()
        tr = Trainer(model, {"run_log_dir": tmp, "DEVICE": "cpu"},
                     _loader(), cast(Any, _loader()), crit, None)
        res = tr.validate_epoch()
        self.assertIsInstance(res, dict)
        self.assertIn("loss", res)
        loss, acc, labels, preds = res  # 兼容旧 tuple 解包
        self.assertEqual(res["loss"], loss)
        self.assertEqual(res["accuracy"], acc)
        self.assertEqual(labels.shape[0], 16)
        self.assertEqual(preds.shape[0], 16)

    def test_validate_epoch_retail_dict(self):
        from models.retail_friendly.config import RetailModelConfig
        from models.retail_friendly.loss import RetailLoss
        from models.retail_friendly.model import RetailFriendlyModel
        cfg = RetailModelConfig(featurenum=8, seq_len=32)
        model = RetailFriendlyModel(cfg)
        crit = RetailLoss()
        tmp = tempfile.mkdtemp()
        tr = Trainer(model, {"run_log_dir": tmp, "DEVICE": "cpu", "MODEL": "retail_friendly"},
                     _loader(retail=True), cast(Any, _loader(retail=True)), crit, None)
        res = tr.validate_epoch()
        self.assertIn("precision", res)
        loss, acc, labels, preds = res
        self.assertEqual(res["loss"], loss)
        self.assertGreaterEqual(acc, 0.0)
        self.assertEqual(preds.shape[0], labels.shape[0])
        self.assertTrue(os.path.exists(os.path.join(tmp, "epoch_metrics.csv")))

    def test_factory_mode_param_builds_retail(self):
        from models.retail_friendly.loss import RetailLoss
        from models.retail_friendly.model import RetailFriendlyModel
        cfg = {"DEVICE": "cpu", "SEQ_LEN": 32, "FEATURENUM": 8,
               "CNNTransformerConfig": {"dropout_rate": 0.3}}
        model, _ = build_model(cfg, actual_featurenum=8, mode="retail_friendly")
        self.assertIsInstance(model, RetailFriendlyModel)
        crit = build_criterion(cfg, mode="retail_friendly")
        self.assertIsInstance(crit, RetailLoss)

    def test_forward_interfaces(self):
        from models.retail_friendly.config import RetailModelConfig
        from models.retail_friendly.model import RetailFriendlyModel
        m = RetailFriendlyModel(RetailModelConfig(featurenum=8, seq_len=32))
        bin_l, ret = m(torch.randn(4, 8, 32))
        self.assertEqual(tuple(bin_l.shape), (4,))
        self.assertEqual(tuple(ret.shape), (4,))


if __name__ == "__main__":
    unittest.main()
