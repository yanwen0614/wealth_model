"""cnn 订单路径回归：确定性合成样本上的执行/成本健康检查（纯新引擎，无 legacy 对照）.

历史沿革（仅说明为何不再有对照，不保留旧代码）：本文件原为 B05「旧 rolling 引擎 vs 新
订单路径」对比回归，legacy 退役后对照失去意义——旧侧数值来自已冻结的解析式账本
（每日投 nav/horizon、退出日一次性实现收益），与新事件驱动账户不可对等，比对只能
得到「口径差异记录」而非回归信号。故改为**单侧基线回归**：固定合成样本 + 固定参数，
锁定新引擎的可观测事实（方向、逐日快照、费用恒等式、成本量级、无异常拦截）。

样本为什么不换手：4 只确定性漂移股、榜单稳定（A/B 恒居前二），只暴露执行/成本/持有
语义；换手与卖出路径由 ``test_cnn_adapter_rolling_semantics`` / ``_target_semantics``
按语义逐条覆盖。

判据（全部可在新引擎内自证，不引用 legacy）：
- 选股为截面分数前二（A/B），建仓在 T+1 open，尾日 forced_exit 清算；
- 每个成交事件的 ``commission/stamp_tax/transfer_fee`` 精确等于 ``AShareCostModel``
  对该 ``amount`` 与方向的计算值（费用恒等式）；
- ``nav[-1] == initial - Σ费用 - Σ滑点``（无隐性扣减或重复计提）；
- 成本量级 < 本金 2%（防费用模型量纲错误）；
- 合成趋势样本不含涨跌停/停牌，故不得出现 ``limit_up``/``limit_down``/``suspended``。
"""
import unittest

import numpy as np
from backtest_core.contracts import EventStatus
from backtest_core.contracts.config import CostConfig
from backtest_core.policies.cost import AShareCostModel

from tests.unit.backtest._adapter_fixtures import (
    build_synthetic_sample,
    fill_events,
    run_synthetic_backtest,
    trading_days,
)

_CODES = ("000001.SZ", "000002.SZ", "600000.SH", "600001.SH")
_DRIFTS = (0.008, 0.003, -0.003, -0.008)
_SCORES = (0.05, 0.02, -0.02, -0.05)
_TRADING_DAYS = 12
_TOP_N = 2
_INITIAL_CAPITAL = 1_000_000.0
# runner 缺省 transfer_fee_rate=0.00001（过户费万1双边）
_EXPECTED_COST_CONFIG = CostConfig(transfer_fee_rate=0.00001)


class TestOrderPathRegression(unittest.TestCase):
    """确定性合成样本：执行 / 费用 / 量级 / 拦截 四项回归。"""

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile

        cls.tmp = tempfile.mkdtemp(prefix="b05r_")
        days = trading_days(_TRADING_DAYS)
        previous = {code: 10.0 + index for index, code in enumerate(_CODES)}
        sample = []
        for day_index, day in enumerate(days):
            for code_index, code in enumerate(_CODES):
                close = previous[code] * (1.0 + _DRIFTS[code_index] + 0.001 * np.sin(day_index + code_index))
                sample.append((day, code, _SCORES[code_index], previous[code], close))
                previous[code] = close
        cls.days = days
        cls.pred_cache, cls.parquet_path = build_synthetic_sample(cls.tmp, sample, "regression")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def _run(self, **kwargs):
        return run_synthetic_backtest(self.pred_cache, self.parquet_path, top_n=_TOP_N,
                                      initial_capital=_INITIAL_CAPITAL, **kwargs)

    def test_selects_top_two_and_liquidates_on_last_day(self):
        outcome = self._run()
        snapshots = outcome.result.account_snapshots
        self.assertEqual([snapshot.date for snapshot in snapshots], self.days)
        buys = [event for event in fill_events(outcome) if event.side.value == "buy"]
        self.assertEqual({event.instrument_id for event in buys}, {_CODES[0], _CODES[1]})
        for event in buys:
            self.assertEqual(event.status, EventStatus.FILLED)
            self.assertEqual(event.execution_time.date().isoformat(), self.days[1].isoformat())
        sells = [event for event in fill_events(outcome) if event.side.value == "sell"]
        self.assertEqual({event.instrument_id for event in sells}, {_CODES[0], _CODES[1]})
        for event in sells:
            self.assertEqual(event.status, EventStatus.FORCED_EXIT)
            self.assertEqual(event.execution_time.date().isoformat(), self.days[-1].isoformat())
        self.assertEqual(snapshots[-1].positions, {})

    def test_snapshot_nav_is_cash_plus_market_value(self):
        outcome = self._run()
        for snapshot in outcome.result.account_snapshots:
            market_value = sum(position.market_value for position in snapshot.positions.values()
                               if position.market_value is not None)
            self.assertAlmostEqual(snapshot.nav, snapshot.cash + market_value, places=6)
        self.assertGreater(len(outcome.result.account_snapshots), 0)

    def test_per_event_fees_match_cost_model(self):
        outcome = self._run()
        model = AShareCostModel(_EXPECTED_COST_CONFIG)
        events = fill_events(outcome)
        self.assertGreater(len(events), 0)
        for event in events:
            with self.subTest(code=event.instrument_id, side=event.side):
                expected_commission, expected_stamp, expected_transfer = model.calculate(
                    event.side, event.amount)
                self.assertAlmostEqual(event.commission, expected_commission, places=9)
                self.assertAlmostEqual(event.stamp_tax, expected_stamp, places=9)
                self.assertAlmostEqual(event.transfer_fee, expected_transfer, places=9)
                self.assertAlmostEqual(event.amount, event.shares * event.execution_price, places=6)
                for fee in (event.commission, event.stamp_tax, event.transfer_fee):
                    self.assertGreaterEqual(fee, 0.0)

    def test_nav_conserves_initial_minus_fees_and_slippage(self):
        """价格不变样本上 nav 必须精确等于「初始本金 − Σ费用 − Σ滑点」。

        为什么用平价样本：价格漂移时 nav 还含持仓盈亏，无法把费用单列出来验证；
        平价样本把盈亏项消掉，费用/滑点是唯一差额来源（若引擎重复计提或漏计即失败）。
        """
        days = trading_days(6)
        sample = [(day, code, _SCORES[index], 10.0, 10.0)
                  for day in days for index, code in enumerate(_CODES)]
        pred_cache, parquet_path = build_synthetic_sample(self.tmp, sample, "flat")
        outcome = run_synthetic_backtest(pred_cache, parquet_path, top_n=_TOP_N,
                                         initial_capital=_INITIAL_CAPITAL)
        events = fill_events(outcome)
        self.assertGreater(len(events), 0)
        fees = sum(event.commission + event.stamp_tax + event.transfer_fee for event in events)
        slippage = sum(event.slippage_cost for event in events)
        final_nav = outcome.result.account_snapshots[-1].nav
        self.assertAlmostEqual(final_nav, _INITIAL_CAPITAL - fees - slippage, places=6)
        self.assertLess(final_nav, _INITIAL_CAPITAL)  # 平价下费用/滑点必为净损失

    def test_cost_magnitude_below_two_percent_of_capital(self):
        outcome = self._run()
        events = fill_events(outcome)
        total_cost = sum(event.commission + event.stamp_tax + event.transfer_fee + event.slippage_cost
                         for event in events) / _INITIAL_CAPITAL
        self.assertGreater(total_cost, 0.0)
        self.assertLess(total_cost, 0.02, f"成本量级异常：{total_cost}")

    def test_trend_sample_triggers_no_limit_or_suspension_blocks(self):
        outcome = self._run()
        blocked = [event for event in outcome.result.trades
                   if event.reason is not None
                   and event.reason.value in ("limit_up", "limit_down", "suspended")]
        self.assertEqual(blocked, [])
        for code in ("limit_up", "limit_down", "suspended"):
            self.assertNotIn(code, outcome.result.skipped_counts)

    def test_direction_matches_positive_drift_sample(self):
        """确定性漂移样本（A/B 正漂移、各约 +0.8%/+0.3%/日）应产生正收益。

        这是**方向**判据，不是 legacy 数值对照：只断言终值 > 初始本金且回撤有限。
        """
        outcome = self._run()
        final_nav = outcome.result.account_snapshots[-1].nav
        self.assertGreater(final_nav, _INITIAL_CAPITAL)
        metrics = outcome.result.account_metrics
        self.assertGreater(metrics["total_return"], 0.0)
        self.assertLess(metrics["max_drawdown"], 0.01)

    def test_derived_metrics_recompute_from_snapshots(self):
        """account_metrics 必须能由快照 nav 复算（防止指标与账户两层口径分叉）。"""
        from backtest_core.evaluation import metrics as core_metrics

        outcome = self._run()
        nav = [snapshot.nav / outcome.result.account_snapshots[0].nav
               for snapshot in outcome.result.account_snapshots]
        metrics = outcome.result.account_metrics
        self.assertAlmostEqual(metrics["total_return"], core_metrics.total_return(nav), places=9)
        self.assertAlmostEqual(metrics["max_drawdown"], core_metrics.max_drawdown(nav), places=9)


if __name__ == "__main__":
    unittest.main()
