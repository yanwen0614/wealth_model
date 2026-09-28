"""C05 goal 跨仓库契约测试（规格 §14.3）：共享 fixtures → goal 原生 parquet → 标准契约语义。

覆盖：
1. ``backtest_core.testing.SCENARIOS`` 全部 9 场景转为 goal 原生 parquet 行，经
   GoalMarketDataProvider + MarketState 消费，断言 MarketBar 标准语义（停牌全 None /
   缺价缺量 None / 涨跌停网格派生 / 真实股·真实元不缩放）；
2. 订单路径端到端四态事件 + reason（filled/skipped/locked/forced_exit）：
   cash_amount 整手折算、现金不足整单拒绝、T+1 当日买入锁定与次日解锁可卖、
   尾日 force 清算与尾日买入锁定；
3. daily 订单路径滞后带持有（GoalPredictionAdapter + DailyOrderStrategy 联调）；
4. 截面评估：Prediction（PREDICTED_RETURN/DESCENDING）直供
   ``evaluate_cross_section(_range)``，上涨/下跌场景方向断言；future_ret_5d 仅经
   ``actuals_for_cross_section`` 进入评估。

口径说明（规格 §14.3）：只要求与 core fixtures 的语义一致，**不要求**与旧引擎历史数值一致。
fixture→parquet 转换：core 用布尔表达涨跌停，goal provider 只能由「前收 + 价格网格」
派生，故标记日 close 整体夹到网格价（用 goal_adapter.common 同一函数，保证转换后语义等价）；
非标记日偏离前收 ±9% 以上逐行夹紧，避免制造伪涨跌停。
纪律：全合成数据（tempfile parquet）、零触网、goal 无 DB、不改 C01–C04 源码。
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pandas as pd
from backtest_core.contracts import (
    AccountView,
    EvaluationResult,
    EventStatus,
    MarketBar,
    MarketView,
    OrderIntent,
    OrderStatus,
    Prediction,
    ReasonCode,
    Side,
)
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.protocols import OrderStrategy
from backtest_core.engine import MarketState, run_account_backtest_from_orders
from backtest_core.evaluation import (
    CrossSectionSpec,
    evaluate_cross_section,
    evaluate_cross_section_range,
)
from backtest_core.testing import (
    SCENARIOS,
    SyntheticMarketProvider,
    build_downtrend,
    build_uptrend,
)

from goal_adapter.common import SHANGHAI_TZ, default_limit_pct, limit_price
from goal_adapter.market import GoalMarketDataProvider

if TYPE_CHECKING:  # 只供注解：运行时由函数内导入，避免模块级重依赖
    from goal_adapter.predictions import GoalPredictionAdapter

_CODE = "000001.SZ"
_INITIAL_CAPITAL = 1_000_000.0
_MKT_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]
_PRED_COLS = ["code", "kline_time", "score", "future_ret_5d", "q_true"]


def _cell(value: float | None) -> float:
    """数值 → parquet 单元：None 写 NaN（provider 侧归一为 None，不断流）。"""
    return float("nan") if value is None else float(value)


def _snap_price(prev_close: float, factor: Decimal, code: str) -> float:
    """前收 × 幅度经 provider 同款取整：与派生侧同一函数，消除转换口径差。"""
    pct = default_limit_pct(code)
    up = factor > 1
    return float(limit_price(prev_close, pct, up=up, min_tick_rule=code.upper().endswith(".SZ")))


def fixture_rows(provider: SyntheticMarketProvider, code: str) -> tuple[list[dict], dict]:
    """fixture → goal 原生 parquet 行（真实股/真实元，不做缩放）+ 期望 close 映射。

    停牌行按实证口径写 NaN/0.0（provider 须转全 None）；缺价缺量字段写 NaN。
    """
    bars = provider.bars_for(code)
    rows: list[dict] = []
    for bar in bars:
        if not bar.is_trading:
            rows.append({"code": code, "kline_time": pd.Timestamp(bar.trading_date),
                         "open": float("nan"), "high": float("nan"), "low": float("nan"),
                         "close": float("nan"), "volume": 0.0, "amount": 0.0, "is_trading": False})
            continue
        rows.append({"code": code, "kline_time": pd.Timestamp(bar.trading_date),
                     "open": _cell(bar.open), "high": _cell(bar.high), "low": _cell(bar.low),
                     "close": _cell(bar.close), "volume": _cell(bar.volume), "amount": _cell(bar.amount),
                     "is_trading": True})
    trading = [bar for bar in bars if bar.is_trading]
    positions = [i for i, row in enumerate(rows) if row["is_trading"]]
    adjusted: dict[date, float] = {}
    prev_close: float | None = None
    for row_pos, bar in zip(positions, trading):
        row = rows[row_pos]
        if bar.limit_up or bar.limit_down:
            assert prev_close is not None  # 首日无前收，fixture 标记日恒在中间
            factor = Decimal("1.10") if bar.limit_up else Decimal("0.90")
            snapped = _snap_price(prev_close, factor, code)
            row["close"] = row["open"] = row["high"] = row["low"] = snapped
            adjusted[bar.trading_date] = snapped
            prev_close = snapped
            continue
        current = row["close"]
        if prev_close is not None and not math.isnan(current) and not 0.91 * prev_close <= current <= 1.09 * prev_close:
            clamped = round(prev_close * 1.005, 2)
            row["close"] = clamped
            adjusted[bar.trading_date] = clamped
            prev_close = clamped
            continue
        if not math.isnan(current):
            prev_close = current
    expected = {bar.trading_date: adjusted.get(bar.trading_date, bar.close) for bar in trading}
    return rows, expected


def build_provider(scenario: SyntheticMarketProvider, code: str, tmpdir: str,
                   tag: str) -> tuple[GoalMarketDataProvider, dict]:
    """场景 → 落盘 parquet → goal provider（首 bar 无前收，limit_unknown 恒为 1）。"""
    rows, expected = fixture_rows(scenario, code)
    path = os.path.join(tmpdir, f"{tag}.parquet")
    pd.DataFrame(rows, columns=_MKT_COLS).to_parquet(path, index=False)
    return GoalMarketDataProvider(path), expected


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c05c_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RecordingStrategy:
    """脚本化订单策略：按日期提交固定订单，记录回调时的只读账户视图（无影子账户）。"""

    def __init__(self, orders: Mapping[date, Sequence[OrderIntent]]) -> None:
        self._orders = {day: tuple(items) for day, items in orders.items()}
        self.views: list[tuple[date, dict[str, int], dict[str, int]]] = []

    def orders_for(self, *, trading_date: date, signal_time: datetime, account: AccountView,
                   market: MarketView) -> Sequence[OrderIntent]:
        del market
        assert signal_time.tzinfo is not None  # 引擎回调 signal_time 必须 tz-aware
        self.views.append((trading_date, {code: view.shares for code, view in account.positions.items()},
                           dict(account.locked)))
        return self._orders.get(trading_date, ())


def run_order_path(scenario: SyntheticMarketProvider, code: str, orders: Mapping[date, Sequence[OrderIntent]],
                   tmpdir: str, tag: str) -> tuple[EvaluationResult, RecordingStrategy, tuple[date, ...],
                                                   GoalMarketDataProvider]:
    """场景 → goal parquet provider → 脚本化策略 → core 订单引擎（默认 T+1 open）。"""
    provider, _ = build_provider(scenario, code, tmpdir, tag)
    dates = tuple(bar.trading_date for bar in scenario.bars_for(code))
    strategy = RecordingStrategy(orders)
    result = run_account_backtest_from_orders(
        dates=dates, strategy=strategy, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
        cost_config=CostConfig(), run_id="run-c05", model_id="model-c05",
        initial_capital=_INITIAL_CAPITAL)
    return result, strategy, dates, provider


class TestOrderPathContract(_TempDirMixin):
    """订单路径契约：cash_amount 整手折算 / 整单现金拒绝 / T+1 锁定 / 四态事件 + reason。"""

    CODE = "000001.SZ"

    def test_cash_amount_budget_becomes_whole_lots(self) -> None:
        from backtest_core.testing import build_market

        scenario = build_market(self.CODE, trading_days=4)
        dates = scenario.trading_dates(self.CODE)
        budget = 10_000.0
        result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[0]: (OrderIntent(self.CODE, Side.BUY, cash_amount=budget),)},
            self.tmp, "lots")
        fills = [event for event in result.trades
                 if event.side is Side.BUY and event.status is EventStatus.FILLED]
        self.assertEqual(len(fills), 1)
        fill = fills[0]
        assert fill.execution_price is not None
        self.assertEqual(fill.shares % 100, 0)  # 整手向下
        self.assertGreater(fill.shares, 0)
        self.assertLessEqual(fill.shares * fill.execution_price, budget)
        outcomes = [item for item in result.order_results if item.order.side is Side.BUY]
        self.assertEqual(len(outcomes), 1)
        self.assertIs(outcomes[0].status, OrderStatus.FILLED)
        self.assertEqual(outcomes[0].filled_shares, fill.shares)
        assert outcomes[0].fill_price is not None
        self.assertAlmostEqual(outcomes[0].fill_price, fill.execution_price, places=9)
        self.assertGreater(outcomes[0].fees, 0.0)

    def test_whole_order_cash_rejection(self) -> None:
        scenario = build_uptrend(self.CODE, trading_days=3)
        dates = scenario.trading_dates(self.CODE)
        result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[0]: (OrderIntent(self.CODE, Side.BUY, shares=1_000_000),)},
            self.tmp, "reject")
        events = [event for event in result.trades if event.side is Side.BUY]
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].status, EventStatus.SKIPPED)
        self.assertIs(events[0].reason, ReasonCode.INSUFFICIENT_CASH)
        self.assertEqual(len(result.order_results), 1)
        self.assertIs(result.order_results[0].status, OrderStatus.REJECTED)
        self.assertIs(result.order_results[0].reason, ReasonCode.INSUFFICIENT_CASH)
        snapshot = result.account_snapshots[0]
        self.assertEqual(dict(snapshot.positions), {})
        self.assertAlmostEqual(snapshot.cash, _INITIAL_CAPITAL, places=6)

    def test_t1_lock_on_buy_day_and_unlock_next_day(self) -> None:
        from backtest_core.testing import build_market

        scenario = build_market(self.CODE, trading_days=4)
        dates = scenario.trading_dates(self.CODE)
        orders = {dates[0]: (OrderIntent(self.CODE, Side.BUY, shares=100),),
                  dates[1]: (OrderIntent(self.CODE, Side.SELL, shares=100),)}
        result, strategy, _, _ = run_order_path(scenario, self.CODE, orders, self.tmp, "t1")
        self.assertIsInstance(strategy, OrderStrategy)
        views = {day: (positions, locked) for day, positions, locked in strategy.views}
        self.assertEqual(views[dates[1]][0], {self.CODE: 100})
        self.assertEqual(views[dates[1]][1], {self.CODE: 100})  # 当日买入不可卖（变异自证①：同日模式恒 locked）
        self.assertEqual(views[dates[2]][1], {})  # 次日开盘释放冻结
        buy_fills = [event for event in result.trades
                     if event.side is Side.BUY and event.status is EventStatus.FILLED]
        sell_fills = [event for event in result.trades
                      if event.side is Side.SELL and event.status is EventStatus.FILLED]
        self.assertEqual(len(buy_fills), 1)
        self.assertEqual(len(sell_fills), 1)
        self.assertEqual(buy_fills[0].execution_time.date(), dates[1])
        self.assertEqual(sell_fills[0].execution_time.date(), dates[2])  # 买入成交的下一交易日可卖
        self.assertEqual(sell_fills[0].signal_time,
                         datetime.combine(dates[1], time(15, 0), tzinfo=SHANGHAI_TZ))


class TestScenarioContract(_TempDirMixin):
    """9 个共享场景逐项：原生 parquet 行 → provider → MarketBar 标准语义 + MarketState 批量消费。"""

    def test_all_scenarios_market_bar_semantics(self) -> None:
        for name in sorted(SCENARIOS):
            with self.subTest(scenario=name):
                from backtest_core.testing import build_scenario

                scenario = build_scenario(name)
                code = scenario.instrument_ids()[0]
                provider, expected_close = build_provider(scenario, code, self.tmp, name)
                bars = scenario.bars_for(code)
                for bar in bars:
                    got = provider.get_bar(code, bar.trading_date)
                    assert got is not None  # 场景内所有日期 provider 必有响应
                    self.assertEqual(got.instrument_id, code)
                    self.assertEqual(got.trading_date, bar.trading_date)
                    if not bar.is_trading:
                        self.assert_suspended_bar(got)
                        continue
                    self.assertTrue(got.is_trading)
                    self.assertEqual(got.limit_up, bar.limit_up)
                    self.assertEqual(got.limit_down, bar.limit_down)
                    self.assert_prices(got, bar, expected_close[bar.trading_date])
                self.assertEqual(provider.counters.limit_unknown_count, 1)
                if name in ("missing_price_day", "missing_volume_day"):
                    self.assertEqual(provider.counters.missing_bar_count, 1)
                else:
                    self.assertEqual(provider.counters.missing_bar_count, 0)
                market = MarketState(provider)
                batch = market.get_bars(code, bars[0].trading_date, bars[-1].trading_date)
                self.assertEqual(set(batch), {code})
                self.assertEqual([item.trading_date for item in batch[code]],
                                 [bar.trading_date for bar in bars])
                self.assertEqual([item.is_trading for item in batch[code]],
                                 [bar.is_trading for bar in bars])

    def assert_suspended_bar(self, bar: MarketBar) -> None:
        """停牌合成语义：is_trading=False 且 OHLC/量额一律 None（禁 0.0 冒充）。"""
        self.assertFalse(bar.is_trading)
        for value in (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount):
            self.assertIsNone(value)

    def assert_prices(self, got: MarketBar, fixture: MarketBar, expected_close: float | None) -> None:
        """OHLC 缺失语义逐字段 + 量额真实单位（parquet 已是真实股/元，不做二次缩放）。"""
        for field_name in ("open", "high", "low"):
            expected = getattr(fixture, field_name)
            actual = getattr(got, field_name)
            if expected is None:
                self.assertIsNone(actual, field_name)
            elif fixture.limit_up or fixture.limit_down:
                assert expected_close is not None  # 标记日 OHLC 已整体夹到网格价
                self.assertAlmostEqual(actual, expected_close, places=9, msg=field_name)
            else:
                self.assertAlmostEqual(actual, expected, places=9, msg=field_name)
        if expected_close is None:
            self.assertIsNone(got.close)
        else:
            assert got.close is not None
            self.assertAlmostEqual(got.close, expected_close, places=9)
        if fixture.volume is None:
            self.assertIsNone(got.volume)
            self.assertIsNone(got.amount)
        else:
            assert got.volume is not None and got.amount is not None and fixture.amount is not None
            self.assertAlmostEqual(got.volume, fixture.volume, places=6)
            self.assertAlmostEqual(got.amount, fixture.amount, places=3)


class TestLimitAndLastDay(_TempDirMixin):
    """涨跌停拦截与尾日语义：买入涨停 skip / 跌停卖出 lock / 尾日 force 清算与尾日买入锁定。"""

    CODE = "000001.SZ"

    def test_skipped_buy_on_limit_up_day(self) -> None:
        from backtest_core.testing import build_limit_up_day

        scenario = build_limit_up_day(self.CODE, trading_days=3, at=1)
        dates = scenario.trading_dates(self.CODE)
        result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[0]: (OrderIntent(self.CODE, Side.BUY, cash_amount=10_000.0),)},
            self.tmp, "limitup")
        events = [event for event in result.trades if event.side is Side.BUY]
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].status, EventStatus.SKIPPED)
        self.assertIs(events[0].reason, ReasonCode.LIMIT_UP)
        self.assertEqual(len(result.order_results), 1)
        self.assertIs(result.order_results[0].status, OrderStatus.REJECTED)
        self.assertIs(result.order_results[0].reason, ReasonCode.LIMIT_UP)
        self.assertEqual(dict(result.account_snapshots[-1].positions), {})

    def test_locked_sell_on_limit_down_day(self) -> None:
        from backtest_core.testing import build_limit_down_day

        scenario = build_limit_down_day(self.CODE, trading_days=3, at=2)
        dates = scenario.trading_dates(self.CODE)
        orders = {dates[0]: (OrderIntent(self.CODE, Side.BUY, shares=100),),
                  dates[1]: (OrderIntent(self.CODE, Side.SELL, shares=100),)}
        result, _, _, _ = run_order_path(scenario, self.CODE, orders, self.tmp, "limitdown")
        sell_events = [event for event in result.trades if event.side is Side.SELL]
        self.assertTrue(sell_events)
        self.assertTrue(all(event.status is EventStatus.LOCKED for event in sell_events),
                        [event.status for event in sell_events])
        self.assertTrue(all(event.reason is ReasonCode.LIMIT_DOWN for event in sell_events))
        self.assertIs(result.order_results[-1].status, OrderStatus.REJECTED)
        self.assertIs(result.order_results[-1].reason, ReasonCode.LIMIT_DOWN)
        self.assertEqual(result.account_snapshots[-1].positions[self.CODE].shares, 100)

    def test_forced_exit_and_last_day_locked_buy(self) -> None:
        from backtest_core.testing import build_market

        scenario = build_market(self.CODE, trading_days=3)
        dates = scenario.trading_dates(self.CODE)
        result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[0]: (OrderIntent(self.CODE, Side.BUY, shares=100),)},
            self.tmp, "forced")
        exits = [event for event in result.trades if event.status is EventStatus.FORCED_EXIT]
        self.assertEqual(len(exits), 1)
        self.assertIs(exits[0].reason, ReasonCode.FORCED_EXIT)
        self.assertEqual(exits[0].side, Side.SELL)
        self.assertEqual(exits[0].shares, 100)
        self.assertEqual(exits[0].execution_time.date(), dates[-1])
        self.assertEqual(dict(result.account_snapshots[-1].positions), {})
        locked_result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[1]: (OrderIntent(self.CODE, Side.BUY, shares=100),)},
            self.tmp, "lastday")
        locked = [event for event in locked_result.trades
                  if event.status is EventStatus.LOCKED and event.reason is ReasonCode.LOCKED_POSITION]
        self.assertEqual(len(locked), 1)  # 尾日买入即冻结，清算卖出落 locked 事件
        self.assertEqual(locked[0].side, Side.SELL)
        self.assertEqual(locked[0].shares, 0)
        self.assertEqual(locked_result.account_snapshots[-1].positions[self.CODE].shares, 100)


class _FakePosition:
    def __init__(self, shares: int) -> None:
        self._shares = shares

    @property
    def shares(self) -> int:
        return self._shares


class _FakeAccount:
    """最小 AccountView：策略只读 positions/available_cash（禁影子账户由 C04 单测锁定）。"""

    def __init__(self, cash: float = 1_000_000.0, positions: dict | None = None) -> None:
        self._cash = cash
        self._positions = positions or {}

    @property
    def available_cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict:
        return self._positions


class TestDailyLagBand(_TempDirMixin):
    """daily 订单路径滞后带：pred parquet → GoalPredictionAdapter → DailyOrderStrategy。

    存盘 score 取负后使用（C03）：raw 升序即 trade 降序，Top-N 选中 raw 最小的码。
    """

    CODES = tuple(f"C{i:02d}" for i in range(6))
    DAY = date(2024, 4, 2)

    def _write_pred(self, path: str) -> None:
        rows = [{"code": code, "kline_time": pd.Timestamp(self.DAY),
                 "score": float(-(10 - i)), "future_ret_5d": 0.001 * i, "q_true": 3}
                for i, code in enumerate(self.CODES)]
        pd.DataFrame(rows, columns=_PRED_COLS).to_parquet(path, index=False)

    def _write_market(self, path: str) -> None:
        rows = [{"code": code, "kline_time": pd.Timestamp(self.DAY),
                 "open": 99.9, "high": 100.1, "low": 99.8, "close": 100.0,
                 "volume": 2_000_000.0, "amount": 200_000_000.0, "is_trading": True}
                for code in self.CODES]
        pd.DataFrame(rows, columns=_MKT_COLS).to_parquet(path, index=False)

    def test_hold_inside_buffer_and_sell_outside(self) -> None:
        from goal_adapter.common import signal_time_for
        from goal_adapter.daily_policy import DailyOrderStrategy
        from goal_adapter.predictions import GoalPredictionAdapter

        pred_path = os.path.join(self.tmp, "pred.parquet")
        mkt_path = os.path.join(self.tmp, "mkt.parquet")
        self._write_pred(pred_path)
        self._write_market(mkt_path)
        adapter = GoalPredictionAdapter(pred_path, model_name="c05", model_artifact="c05.pkl",
                                        feature_version="c05", script_version="c05")
        provider = GoalMarketDataProvider(mkt_path)
        strategy = DailyOrderStrategy(adapter, provider, top_n=2, sell_buffer=2)
        # trade 降序：C00(10) > C01(9) > ...，允许集为前 4；C03(第 4 名)持有不动，C05 跌出全卖
        held = {"C03": _FakePosition(100), "C05": _FakePosition(200)}
        orders = strategy.orders_for(
            trading_date=self.DAY, signal_time=signal_time_for(self.DAY),
            # 最小 fake 只实现策略实际读取的成员（positions/available_cash）；
            # cast 只收窄静态类型，运行时仍走同一 fake 对象与 market=None 路径。
            account=cast(AccountView, _FakeAccount(positions=held)),
            market=cast(MarketView, None))
        sells = {o.instrument_id: o.shares for o in orders if o.side is Side.SELL}
        self.assertNotIn("C03", sells)
        self.assertEqual(sells.get("C05"), 200)
        buys = [o for o in orders if o.side is Side.BUY]
        self.assertEqual([o.instrument_id for o in buys], ["C00", "C01"])
        for order in buys:
            self.assertAlmostEqual(order.cash_amount, 500_000.0)  # 等权：可用现金/目标数
        self.assertEqual(strategy.counters.filtered_low_liquidity_count, 0)  # 2e8 真实元 ≥ 默认护栏
        preds = {p.instrument_id: p.value for p in adapter.predictions_for_date(self.DAY)}
        self.assertAlmostEqual(preds["C00"], 10.0)  # score_trade = -score
        self.assertIsInstance(strategy, OrderStrategy)

    def test_daily_strategy_end_to_end(self) -> None:
        from backtest_core.testing import build_market

        from goal_adapter.daily_policy import DailyOrderStrategy
        from goal_adapter.predictions import GoalPredictionAdapter

        scenario = build_market("C00", trading_days=4)
        dates = scenario.trading_dates("C00")
        codes = ("C00", "C01", "C02")
        mkt_rows, pred_rows = [], []
        for day in dates:
            for i, code in enumerate(codes):
                mkt_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                                 "open": 9.9, "high": 10.1, "low": 9.8, "close": 10.0,
                                 "volume": 2_000_000.0, "amount": 200_000_000.0, "is_trading": True})
                pred_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                                  "score": float(-(3 - i)), "future_ret_5d": 0.001, "q_true": 3})
        mkt_path = os.path.join(self.tmp, "e2e_mkt.parquet")
        pred_path = os.path.join(self.tmp, "e2e_pred.parquet")
        pd.DataFrame(mkt_rows, columns=_MKT_COLS).to_parquet(mkt_path, index=False)
        pd.DataFrame(pred_rows, columns=_PRED_COLS).to_parquet(pred_path, index=False)
        provider = GoalMarketDataProvider(mkt_path)
        adapter = GoalPredictionAdapter(pred_path, model_name="c05", model_artifact="c05.pkl",
                                        feature_version="c05", script_version="c05")
        strategy = DailyOrderStrategy(adapter, provider, top_n=1, sell_buffer=0, min_amount_yuan=0.0)
        result = run_account_backtest_from_orders(
            dates=list(dates), strategy=strategy, market=provider,
            execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
            cost_config=CostConfig(), run_id="run-c05-daily", model_id="model-c05",
            initial_capital=_INITIAL_CAPITAL)
        fills = [event for event in result.trades if event.status is EventStatus.FILLED]
        self.assertTrue(fills)  # Top-1 每日持有同一目标：建仓 + 尾日强平
        self.assertEqual(len(result.account_snapshots), len(dates))
        for snapshot in result.account_snapshots:
            market_value = sum(p.market_value for p in snapshot.positions.values() if p.market_value is not None)
            self.assertAlmostEqual(snapshot.nav, snapshot.cash + market_value, places=6)


_UP = "UP.SZ"
_DOWN = "DOWN.SZ"


def _cross_section_setup(tmpdir: str, up_raw: float, down_raw: float,
                         trading_days: int = 25) -> tuple[GoalMarketDataProvider, GoalPredictionAdapter,
                                                           tuple[date, ...]]:
    """双趋势合成市场：UP 涨 / DOWN 跌同日历 + 双码 pred parquet（score 取负后排序）。

    future_ret_5d 取有限常量：只进 actuals 诊断口径，成交路径只消费 score_trade。
    """
    from goal_adapter.predictions import GoalPredictionAdapter

    up = build_uptrend(_UP, trading_days=trading_days)
    down = build_downtrend(_DOWN, trading_days=trading_days)
    rows: list[dict] = []
    for scenario, code in ((up, _UP), (down, _DOWN)):
        part, _ = fixture_rows(scenario, code)
        rows.extend(part)
    parquet_path = os.path.join(tmpdir, "cross_mkt.parquet")
    pd.DataFrame(rows, columns=_MKT_COLS).to_parquet(parquet_path, index=False)
    provider = GoalMarketDataProvider(parquet_path)
    dates = tuple(up.trading_dates(_UP))
    pred_rows = []
    for day in dates:
        for code, raw, actual in ((_UP, up_raw, 0.005), (_DOWN, down_raw, -0.005)):
            pred_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                              "score": raw, "future_ret_5d": actual, "q_true": 3})
    pred_path = os.path.join(tmpdir, "cross_pred.parquet")
    pd.DataFrame(pred_rows, columns=_PRED_COLS).to_parquet(pred_path, index=False)
    adapter = GoalPredictionAdapter(pred_path, model_name="c05", model_artifact="c05.pkl",
                                    feature_version="c05", script_version="c05")
    return provider, adapter, dates


class TestCrossSectionDirection(_TempDirMixin):
    """截面契约：PREDICTED_RETURN/DESCENDING 直供评估，上涨/下跌场景方向与 rank_ic 断言。"""

    SPEC = CrossSectionSpec(holding_days=1, top_n=1, min_cross_section=2, n_quantiles=2)

    def test_uptrend_ranked_first_gives_positive_direction(self) -> None:
        import math

        provider, adapter, dates = _cross_section_setup(self.tmp, -0.8, -0.2)
        actuals = adapter.actuals_for_cross_section(dates[0])
        self.assertEqual(set(actuals), {_UP, _DOWN})  # future_ret_5d 唯一出口可用
        self.assertTrue(all(math.isfinite(value) for value in actuals.values()))
        self.assertGreater(actuals[_UP], actuals[_DOWN])
        window = dates[:-2]  # 尾部两日不足 T+1 入 + 1 日持有出，评估窗口自然剔除
        scores = {day: adapter.predictions_for_date(day) for day in dates}
        self.assertTrue(all(isinstance(pred, Prediction) for pred in scores[dates[0]]))
        summary = evaluate_cross_section_range(signal_dates=window, market=provider,
                                               scores_by_date=scores, spec=self.SPEC)
        self.assertGreater(summary.metrics["ic_mean"], 0.5)
        self.assertGreater(summary.metrics["topn_mean_return"], 0.0)
        self.assertGreater(summary.metrics["evaluated_count"], 0.0)
        single = evaluate_cross_section(signal_date=window[0], market=provider,
                                        scores=scores[window[0]], spec=self.SPEC)
        assert single.topn_mean_return is not None and single.rank_ic is not None
        self.assertGreater(single.topn_mean_return, 0.0)
        self.assertGreater(single.rank_ic, 0.5)

    def test_downtrend_ranked_first_gives_negative_direction(self) -> None:
        """score 符号取反（变异自证②）：排序反转后截面方向同步反转。"""
        provider, adapter, dates = _cross_section_setup(self.tmp, -0.2, -0.8)
        window = dates[:-2]
        scores = {day: adapter.predictions_for_date(day) for day in dates}
        summary = evaluate_cross_section_range(signal_dates=window, market=provider,
                                               scores_by_date=scores, spec=self.SPEC)
        self.assertLess(summary.metrics["ic_mean"], -0.5)
        self.assertLess(summary.metrics["topn_mean_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
