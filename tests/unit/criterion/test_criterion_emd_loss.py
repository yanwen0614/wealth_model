"""T01 RED: EMDLoss P0 device-migration regression (52-class default)."""
import unittest

import torch
import torch.nn.functional as F

from criterion.emd_loss import EMDLoss


class TestEMDLossP0(unittest.TestCase):
    def test_forward_shape_scalar_52(self):
        loss_fn = EMDLoss(num_classes=52, p=2, label_smoothing=True, smooth_eps=0.1)
        logits = torch.randn(4, 52, requires_grad=True)
        labels = torch.randint(0, 52, (4,))
        loss = loss_fn(logits, labels)
        self.assertEqual(loss.dim(), 0)
        loss.backward()
        self.assertIsNotNone(logits.grad)

    def test_smooth_weights_is_register_buffer(self):
        loss_fn = EMDLoss(num_classes=52, p=2, label_smoothing=True, smooth_eps=0.1)
        self.assertIn("smooth_weights", dict(loss_fn.named_buffers()))

    def test_no_custom_to_override(self):
        self.assertNotIn("to", EMDLoss.__dict__)

    def test_to_cpu_keeps_buffer_device(self):
        loss_fn = EMDLoss(num_classes=52, p=2, label_smoothing=True, smooth_eps=0.1)
        out = loss_fn.to("cpu")
        self.assertIs(out, loss_fn)
        buf = dict(loss_fn.named_buffers())["smooth_weights"]
        self.assertEqual(buf.device.type, "cpu")

    def test_softmax_cumsum_semantics(self):
        loss_fn = EMDLoss(num_classes=5, p=2, label_smoothing=False)
        logits = torch.tensor([[5.0, 1.0, 0.0, 0.0, 0.0]])
        targets = torch.tensor([0])
        probs = F.softmax(logits, dim=1)
        pred_cdf = torch.cumsum(probs, dim=1)
        target_cdf = torch.cumsum(F.one_hot(targets, num_classes=5).float(), dim=1)
        expected = torch.mean(torch.pow(pred_cdf - target_cdf, 2))
        self.assertAlmostEqual(loss_fn(logits, targets).item(), expected.item(), places=6)


if __name__ == "__main__":
    unittest.main()
