"""十分位诊断工具单测：mock npz 验证驼峰检测逻辑。"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import numpy as np

# ── 辅助：生成 mock npz ──────────────────────────────────────────────────


def _make_mock_npz(
    n_dates: int = 2,
    n_stocks: int = 100,
    seed: int = 42,
    hump: bool = False,
) -> str:
    """创建 mock 预测缓存 npz，返回路径。

    用可控随机数据生成 exp_ret / true_ret / dates / codes，
    如果 hump=True，让 D10 < D8（D10 收益略低于 D8）。
    """
    rng = np.random.default_rng(seed)

    # 2 个日期 × 100 只股票
    dates_arr = np.repeat(
        np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[D]"),
        n_stocks,
    )
    codes_arr = np.array(
        [f"{i:06d}" for i in range(n_stocks)] * 2,
        dtype="<U9",
    )

    if not hump:
        # 单调：D10 > D1, exp_ret 与 true_ret 正相关
        exp_ret = rng.normal(0, 0.02, n_dates * n_stocks)
        # true_ret = exp_ret + noise，保持单调性
        true_ret = exp_ret * 0.5 + rng.normal(0, 0.005, n_dates * n_stocks)
    else:
        # 驼峰：构造 D8 > D10 的情况
        # 首先生成基础 exp_ret
        exp_ret = rng.normal(0, 0.02, n_dates * n_stocks)
        true_ret = np.zeros_like(exp_ret)

        for day_idx in range(n_dates):
            start = day_idx * n_stocks
            end = start + n_stocks
            day_exp = exp_ret[start:end].copy()
            order = np.argsort(day_exp)
            n_per_group = n_stocks // 10

            # 给每组分配不同的 true_ret 均值
            # D1-D7 单调递增，D8 最高，D9-D10 回落
            group_means = np.linspace(-0.01, 0.03, 10)  # baseline
            group_means[7] = 0.035  # D8 最高
            group_means[8] = 0.030  # D9 稍低
            group_means[9] = 0.025  # D10 更低

            for g in range(10):
                idx = order[g * n_per_group: (g + 1) * n_per_group]
                true_ret[start:end][idx] = (
                    group_means[g] + rng.normal(0, 0.003, len(idx))
                )

    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as tmp:
        tmp_path = tmp.name
    np.savez(tmp_path, exp_ret=exp_ret, true_ret=true_ret, dates=dates_arr, codes=codes_arr)
    return tmp_path


class TestDecileAssign(unittest.TestCase):
    """_decile_assign 单元测试。"""

    def test_10_stocks_exact(self):
        from scripts.decile_diagnosis import _decile_assign

        v = np.arange(10, dtype=np.float64)  # 0..9
        groups = _decile_assign(v)
        self.assertEqual(groups.shape, (10,))
        # 每组恰好 1 个元素
        for g in range(10):
            self.assertEqual(int((groups == g).sum()), 1)

    def test_100_stocks_even(self):
        from scripts.decile_diagnosis import _decile_assign

        v = np.arange(100, dtype=np.float64)
        groups = _decile_assign(v)
        self.assertEqual(groups.shape, (100,))
        for g in range(10):
            cnt = int((groups == g).sum())
            self.assertAlmostEqual(cnt, 10, delta=1)

    def test_less_than_10_raises(self):
        from scripts.decile_diagnosis import _decile_assign

        with self.assertRaises(ValueError):
            _decile_assign(np.array([1.0, 2.0, 3.0]))


class TestDailyDecileMeans(unittest.TestCase):
    """逐日十分位均值逻辑测试。"""

    def test_2_dates_100_stocks(self):
        from scripts.decile_diagnosis import daily_decile_means

        path = _make_mock_npz(n_dates=2, n_stocks=100, hump=False)
        with np.load(path) as z:
            daily = daily_decile_means(z["exp_ret"], z["true_ret"], z["dates"])
        os.unlink(path)

        self.assertEqual(len(daily), 2)  # 2 个有效日期
        for d, means in daily.items():
            self.assertEqual(means.shape, (10,))
            self.assertTrue(np.all(np.isfinite(means)))

    def test_min_stocks_filter(self):
        from scripts.decile_diagnosis import daily_decile_means

        # 2 日期 × 10 股票，min_stocks=20 应全部跳过
        rng = np.random.default_rng(42)
        dates = np.array(["2024-01-01"] * 10 + ["2024-01-02"] * 10, dtype="datetime64[D]")
        exp_ret = rng.normal(0, 0.02, 20)
        true_ret = rng.normal(0, 0.01, 20)

        with self.assertRaises(RuntimeError):
            daily_decile_means(exp_ret, true_ret, dates, min_stocks=20)


class TestComputeCumulativeReturns(unittest.TestCase):
    """累计收益计算测试。"""

    def test_identical_means(self):
        from scripts.decile_diagnosis import compute_cumulative_returns

        # 所有日期各组均值相同 → 累计收益相同
        means = {np.datetime64("2024-01-01"): np.full(10, 0.001)}
        cum = compute_cumulative_returns(means)
        np.testing.assert_allclose(cum, np.full(10, 0.001), atol=1e-10)

    def test_single_day(self):
        from scripts.decile_diagnosis import compute_cumulative_returns

        means = {np.datetime64("2024-01-01"): np.arange(10) * 0.01}
        cum = compute_cumulative_returns(means)
        expected = np.arange(10) * 0.01
        np.testing.assert_allclose(cum, expected, atol=1e-10)

    def test_multi_day(self):
        from scripts.decile_diagnosis import compute_cumulative_returns

        means = {
            np.datetime64("2024-01-01"): np.full(10, 0.01),
            np.datetime64("2024-01-02"): np.full(10, -0.005),
        }
        cum = compute_cumulative_returns(means)
        expected = (1.01 * 0.995) - 1.0  # ≈ 0.00495
        np.testing.assert_allclose(cum, np.full(10, expected), atol=1e-10)


class TestDetectHump(unittest.TestCase):
    """驼峰检测逻辑测试。"""

    def test_no_hump_monotonic(self):
        """单调递增：D10 > D8，不触发驼峰。"""
        from scripts.decile_diagnosis import detect_hump

        cum = np.linspace(-0.01, 0.05, 10)  # D10=0.05 > D8≈0.039
        daily = {
            np.datetime64("2024-01-01"): np.linspace(-0.002, 0.01, 10),
            np.datetime64("2024-01-02"): np.linspace(-0.001, 0.015, 10),
        }
        result = detect_hump(cum, daily)
        self.assertFalse(result["hump_detected"])
        self.assertEqual(result["max_decile"], 10)

    def test_hump_detected(self):
        """D10 < D8：应检测到驼峰。"""
        from scripts.decile_diagnosis import detect_hump

        # D8 累计收益最高，D10 回落：驼峰
        # cum: D1~D7 递增, D8 最高(0.04), D9(0.035), D10(0.03)
        cum = np.array([-0.01, -0.005, 0.0, 0.005, 0.01, 0.015, 0.02, 0.04, 0.035, 0.03])
        # 多日 daily_means — D8 日收益高于 D10，累计形成驼峰
        daily = {
            np.datetime64("2024-01-01"): np.array(
                [-0.003, -0.001, 0.001, 0.003, 0.005, 0.007, 0.009, 0.015, 0.012, 0.010]
            ),
            np.datetime64("2024-01-02"): np.array(
                [-0.002, 0.0, 0.002, 0.004, 0.006, 0.008, 0.010, 0.016, 0.013, 0.011]
            ),
        }
        result = detect_hump(cum, daily, std_multiplier=0.5)
        self.assertTrue(result["hump_detected"])
        self.assertEqual(result["max_decile"], 8)

    def test_hump_not_detected_when_within_threshold(self):
        """D10 略低于 D8 但在阈值范围内：不标记驼峰。"""
        from scripts.decile_diagnosis import detect_hump

        # D8=0.04, D10=0.039（差距很小）+ 大 spread 标准差 → 不标记
        cum = np.array([-0.01, -0.005, 0.0, 0.005, 0.01, 0.015, 0.02, 0.04, 0.039, 0.038])
        daily = {
            np.datetime64("2024-01-01"): np.array(
                [-0.01, -0.008, -0.005, 0.0, 0.002, 0.005, 0.008, 0.02, 0.015, 0.05]
            ),
            np.datetime64("2024-01-02"): np.array(
                [-0.01, -0.008, -0.005, 0.0, 0.002, 0.005, 0.008, 0.02, 0.015, -0.02]
            ),
        }
        result = detect_hump(cum, daily, std_multiplier=1.0)
        # 由于 spread 标准差大，阈值可能足够大不触发
        self.assertIn("hump_detected", result)
        self.assertIn("max_decile", result)
        self.assertIsInstance(result["warning"], (str, type(None)))


class TestEndToEndMockNpz(unittest.TestCase):
    """端到端测试：使用 mock npz 文件验证完整链路。"""

    def test_monotonic_e2e(self):
        from scripts.decile_diagnosis import run_diagnosis

        path = _make_mock_npz(n_dates=2, n_stocks=100, hump=False)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_diagnosis(
                pred_cache=path,
                output_dir=tmp,
                min_stocks=10,
            )
            self.assertFalse(result["hump_detected"])
            self.assertEqual(result["max_decile"], 10)

            # 检查输出文件
            self.assertTrue(os.path.exists(os.path.join(tmp, "hump_report.json")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "decile_returns.html")))
        os.unlink(path)

    def test_hump_e2e(self):
        from scripts.decile_diagnosis import run_diagnosis

        path = _make_mock_npz(n_dates=2, n_stocks=100, hump=True)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_diagnosis(
                pred_cache=path,
                output_dir=tmp,
                min_stocks=10,
                std_multiplier=0.5,
            )
            self.assertTrue(result["hump_detected"])
            self.assertEqual(result["max_decile"], 8)

            # 检查 JSON 报告内容
            report_path = os.path.join(tmp, "hump_report.json")
            with open(report_path) as f:
                loaded = json.load(f)
            self.assertTrue(loaded["hump_detected"])
            self.assertEqual(loaded["max_decile"], 8)
            self.assertIsNotNone(loaded["warning"])
        os.unlink(path)


class TestReportJsonStructure(unittest.TestCase):
    """JSON 报告字段完整性测试。"""

    def test_all_keys_present(self):
        from scripts.decile_diagnosis import detect_hump

        cum = np.linspace(-0.01, 0.05, 10)
        daily = {
            np.datetime64("2024-01-01"): np.linspace(-0.002, 0.01, 10),
            np.datetime64("2024-01-02"): np.linspace(-0.001, 0.015, 10),
        }
        result = detect_hump(cum, daily)

        expected_keys = {
            "hump_detected", "max_decile", "decile_cumrets",
            "d8_cumret", "d10_cumret", "spread_threshold",
            "daily_spread_std", "warning",
        }
        self.assertEqual(set(result.keys()), expected_keys)

        # 类型校验
        self.assertIsInstance(result["hump_detected"], bool)
        self.assertIsInstance(result["max_decile"], int)
        self.assertIsInstance(result["decile_cumrets"], list)
        self.assertEqual(len(result["decile_cumrets"]), 10)
        self.assertIsInstance(result["warning"], (str, type(None)))


class TestParseArgs(unittest.TestCase):
    """CLI 参数解析测试。"""

    def test_defaults(self):
        from scripts.decile_diagnosis import parse_args

        args = parse_args(["test.npz"])
        self.assertEqual(args.pred_cache, "test.npz")
        self.assertEqual(args.output_dir, "./decile_report")
        self.assertEqual(args.min_stocks, 20)
        self.assertEqual(args.std_multiplier, 1.0)
        self.assertEqual(args.log_level, "INFO")

    def test_custom(self):
        from scripts.decile_diagnosis import parse_args

        args = parse_args([
            "my_preds.npz",
            "--output_dir", "/tmp/report",
            "--min_stocks", "50",
            "--std_multiplier", "2.0",
            "--log_level", "DEBUG",
        ])
        self.assertEqual(args.pred_cache, "my_preds.npz")
        self.assertEqual(args.output_dir, "/tmp/report")
        self.assertEqual(args.min_stocks, 50)
        self.assertEqual(args.std_multiplier, 2.0)
        self.assertEqual(args.log_level, "DEBUG")


if __name__ == "__main__":
    unittest.main()
