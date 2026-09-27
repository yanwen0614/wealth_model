"""B02: CnnMarketDataProvider 单测（TDD，合成 parquet + 真实小样本，只读零触网）.

合成表经 tempfile 落盘走真实 pyarrow 读路径；真实 parquet 缺文件显式 skip。
"""
import datetime
import os
import shutil
import tempfile
import unittest

import pandas as pd

from backtest.cnn_adapter.market import AMOUNT_UNIT, VOLUME_UNIT, CnnMarketDataProvider

CODE_A = "000001.SZ"
CODE_B = "600000.SH"


def _write_parquet(rows: list[dict], path: str) -> str:
    frame = pd.DataFrame(rows, columns=["code", "kline_time", "open", "high", "low", "close",
                                        "volume", "amount", "is_trading"])
    frame.to_parquet(path, index=False)
    return path


def _row(code: str, day: str, **overrides) -> dict:
    base = {"code": code, "kline_time": pd.Timestamp(day), "open": 10.0, "high": 10.5,
            "low": 9.8, "close": 10.2, "volume": 1_000_000.0, "amount": 10_200_000.0,
            "is_trading": True}
    base.update(overrides)
    return base


def _suspended_row(code: str, day: str) -> dict:
    # 与真实 parquet 同口径：停牌合成行 OHLC=NaN、volume/amount=0
    return _row(code, day, open=float("nan"), high=float("nan"), low=float("nan"),
                close=float("nan"), volume=0.0, amount=0.0, is_trading=False)


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b02_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tmp_path(self, name: str) -> str:
        return os.path.join(self.tmp, name)


class TestSuspendedBar(_TempDirMixin):
    def test_is_trading_false_maps_to_all_none(self):
        path = _write_parquet([_row(CODE_A, "2025-01-02"),
                               _suspended_row(CODE_A, "2025-01-03"),
                               _row(CODE_A, "2025-01-06")], self.tmp_path("s.parquet"))
        provider = CnnMarketDataProvider(path)
        bar = provider.get_bar(CODE_A, datetime.date(2025, 1, 3))
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertFalse(bar.is_trading)
        # 禁 0.0 填充：停牌 bar 价格与量必须全 None（0 会被引擎误读为有效报价）
        self.assertIsNone(bar.open)
        self.assertIsNone(bar.high)
        self.assertIsNone(bar.low)
        self.assertIsNone(bar.close)
        self.assertIsNone(bar.volume)
        self.assertIsNone(bar.amount)
        self.assertEqual(provider.counters.suspended_bar_count, 1)

    def test_trading_bar_keeps_values(self):
        path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("t.parquet"))
        provider = CnnMarketDataProvider(path)
        bar = provider.get_bar(CODE_A, datetime.date(2025, 1, 2))
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertTrue(bar.is_trading)
        self.assertAlmostEqual(bar.close if bar.close is not None else -1.0, 10.2)


class TestMissingBar(_TempDirMixin):
    def test_unknown_date_returns_none_and_counts(self):
        path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("m.parquet"))
        provider = CnnMarketDataProvider(path)
        self.assertIsNone(provider.get_bar(CODE_A, datetime.date(2025, 1, 3)))
        self.assertEqual(provider.counters.missing_bar_count, 1)

    def test_missing_price_row_counts_but_keeps_trading_flag(self):
        path = _write_parquet([_row(CODE_A, "2025-01-02", close=float("nan"))],
                              self.tmp_path("p.parquet"))
        provider = CnnMarketDataProvider(path)
        bar = provider.get_bar(CODE_A, datetime.date(2025, 1, 2))
        self.assertIsNotNone(bar)
        assert bar is not None
        self.assertTrue(bar.is_trading)
        self.assertIsNone(bar.close)
        self.assertEqual(provider.counters.missing_bar_count, 1)


class TestUnits(_TempDirMixin):
    def test_unit_constants_mean_no_rescale(self):
        self.assertEqual(VOLUME_UNIT, 1.0)
        self.assertEqual(AMOUNT_UNIT, 1.0)

    def test_bar_values_match_parquet_raw(self):
        import pyarrow.parquet as pq

        path = _write_parquet([_row(CODE_A, "2025-01-02", volume=1_234_567.0, amount=12_345_678.0)],
                              self.tmp_path("u.parquet"))
        provider = CnnMarketDataProvider(path)
        bar = provider.get_bar(CODE_A, datetime.date(2025, 1, 2))
        assert bar is not None
        raw = pq.read_table(path, columns=["volume", "amount"]).to_pandas().iloc[0]
        # parquet 已是真实股/元：provider 不得二次缩放，必须与直读值逐值相等
        self.assertEqual(bar.volume, float(raw["volume"]))
        self.assertEqual(bar.amount, float(raw["amount"]))
        self.assertEqual(provider.amount_basis, "yuan")
        assert bar.volume is not None and bar.amount is not None
        implied_price = bar.amount / bar.volume
        self.assertGreater(implied_price, 2.0)
        self.assertLess(implied_price, 60.0)


class TestLimitGrid(_TempDirMixin):
    def _provider_two_days(self, code: str, prev_close: float, close: float,
                           st_codes=frozenset()) -> CnnMarketDataProvider:
        path = self.tmp_path(f"{code}.parquet")
        _write_parquet([_row(code, "2025-01-02", open=prev_close, high=prev_close,
                             low=prev_close, close=prev_close),
                        _row(code, "2025-01-03", open=close, high=close,
                             low=close, close=close)], path)
        return CnnMarketDataProvider(path, st_codes=st_codes)

    def test_main_board_10pct(self):
        up = self._provider_two_days("600000.SH", 10.0, 11.0)
        bar = up.get_bar("600000.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_up)
        self.assertFalse(bar.limit_down)
        down = self._provider_two_days("600000.SH", 10.0, 9.0)
        bar = down.get_bar("600000.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_down)
        self.assertFalse(bar.limit_up)
        flat = self._provider_two_days("600000.SH", 10.0, 10.5)
        bar = flat.get_bar("600000.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertFalse(bar.limit_up)
        self.assertFalse(bar.limit_down)

    def test_chinext_20pct_and_bse_30pct(self):
        provider = self._provider_two_days("300001.SZ", 10.0, 11.5)
        bar = provider.get_bar("300001.SZ", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertFalse(bar.limit_up)
        provider = self._provider_two_days("300001.SZ", 10.0, 12.0)
        bar = provider.get_bar("300001.SZ", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_up)
        provider = self._provider_two_days("430001.BJ", 10.0, 12.9)
        bar = provider.get_bar("430001.BJ", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertFalse(bar.limit_up)
        provider = self._provider_two_days("430001.BJ", 10.0, 13.0)
        bar = provider.get_bar("430001.BJ", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_up)

    def test_st_main_board_5pct(self):
        st = self._provider_two_days("600001.SH", 10.0, 10.5, st_codes=frozenset({"600001.SH"}))
        bar = st.get_bar("600001.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_up)
        plain = self._provider_two_days("600001.SH", 10.0, 10.5)
        bar = plain.get_bar("600001.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertFalse(bar.limit_up)

    def test_sz_min_tick_rule(self):
        # 前收 0.04：10% 限制价 0.044 取整回 0.04，深市补一跳至 0.05；沪市无此条
        provider = self._provider_two_days("000001.SZ", 0.04, 0.04)
        bar = provider.get_bar("000001.SZ", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertFalse(bar.limit_up)
        provider = self._provider_two_days("600000.SH", 0.04, 0.04)
        bar = provider.get_bar("600000.SH", datetime.date(2025, 1, 3))
        assert bar is not None
        self.assertTrue(bar.limit_up)

    def test_first_bar_limit_unknown(self):
        path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("f.parquet"))
        provider = CnnMarketDataProvider(path)
        bar = provider.get_bar(CODE_A, datetime.date(2025, 1, 2))
        assert bar is not None
        self.assertFalse(bar.limit_up)
        self.assertFalse(bar.limit_down)
        self.assertEqual(provider.counters.limit_unknown_count, 1)


class TestLookahead(_TempDirMixin):
    def _provider_gap(self) -> CnnMarketDataProvider:
        # 01-06 缺行（缺失日期）：get_history 不得填充，只能返回 present 日期
        path = _write_parquet([_row(CODE_A, "2025-01-02"), _row(CODE_A, "2025-01-03"),
                               _suspended_row(CODE_A, "2025-01-06"),
                               _row(CODE_A, "2025-01-07")], self.tmp_path("g.parquet"))
        return CnnMarketDataProvider(path)

    def test_range_is_right_closed_ascending_without_fill(self):
        provider = self._provider_gap()
        bars = provider.get_history(CODE_A, datetime.date(2025, 1, 2), datetime.date(2025, 1, 7))
        self.assertEqual([b.trading_date for b in bars],
                         [datetime.date(2025, 1, 2), datetime.date(2025, 1, 3),
                          datetime.date(2025, 1, 6), datetime.date(2025, 1, 7)])
        suspended = [b for b in bars if b.trading_date == datetime.date(2025, 1, 6)]
        self.assertEqual(len(suspended), 1)
        self.assertFalse(suspended[0].is_trading)

    def test_range_excludes_future(self):
        provider = self._provider_gap()
        bars = provider.get_history(CODE_A, datetime.date(2025, 1, 2), datetime.date(2025, 1, 3))
        self.assertEqual(len(bars), 2)
        self.assertTrue(all(b.trading_date <= datetime.date(2025, 1, 3) for b in bars))

    def test_protocol_mode_lookback_counts_present_days(self):
        provider = self._provider_gap()
        bars = provider.get_history(CODE_A, datetime.date(2025, 1, 7), 2)
        self.assertEqual([b.trading_date for b in bars],
                         [datetime.date(2025, 1, 6), datetime.date(2025, 1, 7)])


class TestMarketStateBatch(_TempDirMixin):
    def test_to_market_state_serves_get_bars(self):
        from backtest_core.engine.market_state import MarketState

        path = _write_parquet([_row(CODE_A, "2025-01-02"), _row(CODE_A, "2025-01-03"),
                               _row(CODE_B, "2025-01-02"), _suspended_row(CODE_B, "2025-01-03")],
                              self.tmp_path("b.parquet"))
        provider = CnnMarketDataProvider(path)
        state = provider.to_market_state()
        self.assertIsInstance(state, MarketState)
        got = state.get_bars([CODE_A, CODE_B], datetime.date(2025, 1, 2), datetime.date(2025, 1, 3))
        self.assertEqual(set(got.keys()), {CODE_A, CODE_B})
        self.assertEqual([b.trading_date for b in got[CODE_A]],
                         [datetime.date(2025, 1, 2), datetime.date(2025, 1, 3)])
        self.assertFalse(got[CODE_B][1].is_trading)
        self.assertIsNone(got[CODE_B][1].close)


class TestOhlcPath(_TempDirMixin):
    def _write_ohlc(self, name: str, drop: str | None = None) -> str:
        import numpy as np

        dates = np.arange(np.datetime64("2025-01-02"), np.datetime64("2025-01-04"), dtype="datetime64[D]")
        arrays = {"codes": np.array([CODE_A, CODE_A]), "dates": dates,
                  "t_close": np.array([10.2, 10.4]), "open_t1": np.array([10.3, 10.5]),
                  "open_t6": np.array([10.8, 11.0])}
        if drop is not None:
            del arrays[drop]
        path = self.tmp_path(name)
        np.savez(path, **arrays)
        return path

    def test_ohlc_lookup_after_validation(self):
        market_path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("m.parquet"))
        provider = CnnMarketDataProvider(market_path, ohlc_path=self._write_ohlc("o.npz"))
        self.assertEqual(provider.get_ohlc_path(CODE_A, datetime.date(2025, 1, 2)), (10.2, 10.3, 10.8))
        self.assertIsNone(provider.get_ohlc_path(CODE_A, datetime.date(2025, 1, 9)))

    def test_bad_ohlc_rejected(self):
        market_path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("m.parquet"))
        with self.assertRaises(ValueError):
            CnnMarketDataProvider(market_path, ohlc_path=self._write_ohlc("bad.npz", drop="open_t6"))

    def test_no_ohlc_returns_none(self):
        market_path = _write_parquet([_row(CODE_A, "2025-01-02")], self.tmp_path("m.parquet"))
        self.assertIsNone(CnnMarketDataProvider(market_path).get_ohlc_path(CODE_A, datetime.date(2025, 1, 2)))


class TestRealParquet(unittest.TestCase):
    @staticmethod
    def _find_real_parquet() -> str | None:
        import glob

        hits = sorted(glob.glob("data/test/train_data/*.parquet"))
        return hits[0] if hits else None

    def test_two_codes_sixty_days_match_raw(self):
        import pyarrow.parquet as pq

        real = self._find_real_parquet()
        if real is None:
            self.skipTest("真实 parquet 缺文件")
        assert real is not None
        provider = CnnMarketDataProvider(real)
        for code in (CODE_A, CODE_B):
            frame = pq.read_table(real, columns=list(_READ_COLS_SAFE),
                                  filters=[("code", "=", code)]).to_pandas()
            frame["kline_time"] = pd.to_datetime(frame["kline_time"])
            frame = frame.sort_values("kline_time").reset_index(drop=True)
            window = frame.tail(60)
            checked = 0
            for _, row in window.iterrows():
                day = row["kline_time"].date()
                bar = provider.get_bar(code, day)
                self.assertIsNotNone(bar)
                assert bar is not None
                if bool(row["is_trading"]):
                    self.assertTrue(bar.is_trading)
                    if pd.notna(row["volume"]):
                        self.assertEqual(bar.volume, float(row["volume"]))
                    if pd.notna(row["amount"]):
                        self.assertEqual(bar.amount, float(row["amount"]))
                    if pd.notna(row["amount"]) and pd.notna(row["volume"]) and float(row["volume"]) > 0:
                        implied = float(row["amount"]) / float(row["volume"])
                        self.assertGreater(implied, 1.0)
                        self.assertLess(implied, 200.0)
                    checked += 1
                else:
                    self.assertFalse(bar.is_trading)
                    self.assertIsNone(bar.close)
                    self.assertIsNone(bar.volume)
            self.assertGreater(checked, 0)


_READ_COLS_SAFE = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]


if __name__ == "__main__":
    unittest.main()
