"""backtest engine 单测（TDD，合成小数据，期望值全部手工推得写死断言）.

口径：open-open（T+1 open 买入 → T+6 open 卖出，跨 horizon=5 交易日），
费用为 A 股真实模型（买卖佣金万2.5 最低 5 元 + 卖出印花税万2.5），本金 capital 折算最低佣金。
"""
import unittest

import numpy as np

from backtest.engine import (
    BUY_COMMISSION_RATE,
    DEFAULT_CAPITAL,
    MIN_COMMISSION,
    SELL_COMMISSION_RATE,
    STAMP_DUTY_RATE,
    BacktestResult,
    benchmark_index_nav,
    benchmark_nav,
    commission,
    limit_up_mask,
    nav_metrics,
    net_return_after_fees,
    run_backtest,
    run_backtest_target,
)

CAP = DEFAULT_CAPITAL


def _roll_ret(buy_notional: float, gross: float) -> float:
    """滚动单笔：买额 buy_notional、卖额 buy_notional×(1+gross) 的净收益（供手算对照）."""
    return net_return_after_fees(buy_notional, buy_notional * (1.0 + gross))


class TestFeeModel(unittest.TestCase):
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


def _days(n: int) -> np.ndarray:
    return np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(n, "D"),
                     dtype="datetime64[D]")


def _synth(n_days: int, rets, t_close: float = 10.0, open_t1: float = 10.0):
    """rets: [(code, gross_ret), ...]；每 (code, day) 一行，ohlc 与 preds 逐样本同构."""
    days = _days(n_days)
    codes, dates, exp_ret = [], [], []
    for i, (c, _) in enumerate(rets):
        codes.extend([c] * n_days)
        dates.extend(days)
        exp_ret.extend([0.50 - 0.01 * i] * n_days)
    codes = np.array(codes)
    dates = np.array(dates, dtype="datetime64[D]")
    exp_ret = np.array(exp_ret, dtype=np.float64)
    oc, od, tc, o1, o6 = [], [], [], [], []
    for c, r in rets:
        oc.extend([c] * n_days)
        od.extend(days)
        tc.extend([t_close] * n_days)
        o1.extend([open_t1] * n_days)
        o6.extend([open_t1 * (1.0 + r)] * n_days)
    ohlc = {"codes": np.array(oc), "dates": np.array(od, dtype="datetime64[D]"),
            "t_close": np.array(tc, dtype=np.float64),
            "open_t1": np.array(o1, dtype=np.float64),
            "open_t6": np.array(o6, dtype=np.float64)}
    return exp_ret, codes, dates, ohlc


class TestLimitUpMask(unittest.TestCase):
    def test_10pct_threshold(self):
        open_t1 = np.array([10.99, 10.97, 10.0])
        t_close = np.array([10.0, 10.0, 10.0])
        codes = np.array(["000001", "000001", "000001"])
        m = limit_up_mask(open_t1, t_close, codes)
        self.assertEqual(m.tolist(), [True, False, False])

    def test_20pct_threshold_300_688(self):
        open_t1 = np.array([11.99, 11.97, 11.00, 11.99])
        t_close = np.full(4, 10.0)
        codes = np.array(["300001", "300001", "300001", "688001"])
        m = limit_up_mask(open_t1, t_close, codes)
        self.assertEqual(m.tolist(), [True, False, False, True])


class TestRunBacktest(unittest.TestCase):
    def test_cost_exact_deduction(self):
        exp_ret, codes, dates, ohlc = _synth(8, [("000001", 0.10)])
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=1)
        self.assertIsInstance(res, BacktestResult)
        # 单票 nav=1：买额=(1/5/1)×1e6=200000，卖额=220000
        nr = _roll_ret(200000.0, 0.10)
        self.assertAlmostEqual(float(res.nav[6]), 1 + 0.2 * nr, places=12)
        self.assertAlmostEqual(float(res.nav[7]), 1 + 0.4 * nr, places=12)
        np.testing.assert_array_equal(res.nav[:6], np.ones(6))
        self.assertEqual(len(res.holdings), 2)
        self.assertEqual(res.skipped, {})

    def test_five_batch_rolling(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(12, rets)
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        # 5 只等权：买额=(1/5/5)×1e6=40000
        nr = _roll_ret(40000.0, 0.10)
        self.assertAlmostEqual(float(res.nav[5]), 1.0, places=12)
        self.assertAlmostEqual(float(res.nav[6]), 1 + 0.2 * nr, places=12)
        self.assertAlmostEqual(float(res.nav[11]), 1 + 6 * 0.2 * nr, places=12)
        self.assertEqual(len(res.holdings), 30)
        np.testing.assert_array_equal(res.holdings["entry_date"][:5], np.tile(_days(12)[0], 5))
        np.testing.assert_array_equal(res.holdings["exit_date"][:5], np.tile(_days(12)[6], 5))

    def test_equal_weight_allocation(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        day0 = res.holdings[res.holdings["entry_date"] == _days(7)[0]]
        self.assertEqual(len(day0), 5)
        np.testing.assert_allclose(day0["weight"], np.full(5, 1.0 / 25.0), atol=1e-15)

    def test_open_open_return_exact(self):
        exp_ret, codes, dates, ohlc = _synth(7, [("000001", 0.25)], open_t1=10.0)
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=1)
        h = res.holdings[0]
        self.assertAlmostEqual(float(h["open_t1"]), 10.0, places=12)
        self.assertAlmostEqual(float(h["open_t6"]), 12.5, places=12)
        self.assertAlmostEqual(float(h["ret_gross"]), 0.25, places=12)
        self.assertAlmostEqual(float(h["ret_net"]), net_return_after_fees(200000.0, 250000.0), places=12)

    def test_skip_limit_up_and_redistribute(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 5)] + [("300005", 0.10)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        m = ohlc["codes"] == "300005"
        ohlc["open_t1"][m] = 12.0
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        day0 = res.holdings[res.holdings["entry_date"] == _days(7)[0]]
        self.assertEqual(len(day0), 4)
        np.testing.assert_allclose(day0["weight"], np.full(4, 0.2 / 4), atol=1e-15)
        self.assertEqual(res.skipped[_days(7)[0]], 1)
        # 4 只等权（涨停剔除后重分）：买额=(1/5/4)×1e6=50000
        self.assertAlmostEqual(float(res.nav[6]), 1 + 0.2 * _roll_ret(50000.0, 0.10), places=12)


class TestRollingFeeModel(unittest.TestCase):
    def test_capital_min_commission_changes_nav(self):
        exp_ret, codes, dates, ohlc = _synth(8, [("000001", 0.10)])
        big = run_backtest(exp_ret, codes, dates, ohlc, topn=1, capital=CAP)
        small = run_backtest(exp_ret, codes, dates, ohlc, topn=1, capital=10000.0)
        # capital=1e4 → 单票买额=(1/5)×1e4=2000 < 20000 → 最低佣金 5 元生效，收益被拉低
        self.assertAlmostEqual(float(small.nav[6]), 1 + 0.2 * _roll_ret(2000.0, 0.10), places=12)
        self.assertLess(float(small.nav[6]), float(big.nav[6]))

    def test_holdings_ret_net_uses_fee_model(self):
        exp_ret, codes, dates, ohlc = _synth(7, [("000001", 0.10)])
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=1)
        expected = net_return_after_fees(200000.0, 220000.0)
        np.testing.assert_allclose(res.holdings["ret_net"], np.full(len(res.holdings), expected), atol=1e-15)

    def test_invalid_fee_inputs_raise(self):
        exp_ret, codes, dates, ohlc = _synth(7, [("000001", 0.10)])
        with self.assertRaises(ValueError):
            run_backtest(exp_ret, codes, dates, ohlc, topn=1, capital=0.0)
        with self.assertRaises(ValueError):
            run_backtest(exp_ret, codes, dates, ohlc, topn=1, buy_rate=-0.001)


class TestBenchmarkAndEdges(unittest.TestCase):
    def test_benchmark_equal_weight_no_limit_filter(self):
        rets = [("000001", 0.10), ("000002", -0.10)]
        _, codes, dates, ohlc = _synth(7, rets)
        m = ohlc["codes"] == "000001"
        ohlc["open_t1"][m] = 12.0
        nav = benchmark_nav(codes, dates, ohlc)
        self.assertEqual(len(nav), 7)
        # 全截面 2 只等权：买额=(1/5/2)×1e6=100000
        self.assertAlmostEqual(
            float(nav[6]),
            1 + 0.1 * _roll_ret(100000.0, 11.0 / 12.0 - 1.0) + 0.1 * _roll_ret(100000.0, -0.10),
            places=12)
        np.testing.assert_array_equal(nav[:6], np.ones(6))

    def test_all_nan_path_empty_batches(self):
        exp_ret, codes, dates, ohlc = _synth(7, [("000001", 0.10), ("000002", 0.10)])
        ohlc["open_t1"][:] = np.nan
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=2)
        np.testing.assert_array_equal(res.nav, np.ones(7))
        self.assertEqual(len(res.holdings), 0)
        self.assertEqual(res.skipped, {})

    def test_zero_samples(self):
        exp_ret = np.array([], dtype=np.float64)
        codes = np.array([], dtype="U6")
        dates = np.array([], dtype="datetime64[D]")
        ohlc = {"codes": np.array([], dtype="U6"), "dates": np.array([], dtype="datetime64[D]"),
                "t_close": np.array([], dtype=np.float64), "open_t1": np.array([], dtype=np.float64),
                "open_t6": np.array([], dtype=np.float64)}
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        np.testing.assert_array_equal(res.nav, np.ones(1))

    def test_single_stock_topn_exceeds(self):
        exp_ret, codes, dates, ohlc = _synth(7, [("000001", 0.10)])
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        self.assertAlmostEqual(float(res.holdings[0]["weight"]), 0.2, places=12)
        self.assertAlmostEqual(float(res.nav[6]), 1 + 0.2 * _roll_ret(200000.0, 0.10), places=12)

    def test_all_limit_up(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        ohlc["open_t1"][:] = 10.99
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        np.testing.assert_array_equal(res.nav, np.ones(7))
        self.assertEqual(len(res.holdings), 0)
        self.assertEqual(res.skipped[_days(7)[0]], 5)


class TestLookaheadAndOrdering(unittest.TestCase):
    def test_no_lookahead_future_rows_do_not_affect_past_nav(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(12, rets)
        base = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        exp2 = exp_ret.copy()
        exp2[dates >= _days(12)[6]] = 0.99
        ohlc2 = {k: v.copy() for k, v in ohlc.items()}
        fut = ohlc2["dates"] >= _days(12)[6]
        for k in ("t_close", "open_t1", "open_t6"):
            ohlc2[k][fut] += 0.5
        alt = run_backtest(exp2, codes, dates, ohlc2, topn=5)
        np.testing.assert_array_equal(base.nav[:6], alt.nav[:6])

    def test_stable_tie_break_keeps_cross_section_order(self):
        rets = [("000001", 0.10), ("000002", 0.10)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        exp_ret[:] = 0.5
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=1)
        day0 = res.holdings[res.holdings["entry_date"] == _days(7)[0]]
        self.assertEqual(day0["code"].tolist(), ["000001"])

    def test_nan_open_t6_excluded_not_counted_as_limit(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        ohlc["open_t6"][ohlc["codes"] == "000005"] = np.nan
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        day0 = res.holdings[res.holdings["entry_date"] == _days(7)[0]]
        self.assertEqual(len(day0), 4)
        self.assertEqual(res.skipped, {})


class TestNavMetrics(unittest.TestCase):
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


def _target_fixture(specs, n_days, opens=None, closes=None):
    """specs: [(code, exp_ret)]，exp_ret 可为标量或逐日 list；返回全票全日在截面的矩阵 fixture."""
    days = _days(n_days)
    n_c = len(specs)
    open_m = np.full((n_c, n_days), 10.0) if opens is None else np.asarray(opens, dtype=np.float64)
    close_m = np.full((n_c, n_days), 10.0) if closes is None else np.asarray(closes, dtype=np.float64)
    exp_ret, scodes, sdates = [], [], []
    for j in range(n_days):
        for c, es in specs:
            exp_ret.append(es[j] if isinstance(es, list) else es)
            scodes.append(c)
            sdates.append(days[j])
    ohlc = {"codes": np.array([c for c, _ in specs]), "dates": days, "open_m": open_m, "close_m": close_m}
    return (np.array(exp_ret, dtype=np.float64), np.array(scodes),
            np.array(sdates, dtype="datetime64[D]"), ohlc)


class TestRunBacktestTarget(unittest.TestCase):
    def test_buy_top_zone_open_t1(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30), ("000002", 0.20)], 4)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, sell_buffer=200)
        # 单槽预算=(1/2)×1e6=500000 ≥ B* → 费率生效；扣买佣后 nav=1/1.00025
        self.assertAlmostEqual(float(res.nav[0]), 1.0, places=12)
        self.assertAlmostEqual(float(res.nav[1]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[2]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[3]), 0.9995 / 1.00025, places=12)
        self.assertEqual(len(res.holdings), 2)
        self.assertEqual(set(res.holdings["code"].tolist()), {"000001", "000002"})
        np.testing.assert_array_equal(res.holdings["entry_date"], np.tile(_days(4)[1], 2))
        np.testing.assert_array_equal(res.holdings["exit_date"], np.tile(_days(4)[3], 2))
        self.assertEqual(res.skipped, {})


    def test_buffer_zone_hold(self):
        specs = [("000001", [0.30, 0.20, 0.20, 0.20, 0.20]), ("000002", [0.20, 0.30, 0.30, 0.30, 0.30])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 5)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=1)
        self.assertAlmostEqual(float(res.nav[1]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[2]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[3]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[4]), 0.9995 / 1.00025, places=12)
        self.assertEqual(len(res.holdings), 1)
        self.assertEqual(res.holdings["code"][0], "000001")
        self.assertEqual(res.holdings["entry_date"][0], _days(5)[1])
        self.assertEqual(res.holdings["exit_date"][0], _days(5)[4])
        self.assertEqual(res.skipped, {})

    def test_sell_beyond_buffer_open_t1(self):
        specs = [("000001", [0.30, 0.10, 0.05, 0.05, 0.05]),
                 ("000002", [0.20, 0.30, 0.30, 0.30, 0.30]),
                 ("000003", [0.10, 0.20, 0.30, 0.30, 0.30])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 5)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=1)
        cash_after_sell = 1.0 / 1.00025 * 0.9995
        self.assertAlmostEqual(float(res.nav[1]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[2]), cash_after_sell / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[3]), cash_after_sell / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[4]), cash_after_sell / 1.00025 * 0.9995, places=12)
        self.assertEqual(res.holdings["code"].tolist(), ["000001", "000002"])
        self.assertEqual(res.holdings["exit_date"][0], _days(5)[2])
        self.assertEqual(res.holdings["entry_date"][1], _days(5)[2])
        self.assertAlmostEqual(float(res.holdings["ret_gross"][0]), 0.0, places=12)
        self.assertAlmostEqual(float(res.holdings["ret_net"][0]), 0.9995 / 1.00025 - 1.0, places=12)


    def test_min_edge_tail_skipped_cash(self):
        specs = [("000001", 0.20), ("000002", 0.005), ("000003", 0.001)]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 4)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, sell_buffer=10,
                                  min_edge=0.01, edge_tail_pct=0.5)
        self.assertAlmostEqual(float(res.nav[1]), 0.5 + 0.5 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[2]), 0.5 + 0.5 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[3]), 0.5 + 0.5 * 0.9995 / 1.00025, places=12)
        self.assertEqual(len(res.holdings), 1)
        self.assertEqual(res.holdings["code"][0], "000001")
        self.assertEqual(res.skipped[_days(4)[1]], {"min_edge": 1})
        self.assertEqual(res.skipped[_days(4)[2]], {"min_edge": 1})
        self.assertEqual(len(res.skipped), 2)

    def test_min_edge_front_rank_low_exp_buys_boundary(self):
        exp_ret, codes, dates, ohlc = _target_fixture(
            [("000001", 0.003), ("000002", 0.01), ("000003", 0.001)], 4)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=3, sell_buffer=10,
                                  min_edge=0.01, edge_tail_pct=0.25)
        self.assertAlmostEqual(float(res.nav[1]), (1.0 + 2.0 / 1.00025) / 3.0, places=12)
        self.assertAlmostEqual(float(res.nav[3]), (1.0 + 2.0 * 0.9995 / 1.00025) / 3.0, places=12)
        self.assertEqual(len(res.holdings), 2)
        self.assertEqual(set(res.holdings["code"].tolist()), {"000001", "000002"})
        self.assertEqual(res.skipped[_days(4)[1]], {"min_edge": 1})


    def test_force_liquidation_last_day(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30)], 5)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=10)
        self.assertAlmostEqual(float(res.nav[1]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[3]), 1.0 / 1.00025, places=12)
        self.assertAlmostEqual(float(res.nav[4]), 0.9995 / 1.00025, places=12)
        self.assertEqual(len(res.holdings), 1)
        self.assertEqual(res.holdings["entry_date"][0], _days(5)[1])
        self.assertEqual(res.holdings["exit_date"][0], _days(5)[4])

    def test_nav_daily_mark_open(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30)], 4, opens=[[10.0, 10.0, 11.0, 9.0]])
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=10)
        shares = 1.0 / (10.0 * 1.00025)
        self.assertAlmostEqual(float(res.nav[1]), shares * 10.0, places=12)
        self.assertAlmostEqual(float(res.nav[2]), shares * 11.0, places=12)
        self.assertAlmostEqual(float(res.nav[3]), shares * 9.0 * 0.9995, places=12)
        self.assertAlmostEqual(float(res.holdings["open_t1"][0]), 10.0, places=12)
        self.assertAlmostEqual(float(res.holdings["open_t6"][0]), 9.0, places=12)


    def test_limit_up_skip_buy(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30)], 4, opens=[[11.0] * 4],
                                                      closes=[[10.0] * 4])
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=10)
        np.testing.assert_array_equal(res.nav, np.ones(4))
        self.assertEqual(len(res.holdings), 0)
        self.assertEqual(res.skipped[_days(4)[1]], {"limit_up": 1})
        self.assertEqual(res.skipped[_days(4)[2]], {"limit_up": 1})
        self.assertEqual(len(res.skipped), 2)

    def test_no_lookahead_future_rows_do_not_affect_past_nav(self):
        specs = [("000001", [0.30, 0.10, 0.05, 0.05, 0.05]),
                 ("000002", [0.20, 0.30, 0.30, 0.30, 0.30]),
                 ("000003", [0.10, 0.20, 0.30, 0.30, 0.30])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 5)
        base = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=1)
        exp2 = exp_ret.copy()
        exp2[dates >= _days(5)[2]] = 0.99
        ohlc2 = {k: v.copy() for k, v in ohlc.items()}
        ohlc2["open_m"][:, 2:] += 0.5
        ohlc2["close_m"][:, 2:] += 0.5
        alt = run_backtest_target(exp2, codes, dates, ohlc2, target_size=1, sell_buffer=1)
        np.testing.assert_array_equal(base.nav[:2], alt.nav[:2])

    def test_zero_samples_target(self):
        _, _, _, ohlc = _target_fixture([("000001", 0.30), ("000002", 0.20)], 3)
        res = run_backtest_target(np.array([], dtype=np.float64), np.array([], dtype="U6"),
                                  np.array([], dtype="datetime64[D]"), ohlc, target_size=2)
        np.testing.assert_array_equal(res.nav, np.ones(3))
        self.assertEqual(len(res.holdings), 0)
        self.assertEqual(res.skipped, {})


class TestTargetFeeAndExit(unittest.TestCase):
    def test_buy_solver_two_cases(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30), ("000002", 0.20)], 4)
        # 费率情形：budget=500000 ≥ B*=20005 → shares=budget/(px×(1+buy_rate))
        rate_res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, capital=CAP)
        self.assertAlmostEqual(float(rate_res.nav[1]), 1.0 / 1.00025, places=12)
        # 最低佣金情形：capital=4e4 → budget=20000 < B* → shares=(budget−5)/px=1999.5
        min_res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, capital=40000.0)
        self.assertAlmostEqual(float(min_res.nav[1]), 0.99975, places=12)
        self.assertNotAlmostEqual(float(rate_res.nav[1]), float(min_res.nav[1]), places=10)

    def test_budget_not_enough_skipped(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30), ("000002", 0.20)], 3)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, capital=8.0)
        np.testing.assert_array_equal(res.nav, np.ones(3))
        self.assertEqual(len(res.holdings), 0)

    def test_default_sell_buffer_500_bounds(self):
        # 持仓跌至 rank 300（≤1+500）不卖；次日 rank 502（>501）卖出
        n_days = 5
        others = [f"{i:06d}" for i in range(501)]
        held = "999999"
        days = _days(n_days)
        exp_day = {0: {c: 0.0 for c in others},
                   1: {c: (0.01 if i < 299 else 0.0) for i, c in enumerate(others)},
                   2: {c: 0.0 for c in others}, 3: {c: 0.0 for c in others}, 4: {c: 0.0 for c in others}}
        exp_day[0][held] = 0.9
        exp_day[1][held] = 0.005
        for d in (2, 3, 4):
            exp_day[d][held] = -0.5
        specs = [(c, [exp_day[d][c] for d in range(n_days)]) for c in others + [held]]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, n_days)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1)
        held_holds = res.holdings[res.holdings["code"] == held]
        self.assertEqual(len(held_holds), 1)
        self.assertEqual(held_holds["exit_date"][0], days[3])

    def test_exit_on_nonpositive_sells(self):
        specs = [("000001", [0.90, 0.00, 0.00, 0.00, 0.00]),
                 ("000002", [0.10, 0.50, 0.50, 0.50, 0.50]),
                 ("000003", [0.20, 0.20, 0.20, 0.20, 0.20])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 5)
        hold = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1)
        self.assertEqual(hold.holdings[0]["code"], "000001")
        self.assertEqual(hold.holdings[0]["exit_date"], _days(5)[4])
        ex = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, exit_on_nonpositive=True)
        self.assertEqual(ex.holdings[0]["code"], "000001")
        self.assertEqual(ex.holdings[0]["exit_date"], _days(5)[2])

    def test_exit_threshold_configurable(self):
        specs = [("000001", [0.90, 0.005, 0.005, 0.005, 0.005]),
                 ("000002", [0.10, 0.50, 0.50, 0.50, 0.50])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 5)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1,
                                  exit_on_nonpositive=True, exit_threshold=0.01)
        self.assertEqual(res.holdings[0]["code"], "000001")
        self.assertEqual(res.holdings[0]["exit_date"], _days(5)[2])

    def test_missing_pred_does_not_force_exit(self):
        days = _days(5)
        samples = [[("000001", 0.9), ("000002", 0.1)], [("000001", 0.5), ("000002", 0.1)],
                   [("000002", 0.5)], [("000001", 0.5), ("000002", 0.1)],
                   [("000001", 0.5), ("000002", 0.1)]]
        exp_ret, scodes, sdates = [], [], []
        for j, row in enumerate(samples):
            for c, e in row:
                exp_ret.append(e)
                scodes.append(c)
                sdates.append(days[j])
        ohlc = {"codes": np.array(["000001", "000002"]), "dates": days,
                "open_m": np.full((2, 5), 10.0), "close_m": np.full((2, 5), 10.0)}
        res = run_backtest_target(np.array(exp_ret, dtype=np.float64), np.array(scodes),
                                  np.array(sdates, dtype="datetime64[D]"), ohlc,
                                  target_size=1, exit_on_nonpositive=True)
        self.assertEqual(res.holdings[0]["code"], "000001")
        self.assertEqual(res.holdings[0]["exit_date"], days[4])

    def test_target_invalid_fee_inputs_raise(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30)], 3)
        with self.assertRaises(ValueError):
            run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, capital=-1.0)
        with self.assertRaises(ValueError):
            run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, stamp_rate=-0.001)


class TestAvgCashRatio(unittest.TestCase):
    def test_rolling_avg_cash_ratio_zero(self):
        rets = [(f"00000{i}", 0.10) for i in range(1, 6)]
        exp_ret, codes, dates, ohlc = _synth(7, rets)
        res = run_backtest(exp_ret, codes, dates, ohlc, topn=5)
        self.assertEqual(res.avg_cash_ratio, 0.0)

    def test_target_fully_invested_near_zero(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30), ("000002", 0.20)], 41)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=2, sell_buffer=500)
        self.assertGreaterEqual(res.avg_cash_ratio, 0.0)
        self.assertLess(res.avg_cash_ratio, 0.06)  # 仅首日未建仓、末日清仓为现金

    def test_target_exit_raises_cash_ratio(self):
        specs = [("000001", [0.90, 0.00, 0.00, 0.00, 0.00, 0.00])]
        exp_ret, codes, dates, ohlc = _target_fixture(specs, 6)
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, exit_on_nonpositive=True)
        self.assertGreater(res.avg_cash_ratio, 0.5)
        self.assertLessEqual(res.avg_cash_ratio, 1.0)

    def test_target_all_cash_when_limit_up(self):
        exp_ret, codes, dates, ohlc = _target_fixture([("000001", 0.30)], 4,
                                                      opens=[[11.0] * 4], closes=[[10.0] * 4])
        res = run_backtest_target(exp_ret, codes, dates, ohlc, target_size=1, sell_buffer=10)
        self.assertEqual(res.avg_cash_ratio, 1.0)

    def test_target_no_signals_all_cash(self):
        _, _, _, ohlc = _target_fixture([("000001", 0.30)], 5)
        res = run_backtest_target(np.array([], dtype=np.float64), np.array([], dtype="U6"),
                                  np.array([], dtype="datetime64[D]"), ohlc, target_size=1)
        self.assertEqual(res.avg_cash_ratio, 1.0)


class TestBenchmarkIndexNav(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
