"""训练模型、损失和调度器工厂契约。"""
import unittest

from config.defaults import make_default_config
from criterion.dual_loss import DualLoss
from criterion.emd_loss import EMDLoss
from criterion.pure_reg_loss import PureRegLoss
from training.factory import build_criterion


class TestTrainingFactory(unittest.TestCase):
    def test_builds_three_loss_modes(self):
        baseline = make_default_config()
        self.assertIsInstance(build_criterion(baseline), EMDLoss)

        dual = make_default_config(dual_head=True)
        self.assertIsInstance(build_criterion(dual), DualLoss)

        pure_reg = make_default_config()
        pure_reg["PURE_REG"] = True
        self.assertIsInstance(build_criterion(pure_reg), PureRegLoss)


if __name__ == "__main__":
    unittest.main()
