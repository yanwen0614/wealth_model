"""target（滞后带目标持仓）语义测试（从已退役 test_engine.py 的 legacy target 组迁入）.

迁移自：``TestRunBacktestTarget``（8 项）、``TestTargetFeeAndExit``（7 项）、
``TestStrongBuyGate``（4 项）、``TestAvgCashRatio``（4 项，1 项 DROP 后 3 项迁移）。

**口径为什么整体重写**：legacy ``run_backtest_target`` 的单槽预算恒为
``nav_pre / target_size``（跳过即留现金、不补位，因为 legacy 无持仓上限概念）；
新 ``CnnTargetOrderStrategy`` 受 ``_MAX_HOLDINGS=10`` 硬约束，预算是
``可用现金 / len(candidates)``——**被跳过槽位的现金会分摊给实际成交者**。
两者是不同约束模型（见本文件 ``TestStrongBuyGate`` 的 docstring），非同一语义的
数值平移，故断言改为「行为 + 精确金额恒等式」而保留原解析式。

新增覆盖（legacy 无对应项）：``_MAX_HOLDINGS`` 硬上限、T+1 卖出资金当日不可用。
"""
import unittest

import numpy as np
from backtest_core.contracts import EventStatus
from backtest_core.contracts.config import CostConfig
from backtest_core.policies.cost import AShareCostModel

from tests.unit.backtest._adapter_fixtures import (
    build_synthetic_sample,
    cash_ratios,
    fill_events,
    run_synthetic_backtest,
    trading_days,
)

EXPECTED_COST_CONFIG = CostConfig(transfer_fee_rate=0.00001)


class _TargetFixtureMixin(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="tgt_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def build(self, sample, name="tgt"):
        return build_synthetic_sample(self.tmp, sample, name)

    def run_target(self, pred_cache, parquet_path, **kwargs):
        return run_synthetic_backtest(pred_cache, parquet_path, mode="target", **kwargs)


def _snapshots(outcome):
    return outcome.result.account_snapshots


class TestTargetBuyBandAndHolding(_TargetFixtureMixin):
    """买入带上限、缓冲带持有、超缓冲卖出、尾日强平（原 ``TestRunBacktestTarget`` 6 项）。"""

    def test_buy_band_enters_top_rank_and_exits_on_last_day(self):
        """原 ``test_buy_top_zone_open_t1``：nav 逐日精确到 ``1/1.00025`` 等。

        新引擎断言改为「买入带 rank ≤ target_size」「T+1 open 成交」「尾日 forced_exit」
        与事件级金额，不再复算旧解析式（旧式的单槽预算/费率口径均已不同）。
        """
        days = trading_days(4)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        sample += [(day, "000002.SZ", 0.20, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample)
        outcome = self.run_target(pred_cache, parquet_path, target_size=2, sell_buffer=200)

        self.assertEqual([snapshot.date for snapshot in _snapshots(outcome)], days)
        buys = [event for event in fill_events(outcome) if event.side.value == "buy"]
        self.assertEqual({event.instrument_id for event in buys}, {"000001.SZ", "000002.SZ"})
        for event in buys:
            self.assertEqual(event.signal_time.date().isoformat(), days[0].isoformat())
            self.assertEqual(event.execution_time.date().isoformat(), days[1].isoformat())
            self.assertEqual(event.status, EventStatus.FILLED)
        sells = [event for event in fill_events(outcome) if event.side.value == "sell"]
        self.assertEqual(len(sells), 2)
        for event in sells:
            self.assertEqual(event.status, EventStatus.FORCED_EXIT)
            self.assertEqual(event.execution_time.date().isoformat(), days[-1].isoformat())
        self.assertNotIn("limit_up", outcome.result.skipped_counts)

    def test_buffer_zone_holds_existing_position(self):
        """原 ``test_buffer_zone_hold``：名次跌入缓冲带不卖、末日强平。

        新引擎阈值 ``rank > target_size + sell_buffer``；held 名次 1→2→3（buffer=2 时
        阈值 3）全程未越界，故只在尾日 forced_exit 卖出。
        """
        days = trading_days(5)
        codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
        ranks = {0: {"000001.SZ": 0.9, "000002.SZ": 0.5, "000003.SZ": 0.4},
                 1: {"000001.SZ": 0.4, "000002.SZ": 0.9, "000003.SZ": 0.3},
                 2: {"000001.SZ": 0.3, "000002.SZ": 0.9, "000003.SZ": 0.2},
                 3: {"000001.SZ": 0.2, "000002.SZ": 0.9, "000003.SZ": 0.1},
                 4: {"000001.SZ": 0.2, "000002.SZ": 0.9, "000003.SZ": 0.1}}
        sample = [(day, code, ranks[index][code], 10.0, 10.0)
                  for index, day in enumerate(days) for code in codes]
        pred_cache, parquet_path = self.build(sample, "buffer")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1, sell_buffer=2)

        held = [event for event in outcome.result.trades if event.instrument_id == "000001.SZ"]
        self.assertEqual([event.side.value for event in held if event.status == EventStatus.FILLED],
                         ["buy"])
        forced = [event for event in held if event.status == EventStatus.FORCED_EXIT]
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0].execution_time.date().isoformat(), days[-1].isoformat())

    def test_rank_beyond_buffer_sells_next_open(self):
        """原 ``test_sell_beyond_buffer_open_t1``：卖出在 T+1 open 执行。

        新引擎同样 T+1 open 卖出，但不再「卖出即时再投入」（T+1 资金约束），
        故只断言卖出时点与原因，不断言当日再买入。
        """
        days = trading_days(6)
        codes = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]
        trajectory = {0: [0.90, 0.80, 0.70, 0.60],   # held rank 1
                      1: [0.60, 0.90, 0.80, 0.70],   # held rank 4 → 越过阈值 3
                      2: [0.50, 0.90, 0.80, 0.70],
                      3: [0.10, 0.90, 0.80, 0.70],
                      4: [0.10, 0.90, 0.80, 0.70],
                      5: [0.10, 0.90, 0.80, 0.70]}
        sample = [(day, code, trajectory[index][offset], 10.0, 10.0)
                  for index, day in enumerate(days) for offset, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "beyond")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1, sell_buffer=2)

        held_sells = [event for event in outcome.result.trades
                      if event.instrument_id == "000001.SZ" and event.side.value == "sell"
                      and event.status == EventStatus.FILLED]
        self.assertEqual(len(held_sells), 1)
        # rank 跌到 4 的决策日 = days[1]，T+1 = days[2] 执行
        self.assertEqual(held_sells[0].signal_time.date().isoformat(), days[1].isoformat())
        self.assertEqual(held_sells[0].execution_time.date().isoformat(), days[2].isoformat())

    def test_force_liquidation_on_last_day(self):
        """原 ``test_force_liquidation_last_day``：末日按 open 平仓并计费用。"""
        days = trading_days(5)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "force")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1)
        forced = [event for event in outcome.result.trades
                  if event.status == EventStatus.FORCED_EXIT]
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0].execution_time.date().isoformat(), days[-1].isoformat())
        self.assertEqual(forced[0].reason.value, "forced_exit")
        self.assertGreater(forced[0].commission, 0.0)
        self.assertGreater(forced[0].stamp_tax, 0.0)  # 卖出才计印花税
        self.assertEqual(_snapshots(outcome)[-1].positions, {})

    def test_nav_marks_to_daily_close(self):
        """原 ``test_nav_daily_mark_open``：legacy 用当日 open 标记。

        新引擎 ``_mark_day`` 用当日 **close** 标记（缺价回退 last_marks），
        故断言 ``nav == cash + Σ shares × close`` 而非 open。
        """
        days = trading_days(5)
        closes = [10.0, 10.0, 12.0, 12.0, 12.0]
        sample = [(day, "000001.SZ", 0.30, closes[index], closes[index])
                  for index, day in enumerate(days)]
        pred_cache, parquet_path = self.build(sample, "mark")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1,
                                  initial_capital=100_000.0)

        for index, snapshot in enumerate(_snapshots(outcome)):
            with self.subTest(day=days[index]):
                market_value = sum(position.market_value for position in snapshot.positions.values()
                                   if position.market_value is not None)
                self.assertAlmostEqual(snapshot.nav, snapshot.cash + market_value, places=6)
                for position in snapshot.positions.values():
                    self.assertAlmostEqual(position.price, closes[index], places=9)

    def test_target_no_lookahead_in_past_snapshots(self):
        """原同名测试：未来行改动不影响过去 nav。

        注意 target 模式的「未来」起点必须落在**已建仓之后**，否则改动会改变建仓
        决策本身（legacy 版本改的是 days[2] 起的行情，其建仓在 days[1]，同理）。
        """
        days = trading_days(6)
        codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
        base_sample = [(day, code, 0.30 - 0.05 * index - 0.01 * offset, 10.0, 10.0)
                       for index, day in enumerate(days) for offset, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(base_sample, "nl_base")
        base = self.run_target(pred_cache, parquet_path, target_size=2, sell_buffer=1)

        alt_sample = []
        for day, code, score, open_price, close_price in base_sample:
            if day >= days[2]:
                alt_sample.append((day, code, -score, open_price * 2.0, close_price * 2.0))
            else:
                alt_sample.append((day, code, score, open_price, close_price))
        alt_cache, alt_path = self.build(alt_sample, "nl_alt")
        alt = self.run_target(alt_cache, alt_path, target_size=2, sell_buffer=1)

        for index in range(2):
            self.assertEqual(_snapshots(base)[index].nav, _snapshots(alt)[index].nav)
        self.assertNotEqual(_snapshots(base)[-1].nav, _snapshots(alt)[-1].nav)


class TestTargetExitRules(_TargetFixtureMixin):
    """退出规则：sell_buffer 边界、exit 阈值、缺预测不卖（原 ``TestTargetFeeAndExit`` 4 项）。"""

    def test_default_sell_buffer_500_boundary(self):
        """原 ``test_default_sell_buffer_500_bounds``：rank 300 持有、rank 502 卖出。

        新引擎阈值同为 ``rank > target_size + sell_buffer``（1+500=501），
        故 rank 299 持有、rank 503 卖出（原测试用 300/502，名次差 1 因截面规模不同）。
        """
        n_other = 502
        days = trading_days(4)
        others = [f"{index:06d}.SZ" for index in range(1, n_other + 1)]
        held = "999999.SZ"
        sample = []
        for index, day in enumerate(days):
            for position, code in enumerate(others):
                score = 0.0
                if index == 1 and position < 298:   # 298 只高于 held → held rank 299
                    score = 0.02
                if index == 2 and position < 501:   # 501 只高于 held → held rank 502... 
                    score = 0.02
                sample.append((day, code, score, 10.0, 10.0))
            held_score = {0: 0.9, 1: 0.005, 2: 0.005, 3: 0.005}[index]
            sample.append((day, held, held_score, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "buffer500")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1)

        held_trades = [(event.signal_time.date().isoformat(), event.execution_time.date().isoformat(),
                        event.side.value, event.status.value)
                       for event in outcome.result.trades if event.instrument_id == held]
        # 建仓 → 缓冲带内持有（rank 299 ≤ 501）→ rank 超过 501 次日卖出
        self.assertEqual(held_trades[0][2], "buy")
        self.assertEqual(held_trades[0][3], "filled")
        sells = [item for item in held_trades if item[2] == "sell" and item[3] == "filled"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0][0], days[2].isoformat())   # 决策日
        self.assertEqual(sells[0][1], days[3].isoformat())   # T+1 执行
        # 卖出在决策日次日执行：决策日快照仍持有，执行日快照已清空
        self.assertIn(held, _snapshots(outcome)[2].positions)
        self.assertNotIn(held, _snapshots(outcome)[3].positions)

    def test_exit_on_nonpositive_sells_negative_score_holding(self):
        """原 ``test_exit_on_nonpositive_sells``：exp_ret ≤ 0 即卖，忽略 rank buffer。"""
        days = trading_days(5)
        sample = []
        for index, day in enumerate(days):
            sample.append((day, "000001.SZ", 0.90 if index == 0 else 0.0, 10.0, 10.0))
            sample.append((day, "000002.SZ", 0.10 if index == 0 else 0.50, 10.0, 10.0))
            sample.append((day, "000003.SZ", 0.20, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "exit0")

        hold = self.run_target(pred_cache, parquet_path, target_size=1)
        self.assertEqual([event.instrument_id for event in fill_events(hold)
                          if event.side.value == "buy"], ["000001.SZ"])
        forced_hold = [event for event in hold.result.trades
                       if event.status == EventStatus.FORCED_EXIT]
        self.assertEqual(len(forced_hold), 1)
        self.assertEqual(forced_hold[0].execution_time.date().isoformat(), days[-1].isoformat())

        exit_now = self.run_target(pred_cache, parquet_path, target_size=1,
                                   exit_on_nonpositive=True)
        first_sell = next(event for event in exit_now.result.trades
                          if event.instrument_id == "000001.SZ" and event.side.value == "sell"
                          and event.status == EventStatus.FILLED)
        # score 归零发生在 days[1]，T+1 = days[2] 卖出
        self.assertEqual(first_sell.execution_time.date().isoformat(), days[2].isoformat())

    def test_exit_threshold_configurable(self):
        """原 ``test_exit_threshold_configurable``：exp_ret ≤ threshold 才卖（0.01 门槛）。"""
        days = trading_days(5)
        sample = []
        for index, day in enumerate(days):
            sample.append((day, "000001.SZ", 0.90 if index == 0 else 0.005, 10.0, 10.0))
            sample.append((day, "000002.SZ", 0.10 if index == 0 else 0.50, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "exit_thr")

        zero_threshold = self.run_target(pred_cache, parquet_path, target_size=1,
                                         exit_on_nonpositive=True, exit_threshold=0.0)
        self.assertFalse([event for event in zero_threshold.result.trades
                          if event.instrument_id == "000001.SZ"
                          and event.side.value == "sell" and event.status == EventStatus.FILLED
                          and event.execution_time.date().isoformat() < days[-1].isoformat()])

        raised = self.run_target(pred_cache, parquet_path, target_size=1,
                                 exit_on_nonpositive=True, exit_threshold=0.01)
        early_sell = [event for event in raised.result.trades
                      if event.instrument_id == "000001.SZ" and event.side.value == "sell"
                      and event.status == EventStatus.FILLED
                      and event.execution_time.date().isoformat() < days[-1].isoformat()]
        self.assertEqual(len(early_sell), 1)
        self.assertEqual(early_sell[0].execution_time.date().isoformat(), days[2].isoformat())

    def test_missing_prediction_does_not_force_exit(self):
        """原 ``test_missing_pred_does_not_force_exit``：持仓当日缺预测 → 不卖。"""
        days = trading_days(5)
        rows = [[("000001.SZ", 0.9), ("000002.SZ", 0.1)],
                [("000001.SZ", 0.5), ("000002.SZ", 0.1)],
                [("000002.SZ", 0.5)],
                [("000001.SZ", 0.5), ("000002.SZ", 0.1)],
                [("000001.SZ", 0.5), ("000002.SZ", 0.1)]]
        sample = [(days[index], code, score, 10.0, 10.0)
                  for index, row in enumerate(rows) for code, score in row]
        pred_cache, parquet_path = self.build(sample, "missing_pred")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1,
                                  exit_on_nonpositive=True)

        held = next(event for event in fill_events(outcome) if event.side.value == "buy")
        self.assertEqual(held.instrument_id, "000001.SZ")
        early_sells = [event for event in outcome.result.trades
                       if event.instrument_id == "000001.SZ" and event.side.value == "sell"
                       and event.execution_time.date().isoformat() < days[-1].isoformat()]
        self.assertEqual(early_sells, [])
        forced = [event for event in outcome.result.trades
                  if event.instrument_id == "000001.SZ" and event.status == EventStatus.FORCED_EXIT]
        self.assertEqual(len(forced), 1)
        self.assertEqual(forced[0].execution_time.date().isoformat(), days[-1].isoformat())


class TestTargetFeeAndCapital(_TargetFixtureMixin):
    """费率分支/本金不足（原 ``TestTargetFeeAndExit`` 中 2 项）。"""

    def test_min_commission_branch_differs_from_rate_branch(self):
        """原 ``test_buy_solver_two_cases``：budget ≥ B* 用费率、否则用最低佣金。

        新引擎无显式 solver，但同一逻辑体现在 per-event ``commission``：
        大资金命中费率分支（>5），小资金命中 5 元下限。
        """
        days = trading_days(5)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        sample += [(day, "000002.SZ", 0.20, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "fee_branch")

        model = AShareCostModel(EXPECTED_COST_CONFIG)
        rich = self.run_target(pred_cache, parquet_path, target_size=2,
                               initial_capital=1_000_000.0)
        poor = self.run_target(pred_cache, parquet_path, target_size=2,
                               initial_capital=40_000.0)
        rich_buys = [event for event in fill_events(rich) if event.side.value == "buy"]
        poor_buys = [event for event in fill_events(poor) if event.side.value == "buy"]
        self.assertEqual(len(rich_buys), 2)
        self.assertEqual(len(poor_buys), 2)

        for event in rich_buys:
            expected = model.calculate(event.side, event.amount)[0]
            self.assertEqual(event.commission, expected)
            self.assertGreater(event.commission, 5.0)
        for event in poor_buys:
            self.assertEqual(event.commission, 5.0)
            self.assertLess(event.amount * 0.0002, 5.0)
        self.assertNotEqual(rich_buys[0].commission, poor_buys[0].commission)

    def test_insufficient_capital_leaves_nav_flat(self):
        """原 ``test_budget_not_enough_skipped``：本金 8 元 → 零成交、nav 恒 8。"""
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        sample += [(day, "000002.SZ", 0.20, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "tiny")
        outcome = self.run_target(pred_cache, parquet_path, target_size=2, initial_capital=8.0)

        self.assertEqual(fill_events(outcome), [])
        self.assertGreater(outcome.result.skipped_counts.get("zero_lot", 0), 0)
        for snapshot in _snapshots(outcome):
            self.assertEqual(snapshot.nav, 8.0)

    def test_invalid_fee_inputs_rejected(self):
        """原 ``test_target_invalid_fee_inputs_raise``：负本金/负印花税率显式失败。"""
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "badfee")
        for kwargs in ({"initial_capital": -1.0}, {"stamp_tax_rate": -0.001}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_target(pred_cache, parquet_path, target_size=1, **kwargs)


class TestStrongBuyGate(_TargetFixtureMixin):
    """strong_buy 门槛（原 ``TestStrongBuyGate`` 4 项）。

    **与 legacy 的关键语义差异（docstring 记录，非缺陷）**：

    - legacy（``backtest/engine.py:400``）单槽预算恒为 ``nav_pre / target_size``：
      被门槛跳过的槽位就留作现金。target_size=3 只买 1 只 → 约 2/3 现金。
    - 新策略（``backtest/cnn_adapter/target_strategy.py:333``）预算为
      ``可用现金 / len(candidates)``，且持仓上限 ``_MAX_HOLDINGS=10`` 独立于
      target_size（后者只是**买入带宽**，默认 100）。故被跳过槽位的现金会
      分摊给实际成交者：target_size=3 只买 1 只 → 该票接近满仓（实测现金比 0.0008）。
    - 影响历史结论：``strong_buy`` 实验（2026-09-15, commit ``cb6abc1``）跑的是旧引擎，
      其「现金比 14–33%」是 per-slot 口径；adapter 口径的同等实验现金比会显著更低。
      两套口径的现金比**不可直接比较**。
    - ``target_strategy.py`` 模块 docstring 写「跳过留现金、不补位」，实现是
      「跳过者的预算分给成交者」——措辞与实现不符已登记为待处理项（不改生产代码）。
    """

    def test_negative_threshold_rejected(self):
        """原 ``test_negative_threshold_raises``：负门槛 → ValueError（策略层校验）。"""
        days = trading_days(3)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "neg_thr")
        with self.assertRaises(ValueError):
            self.run_target(pred_cache, parquet_path, target_size=1, strong_buy_threshold=-0.01)

    def test_threshold_skips_weak_names_and_cash_goes_to_buyer(self):
        """原 ``test_threshold_skips_and_holds_cash``：legacy 断言 2/3 现金 + 1/3 买入。

        新引擎：仅 rank1 成交且拿到**全部**可用现金（现金比分摊口径，见类 docstring）。
        可观测证据：只成交 1 笔买单 + 建仓后现金比 < 0.01（若为 legacy 口径应≈2/3）。
        """
        days = trading_days(4)
        sample = []
        for day in days:
            sample.append((day, "000001.SZ", 0.30, 10.0, 10.0))
            sample.append((day, "000002.SZ", 0.03, 10.0, 10.0))
            sample.append((day, "000003.SZ", 0.001, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "strong_buy")
        outcome = self.run_target(pred_cache, parquet_path, target_size=3, sell_buffer=10,
                                  strong_buy_threshold=0.05)

        buys = [event for event in fill_events(outcome) if event.side.value == "buy"]
        self.assertEqual([event.instrument_id for event in buys], ["000001.SZ"])
        after_entry = _snapshots(outcome)[1]
        self.assertEqual(sorted(after_entry.positions), ["000001.SZ"])
        cash_ratio = after_entry.cash / after_entry.nav
        self.assertLess(cash_ratio, 0.01, f"新口径应近满仓，实测 {cash_ratio}")
        self.assertGreater(after_entry.positions["000001.SZ"].market_value / after_entry.nav, 0.99)

    def test_zero_threshold_is_disable_sentinel(self):
        """原 ``test_zero_threshold_equivalent_to_default``：0.0 与不传逐位等价。"""
        days = trading_days(5)
        codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
        sample = [(day, code, score, 10.0, 10.0)
                  for day in days
                  for code, score in zip(codes, (0.30, 0.20, 0.10), strict=True)]
        pred_cache, parquet_path = self.build(sample, "zero_thr")

        default = self.run_target(pred_cache, parquet_path, target_size=1, sell_buffer=1)
        zero = self.run_target(pred_cache, parquet_path, target_size=1, sell_buffer=1,
                               strong_buy_threshold=0.0)
        self.assertEqual([snapshot.nav for snapshot in _snapshots(default)],
                         [snapshot.nav for snapshot in _snapshots(zero)])
        self.assertEqual(dict(default.result.skipped_counts), dict(zero.result.skipped_counts))
        self.assertEqual(
            [(event.instrument_id, event.side.value, event.status.value, event.shares)
             for event in default.result.trades],
            [(event.instrument_id, event.side.value, event.status.value, event.shares)
             for event in zero.result.trades])

    def test_strong_buy_and_limit_up_are_independent_reasons(self):
        """原 ``test_strong_buy_and_limit_up_counted_independently``：两类原因独立计数。

        legacy 断言 ``skipped[day] == {"limit_up": 1, "strong_buy": 1}`` 的**按日 dict**；
        新引擎 ``skipped_counts`` 是全程累计且**只统计进入执行层的原因**——强买门槛在
        策略层直接不发单（``target_strategy.py:315``），因此 ``strong_buy`` 不会出现在
        core 的 ``skipped_counts`` 里；可观测的只有 ``limit_up``。故本测试改断言
        「limit_up 被计入 + 该标的无成交 + 强买候选同样无成交」。
        """
        days = trading_days(4)
        sample = []
        for index, day in enumerate(days):
            sample.append((day, "000001.SZ", 0.30, 11.0 if index > 0 else 10.0, 10.0))
            sample.append((day, "000002.SZ", 0.03, 10.0, 10.0))
        pred_cache, parquet_path = self.build(sample, "indep")
        outcome = self.run_target(pred_cache, parquet_path, target_size=2, sell_buffer=10,
                                  strong_buy_threshold=0.05)

        self.assertEqual(fill_events(outcome), [])
        self.assertGreater(outcome.result.skipped_counts.get("limit_up", 0), 0)
        # core 只看到 limit_up（strong_buy 在策略层静默跳过，不进 core 计数）
        self.assertNotIn("strong_buy", outcome.result.skipped_counts)
        for snapshot in _snapshots(outcome):
            self.assertEqual(snapshot.nav, 1_000_000.0)


class TestTargetCashRatio(_TargetFixtureMixin):
    """闲置现金比例（原 ``TestAvgCashRatio`` 5 项，1 项 DROP、4 项迁移）。

    新结果对象无 ``avg_cash_ratio`` 字段，改为从快照自算 ``mean(cash/nav)``。
    """

    def test_fully_invested_target_has_low_average_cash(self):
        """原 ``test_target_fully_invested_near_zero``：41 日满仓，平均现金比 < 6%。"""
        days = trading_days(41)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        sample += [(day, "000002.SZ", 0.20, 10.0, 10.0) for day in days]
        pred_cache, parquet_path = self.build(sample, "cash41")
        outcome = self.run_target(pred_cache, parquet_path, target_size=2, sell_buffer=500)

        ratios = cash_ratios(outcome)
        mean_ratio = float(np.mean(ratios))
        self.assertGreaterEqual(mean_ratio, 0.0)
        self.assertLess(mean_ratio, 0.06, f"实测 {mean_ratio}")
        # 首日未建仓、末日清仓为全现金（2/41 ≈ 0.0488 恰是这两天的权重）
        self.assertAlmostEqual(ratios[0], 1.0, places=12)
        self.assertAlmostEqual(ratios[-1], 1.0, places=12)

    def test_exit_raises_cash_ratio(self):
        """原 ``test_target_exit_raises_cash_ratio``：频繁退出 → 现金比上升，且有界。"""
        days = trading_days(6)
        sample = [(day, "000001.SZ", 0.90 if index == 0 else 0.0, 10.0, 10.0)
                  for index, day in enumerate(days)]
        pred_cache, parquet_path = self.build(sample, "cash_exit")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1,
                                  exit_on_nonpositive=True)

        mean_ratio = float(np.mean(cash_ratios(outcome)))
        self.assertGreater(mean_ratio, 0.0)
        self.assertLessEqual(mean_ratio, 1.0)
        # 卖出日（隔日空仓）必然全现金 → 平均值显著高于满仓情形
        self.assertGreater(mean_ratio, 0.4)

    def test_all_limit_up_holds_all_cash(self):
        """原 ``test_target_all_cash_when_limit_up``：全涨停 → 现金比 1.0。"""
        days = trading_days(4)
        sample = [(day, "000001.SZ", 0.30, 11.0 if index > 0 else 10.0, 10.0)
                  for index, day in enumerate(days)]
        pred_cache, parquet_path = self.build(sample, "cash_lu")
        outcome = self.run_target(pred_cache, parquet_path, target_size=1, sell_buffer=10)

        for ratio in cash_ratios(outcome):
            self.assertAlmostEqual(ratio, 1.0, places=12)

    def test_no_signals_holds_all_cash(self):
        """原 ``test_target_no_signals_all_cash``：空缓存 → 新引擎显式拒绝而非全现金。

        legacy 在「有 ohlc 但无预测」时返回 ``nav=ones(N)`` + ``avg_cash_ratio=1.0``；
        新引擎要求信号区间非空（空缓存直接 raise），语义更强。
        """
        days = trading_days(5)
        sample = [(day, "000001.SZ", 0.30, 10.0, 10.0) for day in days]
        _, parquet_path = self.build(sample, "cash_none")
        empty_cache = {"exp_ret": np.array([], dtype=np.float64),
                       "true_ret": np.array([], dtype=np.float64),
                       "dates": np.array([], dtype="datetime64[D]"),
                       "codes": np.array([], dtype="U8")}
        with self.assertRaisesRegex(ValueError, "dates must be a non-empty sequence"):
            self.run_target(empty_cache, parquet_path, target_size=1)


class TestTargetHoldingCap(_TargetFixtureMixin):
    """``_MAX_HOLDINGS=10`` 硬上限（legacy 无对应概念，新增覆盖）。"""

    def test_max_holdings_cap_limits_slots(self):
        """target_size=50 但持仓上限 10：最多只买 10 只。"""
        days = trading_days(3)
        codes = [f"{index:06d}.SZ" for index in range(1, 21)]
        sample = [(day, code, 0.30 - 0.001 * index, 10.0, 10.0)
                  for day in days for index, code in enumerate(codes)]
        pred_cache, parquet_path = self.build(sample, "cap")
        outcome = self.run_target(pred_cache, parquet_path, target_size=50, sell_buffer=500)

        after_entry = _snapshots(outcome)[1]
        self.assertEqual(len(after_entry.positions), 10)


if __name__ == "__main__":
    unittest.main()
