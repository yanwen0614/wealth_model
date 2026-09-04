"""T03 RED: DualLoss = EMD + lambda*Huber numeric composition."""
import unittest

import torch
from torch import nn

from criterion.dual_loss import DualLoss
from criterion.emd_loss import EMDLoss


class TestDualLoss(unittest.TestCase):
    def test_total_equals_emd_plus_lambda_huber(self):
        torch.manual_seed(0)
        loss_fn = DualLoss(num_classes=52, p=2, label_smoothing=True,
                           smooth_eps=0.1, lambda_reg=0.2, huber_delta=1.0)
        logits = torch.randn(4, 52, requires_grad=True)
        ret_pred = torch.randn(4, requires_grad=True)
        y_cls = torch.randint(0, 52, (4,))
        y_ret = torch.randn(4)
        total, emd_part, huber_part = loss_fn(logits, ret_pred, y_cls, y_ret)
        emd_ref = EMDLoss(num_classes=52, p=2, label_smoothing=True,
                          smooth_eps=0.1)(logits.detach(), y_cls)
        huber_ref = nn.HuberLoss(delta=1.0)(ret_pred.detach(), y_ret)
        self.assertAlmostEqual(emd_part.item(), emd_ref.item(), places=5)
        self.assertAlmostEqual(huber_part.item(), huber_ref.item(), places=5)
        self.assertAlmostEqual(total.item(),
                               emd_ref.item() + 0.2 * huber_ref.item(), places=5)
        total.backward()
        self.assertIsNotNone(logits.grad)

    def test_missing_ret_skips_huber(self):
        loss_fn = DualLoss(num_classes=5, p=2, lambda_reg=0.2)
        logits = torch.randn(3, 5)
        y_cls = torch.randint(0, 5, (3,))
        total, emd_part, huber_part = loss_fn(logits, None, y_cls, None)
        self.assertAlmostEqual(total.item(), emd_part.item(), places=6)
        self.assertEqual(huber_part.item(), 0.0)

    def test_legacy_two_arg_call_compat(self):
        loss_fn = DualLoss(num_classes=5, p=2, lambda_reg=0.2)
        logits = torch.randn(3, 5)
        y_cls = torch.randint(0, 5, (3,))
        total, emd_part, huber_part = loss_fn(logits, y_cls)
        self.assertAlmostEqual(total.item(), emd_part.item(), places=6)
        self.assertEqual(huber_part.item(), 0.0)


if __name__ == "__main__":
    unittest.main()
