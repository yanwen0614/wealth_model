"""raw市场输入只读合成测试，不接撮合器或真实大行情。"""

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backtest.cnn_adapter.ca.raw_market_inputs import (
    normalize_raw_market_frame,
    read_raw_market_inputs,
)


def _row(day: date, *, volume: int = 10_000, amount: float = 100_000_000.0) -> dict:
    return {"code": "000001.SZ", "kline_time": day.isoformat(), "open": 10.0,
            "high": 10.5, "low": 9.5, "close": 10.0,
            "volume": volume, "amount": amount}


class RawMarketInputsTest(unittest.TestCase):
    def test_explicit_empty_window_preserves_schema_and_duplicate_failures(self):
        day = date(2021, 1, 4)
        frame = pd.DataFrame([_row(day - timedelta(days=1))])
        window = normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
            signal_end=day, execution_end=day, allow_empty_window=True, history_bars=21)
        self.assertFalse(window.signal)
        self.assertEqual(len(window.history), 1)
        with self.assertRaisesRegex(ValueError, "missing required"):
            normalize_raw_market_frame(frame.drop(columns="volume"), instrument_id="000001.SZ",
                signal_start=day, signal_end=day, execution_end=day,
                allow_empty_window=True, history_bars=21)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            normalize_raw_market_frame(pd.concat([frame, frame]), instrument_id="000001.SZ",
                signal_start=day, signal_end=day, execution_end=day,
                allow_empty_window=True, history_bars=21)

    def test_units_prices_unknown_states_and_bounded_history(self):
        start = date(2026, 1, 5)
        days = tuple(start + timedelta(days=offset) for offset in range(5))
        frame = pd.DataFrame([_row(day) for day in days])
        window = normalize_raw_market_frame(
            frame, instrument_id="000001.SZ", signal_start=days[2],
            signal_end=days[3], execution_end=days[4], history_bars=2,
        )
        self.assertEqual(tuple(row.trading_date for row in window.history), days[:2])
        self.assertEqual(tuple(row.trading_date for row in window.signal), days[2:4])
        self.assertEqual(tuple(row.trading_date for row in window.execution_buffer), days[4:])
        first = window.history[0]
        self.assertEqual((first.open, first.high, first.low, first.close), (10.0, 10.5, 9.5, 10.0))
        self.assertEqual(first.volume_shares, 100)
        self.assertEqual(first.amount_yuan, 1000.0)
        self.assertEqual((first.market_state, first.st_state, first.reference_state),
                         ("unknown", "unknown", "unknown"))
        self.assertIsNone(first.reference_price)

    def test_volume_scale_must_produce_integer_shares_and_vwap_must_fit_ohlc(self):
        day = date(2026, 1, 5)
        frame = pd.DataFrame([_row(day, volume=10_001)])
        with self.assertRaisesRegex(ValueError, "divisible by 100"):
            normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)
        frame = pd.DataFrame([_row(day, amount=200_000_000.0)])
        with self.assertRaisesRegex(ValueError, "VWAP"):
            normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)
        frame = pd.DataFrame([_row(day, volume=0)])
        with self.assertRaisesRegex(ValueError, "zero source volume"):
            normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)

    def test_large_integer_volume_is_not_rounded_through_float(self):
        day = date(2026, 1, 5)
        exact_volume = 2**53 + 8
        frame = pd.DataFrame([_row(day, volume=exact_volume, amount=exact_volume // 100 * 1_000_000.0)])
        window = normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
                                            signal_end=day, execution_end=day)
        self.assertEqual(window.signal[0].source_volume, exact_volume)
        self.assertEqual(window.signal[0].volume_shares, exact_volume // 100)
        frame = pd.DataFrame([{**_row(day), "volume": float(exact_volume)}])
        with self.assertRaisesRegex(ValueError, "not exactly representable"):
            normalize_raw_market_frame(frame, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)

    def test_duplicate_code_date_and_wrong_code_fail_closed(self):
        day = date(2026, 1, 5)
        duplicate = pd.DataFrame([_row(day), _row(day)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            normalize_raw_market_frame(duplicate, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)
        wrong = pd.DataFrame([{**_row(day), "code": "600519.SH"}])
        with self.assertRaisesRegex(ValueError, "codes must equal"):
            normalize_raw_market_frame(wrong, instrument_id="000001.SZ", signal_start=day,
                                       signal_end=day, execution_end=day)

    def test_known_suspension_is_not_selected_as_valid_trading_history(self):
        day = date(2026, 1, 5)
        frame = pd.DataFrame([{**_row(day), "is_trading": False},
                              {**_row(day + timedelta(days=1)), "is_trading": True},
                              {**_row(day + timedelta(days=2)), "is_trading": True}])
        window = normalize_raw_market_frame(
            frame, instrument_id="000001.SZ", signal_start=day + timedelta(days=2),
            signal_end=day + timedelta(days=2), execution_end=day + timedelta(days=2),
        )
        self.assertEqual(tuple(row.trading_date for row in window.history), (day + timedelta(days=1),))
        self.assertEqual(window.signal[0].market_state, "trading")
        self.assertEqual(window.signal[0].st_state, "unknown")
        self.assertEqual(window.signal[0].reference_state, "unknown")

    def test_parquet_reader_rejects_unsorted_and_duplicate_dates(self):
        start = date(2026, 1, 5)
        cases = (([_row(start + timedelta(days=1)), _row(start)], "sorted by date"),
                 ([_row(start), _row(start)], "duplicate"))
        with tempfile.TemporaryDirectory() as directory:
            for index, (rows, message) in enumerate(cases):
                path = Path(directory) / f"case-{index}.parquet"
                frame = pd.DataFrame(rows)
                frame["kline_time"] = pd.to_datetime(frame["kline_time"])
                pq.write_table(pa.Table.from_pandas(frame), path)
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    read_raw_market_inputs(
                        path, instrument_id="000001.SZ", signal_start=start,
                        signal_end=start + timedelta(days=1), execution_end=start + timedelta(days=1),
                    )

    def test_parquet_reader_uses_column_subset_and_keeps_missing_states_unknown(self):
        day = date(2026, 1, 5)
        frame = pd.DataFrame([_row(day), {**_row(day), "code": "600519.SH"},
                              _row(day + timedelta(days=1))])
        frame["kline_time"] = pd.to_datetime(frame["kline_time"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "000001.SZ.parquet"
            pq.write_table(pa.Table.from_pandas(frame), path)
            window = read_raw_market_inputs(path, instrument_id="000001.SZ", signal_start=day,
                                            signal_end=day, execution_end=day)
        self.assertEqual(len(window.period), 1)
        self.assertEqual(window.period[0].market_state, "unknown")
