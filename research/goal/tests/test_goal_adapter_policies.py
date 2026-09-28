"""goal_adapter daily/joint 订单策略单测（C04）：unittest.TestCase 风格，双运行器兼容。

零触网；合成 adapter+provider 走内存 fake；goal 无 DB。
"""

import unittest
from datetime import date

from backtest_core.contracts import Prediction, PredictionType, RankingDirection, Side

from goal_adapter.common import signal_time_for


class _FakeBar:
    """内存行情行：仅承载成交额（真实元口径，与 C02 一致）。"""

    def __init__(self, amount=None):
        self.amount = amount


class _FakeProvider:
    """内存行情 fake：(code, date) → amount；缺键返回 None（无行情）。"""

    def __init__(self, amounts=None):
        self._amounts = dict(amounts or {})

    def get_bar(self, instrument_id, trading_date):
        if (instrument_id, trading_date) not in self._amounts:
            return None
        return _FakeBar(self._amounts[(instrument_id, trading_date)])


class _FakeAdapter:
    """内存预测 fake：date → [(code, score_trade)]，排序由策略负责."""

    def __init__(self, sections):
        self._sections = {day: list(rows) for day, rows in sections.items()}

    @property
    def available_dates(self):
        return tuple(sorted(self._sections))

    def predictions_for_date(self, trading_date):
        rows = self._sections.get(trading_date, [])
        return tuple(
            Prediction(
                instrument_id=code,
                signal_time=signal_time_for(trading_date),
                value=value,
                prediction_type=PredictionType.PREDICTED_RETURN,
                ranking_direction=RankingDirection.DESCENDING,
                model_id="fake",
                run_id="fake#v1",
                predicted_horizon=5,
            )
            for code, value in rows
        )


class _FakePosition:
    def __init__(self, shares, price=None):
        self._shares = shares
        self._price = price

    @property
    def shares(self):
        return self._shares

    @property
    def cost(self):
        return 0.0

    @property
    def price(self):
        return self._price

    @property
    def market_value(self):
        return None if self._price is None else self._shares * self._price


class _FakeAccount:
    def __init__(self, cash=100000.0, positions=None):
        self._cash = cash
        self._positions = positions or {}

    @property
    def cash(self):
        return self._cash

    @property
    def available_cash(self):
        return self._cash

    @property
    def positions(self):
        return self._positions

    @property
    def locked(self):
        return {}

    @property
    def nav(self):
        return self._cash + sum((pos.market_value or 0.0) for pos in self._positions.values())


class _FakeMarket:
    """空 MarketView fake：策略不消费 MarketView（护栏走注入 provider），仅满足协议形状."""

    def get_bars(self, instrument_ids, start, end, interval="1d"):
        return {}


DAY = date(2024, 4, 2)


def _section():
    return [(f"C{i:02d}", float(10 - i)) for i in range(6)]


class DailyTopNTests(unittest.TestCase):
    def test_picks_top_n_by_score_trade_descending(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2)
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(), market=_FakeMarket(),
        )
        buys = [o for o in orders if o.side is Side.BUY]
        self.assertEqual([o.instrument_id for o in buys], ["C00", "C01"])

    def test_hold_inside_buffer_sells_outside(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2, sell_buffer=2)
        held = {"C03": _FakePosition(100), "C05": _FakePosition(200)}
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(positions=held), market=_FakeMarket(),
        )
        sells = {o.instrument_id: o.shares for o in orders if o.side is Side.SELL}
        # C03 排名第 4（前 4 允许集内）持有不动；C05 排名第 6 跌出前 4 全卖
        self.assertNotIn("C03", sells)
        self.assertEqual(sells.get("C05"), 200)

    def test_low_liquidity_filtered_and_counted(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        provider = _FakeProvider({("C00", DAY): 5e7, ("C01", DAY): 2e8})
        strategy = DailyOrderStrategy(adapter, provider, top_n=2)
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(), market=_FakeMarket(),
        )
        buys = [o for o in orders if o.side is Side.BUY]
        self.assertEqual([o.instrument_id for o in buys], ["C01"])
        self.assertEqual(strategy.counters.filtered_low_liquidity_count, 1)

    def test_equal_cash_budget_over_targets(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2)
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(cash=100000.0), market=_FakeMarket(),
        )
        buys = [o for o in orders if o.side is Side.BUY]
        self.assertEqual(len(buys), 2)
        for order in buys:
            self.assertAlmostEqual(order.cash_amount, 50000.0)

    def test_unknown_date_fail_fast(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2)
        with self.assertRaises(ValueError):
            strategy.orders_for(
                trading_date=date(2024, 4, 3), signal_time=signal_time_for(date(2024, 4, 3)),
                account=_FakeAccount(), market=_FakeMarket(),
            )


class JointPolicyTests(unittest.TestCase):
    def test_joint_topn_buffer_defaults_match_dispersed(self):
        from goal_adapter.joint_policy import (
            DEFAULT_SELL_BUFFER,
            DEFAULT_TOP_N,
            JointOrderStrategy,
        )

        self.assertEqual((DEFAULT_TOP_N, DEFAULT_SELL_BUFFER), (100, 50))
        adapter = _FakeAdapter({DAY: _section()})
        strategy = JointOrderStrategy(adapter, _FakeProvider())
        self.assertEqual((strategy.top_n, strategy.sell_buffer), (100, 50))

    def test_joint_ranking_and_buffer(self):
        from goal_adapter.joint_policy import JointOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = JointOrderStrategy(adapter, _FakeProvider(), top_n=2, sell_buffer=1)
        held = {"C02": _FakePosition(100), "C05": _FakePosition(100)}
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(positions=held), market=_FakeMarket(),
        )
        sells = {o.instrument_id for o in orders if o.side is Side.SELL}
        # 允许集为前 3：C02（第 3 名）持有不动；C05（第 6 名）全卖
        self.assertNotIn("C02", sells)
        self.assertIn("C05", sells)

    def test_joint_fail_fast_on_unknown_date(self):
        from goal_adapter.joint_policy import JointOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = JointOrderStrategy(adapter, _FakeProvider(), top_n=2)
        with self.assertRaises(ValueError):
            strategy.orders_for(
                trading_date=date(2024, 4, 3), signal_time=signal_time_for(date(2024, 4, 3)),
                account=_FakeAccount(), market=_FakeMarket(),
            )

    def test_joint_low_liquidity_filtered(self):
        from goal_adapter.joint_policy import JointOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        provider = _FakeProvider({("C00", DAY): 1e7, ("C01", DAY): 3e8})
        strategy = JointOrderStrategy(adapter, provider, top_n=2)
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(), market=_FakeMarket(),
        )
        buys = [o for o in orders if o.side is Side.BUY]
        self.assertEqual([o.instrument_id for o in buys], ["C01"])
        self.assertEqual(strategy.counters.filtered_low_liquidity_count, 1)


class ExitAndShadowTests(unittest.TestCase):
    def test_off_target_holdings_fully_sold(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2, sell_buffer=0)
        held = {"C04": _FakePosition(300), "C05": _FakePosition(400)}
        orders = strategy.orders_for(
            trading_date=DAY, signal_time=signal_time_for(DAY),
            account=_FakeAccount(positions=held), market=_FakeMarket(),
        )
        sells = {o.instrument_id: o.shares for o in orders if o.side is Side.SELL}
        self.assertEqual(sells, {"C04": 300, "C05": 400})
        for order in orders:
            if order.side is Side.SELL:
                self.assertIsNone(order.cash_amount)

    def test_no_shadow_account_double_run_consistent(self):
        from goal_adapter.daily_policy import DailyOrderStrategy
        from goal_adapter.joint_policy import JointOrderStrategy

        for factory in (DailyOrderStrategy, JointOrderStrategy):
            adapter = _FakeAdapter({DAY: _section()})
            strategy = factory(adapter, _FakeProvider(), top_n=2)
            account = _FakeAccount(positions={"C05": _FakePosition(100)})
            first = strategy.orders_for(
                trading_date=DAY, signal_time=signal_time_for(DAY), account=account, market=_FakeMarket())
            second = strategy.orders_for(
                trading_date=DAY, signal_time=signal_time_for(DAY), account=account, market=_FakeMarket())
            self.assertEqual(first, second)
            blob = " ".join(vars(strategy).keys())
            for token in ("holding", "position", "cash", "share"):
                self.assertNotIn(token, blob)

    def test_signal_time_mismatch_fail_fast(self):
        from goal_adapter.daily_policy import DailyOrderStrategy

        adapter = _FakeAdapter({DAY: _section()})
        strategy = DailyOrderStrategy(adapter, _FakeProvider(), top_n=2)
        with self.assertRaises(ValueError):
            strategy.orders_for(
                trading_date=DAY, signal_time=signal_time_for(date(2024, 4, 3)),
                account=_FakeAccount(), market=_FakeMarket(),
            )


class CheckpointIsolationTests(unittest.TestCase):
    def test_policy_sources_have_no_checkpoint_or_torch(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "goal_adapter"
        blob = "".join((root / name).read_text(encoding="utf-8") for name in ("daily_policy.py", "joint_policy.py"))
        code = re.sub(r'""".*?"""', "", blob, flags=re.DOTALL)
        code = re.sub(r"#.*", "", code)
        hits = re.findall(r"checkpoint|joblib|pickle|sklearn|torch", code)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
