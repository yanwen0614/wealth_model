import unittest
from typing import cast

import torch

from models.daily_continuous_policy import DailyContinuousPolicy, target_weights


class DailyContinuousPolicyTests(unittest.TestCase):
    def test_policy_accepts_batch_and_single_sample_shapes(self):
        policy = DailyContinuousPolicy()
        batch = torch.randn(2, 1000, 50)

        alpha_logits, trade_gate = policy(batch)

        self.assertEqual(alpha_logits.shape, (2, 1000))
        self.assertEqual(trade_gate.shape, (2, 1000))
        single_alpha, single_gate = policy(batch[0])
        self.assertEqual(single_alpha.shape, (1000,))
        self.assertEqual(single_gate.shape, (1000,))

    def test_policy_gate_is_bounded_and_padding_gate_is_zero(self):
        policy = DailyContinuousPolicy()
        inputs = torch.randn(2, 1000, 50)
        valid_mask = torch.ones(2, 1000, dtype=torch.bool)
        valid_mask[:, 900:] = False

        alpha_logits, trade_gate = policy(inputs, valid_mask=valid_mask)

        self.assertTrue(torch.all((trade_gate >= 0) & (trade_gate <= 1)))
        self.assertTrue(torch.equal(trade_gate[:, 900:], torch.zeros(2, 100)))
        self.assertTrue(torch.isfinite(alpha_logits).all())

    def test_policy_output_is_differentiable(self):
        policy = DailyContinuousPolicy()
        inputs = torch.randn(1, 1000, 50, requires_grad=True)

        alpha_logits, trade_gate = policy(inputs)
        (alpha_logits.square().mean() + trade_gate.mean()).backward()

        self.assertIsNotNone(inputs.grad)
        self.assertTrue(torch.isfinite(cast(torch.Tensor, inputs.grad)).all())
        self.assertTrue(any(parameter.grad is not None for parameter in policy.parameters()))

    def test_target_weights_interpolate_current_and_alpha_portfolios(self):
        logits = torch.tensor([2.0, 0.0, -1.0])
        current = torch.tensor([0.2, 0.3, 0.5])

        unchanged = target_weights(logits, torch.zeros(3), current)
        replaced = target_weights(logits, torch.ones(3), current)
        expected = torch.softmax(logits, dim=-1)

        self.assertTrue(torch.allclose(unchanged, current))
        self.assertTrue(torch.allclose(replaced, expected))
        self.assertTrue(torch.all(replaced >= 0))
        self.assertTrue(torch.isclose(replaced.sum(), torch.tensor(1.0)))

    def test_target_weights_masks_padding_and_stays_differentiable(self):
        logits = torch.tensor([1.0, 0.0, -2.0, 100.0], requires_grad=True)
        gate = torch.tensor([1.0, 0.5, 0.0, 1.0], requires_grad=True)
        current = torch.tensor([0.4, 0.3, 0.3, 0.0])
        valid_mask = torch.tensor([True, True, True, False])

        weights = target_weights(logits, gate, current, valid_mask=valid_mask)
        weights.sum().backward()

        self.assertTrue(torch.allclose(weights[-1], torch.tensor(0.0)))
        self.assertTrue(torch.isclose(weights.sum(), torch.tensor(1.0)))
        self.assertTrue(torch.all(weights >= 0))
        self.assertTrue(torch.isfinite(cast(torch.Tensor, logits.grad)).all())
        self.assertTrue(torch.isfinite(cast(torch.Tensor, gate.grad)).all())

    def test_target_weights_returns_zero_for_all_invalid_cash_state(self):
        logits = torch.tensor([[1.0, 0.0, -2.0], [4.0, 3.0, 2.0]])
        gate = torch.tensor([[1.0, 0.5, 0.0], [0.2, 0.4, 0.6]])
        current = torch.tensor([[0.4, 0.3, 0.3], [0.1, 0.2, 0.7]])
        valid_mask = torch.zeros_like(logits, dtype=torch.bool)

        weights = target_weights(logits, gate, current, valid_mask=valid_mask)

        self.assertEqual(weights.shape, logits.shape)
        self.assertTrue(torch.equal(weights, torch.zeros_like(logits)))
        self.assertTrue(torch.isfinite(weights).all())


if __name__ == "__main__":
    unittest.main()
