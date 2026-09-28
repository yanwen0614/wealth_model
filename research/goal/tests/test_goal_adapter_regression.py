"""C05 新旧初步回归（PLAN D5）：旧 quintile 引擎 vs 新 daily 订单路径。

基线选择（实证后决策）：``backtest/engine.py::run_backtest``（quintile Q5/Q1/bench 纸面口径）。
未选 ``backtest/account_engine*.py`` 的理由：旧 daily 账户引擎按存盘 score **降序**
选股（``sort_values("score", ascending=False)``），而新路径交易信号为
``score_trade = -score``（C03：v2 字面标签倒置，取负后才是可实现方向），两边篮子
天然镜像、无交集，不具可比性；quintile 引擎的 **Q1 袖（最低分位）** 恰与新路径
Top-N（-score 降序）选股一致，同篮子对照只暴露执行/成本/持有语义差异。

对照构造：同一合成小样本（6 只确定性趋势码，30 交易日，零 DB / 零触网），
score 每 5 日轮动一对（A/B 对偶期交替最低，C 对恒高分从未选中），保证新旧同篮子、
每期全换手。旧：Q1 纸面（5 日持有、买入 0.03%/换手 0.16%）；新：daily Top-2
（core 佣金万 2 最低 5 / 卖出印花税万 5 / σ 缩放滑点 v1 + T+1 锁定 + 尾日 force 清算）。
对比：净值方向/净值序列相关性、成交批数、成本量级。
判据（沿 A07/B05，按 goal 口径调整并记录）：同向 + 净值相关 > 0.5 +
买入批数 == 旧调仓数 + 成本比值 [0.25, 4]。结论无数量级异常即可，不要求 parity。

实测结论（2026-09-11，确定性合成数据，仅口径健康检查）：
- 净值序列相关 ≈ 0.99；终值方向一致（同涨，旧 Q1 1.101 / 新 1.062）；
- 调仓批 6（旧）vs 买入批 6（新）相等；总成交 24 笔（12 买 + 10 卖 + 2 尾日强平）；
- 成本 0.0083（旧）vs 0.0201（新，归一到初始本金）约 2.4x，同数量级。

已知口径差异（记录备查，非缺陷）：
- 成本模型：旧 inception 0.03% + 换手×0.16%；新 core 佣金/印花税/σ 滑点（本样本约 2.4x）；
- T+1 现金时序：轮动日卖出次日才交割，轮动日买单因售前现金不足整手折零落
  zero_lot 拒绝 10 笔，次日补单成交（新路径特有事件，旧引擎无此状态机）；
- 持有语义：旧按退出日实现 5 日收益；新逐日 mark-to-market，对比取新路径每期
  末快照与旧 Q1 对齐；
- 整手折算：旧为纸面等权；新 core 按成交价 + 费用折算 cash_amount 整手向下；
- 涨跌停/停牌：合成趋势样本不含，新路径不得出现该类拦截。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd
from backtest_core.contracts import EventStatus
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.engine import run_account_backtest_from_orders

from backtest.engine import run_backtest
from goal_adapter.daily_policy import DailyOrderStrategy
from goal_adapter.market import GoalMarketDataProvider
from goal_adapter.predictions import GoalPredictionAdapter

_CODES = tuple(f"{i + 1:06d}.SZ" for i in range(6))
_DRIFTS = (0.004, 0.003, 0.005, 0.002, -0.002, -0.003)
_TRADING_DAYS = 30
_TOP_N = 2
_INITIAL_CAPITAL = 1_000_000.0
_MKT_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]
_PRED_COLS = ["code", "kline_time", "score", "future_ret_5d", "q_true"]


def _trading_days(n: int) -> list[date]:
    """连续工作日（跳过周末），与合成行情交易日语义一致。"""
    days: list[date] = []
    current = date(2025, 3, 3)
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _scores(period: int, index: int) -> float:
    """偶期 A 对 {0,1} 最低、奇期 B 对 {2,3} 最低，C 对 {4,5} 恒最高（从未选中）。"""
    if period % 2 == 0:
        return float(index)
    return float({0: 2, 1: 3, 2: 0, 3: 1, 4: 4, 5: 5}[index])


def _build_sample(tmpdir: str, negate: bool = False) -> tuple[str, str, pd.DataFrame, list[date]]:
    """同一确定性价格路径 → (mkt 路径, pred 路径, 旧引擎输入 df, 日期)。

    为什么轮动：新旧两路径选股名单逐期一致（A/B 对交替居末两位），回归对比只暴露
    执行/成本/持有语义差异，不混入选股分歧；negate 翻转 score 符号（变异自证）。
    """
    days = _trading_days(_TRADING_DAYS)
    prev = {code: 10.0 + i for i, code in enumerate(_CODES)}
    mkt_rows, pred_rows = [], []
    for day_index, day in enumerate(days):
        period = day_index // 5
        for code_index, code in enumerate(_CODES):
            price = round(prev[code] * (1.0 + _DRIFTS[code_index]), 2)
            open_price = prev[code]
            mkt_rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": open_price,
                             "high": round(max(open_price, price) * 1.005, 2),
                             "low": round(min(open_price, price) * 0.995, 2),
                             "close": price, "volume": 2_000_000.0,
                             "amount": 2_000_000.0 * price, "is_trading": True})
            score = _scores(period, code_index)
            pred_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                              "score": -score if negate else score,
                              "future_ret_5d": 5.0 * _DRIFTS[code_index], "q_true": 1})
            prev[code] = price
    mkt_path = os.path.join(tmpdir, "mkt.parquet")
    pred_path = os.path.join(tmpdir, "pred.parquet")
    pd.DataFrame(mkt_rows, columns=_MKT_COLS).to_parquet(mkt_path, index=False)
    pd.DataFrame(pred_rows, columns=_PRED_COLS).to_parquet(pred_path, index=False)
    # 旧引擎输入恒用原分数（变异只动新路径输入，旧 Q1 基准不动，否则对照自指失效）
    old_rows = [dict(row, score=-row["score"]) if negate else row for row in pred_rows]
    return mkt_path, pred_path, pd.DataFrame(old_rows), days


def _run_new_path(mkt_path: str, pred_path: str, days: list[date]):
    """新 daily 订单路径：min_amount=0 关闭护栏（合成成交额 ~2e7 < 默认 1e8，护栏由 C04/契约覆盖）。"""
    provider = GoalMarketDataProvider(mkt_path)
    adapter = GoalPredictionAdapter(pred_path, model_name="c05", model_artifact="c05.pkl",
                                    feature_version="c05", script_version="c05")
    strategy = DailyOrderStrategy(adapter, provider, top_n=_TOP_N, sell_buffer=0, min_amount_yuan=0.0)
    return run_account_backtest_from_orders(
        dates=list(days), strategy=strategy, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
        cost_config=CostConfig(), run_id="run-c05-reg", model_id="model-c05",
        initial_capital=_INITIAL_CAPITAL)


class TestPartialRegression(unittest.TestCase):
    """新旧初步回归：方向/净值相关 + 笔数 + 成本量级；无数量级异常即通过。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c05r_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direction_correlation_trades_and_cost_magnitude(self) -> None:
        mkt_path, pred_path, old_df, days = _build_sample(self.tmp)
        old = run_backtest(old_df)
        new = _run_new_path(mkt_path, pred_path, days)
        new_nav = np.array([snapshot.nav for snapshot in new.account_snapshots])
        self.assertEqual(len(new_nav), _TRADING_DAYS)
        old_q1 = old["_navs"]["q1"]
        new_sampled = new_nav[[4, 9, 14, 19, 24, 29]] / _INITIAL_CAPITAL  # 每期期末快照与旧 Q1 对齐
        nav_corr = float(np.corrcoef(old_q1, new_sampled)[0, 1])
        old_return = float(old_q1[-1]) - 1.0
        new_return = float(new_nav[-1]) / _INITIAL_CAPITAL - 1.0
        self.assertEqual(old_return < 0.0, new_return < 0.0)  # 方向一致（同涨）
        self.assertGreater(old_return, 0.0)
        self.assertGreater(nav_corr, 0.5)
        fills = [event for event in new.trades
                 if event.status in (EventStatus.FILLED, EventStatus.FORCED_EXIT)]
        buy_batches = len({event.execution_time.date() for event in fills if event.side.name == "BUY"})
        self.assertEqual(old["n_rebalances"], 6)
        self.assertEqual(buy_batches, old["n_rebalances"])  # 买入批数 == 旧调仓数
        self.assertGreater(len(fills), 0)
        old_cost = 0.0003 + 5 * 0.0016  # Q1：inception + 5 期全换手 × ROUNDTRIP
        new_cost = float(sum(event.commission + event.stamp_tax + event.transfer_fee
                             + event.slippage_cost for event in fills)) / _INITIAL_CAPITAL
        self.assertGreater(old_cost, 0.0)
        self.assertGreater(new_cost, 0.0)
        self.assertGreater(new_cost / old_cost, 0.25)  # 成本同数量级（费率口径不同，见模块 docstring）
        self.assertLess(new_cost / old_cost, 4.0)
        self.assertLess(old_cost, 0.05)
        self.assertLess(new_cost, 0.05)
        zero_lot = [item for item in new.order_results if item.reason is not None
                    and item.reason == "zero_lot"]
        self.assertEqual(len(zero_lot), 10)  # T+1 现金时序：轮动日买单售前现金不足，次日补单
        blocked = [event for event in new.trades
                   if event.reason is not None and event.reason.value in ("limit_up", "limit_down", "suspended")]
        self.assertEqual(blocked, [])  # 合成趋势样本无涨跌停/停牌：新路径不得误判拦截

    def test_sign_flip_reverses_direction(self) -> None:
        """score 符号取反（变异自证）：新路径改选 Q5 篮子（负漂移），与旧 Q1 反向。"""
        mkt_path, pred_path, old_df, days = _build_sample(self.tmp, negate=True)
        old = run_backtest(old_df)
        new = _run_new_path(mkt_path, pred_path, days)
        new_nav = np.array([snapshot.nav for snapshot in new.account_snapshots])
        new_sampled = new_nav[[4, 9, 14, 19, 24, 29]] / _INITIAL_CAPITAL
        nav_corr = float(np.corrcoef(old["_navs"]["q1"], new_sampled)[0, 1])
        self.assertLess(nav_corr, 0.0)
        new_return = float(new_nav[-1]) / _INITIAL_CAPITAL - 1.0
        self.assertLess(new_return, 0.0)  # C 对负漂移：新路径转跌，旧 Q1 仍涨


if __name__ == "__main__":
    unittest.main()
