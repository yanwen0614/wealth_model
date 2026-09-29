"""T09 config统一：BINS派生CENTERS契约（方案A漂移声明）。

方案A漂移声明（用户已确认允许一次可解释漂移）：
旧 eval 硬编码 CENTERS52=linspace(-0.255,0.255,52)（步长 0.01）与训练
BINS=linspace(-0.38,0.38,51)（步长 0.0152）不一致，属口径断裂。本模块以
BINS 经 bins_to_centers 派生 CENTERS（内部中点+两尾外推半步，共52中心），
新中心=linspace(-0.3876,0.3876,52)（步长 0.0152），即旧向量精确 1.52 倍线性
缩放（BINS 边界比 0.38/0.255≈1.49，中心比 0.3876/0.255=1.52；任务描述取~1.49
为边界口径近似值）。排序不变（单调线性缩放），仅 exp_ret 绝对阈值需重审。
"""
import json
import unittest

import numpy as np

from config.defaults import DEFAULT_BINS, DEFAULT_CENTERS, bins_to_centers


class TestBinsToCentersLength(unittest.TestCase):
    def test_len_bins_plus_one_equals_centers(self):
        self.assertEqual(len(DEFAULT_BINS), 51)
        self.assertEqual(len(DEFAULT_CENTERS), 52)
        self.assertEqual(len(DEFAULT_BINS) + 1, len(DEFAULT_CENTERS))

    def test_num_classes_chain(self):
        from config.defaults import make_default_config

        cfg = make_default_config()
        self.assertEqual(len(cfg["BINS"]) + 1, cfg["num_classes"])
        self.assertEqual(cfg["num_classes"], len(DEFAULT_CENTERS))
        self.assertEqual(cfg["CNNTransformerConfig"]["num_classes"], 52)


class TestBinsToCentersVector(unittest.TestCase):
    def test_derived_vector_locked(self):
        centers = bins_to_centers(DEFAULT_BINS)
        self.assertEqual(len(centers), 52)
        # 两尾外推半步锁定（BINS 步长 0.0152，半步 0.0076）
        self.assertAlmostEqual(centers[0], -0.3876, places=12)
        self.assertAlmostEqual(centers[-1], 0.3876, places=12)
        # 内部中点锁定
        self.assertAlmostEqual(centers[1], (-0.38 + -0.3648) / 2, places=12)
        # 确定性：json 往返稳定
        self.assertEqual(json.loads(json.dumps(centers)), centers)
        self.assertEqual(centers, list(DEFAULT_CENTERS))


class TestDriftDeclaration(unittest.TestCase):
    """方案A漂移显式声明：旧±0.255≠新值，排序不变，仅绝对阈值重审。"""

    def test_old_hardcode_differs_from_derived(self):
        old = np.linspace(-0.255, 0.255, 52)
        new = np.asarray(DEFAULT_CENTERS, dtype=np.float64)
        self.assertEqual(len(old), len(new))
        # 旧值≠新值（漂移真实存在，非静默一致）
        self.assertFalse(np.allclose(old, new))
        # 精确 1.52 倍线性缩放（旧步长 0.01→新步长 0.0152）
        np.testing.assert_allclose(new, old * 1.52, rtol=1e-12, atol=1e-12)

    def test_order_preserved(self):
        old = np.linspace(-0.255, 0.255, 52)
        new = np.asarray(DEFAULT_CENTERS, dtype=np.float64)
        self.assertEqual(list(np.argsort(old)), list(np.argsort(new)))
        # exp_ret 排序不变：任意 probs 下新旧 exp_ret 均为正线性关系
        rng = np.random.RandomState(42)
        probs = rng.dirichlet(np.ones(52), size=8)
        old_exp = (probs * old).sum(axis=1)
        new_exp = (probs * new).sum(axis=1)
        np.testing.assert_allclose(new_exp, old_exp * 1.52, rtol=1e-12, atol=1e-12)
        self.assertEqual(list(np.argsort(old_exp)), list(np.argsort(new_exp)))

    def test_bins_to_centers_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            bins_to_centers([0.1])
        with self.assertRaises(ValueError):
            bins_to_centers([0.2, 0.1, 0.3])


class TestFeeCentralization(unittest.TestCase):
    def test_default_fees_mirror_unified(self):
        from backtest.cnn_adapter.common import UNIFIED_FEES
        from config.defaults import DEFAULT_FEES

        self.assertEqual(dict(DEFAULT_FEES), dict(UNIFIED_FEES))

    def test_old_engine_frozen_untouched(self):
        from backtest import engine as old_engine

        self.assertAlmostEqual(old_engine.BUY_COMMISSION_RATE, 0.00025)
        self.assertAlmostEqual(old_engine.SELL_COMMISSION_RATE, 0.00025)
        self.assertAlmostEqual(old_engine.STAMP_DUTY_RATE, 0.00025)


if __name__ == "__main__":
    unittest.main()
