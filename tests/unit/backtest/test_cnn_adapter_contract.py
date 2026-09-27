"""B05 跨仓库契约测试（规格 §14.3）：共享 fixtures → cnn 原生 parquet/npz → 标准契约语义。

覆盖：
1. ``backtest_core.testing.SCENARIOS`` 全部 9 场景转为 cnn 原生 parquet 行，经
   CnnMarketDataProvider + MarketState 消费，断言 MarketBar 标准语义（停牌全 None /
   缺价缺量 None / 涨跌停网格派生 / 量额真实单位）；
2. 订单路径端到端四态事件 + reason（filled/skipped/locked/forced_exit）：
   cash_amount 整手折算、现金不足整单拒绝、T+1 当日买入锁定与次日解锁可卖；
3. 截面评估：Prediction（PREDICTED_RETURN/DESCENDING）直供
   ``evaluate_cross_section(_range)``，上涨/下跌场景方向断言；true_ret 仅经
   ``actuals_for_cross_section`` 进入评估。

口径说明（规格 §14.3）：只要求与 core fixtures 的语义一致，**不要求**与旧引擎历史数值一致。
纪律：全合成数据（fixtures 由 backtest_core.testing 生成 + tempfile parquet/npz）、零触网、cnn 无 DB。
"""

import math
import os
import shutil
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
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
from backtest_core.testing import SCENARIOS, SyntheticMarketProvider, build_downtrend, build_uptrend

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.common import SHANGHAI_TZ
from backtest.cnn_adapter.market import CnnMarketDataProvider
from backtest.cnn_adapter.predictions import CnnPredictionAdapter

_CODE = "000001.SZ"
_UP_FACTOR = Decimal("1.10")
_DOWN_FACTOR = Decimal("0.90")
_TICK = Decimal("0.01")
_INITIAL_CAPITAL = 1_000_000.0


def _grid_price(prev_close: float, factor: Decimal) -> float:
    """前收 × 幅度经 ROUND_HALF_UP 量化到分：与 B02 价格网格同一取整口径。"""
    return float((Decimal(str(prev_close)) * factor).quantize(_TICK, rounding=ROUND_HALF_UP))


def _cell(value: float | None) -> float:
    return float("nan") if value is None else float(value)


def fixture_rows(provider: SyntheticMarketProvider, code: str) -> tuple[list[dict], dict]:
    """fixture → cnn 原生 parquet 行（真实股/真实元，不做放大）+ 期望 close 映射。

    为什么调涨跌停日 close：core fixture 用布尔表达涨跌停，cnn provider 只能由
    「前收 + 价格网格」派生；把标记日 close 夹到网格价保证转换后语义等价。
    调整改变后续网格基准：逐行夹紧偏离 ±9% 的 close，避免制造伪涨跌停。
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
    trading_bars = [bar for bar in bars if bar.is_trading]
    positions = [i for i, row in enumerate(rows) if row["is_trading"]]
    adjusted: dict[date, float] = {}
    for pos in range(1, len(positions)):
        row = rows[positions[pos]]
        prev_close = rows[positions[pos - 1]]["close"]
        bar = trading_bars[pos]
        if math.isnan(prev_close):
            continue
        if bar.limit_up or bar.limit_down:
            factor = _UP_FACTOR if bar.limit_up else _DOWN_FACTOR
            snapped = _grid_price(prev_close, factor)
            row["close"] = row["open"] = row["high"] = row["low"] = snapped
            adjusted[bar.trading_date] = snapped
    for pos in range(1, len(positions)):
        day = trading_bars[pos].trading_date
        if day in adjusted:
            continue
        prev_close = rows[positions[pos - 1]]["close"]
        current = rows[positions[pos]]["close"]
        if math.isnan(prev_close) or math.isnan(current):
            continue
        if not 0.91 * prev_close <= current <= 1.09 * prev_close:
            clamped = round(prev_close * 1.005, 2)
            rows[positions[pos]]["close"] = clamped
            adjusted[day] = clamped
    expected = {bar.trading_date: adjusted.get(bar.trading_date, bar.close) for bar in trading_bars}
    return rows, expected


def build_provider(provider: SyntheticMarketProvider, code: str, tmpdir: str,
                   tag: str) -> tuple[CnnMarketDataProvider, dict]:
    """场景 → 落盘 parquet → cnn provider（含涨跌停网格派生，不断言前无 unknown 污染）。"""
    rows, expected = fixture_rows(provider, code)
    path = os.path.join(tmpdir, f"{tag}.parquet")
    pd.DataFrame(rows).to_parquet(path, index=False)
    return CnnMarketDataProvider(path), expected


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b05c_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


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
                # 首根 bar 无前收：limit 派生记 unknown（占位 False），不静默断言为有效判定
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
                # 标记日 OHLC 已整体夹到网格价（见 fixture_rows）：与 close 同值断言
                assert expected_close is not None
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
                                                   CnnMarketDataProvider]:
    """场景 → cnn parquet provider → 脚本化策略 → core 订单引擎（默认 T+1 open）。"""
    provider, _ = build_provider(scenario, code, tmpdir, tag)
    dates = tuple(bar.trading_date for bar in scenario.bars_for(code))
    strategy = RecordingStrategy(orders)
    result = run_account_backtest_from_orders(
        dates=dates, strategy=strategy, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
        cost_config=CostConfig(), run_id="run-b05", model_id="model-b05",
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
        self.assertEqual(views[dates[1]][1], {self.CODE: 100})  # 当日买入不可卖
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

    def test_locked_position_on_last_day_buy(self) -> None:
        from backtest_core.testing import build_market

        scenario = build_market(self.CODE, trading_days=3)
        dates = scenario.trading_dates(self.CODE)
        result, _, _, _ = run_order_path(
            scenario, self.CODE, {dates[1]: (OrderIntent(self.CODE, Side.BUY, shares=100),)},
            self.tmp, "lastday")
        locked = [event for event in result.trades
                  if event.status is EventStatus.LOCKED and event.reason is ReasonCode.LOCKED_POSITION]
        self.assertEqual(len(locked), 1)  # 尾日买入即冻结，清算卖出落 locked 事件
        self.assertEqual(locked[0].side, Side.SELL)
        self.assertEqual(locked[0].shares, 0)
        snapshot = result.account_snapshots[-1]
        self.assertEqual(snapshot.positions[self.CODE].shares, 100)  # 锁定仓保留

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

    def test_forced_exit_on_last_day(self) -> None:
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


_UP = "UP.SZ"
_DOWN = "DOWN.SZ"


def _cross_section_setup(tmpdir: str, up_score: float, down_score: float,
                         trading_days: int = 25) -> tuple[CnnMarketDataProvider, CnnPredictionAdapter,
                                                         tuple[date, ...]]:
    """双趋势合成市场：UP 涨 / DOWN 跌同日历 + 双码截面缓存（scores 决定排序方向）。

    为什么用同日历双码：截面评估要求同归属日多标的可比截面；true_ret 取有限常量，
    成交路径只消费 Prediction（exp_ret），评估收益由引擎从市场状态自算。
    """
    up = build_uptrend(_UP, trading_days=trading_days)
    down = build_downtrend(_DOWN, trading_days=trading_days)
    rows: list[dict] = []
    for scenario, code in ((up, _UP), (down, _DOWN)):
        part, _ = fixture_rows(scenario, code)
        rows.extend(part)
    parquet_path = os.path.join(tmpdir, "cross.parquet")
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    provider = CnnMarketDataProvider(parquet_path)
    dates = tuple(up.trading_dates(_UP))
    exp_ret, true_ret, days, codes = [], [], [], []
    for day in dates:
        for code, score, actual in ((_UP, up_score, 0.005), (_DOWN, down_score, -0.005)):
            exp_ret.append(score)
            true_ret.append(actual)
            days.append(day.isoformat())
            codes.append(code)
    cache_path = os.path.join(tmpdir, "cross_preds.npz")
    save_prediction_cache(cache_path, np.asarray(exp_ret), np.asarray(true_ret),
                          np.asarray(days, dtype="datetime64[D]"), np.asarray(codes))
    adapter = CnnPredictionAdapter(load_prediction_cache(cache_path), model_name="cnn_transformer",
                                   checkpoint="logs/run_demo/best_model.pth",
                                   bins_version="BINS52_v1", eval_script_version="eval_bins_mapping@v1")
    return provider, adapter, dates


class TestCrossSectionDirection(_TempDirMixin):
    """截面契约：PREDICTED_RETURN/DESCENDING 直供评估，上涨/下跌场景方向与 rank_ic 断言。"""

    SPEC = CrossSectionSpec(holding_days=1, top_n=1, min_cross_section=2, n_quantiles=2)

    def test_uptrend_ranked_first_gives_positive_direction(self) -> None:
        provider, adapter, dates = _cross_section_setup(self.tmp, 0.8, 0.2)
        actuals = adapter.actuals_for_cross_section(dates[0])
        self.assertEqual(set(actuals), {_UP, _DOWN})  # true_ret 唯一出口可用
        self.assertTrue(all(math.isfinite(value) for value in actuals.values()))
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
        provider, adapter, dates = _cross_section_setup(self.tmp, 0.2, 0.8)
        window = dates[:-2]
        scores = {day: adapter.predictions_for_date(day) for day in dates}
        summary = evaluate_cross_section_range(signal_dates=window, market=provider,
                                               scores_by_date=scores, spec=self.SPEC)
        self.assertLess(summary.metrics["ic_mean"], -0.5)
        self.assertLess(summary.metrics["topn_mean_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
