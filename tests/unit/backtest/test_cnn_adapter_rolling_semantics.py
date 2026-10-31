"""rolling（top_n 等权现金单）语义测试（从已退役 test_engine.py 的 legacy rolling 组迁入）.

迁移自：``TestRunBacktest``（5 项）、``TestRollingFeeModel``（3 项）、
``TestBenchmarkAndEdges``（4 项中 3 项 + 1 项并入）、``TestLookaheadAndOrdering``（3 项）、
``TestAvgCashRatio.test_rolling_avg_cash_ratio_zero``（1 项，改宽松上界）。

**口径为什么整体重写**：legacy ``run_backtest`` 是「每日投入 nav/horizon、horizon 批重叠、
退出日一次性实现收益」的解析式账本（nav 前 6 日平线，之后按 `1+k*0.2*nr` 精确跳变）。
新 ``run_cnn_backtest(mode="rolling")`` 是事件驱动账户：T 日信号 → T+1 open 成交、
整手折算、逐日 close 标记、超 top_n 即卖、尾日 force 清算。两者数值不可对等，
因此本文件用「语义级 + 可精确验证的金额恒等式」断言，不照搬 legacy 解析式。
"""
import unittest

import numpy as np
from backtest_core.contracts.config import CostConfig
from backtest_core.policies.cost import AShareCostModel

from tests.unit.backtest._adapter_fixtures import (
    build_synthetic_sample,
    cash_ratios,
    fill_events,
    run_synthetic_backtest,
    trading_days,
)

# runner 缺省 transfer_fee_rate=0.00001（A 股过户费万1双边），core 其余费率默认
# 佣万2/min5/印花卖万5；逐笔费用恒等式的期望模型必须与此一致。
EXPECTED_COST_CONFIG = CostConfig(transfer_fee_rate=0.00001)


class _FixtureMixin(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="roll_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, sample, name="roll"):
        return build_synthetic_sample(self.tmp, sample, name)

    def run_backtest(self, pred_cache, parquet_path, **kwargs):
        return run_synthetic_backtest(pred_cache, parquet_path, **kwargs)


class TestRollingFeeExactness(_FixtureMixin):
    """逐笔费用与 nav 恒等式（原 legacy ``TestRunBacktest.test_cost_exact_deduction`` 等）。

    原 legacy 断言：``nav[6] == 1 + 0.2 * net_return_after_fees(200000, 220000)``
    （解析式：当日投 nav/5，单票买额 200000）。
    新引擎口径：预算 = 可用现金 / len(top_n)，整手折算，扣买入佣金+过户费+滑点，
    逐日 close 标记，尾日 force 清算再扣卖出侧费用。故改为「事件级精确 + nav 守恒」。
    """

    def test_per_event_fees_match_cost_model_exactly(self):
        days = trading_days(7)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 10.0, 10.2)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        model = AShareCostModel(EXPECTED_COST_CONFIG)
        events = fill_events(outcome)
        self.assertEqual(len(events), 10)  # 5 建仓 + 5 尾日强平
        for event in events:
            with self.subTest(code=event.instrument_id, side=event.side):
                expected_commission, expected_stamp, expected_transfer = model.calculate(
                    event.side, event.amount)
                self.assertEqual(event.commission, expected_commission)
                self.assertEqual(event.stamp_tax, expected_stamp)
                self.assertEqual(event.transfer_fee, expected_transfer)
                # amount 必须是「股数 × 成交价」本身，费用不得混入
                self.assertAlmostEqual(event.amount, event.shares * event.execution_price, places=9)
                # 卖出才计印花税
                if event.side.value == "buy":
                    self.assertEqual(event.stamp_tax, 0.0)

    def test_nav_conserves_initial_minus_all_fees_and_slippage(self):
        """平价样本：nav 精确等于「初始本金 − Σ费用 − Σ滑点」。

        为什么平价：价格恒定使持仓盈亏为 0，费用/滑点成为唯一差额，
        可精确核对引擎没有重复计提或漏计（含买入与尾日强制清算两侧）。
        """
        days = trading_days(7)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        initial = 1_000_000.0
        fees = sum(event.commission + event.stamp_tax + event.transfer_fee
                   for event in fill_events(outcome))
        slippage = sum(event.slippage_cost for event in fill_events(outcome))
        final_nav = outcome.result.account_snapshots[-1].nav
        self.assertAlmostEqual(final_nav, initial - fees - slippage, places=6)
        self.assertLess(final_nav, initial)  # 平价下费用+滑点必为净损失
        # 费用必须为正（防止引擎静默吞掉费用）
        self.assertGreater(fees, 0.0)
        self.assertGreater(slippage, 0.0)

    def test_filled_price_ticks_against_order_side(self):
        """原 legacy ``test_open_open_return_exact``：open_t1=10 / open_t6=12.5 → ret_gross=0.25。

        新引擎无 horizon 到期卖出，改为断言「成交价从 base_price 向不利方向跳动」：
        买入价 > base、卖出价 < base，且 base_price 等于当日 open。
        """
        days = trading_days(4)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=1)

        buys = [event for event in fill_events(outcome) if event.side.value == "buy"]
        sells = [event for event in fill_events(outcome) if event.side.value == "sell"]
        self.assertEqual(len(buys), 1)
        self.assertEqual(len(sells), 1)  # 尾日 force 清算
        for event in buys:
            self.assertAlmostEqual(event.base_price, 10.0, places=9)
            self.assertGreater(event.execution_price, event.base_price)
        for event in sells:
            self.assertAlmostEqual(event.base_price, 10.0, places=9)
            self.assertLess(event.execution_price, event.base_price)


class TestRollingAllocationAndSelection(_FixtureMixin):
    """等权分配与选股（原 ``test_equal_weight_allocation`` / ``test_single_stock_topn_exceeds`` /
    ``test_skip_limit_up_and_redistribute``）。

    原 legacy 的 weight 是 ``(1/horizon)/n``（5 只 → 1/25，即当日只投 20%）；
    新引擎预算为「可用现金 / top_n」（5 只 → 各 ≈1/5），故断言改为份额口径。
    """

    def test_five_names_equal_weight(self):
        days = trading_days(4)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        after_entry = outcome.result.account_snapshots[1]
        self.assertEqual(len(after_entry.positions), 5)
        weights = {code: position.market_value / after_entry.nav
                   for code, position in after_entry.positions.items()}
        for code, weight in weights.items():
            # 整手向下折算 + 逐笔费用使权重略低于 1/5，但每家偏差同量级
            self.assertLessEqual(weight, 0.2 + 1e-12, code)
            self.assertGreater(weight, 0.195, code)
        spread = max(weights.values()) - min(weights.values())
        self.assertLess(spread, 0.002)  # 等权：各票份额彼此接近

    def test_single_name_uses_full_cash(self):
        """原 ``test_single_stock_topn_exceeds``：单票 weight=0.2 → nav[6]=1+0.2*nr。

        新引擎：候选只有 1 只，预算=可用现金/1，故仓位接近满仓（原 20% → 现 >99%）。
        """
        days = trading_days(4)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        after_entry = outcome.result.account_snapshots[1]
        self.assertEqual(len(after_entry.positions), 1)
        position = next(iter(after_entry.positions.values()))
        self.assertGreater(position.market_value / after_entry.nav, 0.99)
        self.assertLess(position.market_value / after_entry.nav, 1.0)

    def test_limit_up_name_skipped_and_slot_stays_cash(self):
        """原 ``test_skip_limit_up_and_redistribute``：legacy 把 4 只按 1/5/4 重分配。

        新引擎**不重分配**：预算按 top_n 名额固定（每名 1/5），涨停票被
        ``limit_up_policy=skip`` 拒单后该 1/5 留现金。这是 core 的 per-name budget
        口径（``per_name_budget = nav / len(selected)``），与 legacy 的「剔除后重分」不同。
        """
        days = trading_days(5)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 11.0 if index == 0 else 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "limit_up")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        after_entry = outcome.result.account_snapshots[1]
        self.assertEqual(sorted(after_entry.positions), [f"00000{i}.SZ" for i in range(2, 6)])
        # 每日信号都重试买入该票，直至尾日改判 no_next_trading_day：
        # 5 个信号日 → 4 次 limit_up + 1 次 no_next_trading_day
        self.assertEqual(outcome.result.skipped_counts.get("limit_up"), 4)
        self.assertEqual(outcome.result.skipped_counts.get("no_next_trading_day"), 1)
        # 4 只各占约 1/5，涨停票的 1/5 留作现金
        for position in after_entry.positions.values():
            self.assertGreater(position.market_value / after_entry.nav, 0.195)
            self.assertLess(position.market_value / after_entry.nav, 0.2 + 1e-9)
        self.assertGreater(after_entry.cash / after_entry.nav, 0.19)
        self.assertLess(after_entry.cash / after_entry.nav, 0.21)

    def test_rebalance_sells_non_target_before_buying_new(self):
        """排名切换：旧 target 卖出、新 target 次日才买入（卖出资金当日不可用于买入）。"""
        days = trading_days(6)
        sample = []
        for index, day in enumerate(days):
            first = 0.5 if index < 2 else 0.01
            second = 0.01 if index < 2 else 0.5
            sample.append((day, "000001.SZ", first, 10.0, 10.0))
            sample.append((day, "000002.SZ", second, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "switch")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=1)

        events = [(event.execution_time.date().isoformat(), event.instrument_id, event.side.value,
                   event.status.value) for event in outcome.result.trades]
        self.assertIn(("2025-03-04", "000001.SZ", "buy", "filled"), events)
        self.assertIn(("2025-03-06", "000001.SZ", "sell", "filled"), events)
        # 2025-03-06 当天新票买单因「卖出到账前可用现金为 0」被拒（zero_lot），次日再买
        self.assertIn(("2025-03-06", "000002.SZ", "buy", "skipped"), events)
        self.assertIn(("2025-03-07", "000002.SZ", "buy", "filled"), events)


class TestRollingCapitalAndFees(_FixtureMixin):
    """资金规模对费用分支的影响（原 ``TestRollingFeeModel`` 3 项）。

    原 legacy：``capital=1e4`` 时单票买额 (1/5)*1e4=2000 < 20000 → 最低佣金 5 元生效。
    新引擎：``capital=1e4, top_n=1`` → 预算 1e4，整手 900 股 × 10.01 = 9009 元，
    佣金 max(9009*2e-4, 5) = 5.0（仍命中下限），故用「费率分支 vs 下限分支」区分。
    """

    def test_rate_branch_and_min_commission_branch(self):
        days = trading_days(4)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample)

        big = self.run_backtest(pred_cache, parquet_path, top_n=1, initial_capital=1_000_000.0)
        small = self.run_backtest(pred_cache, parquet_path, top_n=1, initial_capital=10_000.0)
        big_buy = fill_events(big)[0]
        small_buy = fill_events(small)[0]

        # 费率分支：大资金佣金 = 成交额 × 万2
        self.assertAlmostEqual(big_buy.commission, big_buy.amount * 0.0002, places=9)
        self.assertGreater(big_buy.commission, 5.0)
        # 最低佣金分支：小资金佣金被 5 元托底
        self.assertEqual(small_buy.commission, 5.0)
        self.assertLess(small_buy.amount * 0.0002, 5.0)
        # 费用占比：小资金被最低佣金相对侵蚀更重
        big_ratio = big_buy.commission / big_buy.amount
        small_ratio = small_buy.commission / small_buy.amount
        self.assertGreater(small_ratio, big_ratio)

    def test_invalid_fee_inputs_rejected(self):
        """原 ``test_invalid_fee_inputs_raise``：负费率/零本金必须显式失败。

        新引擎由 pydantic ``CostConfig`` 校验费率、runner 校验本金，
        异常类型可能是 ``ValidationError``（ValueError 子类）或 ``ValueError``。
        """
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample)

        for kwargs in ({"initial_capital": 0.0}, {"commission_rate_buy": -0.001},
                       {"stamp_tax_rate": -0.001}, {"min_commission": -1.0},
                       {"transfer_fee_rate": -0.00001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_backtest(pred_cache, parquet_path, top_n=1, **kwargs)


class TestRollingBoundaries(_FixtureMixin):
    """缺价/全涨停/零样本/资金不足边界（原 ``TestBenchmarkAndEdges`` +
    ``TestLookaheadAndOrdering.test_nan_open_t6_excluded_not_counted_as_limit`` +
    ``TestTargetFeeAndExit.test_budget_not_enough_skipped`` 的 rolling 侧）。
    """

    def test_missing_price_skipped_and_not_counted_as_limit_up(self):
        """原 ``test_nan_open_t6_excluded_not_counted_as_limit``：缺价不计入涨停。

        新引擎原因码为 ``missing_price``（``missing_price_policy=skip``），
        ``skipped_counts`` 中不得出现 ``limit_up``。
        """
        days = trading_days(4)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index,
                   float("nan") if index == 0 else 10.0,
                   float("nan") if index == 0 else 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "missing")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        self.assertGreater(outcome.result.skipped_counts.get("missing_price", 0), 0)
        self.assertNotIn("limit_up", outcome.result.skipped_counts)
        after_entry = outcome.result.account_snapshots[1]
        self.assertEqual(len(after_entry.positions), 4)
        self.assertTrue(all("000001.SZ" not in snapshot.positions
                            for snapshot in outcome.result.account_snapshots))

    def test_all_names_limit_up_leaves_nav_flat(self):
        """原 ``test_all_limit_up``：全涨停 → 无成交、nav 不变、涨停计数。

        legacy 的 ``skipped`` 是「按日 dict」；新引擎 ``skipped_counts`` 是全程累计。
        """
        days = trading_days(4)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 11.0 if day != days[0] else 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "all_limit_up")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        self.assertEqual(fill_events(outcome), [])
        self.assertGreater(outcome.result.skipped_counts.get("limit_up", 0), 0)
        for snapshot in outcome.result.account_snapshots:
            self.assertEqual(snapshot.nav, 1_000_000.0)

    def test_zero_samples_rejected_loudly(self):
        """原 ``test_zero_samples``：legacy 返回 ``nav=ones(1)``。

        新引擎拒绝空信号区间（``dates must be a non-empty sequence``）——空输入
        无可评估区间，静默返回 1.0 净值会掩盖上游空缓存问题。
        """
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        _, parquet_path = self.build(sample, "zero")
        empty_cache = {"exp_ret": np.array([], dtype=np.float64),
                       "true_ret": np.array([], dtype=np.float64),
                       "dates": np.array([], dtype="datetime64[D]"),
                       "codes": np.array([], dtype="U8")}
        with self.assertRaisesRegex(ValueError, "dates must be a non-empty sequence"):
            self.run_backtest(empty_cache, parquet_path, top_n=1)

    def test_insufficient_capital_rejects_all_buys(self):
        """原 ``test_budget_not_enough_skipped``：预算不足 → 零成交、nav 不变。

        新引擎原因码 ``zero_lot``（买不起 1 手 = 100 股）。
        """
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "poor")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=1, initial_capital=8.0)

        self.assertEqual(fill_events(outcome), [])
        self.assertGreater(outcome.result.skipped_counts.get("zero_lot", 0), 0)
        for snapshot in outcome.result.account_snapshots:
            self.assertEqual(snapshot.nav, 8.0)

    def test_rolling_cash_ratio_upper_bound(self):
        """原 ``test_rolling_avg_cash_ratio_zero`` 断言 ``avg_cash_ratio == 0.0``。

        该恒等式只对 legacy「每日满仓滚动」成立；新引擎整手折算 + per-name 预算
        必然留少量现金，且首末两日为全现金。故 DROP 原断言，改为宽松上界监控：
        5 只满仓时平均现金比不得高于 0.35（实测 0.2884），越界即说明仓位逻辑退化。
        """
        days = trading_days(7)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        sample = [(day, code, 0.20 - 0.01 * index, 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "cash")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=5)

        ratios = cash_ratios(outcome)
        self.assertEqual(len(ratios), 7)
        mean_ratio = float(np.mean(ratios))
        self.assertLess(mean_ratio, 0.35, f"平均现金比过高：{mean_ratio}")
        # 首末两日必然全现金（未建仓 / 尾日清算）
        self.assertAlmostEqual(ratios[0], 1.0, places=12)
        self.assertAlmostEqual(ratios[-1], 1.0, places=12)
        # 中段必须接近满仓（否则是仓位退化，不是「留点现金」）
        mid_ratios = ratios[1:-1]
        self.assertTrue(all(ratio < 0.01 for ratio in mid_ratios), mid_ratios)


class TestRollingNoLookahead(_FixtureMixin):
    """防前视与确定性排序（原 ``TestLookaheadAndOrdering`` 前两项）。"""

    def test_future_rows_do_not_change_past_snapshots(self):
        days = trading_days(12)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        base_sample = [(day, code, 0.20 - 0.01 * index, 10.0, 10.0)
                       for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(base_sample, "base")
        base = self.run_backtest(pred_cache, parquet_path, top_n=5)

        alt_sample = []
        for day, code, score, open_price, close_price in base_sample:
            if day >= days[6]:
                alt_sample.append((day, code, 0.99, open_price * 1.5, close_price * 1.5))
            else:
                alt_sample.append((day, code, score, open_price, close_price))
        alt_cache, alt_path = self.build(alt_sample, "alt")
        alt = self.run_backtest(alt_cache, alt_path, top_n=5)

        for index in range(6):
            self.assertEqual(base.result.account_snapshots[index].nav,
                             alt.result.account_snapshots[index].nav, f"day {index}")
        # 后半段必须真的变了，否则本测试无法证伪前视
        self.assertNotEqual(base.result.account_snapshots[-1].nav,
                            alt.result.account_snapshots[-1].nav)

    def test_tie_break_prefers_lower_code(self):
        """原 ``test_stable_tie_break_keeps_cross_section_order``：同分取截面次序。

        新策略按 ``(-score, instrument_id)`` 排序，同分取代码升序（确定性，非输入次序）。
        """
        days = trading_days(3)
        sample = [(day, "000002.SZ", 0.5, 10.0, 10.0) for day in days]
        sample += [(day, "000001.SZ", 0.5, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "tie")
        outcome = self.run_backtest(pred_cache, parquet_path, top_n=1)

        buys = [event for event in fill_events(outcome) if event.side.value == "buy"]
        self.assertEqual([event.instrument_id for event in buys], ["000001.SZ"])


if __name__ == "__main__":
    unittest.main()
