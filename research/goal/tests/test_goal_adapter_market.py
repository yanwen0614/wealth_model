"""goal_adapter.market 单测（C02）：unittest.TestCase 风格，双运行器兼容。

零触网；合成 parquet 走 tempfile（列对齐实证列名子集）；真实 parquet 只读列子集
小样本（文件缺失显式 skip）；goal 无 DB。
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow.parquet as pq

from goal_adapter.market import AMOUNT_UNIT, VOLUME_UNIT, GoalMarketDataProvider

COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]


def _frame(rows):
    """合成行 → DataFrame（列对齐实证列名子集；kline_time 为 datetime）。"""
    df = pd.DataFrame(rows, columns=COLS)
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    return df


def _write(path, df):
    df.to_parquet(path, index=False)


def _trading_row(code, day, close, prev_close=None, volume=1_000_000.0):
    """合成正常交易行：OHLC 围绕 close，amount=close×volume（implied price=close）。"""
    base = close if prev_close is None else prev_close
    _ = base
    return (code, day, close - 0.1, close + 0.1, close - 0.2, close,
            volume, close * volume, True)


def _suspended_row(code, day):
    """合成停牌行：与实证一致——OHLC 全 NaN、volume/amount 记 0.0（provider 须转 None）。"""
    return (code, day, float("nan"), float("nan"), float("nan"), float("nan"), 0.0, 0.0, False)


class ConcatDedupTests(unittest.TestCase):
    def test_overlay_wins_overlap_and_counts_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            overlay = Path(tmp) / "overlay.parquet"
            code = "000001.SZ"
            _write(primary, _frame([
                _trading_row(code, "2026-01-05", 10.0),
                _trading_row(code, "2026-01-06", 10.5),
            ]))
            _write(overlay, _frame([
                _trading_row(code, "2026-01-06", 99.0),  # 重叠行：overlay 优先
                _trading_row(code, "2026-01-07", 11.0),
            ]))
            provider = GoalMarketDataProvider(str(primary), str(overlay))
            bar = provider.get_bar(code, date(2026, 1, 6))
            self.assertIsNotNone(bar)
            assert bar is not None
            self.assertAlmostEqual(bar.close if bar.close is not None else float("nan"), 99.0)
            self.assertEqual(provider.counters.dedup_overlap_count, 1)
            history = provider.get_history(code, date(2026, 1, 5), date(2026, 1, 7))
            self.assertEqual([b.trading_date for b in history],
                             [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)])

    def test_primary_only_without_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "600000.SH"
            _write(primary, _frame([_trading_row(code, "2026-01-05", 20.0)]))
            provider = GoalMarketDataProvider(str(primary))
            bar = provider.get_bar(code, date(2026, 1, 5))
            self.assertIsNotNone(bar)
            assert bar is not None
            self.assertAlmostEqual(bar.close if bar.close is not None else float("nan"), 20.0)
            self.assertEqual(provider.counters.dedup_overlap_count, 0)


class NoneSemanticsTests(unittest.TestCase):
    def test_suspended_row_maps_to_all_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "000001.SZ"
            _write(primary, _frame([
                _trading_row(code, "2026-01-05", 10.0),
                _suspended_row(code, "2026-01-06"),  # parquet 口径：OHLC NaN + 量额 0.0
                _trading_row(code, "2026-01-07", 10.2),
            ]))
            provider = GoalMarketDataProvider(str(primary))
            bar = provider.get_bar(code, date(2026, 1, 6))
            self.assertIsNotNone(bar)
            assert bar is not None
            self.assertFalse(bar.is_trading)
            self.assertIsNone(bar.open)
            self.assertIsNone(bar.high)
            self.assertIsNone(bar.low)
            self.assertIsNone(bar.close)
            self.assertIsNone(bar.volume)  # 禁 0.0 冒充
            self.assertIsNone(bar.amount)
            self.assertEqual(provider.counters.suspended_bar_count, 1)

    def test_missing_date_returns_none_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "000001.SZ"
            _write(primary, _frame([_trading_row(code, "2026-01-05", 10.0)]))
            provider = GoalMarketDataProvider(str(primary))
            self.assertIsNone(provider.get_bar(code, date(2026, 1, 6)))
            self.assertIsNone(provider.get_bar(code, date(2026, 1, 6)))  # 重复查询去重计数
            self.assertEqual(provider.counters.missing_bar_count, 1)
            self.assertEqual(provider.counters.suspended_bar_count, 0)

    def test_trading_row_with_nan_price_keeps_none_and_counts_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "000001.SZ"
            bad = (code, "2026-01-05", float("nan"), 10.1, 9.9, 10.0, 1_000_000.0, 10_000_000.0, True)
            _write(primary, _frame([bad]))
            provider = GoalMarketDataProvider(str(primary))
            bar = provider.get_bar(code, date(2026, 1, 5))
            self.assertIsNotNone(bar)
            assert bar is not None
            self.assertTrue(bar.is_trading)
            self.assertIsNone(bar.open)
            self.assertEqual(provider.counters.missing_bar_count, 1)


class UnitScaleTests(unittest.TestCase):
    def test_units_are_identity_and_values_pass_through(self):
        self.assertEqual(VOLUME_UNIT, 1.0)
        self.assertEqual(AMOUNT_UNIT, 1.0)
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "000001.SZ"
            _write(primary, _frame([_trading_row(code, "2026-01-05", 12.0, volume=90_885_655.0)]))
            provider = GoalMarketDataProvider(str(primary))
            self.assertEqual(provider.amount_basis, "yuan")
            bar = provider.get_bar(code, date(2026, 1, 5))
            assert bar is not None
            assert bar.volume is not None and bar.amount is not None
            self.assertAlmostEqual(bar.volume, 90_885_655.0)  # 真实股逐值核对
            self.assertAlmostEqual(bar.amount, 12.0 * 90_885_655.0)  # 真实元逐值核对
            implied = bar.amount / bar.volume
            self.assertGreater(implied, 5.0)  # implied price 合理带（元口径，非放大单位）
            self.assertLess(implied, 50.0)


class LimitGridTests(unittest.TestCase):
    def test_limit_up_flag_on_ten_percent_rise(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "600000.SH"  # 主板 ±10%
            _write(primary, _frame([
                _trading_row(code, "2026-01-05", 10.0),
                _trading_row(code, "2026-01-06", 11.0),  # +10% 触涨停
            ]))
            provider = GoalMarketDataProvider(str(primary))
            bar = provider.get_bar(code, date(2026, 1, 6))
            assert bar is not None
            self.assertTrue(bar.limit_up)
            self.assertFalse(bar.limit_down)

    def test_first_bar_limit_unknown_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "600000.SH"
            _write(primary, _frame([_trading_row(code, "2026-01-05", 10.0)]))
            provider = GoalMarketDataProvider(str(primary))
            bar = provider.get_bar(code, date(2026, 1, 5))
            assert bar is not None
            self.assertFalse(bar.limit_up)  # 无前收：unknown 占位 False + 计数
            self.assertFalse(bar.limit_down)
            self.assertEqual(provider.counters.limit_unknown_count, 1)

    def test_st_code_lowes_main_board_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.parquet"
            code = "600000.SH"
            _write(primary, _frame([
                _trading_row(code, "2026-01-05", 10.0),
                _trading_row(code, "2026-01-06", 10.5),  # +5%：ST 涨停，非 ST 则否
            ]))
            provider = GoalMarketDataProvider(str(primary), st_codes={code})
            bar = provider.get_bar(code, date(2026, 1, 6))
            assert bar is not None
            self.assertTrue(bar.limit_up)
            plain = GoalMarketDataProvider(str(primary))
            plain_bar = plain.get_bar(code, date(2026, 1, 6))
            assert plain_bar is not None
            self.assertFalse(plain_bar.limit_up)


class LookbackBoundaryTests(unittest.TestCase):
    def _provider(self, tmp):
        primary = Path(tmp) / "primary.parquet"
        code = "000001.SZ"
        _write(primary, _frame([
            _trading_row(code, "2026-01-05", 10.0),
            _suspended_row(code, "2026-01-06"),
            _trading_row(code, "2026-01-07", 10.2),
            _trading_row(code, "2026-01-08", 10.3),
        ]))
        return GoalMarketDataProvider(str(primary)), code

    def test_range_is_right_closed_ascending_without_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider, code = self._provider(tmp)
            history = provider.get_history(code, date(2026, 1, 5), date(2026, 1, 8))
            self.assertEqual([b.trading_date for b in history],
                             [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)])
            suspended = history[1]
            self.assertFalse(suspended.is_trading)
            self.assertIsNone(suspended.close)
            tail = provider.get_history(code, date(2026, 1, 7), date(2026, 1, 8))
            self.assertEqual([b.trading_date for b in tail], [date(2026, 1, 7), date(2026, 1, 8)])

    def test_protocol_mode_returns_last_n_present_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider, code = self._provider(tmp)
            history = provider.get_history(code, date(2026, 1, 8), 2)
            self.assertEqual([b.trading_date for b in history], [date(2026, 1, 7), date(2026, 1, 8)])
            # 前视边界：end 之前的数据不泄漏未来
            early = provider.get_history(code, date(2026, 1, 6), 10)
            self.assertEqual([b.trading_date for b in early], [date(2026, 1, 5), date(2026, 1, 6)])

    def test_batch_get_bars_via_market_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider, code = self._provider(tmp)
            state = provider.to_market_state()
            result = state.get_bars([code, "600000.SH"], date(2026, 1, 5), date(2026, 1, 8))
            self.assertEqual(len(result[code]), 4)
            self.assertEqual(result["600000.SH"], ())  # 无数据标的返回空序列而非缺键
            self.assertEqual([b.trading_date for b in result[code]],
                             [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)])

    def test_available_dates_for_fail_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider, code = self._provider(tmp)
            self.assertEqual(provider.available_dates(code),
                             (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8)))


class RealSampleTests(unittest.TestCase):
    PRIMARY = Path("data/train_data.parquet")
    OVERLAY = Path("data/feat_2026.parquet")

    def test_real_two_codes_unit_spot_check(self):
        if not self.PRIMARY.exists():
            self.skipTest(f"真实 parquet 缺失：{self.PRIMARY}")
        provider = GoalMarketDataProvider(str(self.PRIMARY), str(self.OVERLAY) if self.OVERLAY.exists() else None)
        for code in ["000001.SZ", "600000.SH"]:
            raw = pq.read_table(
                str(self.PRIMARY), columns=list(COLS),
                filters=[("code", "=", code)],
            ).to_pandas().sort_values("kline_time").tail(60)
            self.assertGreaterEqual(len(raw), 60)
            for _, record in raw.tail(5).iterrows():
                day = cast(date, pd.Timestamp(record["kline_time"]).date())
                bar = provider.get_bar(code, day)
                self.assertIsNotNone(bar)
                assert bar is not None
                if not bool(record["is_trading"]):
                    self.assertFalse(bar.is_trading)
                    self.assertIsNone(bar.volume)
                    continue
                self.assertTrue(bar.is_trading)
                assert bar.volume is not None and bar.amount is not None
                self.assertAlmostEqual(bar.volume, float(record["volume"]))  # 真实股逐值核对
                self.assertAlmostEqual(bar.amount, float(record["amount"]))  # 真实元逐值核对
                implied = bar.amount / bar.volume if bar.volume else float("nan")
                self.assertGreater(implied, 1.0)  # implied price 元口径合理带
                self.assertLess(implied, 100.0)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
