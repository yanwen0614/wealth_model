"""账户指标 / 基准 NAV 单测（从已退役的 tests/unit/backtest/test_engine.py 迁入）.

来源与去留（原 test_engine.py 53 类 → 本文件 4 类）：

- ``TestFeeModelArithmetic``：原 ``TestFeeModel``（4 项，KEEP）。``commission`` /
  ``net_return_after_fees`` 属冻结 OLD_LOGIC 算术（``backtest/engine.py`` 常量不改），
  保留为「冻结费率常量与逐笔净收益公式」的回归钉子，防静默改动。
- ``TestNavMetricsLegacy``：原 ``TestNavMetrics``（2 项，KEEP）。``nav_metrics`` 仍是
  生产函数（``scripts/run_backtest.py`` 基准指标），不属 legacy 入口。
- ``TestMetricParity``：新增 parity 判定（原 legacy 测试无此项）。证明新框架
  ``backtest_core.evaluation.metrics`` 在 ``rf=0, ddof=0, periods_per_year=252``
  下与 legacy ``nav_metrics`` 逐值一致，即指标口径未随引擎切换漂移。
- ``TestBenchmarkIndexNav``：原同名类（4 项，KEEP）。``benchmark_index_nav`` 仍是
  生产函数（沪深300 指数 close-to-close 基准），不属 legacy 入口。

已 DROP（不在本文件）：
- 原 ``TestLimitUpMask``（2 项）—— 近似乘数 1.098/1.198 已被 ``CnnMarketDataProvider``
  的分网格精确判定取代，语义由 ``test_cnn_adapter_market.py::TestLimitGrid`` 覆盖。
- 原 ``TestBenchmarkAndEdges.test_benchmark_equal_weight_no_limit_filter`` ——
  等权全市场基准已被历史否决（基准改为沪深300），新框架无 ``benchmark_nav``。
"""
import unittest

import numpy as np

from backtest.engine import (
    BUY_COMMISSION_RATE,
    DEFAULT_CAPITAL,
    MIN_COMMISSION,
    SELL_COMMISSION_RATE,
    STAMP_DUTY_RATE,
    benchmark_index_nav,
    commission,
    nav_metrics,
    net_return_after_fees,
)


def _days(n: int) -> np.ndarray:
    return np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(n, "D"),
                     dtype="datetime64[D]")


class TestFeeModelArithmetic(unittest.TestCase):
    """冻结 OLD_LOGIC 费率常量的逐笔公式（不调用任何 legacy 入口，无守卫）。"""

    def test_commission_min_and_rate(self):
        self.assertEqual(commission(10000.0, BUY_COMMISSION_RATE), MIN_COMMISSION)
        self.assertAlmostEqual(commission(100000.0, BUY_COMMISSION_RATE), 25.0, places=12)
        self.assertAlmostEqual(commission(20000.0, BUY_COMMISSION_RATE), 5.0, places=12)
        self.assertAlmostEqual(commission(20001.0, BUY_COMMISSION_RATE), 5.00025, places=12)

    def test_sell_fee_commission_plus_stamp(self):
        # 卖 110000：佣金 max(27.5,5)=27.5 + 印花税 27.5 = 55.0
        buy = 110000.0
        buy_fee = commission(buy, BUY_COMMISSION_RATE)
        sell_fee = 27.5 + 27.5
        self.assertAlmostEqual(net_return_after_fees(buy, 110000.0),
                               (110000.0 - sell_fee - buy - buy_fee) / (buy + buy_fee), places=12)

    def test_net_return_rate_and_min(self):
        self.assertAlmostEqual(net_return_after_fees(100000.0, 110000.0),
                               (110000.0 - 55.0 - 100025.0) / 100025.0, places=12)
        self.assertAlmostEqual(net_return_after_fees(10000.0, 11000.0),
                               (11000.0 - 7.75 - 10005.0) / 10005.0, places=12)

    def test_constants(self):
        self.assertAlmostEqual(DEFAULT_CAPITAL, 1_000_000.0, places=6)
        self.assertAlmostEqual(SELL_COMMISSION_RATE, 0.00025, places=12)
        self.assertAlmostEqual(STAMP_DUTY_RATE, 0.00025, places=12)


class TestNavMetricsLegacy(unittest.TestCase):
    """``nav_metrics``（生产：scripts/run_backtest.py 的基准指标）解析式口径。"""

    def test_flat_drawdown_sharpe_zero(self):
        m = nav_metrics(np.array([1.0, 1.1, 0.99]))
        self.assertAlmostEqual(m["mdd"], 0.1, places=12)
        self.assertAlmostEqual(m["win_rate"], 0.5, places=12)
        self.assertAlmostEqual(m["sharpe"], 0.0, places=12)
        self.assertAlmostEqual(m["annual"], 0.99 ** (252 / 2) - 1, places=12)

    def test_mdd_and_sharpe_formula(self):
        nav = np.array([1.0, 1.2, 0.9, 1.1])
        ret = np.array([0.2, -0.25, 1.1 / 0.9 - 1])
        m = nav_metrics(nav)
        self.assertAlmostEqual(m["mdd"], 0.25, places=12)
        self.assertAlmostEqual(m["win_rate"], 2.0 / 3.0, places=12)
        self.assertAlmostEqual(m["sharpe"], ret.mean() / ret.std() * np.sqrt(252.0), places=12)


class TestMetricParity(unittest.TestCase):
    """legacy ``nav_metrics`` vs 新框架 ``backtest_core.evaluation.metrics`` 口径 parity。

    为什么需要：引擎已切到 backtest-core，指标若随切换漂移会让新旧回测结论不可比。
    parity 参数：``risk_free_rate_annual=0.0``、``ddof=0``、``periods_per_year=252``
    对齐 legacy 的 ``ret.std()``（numpy 默认 ddof=0）、无无风险利率、年化 252。
    另外核对空/单点边界：legacy 返回 0.0，core 同口径亦为 0.0。
    """

    def _legacy(self, nav):
        return nav_metrics(np.array(nav, dtype=np.float64))

    def _core(self, nav):
        from backtest_core.evaluation import metrics as core_metrics

        values = [float(value) for value in nav]
        returns = core_metrics.period_returns(values)
        return {"mdd": core_metrics.max_drawdown(values),
                "win_rate": core_metrics.win_rate_daily(returns),
                "sharpe": core_metrics.sharpe_ratio(returns, 0.0, 252, 0),
                "annual": core_metrics.annualized_return(values, 252)}

    def test_parity_on_legacy_fixtures(self):
        for nav in ([1.0, 1.1, 0.99], [1.0, 1.2, 0.9, 1.1], [1.0, 1.0, 1.0, 1.0]):
            with self.subTest(nav=nav):
                old, new = self._legacy(nav), self._core(nav)
                for key in ("mdd", "win_rate", "sharpe", "annual"):
                    self.assertAlmostEqual(new[key], old[key], places=14, msg=f"{key} @ {nav}")

    def test_parity_on_engine_snapshot_nav(self):
        """用新引擎真实快照 nav 序列核对两套指标（非合成手算）。"""
        import shutil
        import tempfile

        from tests.unit.backtest._adapter_fixtures import (
            build_synthetic_sample,
            run_synthetic_backtest,
            trading_days,
        )

        tmp = tempfile.mkdtemp(prefix="parity_")
        try:
            days = trading_days(12)
            sample = []
            for index, day in enumerate(days):
                for offset, code in enumerate(("000001.SZ", "000002.SZ", "000003.SZ")):
                    close = 10.0 * (1.0 + 0.004 * index - 0.01 * offset)
                    sample.append((day, code, 0.20 - 0.05 * offset, close, close))
            pred_cache, parquet_path = build_synthetic_sample(tmp, sample, "parity")
            outcome = run_synthetic_backtest(pred_cache, parquet_path, top_n=2)
            raw = [snapshot.nav for snapshot in outcome.result.account_snapshots]
            # legacy nav_metrics 的 annual 用 nav[-1] ** (252/n) - 1，隐含 nav[0]==1
            # （其调用方喂的是净值序列）。引擎快照是绝对金额，须先归一化到起点 1.0
            # 再比；mdd/win_rate/sharpe 本是比值口径，归一化不改变结果。
            nav = [value / raw[0] for value in raw]
            old, new = self._legacy(nav), self._core(nav)
            for key in ("mdd", "win_rate", "sharpe", "annual"):
                self.assertAlmostEqual(new[key], old[key], places=10, msg=f"{key}: {nav}")
            # 绝对金额口径下两套 annual 必然不等，显式钉住这个差异来源（不是缺陷）
            self.assertNotAlmostEqual(self._legacy(raw)["annual"], self._core(raw)["annual"], places=3)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_core_and_legacy_degenerate_nav_return_zero(self):
        for nav in ([1.0], [2.0]):
            with self.subTest(nav=nav):
                old = self._legacy(nav)
                self.assertEqual(old, {"annual": 0.0, "sharpe": 0.0, "mdd": 0.0, "win_rate": 0.0})
        from backtest_core.evaluation import metrics as core_metrics

        self.assertEqual(core_metrics.max_drawdown([1.0]), 0.0)
        self.assertEqual(core_metrics.annualized_return([1.0], 252), 0.0)
        self.assertEqual(core_metrics.win_rate_daily(core_metrics.period_returns([1.0])), 0.0)
        self.assertEqual(core_metrics.sharpe_ratio((), 0.0, 252, 0), 0.0)


class TestBenchmarkIndexNav(unittest.TestCase):
    """``benchmark_index_nav``（生产：scripts/run_backtest.py 沪深300 close-to-close 基准）。"""

    def _index(self):
        dates = np.array(["2025-01-01", "2025-01-02", "2025-01-04", "2025-01-05"], dtype="datetime64[D]")
        close = np.array([100.0, 110.0, 121.0, 121.0], dtype=np.float64)
        return dates, close

    def test_close_to_close_with_missing_day_zero_return(self):
        idates, iclose = self._index()
        nav = benchmark_index_nav(idates, iclose, _days(5))  # 01-03 指数缺失
        np.testing.assert_allclose(nav, np.array([1.0, 1.1, 1.1, 1.21, 1.21]), atol=1e-15)

    def test_starts_at_one_and_ignores_pre_period_index(self):
        idates = np.array(["2024-12-30", "2024-12-31", "2025-01-01", "2025-01-02"], dtype="datetime64[D]")
        iclose = np.array([90.0, 95.0, 100.0, 105.0], dtype=np.float64)
        nav = benchmark_index_nav(idates, iclose, _days(2))
        self.assertEqual(float(nav[0]), 1.0)
        self.assertAlmostEqual(float(nav[1]), 1.05, places=12)

    def test_unsorted_index_input(self):
        idates = np.array(["2025-01-02", "2025-01-01", "2025-01-03"], dtype="datetime64[D]")
        iclose = np.array([110.0, 100.0, 121.0], dtype=np.float64)
        nav = benchmark_index_nav(idates, iclose, _days(3))
        np.testing.assert_allclose(nav, np.array([1.0, 1.1, 1.21]), atol=1e-15)

    def test_empty_trade_days(self):
        idates, iclose = self._index()
        nav = benchmark_index_nav(idates, iclose, np.array([], dtype="datetime64[D]"))
        self.assertEqual(len(nav), 0)
