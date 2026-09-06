"""T01: PureRegLoss = Huber(ret_pred, y_ret), cls head receives no grad."""
import unittest

import torch
from torch import nn

from criterion.pure_reg_loss import PureRegLoss
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer


def _tiny_model():
    cfg = ModelConfig(featurenum=10, seq_len=20, num_classes=52, cnn_out_channels=8,
                      d_model=32, nhead=4, cnn_kernel_sizes=[1, 3],
                      num_encoder_layers=1, dropout_rate=0.0)
    return CNNTransformer(cfg)


class TestPureRegLoss(unittest.TestCase):
    def test_value_equals_huber(self):
        torch.manual_seed(0)
        loss_fn = PureRegLoss(num_classes=52, huber_delta=1.0)
        logits = torch.randn(4, 52)
        ret_pred = torch.randn(4, requires_grad=True)
        y_cls = torch.randint(0, 52, (4,))
        y_ret = torch.randn(4)
        total, reg_part, cls_part = loss_fn(logits, ret_pred, y_cls, y_ret)
        ref = nn.HuberLoss(delta=1.0)(ret_pred.detach(), y_ret)
        self.assertAlmostEqual(reg_part.item(), ref.item(), places=5)
        self.assertAlmostEqual(total.item(), ref.item(), places=5)
        self.assertEqual(cls_part.item(), 0.0)

    def test_missing_ret_degenerates_to_zeros(self):
        loss_fn = PureRegLoss(num_classes=52, huber_delta=1.0)
        logits = torch.randn(3, 52)
        y_cls = torch.randint(0, 52, (3,))
        parts = loss_fn(logits, None, y_cls, None)
        self.assertIsInstance(parts, tuple)
        for p in parts:
            self.assertIsInstance(p, torch.Tensor)
            self.assertEqual(p.item(), 0.0)

    def test_is_dual_head_and_four_arg_scalar(self):
        loss_fn = PureRegLoss(num_classes=52, huber_delta=1.0)
        self.assertIs(getattr(loss_fn, "is_dual_head", False), True)
        logits = torch.randn(2, 52)
        out = loss_fn(logits, torch.randn(2), torch.randint(0, 52, (2,)), torch.randn(2))
        self.assertIsInstance(out, tuple)
        self.assertIsInstance(out[0], torch.Tensor)
        self.assertEqual(out[0].dim(), 0)

    def test_grad_isolated_from_logits(self):
        loss_fn = PureRegLoss(num_classes=52, huber_delta=1.0)
        logits = torch.randn(4, 52, requires_grad=True)
        ret_pred = torch.randn(4, requires_grad=True)
        y_ret = torch.randn(4)
        total = loss_fn(logits, ret_pred, None, y_ret)[0]
        total.backward()
        self.assertIsNone(logits.grad)
        self.assertIsNotNone(ret_pred.grad)

    def test_model_forward_shapes_and_grad_path(self):
        torch.manual_seed(1)
        model = _tiny_model()
        loss_fn = PureRegLoss(num_classes=52, huber_delta=1.0)
        x = torch.randn(2, 10, 20)
        y_ret = torch.randn(2)
        logits, ret_pred = model(x)
        self.assertEqual(tuple(logits.shape), (2, 52))
        self.assertEqual(tuple(ret_pred.shape), (2,))
        total = loss_fn(logits, ret_pred, None, y_ret)[0]
        ret_pred.retain_grad()
        total.backward()
        self.assertIsNone(logits.grad)
        self.assertIsNotNone(ret_pred.grad)
        for p in model.fc_cls.parameters():
            self.assertIsNone(p.grad)


if __name__ == "__main__":
    unittest.main()
