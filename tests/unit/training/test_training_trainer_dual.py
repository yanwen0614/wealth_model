"""T04 RED: Trainer single/dual-head batch + output unpacking."""
import unittest

import torch

from criterion.dual_loss import DualLoss
from criterion.emd_loss import EMDLoss
from training.trainer import _compute_loss, _unpack_batch, _unpack_outputs


class TestTrainerDualCompat(unittest.TestCase):
    def test_unpack_batch_two_tuple(self):
        data = torch.randn(4, 45, 60)
        y = torch.randint(0, 52, (4,))
        d, yc, yr = _unpack_batch((data, y))
        self.assertIs(d, data)
        self.assertIs(yc, y)
        self.assertIsNone(yr)

    def test_unpack_batch_three_tuple(self):
        data = torch.randn(4, 45, 60)
        y = torch.randint(0, 52, (4,))
        r = torch.randn(4)
        d, yc, yr = _unpack_batch((data, y, r))
        self.assertIs(d, data)
        self.assertIs(yc, y)
        self.assertIs(yr, r)

    def test_unpack_outputs_single_and_tuple(self):
        logits = torch.randn(4, 52)
        out_logits, out_ret = _unpack_outputs(logits)
        self.assertIs(out_logits, logits)
        self.assertIsNone(out_ret)
        ret = torch.randn(4)
        l2, r2 = _unpack_outputs((logits, ret))
        self.assertIs(l2, logits)
        self.assertIs(r2, ret)

    def test_compute_loss_single_head(self):
        crit = EMDLoss(num_classes=52, p=2)
        logits = torch.randn(4, 52)
        y = torch.randint(0, 52, (4,))
        loss = _compute_loss(crit, logits, None, y, None)
        self.assertEqual(loss.dim(), 0)

    def test_compute_loss_dual_head(self):
        crit = DualLoss(num_classes=52, p=2, lambda_reg=0.2)
        logits = torch.randn(4, 52)
        ret = torch.randn(4)
        y = torch.randint(0, 52, (4,))
        r = torch.randn(4)
        loss = _compute_loss(crit, logits, ret, y, r)
        ref = crit(logits, ret, y, r)[0]
        self.assertAlmostEqual(loss.item(), ref.item(), places=6)

    def test_compute_loss_dual_missing_ret(self):
        crit = DualLoss(num_classes=52, p=2, label_smoothing=False, lambda_reg=0.2)
        logits = torch.randn(4, 52)
        y = torch.randint(0, 52, (4,))
        loss = _compute_loss(crit, logits, None, y, None)
        ref = EMDLoss(num_classes=52, p=2, label_smoothing=False)(logits, y)
        self.assertAlmostEqual(loss.item(), ref.item(), places=5)


if __name__ == "__main__":
    unittest.main()
