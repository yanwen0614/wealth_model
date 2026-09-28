"""data.labels 新入口单测：close-close 构建器 + 分位标签 + rank_ic 去重一致性。"""
import unittest

import numpy as np

from data.labels import _future_ret_open_open, future_ret_close_close, quantile_labels, rank_ic


class TestFutureRetCloseClose(unittest.TestCase):
    def test_linear_series_matches_formula(self):
        close = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
        got = future_ret_close_close(close, 5)
        self.assertTrue(np.isnan(got[1:]).all())
        self.assertAlmostEqual(got[0], 15.0 / 10.0 - 1.0)

    def test_horizon_parameterized(self):
        close = np.array([10.0, 11.0, 12.0, 13.0])
        self.assertAlmostEqual(future_ret_close_close(close, 1)[0], 0.1)
        self.assertAlmostEqual(future_ret_close_close(close, 2)[0], 0.2)
        self.assertTrue(np.isnan(future_ret_close_close(close, 0)[0]))

    def test_nan_and_nonpositive_base_yield_nan(self):
        close = np.array([0.0, 11.0, np.nan, 13.0, 14.0])
        got = future_ret_close_close(close, 2)
        self.assertTrue(np.isnan(got[0]))
        self.assertAlmostEqual(got[1], 13.0 / 11.0 - 1.0)
        self.assertTrue(np.isnan(got[2:]).all())

    def test_open_open_unchanged(self):
        open_arr = np.array([10.0, 11.0, 12.0, 13.0])
        got = _future_ret_open_open(open_arr, 1)
        self.assertAlmostEqual(got[0], 12.0 / 11.0 - 1.0)


class TestQuantileLabels(unittest.TestCase):
    def test_monotone_quintiles(self):
        scores = np.arange(10, dtype=np.float64)
        labels = quantile_labels(scores, 5)
        self.assertEqual(labels.tolist(), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])

    def test_degenerate_returns_all_minus_one(self):
        labels = quantile_labels(np.full(10, 0.5), 5)
        self.assertTrue((labels == -1).all())
        labels = quantile_labels(np.array([1.0, 2.0]), 5)
        self.assertTrue((labels == -1).all())


class TestRankIc(unittest.TestCase):
    def test_perfect_and_reverse(self):
        x = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(rank_ic(x, x), 1.0)
        self.assertAlmostEqual(rank_ic(x, x[::-1]), -1.0)

    def test_matches_legacy_spearman(self):
        rng = np.random.default_rng(42)
        x = rng.normal(size=50)
        y = rng.normal(size=50)
        xr = np.argsort(np.argsort(x)).astype(np.float64)
        yr = np.argsort(np.argsort(y)).astype(np.float64)
        xr -= xr.mean()
        yr -= yr.mean()
        expected = float((xr * yr).sum() / np.sqrt((xr ** 2).sum() * (yr ** 2).sum()))
        self.assertAlmostEqual(rank_ic(x, y), expected)


if __name__ == "__main__":
    unittest.main()
