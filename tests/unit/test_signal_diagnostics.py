"""信号诊断工具全套单元测试（全 Mock/合成数据，不读真实 npz/不依赖训练）。

测试覆盖：
  1. compute_rankic_series — 合成日截面校验 IC 符号和正比
  2. compute_topk_overlap — Jaccard 相似度基本值
  3. compute_signal_drift — 漂移率基础逻辑
  4. compute_seed_stability — 多 seed 稳定性
  5. compute_turnover_diagnostics — 换手/成本估计
  6. compute_signal_decay — 衰减分析
  7. 内部工具函数 _spearmanr, _spearman_rank, _estimate_transaction_cost
  8. JSON 序列化辅助
"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np

# 允许从项目根 import scripts
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.signal_diagnostics import (
    _estimate_transaction_cost,
    _kendall_w,
    _serialize,
    _spearman_rank,
    _spearmanr,
    _topk_codes,
    compute_rankic_series,
    compute_seed_stability,
    compute_signal_decay,
    compute_signal_drift,
    compute_topk_overlap,
    compute_turnover_diagnostics,
    plot_cost_analysis,
    plot_rankic_series,
    plot_seed_comparison,
    plot_signal_decay,
    plot_topk_overlap,
    write_summary,
)


def _make_cache(
    n_stocks: int = 30,
    n_days: int = 10,
    seed: int = 42,
) -> dict:
    """合成预测缓存，逐日独立强信号 + 噪声，保证 IC 正且逐日变化。"""
    rng = np.random.default_rng(seed)
    codes = np.array([f"{i:06d}" for i in range(n_stocks)])
    all_exp, all_true, all_dates, all_codes = [], [], [], []
    for d in range(n_days):
        date_str = f"2026-01-{5 + d:02d}"
        signal = rng.normal(0, 1.0, n_stocks)
        exp = signal + rng.normal(0, 0.3, n_stocks)
        true = 0.5 * signal + rng.normal(0, 0.3, n_stocks)
        all_exp.append(exp)
        all_true.append(true)
        all_codes.append(codes)
        all_dates.append(np.repeat(date_str, n_stocks))
    return {
        "exp_ret": np.concatenate(all_exp).astype(np.float64),
        "true_ret": np.concatenate(all_true).astype(np.float64),
        "codes": np.concatenate(all_codes),
        "dates": np.concatenate(all_dates).astype(str),
    }


# ═════════════════════════════════════════════════════════════════════════════
# 内部工具函数
# ═════════════════════════════════════════════════════════════════════════════


class TestSpearmanRank(unittest.TestCase):
    def test_perfect_positive(self):
        r = _spearman_rank(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        np.testing.assert_array_almost_equal(r, [1, 2, 3, 4, 5])

    def test_reverse(self):
        r = _spearman_rank(np.array([5.0, 4.0, 3.0, 2.0, 1.0]))
        np.testing.assert_array_almost_equal(r, [5, 4, 3, 2, 1])

    def test_ties(self):
        r = _spearman_rank(np.array([3.0, 1.0, 2.0, 3.0, 1.0]))
        np.testing.assert_array_almost_equal(r, [4.5, 1.5, 3.0, 4.5, 1.5])


class TestSpearmanR(unittest.TestCase):
    def test_perfect(self):
        self.assertAlmostEqual(
            _spearmanr(np.array([1, 2, 3, 4, 5]), np.array([1, 2, 3, 4, 5])), 1.0, places=6
        )

    def test_negative(self):
        self.assertAlmostEqual(
            _spearmanr(np.array([1, 2, 3, 4, 5]), np.array([5, 4, 3, 2, 1])), -1.0, places=6
        )

    def test_small_n(self):
        self.assertEqual(_spearmanr(np.array([1.0, 2.0]), np.array([2.0, 1.0])), 0.0)

    def test_zero_variance(self):
        self.assertEqual(_spearmanr(np.array([1, 1, 1]), np.array([1, 2, 3])), 0.0)


class TestEstimateTransactionCost(unittest.TestCase):
    def test_sell_more_expensive_than_buy(self):
        cost_sell = _estimate_transaction_cost(buy_amount=0, sell_amount=10000)
        cost_buy = _estimate_transaction_cost(buy_amount=10000, sell_amount=0)
        self.assertGreater(cost_sell, cost_buy)

    def test_min_commission_applies(self):
        cost = _estimate_transaction_cost(buy_amount=100, sell_amount=0, min_commission=5.0)
        buy_comm = max(100 * 0.0002, 5.0)
        buy_cost = buy_comm + 100 * 0.00001
        expected = buy_cost + 5.0  # sell side also min commission
        self.assertAlmostEqual(cost, expected)


class TestTopKCodes(unittest.TestCase):
    def test_basic(self):
        top3 = _topk_codes(
            np.array([0.1, 0.5, -0.2, 0.3, 0.0]),
            np.array(["A", "B", "C", "D", "E"]), 3,
        )
        self.assertEqual(top3, {"B", "D", "A"})

    def test_k_too_large(self):
        top5 = _topk_codes(np.array([0.1, 0.5]), np.array(["A", "B"]), 5)
        self.assertEqual(top5, {"A", "B"})

    def test_nan_handling(self):
        top2 = _topk_codes(
            np.array([0.1, np.nan, 0.5]),
            np.array(["A", "B", "C"]), 2,
        )
        self.assertEqual(top2, {"C", "A"})


class TestKendallW(unittest.TestCase):
    def test_perfect_agreement(self):
        mat = np.array([[1, 2, 3], [1, 2, 3], [1, 2, 3]], dtype=np.float64)
        self.assertAlmostEqual(_kendall_w(mat), 1.0, places=4)

    def test_random_agreement_low(self):
        rng = np.random.default_rng(42)
        mat = np.array([rng.permutation(10) for _ in range(5)], dtype=np.float64)
        self.assertLess(_kendall_w(mat), 0.25)

    def test_too_few_items(self):
        self.assertEqual(_kendall_w(np.array([[1, 2]], dtype=np.float64)), 0.0)


class TestSerialize(unittest.TestCase):
    def test_numpy_types(self):
        data = {
            "int_val": np.int64(42),
            "float_val": np.float64(3.14),
            "nan_val": np.nan,
            "inf_val": np.inf,
            "bool_val": np.bool_(True),
            "arr": np.array([1, 2, 3]),
        }
        result = _serialize(data)
        self.assertEqual(result["int_val"], 42)
        self.assertAlmostEqual(result["float_val"], 3.14)
        self.assertIsNone(result["nan_val"])
        self.assertIsNone(result["inf_val"])
        self.assertEqual(result["bool_val"], True)
        self.assertEqual(result["arr"], [1, 2, 3])


# ═════════════════════════════════════════════════════════════════════════════
# compute_rankic_series
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeRankICSeries(unittest.TestCase):
    def test_positive_ic(self):
        cache = _make_cache(n_stocks=50, n_days=10, seed=42)
        result = compute_rankic_series(cache["exp_ret"], cache["true_ret"], cache["dates"])
        self.assertGreater(result["ic_mean"], 0)
        self.assertGreater(result["ic_std"], 0)
        self.assertGreater(result["ic_positive_pct"], 0.5)
        self.assertEqual(len(result["ic_series"]), len(result["dates_series"]))

    def test_min_cross_section_filter_skips_all(self):
        cache = _make_cache(n_stocks=10, n_days=4, seed=42)
        result = compute_rankic_series(
            cache["exp_ret"], cache["true_ret"], cache["dates"],
            min_cross_section=50,
        )
        self.assertEqual(len(result["ic_series"]), 0)
        self.assertEqual(result["ic_mean"], 0.0)

    def test_negative_ic(self):
        """反相关信号 → 负 IC。"""
        rng = np.random.default_rng(42)
        n = 100
        exp = rng.normal(0, 1, n)
        true = -exp + rng.normal(0, 0.1, n)
        dates = np.array(["2026-01-05"] * n)
        result = compute_rankic_series(exp, true, dates, min_cross_section=10)
        self.assertLess(result["ic_mean"], 0)

    def test_icir_consistency(self):
        """IR = 均值 / 标准差。"""
        cache = _make_cache(n_stocks=50, n_days=10, seed=42)
        result = compute_rankic_series(cache["exp_ret"], cache["true_ret"], cache["dates"])
        if result["ic_std"] > 0:
            expected = result["ic_mean"] / result["ic_std"]
            self.assertAlmostEqual(result["ic_ir"], expected, places=6)


# ═════════════════════════════════════════════════════════════════════════════
# compute_topk_overlap
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeTopKOverlap(unittest.TestCase):
    def test_identical_days(self):
        """两日完全相同 → Jaccard=1。"""
        codes = np.array(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
        exp = np.tile(np.array([0.5, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2, -0.3, -0.4]), 2)
        dates = np.array(["2026-01-05"] * 10 + ["2026-01-06"] * 10)
        codes_all = np.tile(codes, 2)
        result = compute_topk_overlap(exp, codes_all, dates, k_values=[5])
        self.assertAlmostEqual(result["mean_overlaps"][5], 1.0, places=4)

    def test_completely_different_days(self):
        """两日 top-5 完全不同 → Jaccard=0。

        Day1: A-E (exp=1.0) 为 top-5
        Day2: F-J (exp=1.0) 为 top-5
        """
        codes_20 = np.array([f"{i:06d}" for i in range(20)], dtype=str)
        exp = np.zeros(40)
        exp[0:5] = 1.0  # A-E 在 Day1 最高
        exp[25:30] = 1.0  # F-J 在 Day2 最高
        dates = np.array(["2026-01-05"] * 20 + ["2026-01-06"] * 20)
        codes_all = np.tile(codes_20, 2)
        result = compute_topk_overlap(exp, codes_all, dates, k_values=[5])
        self.assertAlmostEqual(result["mean_overlaps"][5], 0.0, places=4)

    def test_multiple_k(self):
        cache = _make_cache(n_stocks=40, n_days=5, seed=42)
        result = compute_topk_overlap(cache["exp_ret"], cache["codes"], cache["dates"],
                                      k_values=[5, 10, 20])
        for k in [5, 10, 20]:
            self.assertIn(k, result["mean_overlaps"])
            self.assertIn(k, result["overlap_series"])

    def test_single_day_returns_empty(self):
        codes = np.array(["A", "B", "C"])
        exp = np.array([0.1, 0.0, -0.1])
        dates = np.array(["2026-01-05", "2026-01-05", "2026-01-05"])
        result = compute_topk_overlap(exp, codes, dates, k_values=[2])
        self.assertEqual(len(result["overlap_series"][2]), 0)


# ═════════════════════════════════════════════════════════════════════════════
# compute_signal_drift
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeSignalDrift(unittest.TestCase):
    def test_no_drift(self):
        """连续日 top-10 全保持在 top-50 → 漂移率 0。"""
        codes = np.array([f"{i:06d}" for i in range(100)])
        exp = np.tile(np.linspace(1.0, -1.0, 100), 3)
        dates = np.array(["2026-01-05"] * 100 + ["2026-01-06"] * 100 + ["2026-01-07"] * 100)
        codes_all = np.tile(codes, 3)
        result = compute_signal_drift(exp, codes_all, dates, top_k=10, drift_k=50)
        self.assertAlmostEqual(result["mean_drift_rate"], 0.0, places=4)

    def test_full_drift(self):
        """连续日 top-10 全部掉出 top-50 → 漂移率 1。

        Day1 top-10: 000000-000009 (exp=1.0)
        Day2 使 000000-000009 的 exp 极低，不在 top-50 内。
        """
        codes = np.array([f"{i:06d}" for i in range(100)])
        exp_day1 = np.zeros(100, dtype=np.float64)
        exp_day1[:10] = 1.0
        exp_day2 = np.full(100, 0.0, dtype=np.float64)
        exp_day2[90:] = 1.0  # 后 10 只最高
        exp_day2[:10] = -1.0  # 前 10 只最低（掉出 top-50）
        exp = np.concatenate([exp_day1, exp_day2])
        dates = np.array(["2026-01-05"] * 100 + ["2026-01-06"] * 100)
        codes_all = np.tile(codes, 2)
        result = compute_signal_drift(exp, codes_all, dates, top_k=10, drift_k=50)
        self.assertAlmostEqual(result["mean_drift_rate"], 1.0, places=4)


# ═════════════════════════════════════════════════════════════════════════════
# compute_seed_stability
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeSeedStability(unittest.TestCase):
    def test_identical_caches(self):
        """完全相同的缓存 → 完全一致。"""
        cache = _make_cache(n_stocks=40, n_days=8, seed=42)
        caches = [cache, dict(cache), dict(cache)]
        result = compute_seed_stability(caches, k=5)
        self.assertAlmostEqual(result["cross_seed_ic_corr"], 1.0, places=4)
        self.assertAlmostEqual(result["topk_intersection_ratio"], 1.0, places=4)
        self.assertAlmostEqual(result["kendall_w_mean"], 1.0, places=4)

    def test_different_seeds_produce_valid_metrics(self):
        """不同 seed 的缓存 → 指标在合理范围，非 NaN。"""
        caches = [_make_cache(n_stocks=40, n_days=8, seed=s) for s in [42, 99, 123]]
        result = compute_seed_stability(caches, k=10)
        self.assertGreaterEqual(result["cross_seed_ic_corr"], -1.0)
        self.assertLessEqual(result["cross_seed_ic_corr"], 1.0)
        self.assertGreaterEqual(result["topk_intersection_ratio"], 0.0)
        self.assertLessEqual(result["kendall_w_mean"], 1.0)
        self.assertGreaterEqual(result["kendall_w_mean"], 0.0)

    def test_single_cache_returns_error(self):
        cache = _make_cache()
        result = compute_seed_stability([cache], k=10)
        self.assertIn("error", result)
        self.assertEqual(result["n_seeds"], 1)


# ═════════════════════════════════════════════════════════════════════════════
# compute_turnover_diagnostics
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeTurnoverDiagnostics(unittest.TestCase):
    def test_no_turnover(self):
        """每日组合完全相同 → 换手率 0。"""
        codes = np.array([f"{i:06d}" for i in range(50)])
        exp_day1 = np.zeros(50, dtype=np.float64)
        exp_day1[:10] = 1.0
        exp = np.tile(exp_day1, 4)
        dates = np.array(
            ["2026-01-05"] * 50 + ["2026-01-06"] * 50 +
            ["2026-01-07"] * 50 + ["2026-01-08"] * 50
        )
        codes_all = np.tile(codes, 4)
        result = compute_turnover_diagnostics(exp, codes_all, dates, top_n=10)
        self.assertAlmostEqual(result["daily_turnover_mean"], 0.0, places=4)

    def test_complete_turnover(self):
        """每日组合完全不同 → 换手率 1。"""
        codes = np.array([f"{i:06d}" for i in range(50)])
        exp_day1 = np.zeros(50, dtype=np.float64)
        exp_day1[:10] = 1.0
        exp_day2 = np.zeros(50, dtype=np.float64)
        exp_day2[40:] = 1.0
        exp = np.concatenate([exp_day1, exp_day2])
        dates = np.array(["2026-01-05"] * 50 + ["2026-01-06"] * 50)
        codes_all = np.tile(codes, 2)
        result = compute_turnover_diagnostics(exp, codes_all, dates, top_n=10)
        self.assertAlmostEqual(result["daily_turnover_mean"], 1.0, places=4)

    def test_cost_series_not_empty(self):
        cache = _make_cache(n_stocks=40, n_days=8, seed=42)
        result = compute_turnover_diagnostics(
            cache["exp_ret"], cache["codes"], cache["dates"], top_n=5,
        )
        self.assertGreater(len(result["daily_turnover_series"]), 0)
        self.assertGreaterEqual(result["total_cost_est"], 0.0)

    def test_holding_distribution_keys(self):
        cache = _make_cache(n_stocks=40, n_days=10, seed=42)
        result = compute_turnover_diagnostics(
            cache["exp_ret"], cache["codes"], cache["dates"], top_n=5,
        )
        dist = result["holding_days_distribution"]
        self.assertGreater(len(dist), 0)
        expected_keys = {"1天", "2-3天", "4-7天", "8-14天", "15天+"}
        for key in dist:
            self.assertIn(key, expected_keys)


# ═════════════════════════════════════════════════════════════════════════════
# compute_signal_decay
# ═════════════════════════════════════════════════════════════════════════════


class TestComputeSignalDecay(unittest.TestCase):
    def test_perfect_persistence(self):
        """T 日 top-N 在 T+1 仍在最高分组 → 分组接近 1。"""
        codes = np.array([f"{i:06d}" for i in range(100)])
        rng = np.random.default_rng(42)
        n_days = 12
        all_exp, all_true, all_dates, all_codes = [], [], [], []
        # 排序每日基本不变（稳定信号）
        base_ret = np.linspace(0.1, -0.1, 100)
        for d in range(n_days):
            date_str = f"2026-01-{5 + d:02d}"
            true = base_ret + rng.normal(0, 0.001, 100)
            exp = true + rng.normal(0, 0.01, 100)
            all_exp.append(exp)
            all_true.append(true)
            all_codes.append(codes)
            all_dates.append(np.full(100, date_str, dtype=str))
        cache = {
            "exp_ret": np.concatenate(all_exp).astype(np.float64),
            "true_ret": np.concatenate(all_true).astype(np.float64),
            "codes": np.concatenate(all_codes),
            "dates": np.concatenate(all_dates),
        }
        result = compute_signal_decay(
            cache["exp_ret"], cache["true_ret"],
            cache["codes"], cache["dates"],
            top_n=5, n_groups=10,
        )
        if "error" not in result:
            self.assertLess(
                result["mean_group_positions"].get(1, 99), 2.0,
            )

    def test_insufficient_days_returns_error(self):
        exp = np.array([0.1, 0.0, -0.1])
        true = np.array([0.05, 0.01, -0.02])
        codes = np.array(["A", "B", "C"])
        dates = np.array(["2026-01-05", "2026-01-05", "2026-01-05"])
        result = compute_signal_decay(exp, true, codes, dates)
        self.assertIn("error", result)


# ═════════════════════════════════════════════════════════════════════════════
# 绘图函数
# ═════════════════════════════════════════════════════════════════════════════


class TestPlotFunctions(unittest.TestCase):
    def _check_has_png(self, plot_fn, *args, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            plot_fn(*args, output_dir=tmp, **kwargs)
            files = os.listdir(tmp)
            self.assertTrue(any(f.endswith(".png") for f in files))

    def test_plot_rankic_series(self):
        self._check_has_png(plot_rankic_series, {
            "ic_mean": 0.05, "ic_std": 0.1, "ic_ir": 0.5, "ic_positive_pct": 0.65,
            "ic_series": [0.1, 0.05, -0.02, 0.08, 0.03],
            "dates_series": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"],
        })

    def test_plot_rankic_series_empty(self):
        self._check_has_png(plot_rankic_series, {
            "ic_mean": 0.0, "ic_std": 0.0, "ic_ir": 0.0, "ic_positive_pct": 0.0,
            "ic_series": [], "dates_series": [],
        })

    def test_plot_topk_overlap(self):
        self._check_has_png(plot_topk_overlap, {
            "k_values": [5, 10], "mean_overlaps": {5: 0.5, 10: 0.6},
            "overlap_series": {5: [0.5, 0.6], 10: [0.6, 0.7]},
            "dates_series": ["2026-01-06", "2026-01-07"],
        })

    def test_plot_seed_comparison(self):
        self._check_has_png(plot_seed_comparison, {
            "n_seeds": 3, "topk_agreement_series": [0.5, 0.6, 0.7],
            "kendall_w_series": [0.4, 0.5, 0.6],
            "topk_intersection_ratio": 0.6, "kendall_w_mean": 0.5,
            "dates_series": ["2026-01-06", "2026-01-07", "2026-01-08"],
        })

    def test_plot_cost_analysis(self):
        self._check_has_png(plot_cost_analysis, {
            "daily_turnover_mean": 0.3, "daily_turnover_std": 0.1,
            "daily_turnover_series": [0.2, 0.4, 0.3],
            "cost_per_trade_mean": 10.5, "cost_per_trade_std": 2.0,
            "total_cost_est": 31.5, "cost_as_pct_of_nav": 0.002,
            "avg_holding_days": 5.0,
            "holding_days_distribution": {"1天": 10, "2-3天": 5, "4-7天": 3},
            "dates_series": ["2026-01-06", "2026-01-07"],
        })

    def test_plot_signal_decay(self):
        self._check_has_png(plot_signal_decay, {
            "top_n": 10, "n_groups": 10, "horizons": [1, 2, 5],
            "mean_group_positions": {1: 1.5, 2: 2.3, 5: 3.1},
        })


# ═════════════════════════════════════════════════════════════════════════════
# write_summary
# ═════════════════════════════════════════════════════════════════════════════


class TestWriteSummary(unittest.TestCase):
    def test_json_serialization(self):
        summary = {"mode": "single", "rankic": {"ic_mean": 0.05, "nan": float("nan")}}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_summary(summary, tmp)
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["rankic"]["ic_mean"], 0.05)
            self.assertIsNone(data["rankic"]["nan"])


# ═════════════════════════════════════════════════════════════════════════════
# 端到端集成
# ═════════════════════════════════════════════════════════════════════════════


class TestEndToEnd(unittest.TestCase):
    def test_single_cache_pipeline(self):
        cache = _make_cache(n_stocks=50, n_days=10, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            rankic = compute_rankic_series(cache["exp_ret"], cache["true_ret"], cache["dates"])
            overlap = compute_topk_overlap(cache["exp_ret"], cache["codes"], cache["dates"])
            turnover = compute_turnover_diagnostics(cache["exp_ret"], cache["codes"], cache["dates"])
            decay = compute_signal_decay(cache["exp_ret"], cache["true_ret"], cache["codes"], cache["dates"])

            plot_rankic_series(rankic, tmp)
            plot_topk_overlap(overlap, tmp)
            plot_cost_analysis(turnover, tmp)
            plot_signal_decay(decay, tmp)

            summary = {"mode": "test", "rankic": rankic, "turnover": turnover}
            write_summary(summary, tmp)
            files = os.listdir(tmp)
            png_files = [f for f in files if f.endswith(".png")]
            self.assertGreaterEqual(len(png_files), 3)

    def test_multi_seed_pipeline(self):
        caches = [_make_cache(n_stocks=40, n_days=8, seed=s) for s in [42, 99, 123]]
        result = compute_seed_stability(caches, k=5)
        self.assertGreaterEqual(result["cross_seed_ic_corr"], -1.0)
        self.assertLessEqual(result["cross_seed_ic_corr"], 1.0)
        self.assertGreaterEqual(result["topk_intersection_ratio"], 0.0)
        self.assertGreaterEqual(result["kendall_w_mean"], 0.0)
        self.assertLessEqual(result["kendall_w_mean"], 1.0)


if __name__ == "__main__":
    unittest.main()
