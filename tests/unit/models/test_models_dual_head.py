"""T02 RED: CNNTransformer dual-head forward -> (logits[B,52], ret_pred[B])."""
import unittest

import torch

from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer


class TestDualHead(unittest.TestCase):
    def test_forward_tuple_shapes(self):
        cfg = ModelConfig(featurenum=45, seq_len=60, num_classes=52,
                          d_model=32, nhead=4, num_encoder_layers=1,
                          cnn_out_channels=16, cnn_kernel_sizes=[1, 3, 5])
        model = CNNTransformer(cfg).eval()
        x = torch.randn(2, 45, 60)
        with torch.no_grad():
            out = model(x)
        self.assertIsInstance(out, tuple, "forward must return tuple")
        self.assertEqual(len(out), 2)
        logits, ret_pred = out
        self.assertEqual(tuple(logits.shape), (2, 52))
        self.assertEqual(tuple(ret_pred.shape), (2,))
        # 旧契约: out[0] 即 [B,52] logits
        self.assertEqual(tuple(out[0].shape), (2, 52))

    def test_heads_share_and_differ(self):
        cfg = ModelConfig(featurenum=45, seq_len=60, num_classes=52,
                          d_model=32, nhead=4, num_encoder_layers=1,
                          cnn_out_channels=16, cnn_kernel_sizes=[1, 3, 5])
        model = CNNTransformer(cfg)
        self.assertTrue(hasattr(model, "fc_cls"))
        self.assertTrue(hasattr(model, "fc_reg"))


if __name__ == "__main__":
    unittest.main()
