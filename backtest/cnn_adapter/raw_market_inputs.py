"""单标的原价日线读取与单位校验；不构造 core 可执行 MarketBar。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

MarketState = Literal["trading", "suspended", "unknown"]
KnowledgeState = Literal["verified", "unknown"]

_REQUIRED_COLUMNS = ("code", "kline_time", "open", "high", "low", "close", "volume", "amount")
_VOLUME_DIVISOR = 100
_AMOUNT_DIVISOR = 100_000


@dataclass(frozen=True)
class RawMarketRecord:
    """原价和按已核验单位换算的数据；未知状态不转成可交易布尔值。"""

    instrument_id: str
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    source_volume: int | None
    volume_shares: int | None
    source_amount: float | None
    amount_yuan: float | None
    market_state: MarketState
    st_state: KnowledgeState
    reference_state: KnowledgeState
    reference_price: float | None


@dataclass(frozen=True)
class RawMarketWindow:
    """必要历史窗口、信号期和执行/buffer期分开，便于防止误用未来行。"""

    instrument_id: str
    history: tuple[RawMarketRecord, ...]
    signal: tuple[RawMarketRecord, ...]
    execution_buffer: tuple[RawMarketRecord, ...]

    @property
    def period(self) -> tuple[RawMarketRecord, ...]:
        return self.signal + self.execution_buffer

    @property
    def records(self) -> tuple[RawMarketRecord, ...]:
        return self.history + self.signal + self.execution_buffer


def _optional_number(value, field: str, *, positive: bool = False) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, got {value!r}")  # noqa: TRY004
    number = float(value)
    if not isfinite(number) or (positive and number <= 0) or (not positive and number < 0):
        raise ValueError(f"{field} is outside its valid range: {value!r}")
    return number


def _raw_volume(value, code: str, day: date) -> int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{code} {day}: source volume must be an integer, got {value!r}")  # noqa: TRY004
    if isinstance(value, (int, np.integer)):
        volume = int(value)
    elif isinstance(value, (float, np.floating)):
        if not isfinite(float(value)) or not float(value).is_integer() or abs(float(value)) > 2**53:
            raise ValueError(f"{code} {day}: source volume float is not exactly representable: {value!r}")
        volume = int(value)
    else:
        raise ValueError(f"{code} {day}: unsupported source volume type: {type(value)!r}")  # noqa: TRY004
    if volume < 0:
        raise ValueError(f"{code} {day}: source volume must be non-negative, got {volume!r}")
    return volume


def _to_date(value: str | date | datetime | np.datetime64) -> date:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"kline_time is invalid: {value!r}") from exc
    if pd.isna(timestamp):
        raise ValueError(f"kline_time is missing: {value!r}")
    parsed_day = timestamp.date()
    if not isinstance(parsed_day, date):
        raise ValueError(f"kline_time did not resolve to a date: {value!r}")  # noqa: TRY004
    return parsed_day


def _raw_record(row: Mapping, expected_code: str, day: date) -> RawMarketRecord:
    code = str(row["code"])
    if code != expected_code:
        raise ValueError(f"code key mismatch: expected {expected_code!r}, got {code!r}")
    prices = tuple(_optional_number(row[name], name, positive=True)
                   for name in ("open", "high", "low", "close"))
    if any(value is None for value in prices) and any(value is not None for value in prices):
        raise ValueError(f"{code} {day}: OHLC must be all present or all missing")
    open_, high, low, close = prices
    if open_ is not None and high is not None and low is not None and close is not None:
        if high < max(open_, close, low) or low > min(open_, close, high):
            raise ValueError(f"{code} {day}: inconsistent OHLC range")
    raw_volume = _raw_volume(row["volume"], code, day)
    if raw_volume is not None and raw_volume % _VOLUME_DIVISOR:
        raise ValueError(f"{code} {day}: source volume must be divisible by {_VOLUME_DIVISOR}")
    source_amount = _optional_number(row["amount"], "amount")
    if raw_volume == 0 and source_amount is not None and source_amount > 0:
        raise ValueError(f"{code} {day}: zero source volume cannot have non-zero amount")
    volume_shares = None if raw_volume is None else raw_volume // _VOLUME_DIVISOR
    amount_yuan = None if source_amount is None else source_amount / _AMOUNT_DIVISOR
    if volume_shares and amount_yuan is not None and low is not None and high is not None:
        vwap = amount_yuan / volume_shares
        if not low - 0.01 <= vwap <= high + 0.01:
            raise ValueError(f"{code} {day}: raw amount/volume VWAP {vwap} outside OHLC range")
    state = row.get("is_trading")
    missing_state = state is None or (isinstance(state, (float, np.floating)) and np.isnan(state))
    if not missing_state and not isinstance(state, (bool, np.bool_)):
        raise ValueError(f"{code} {day}: is_trading must be bool or null, got {state!r}")
    market_state: MarketState = "unknown" if missing_state else (
        "trading" if bool(state) else "suspended"
    )
    return RawMarketRecord(
        instrument_id=code, trading_date=day, open=open_, high=high, low=low, close=close,
        source_volume=raw_volume, volume_shares=volume_shares, source_amount=source_amount,
        amount_yuan=amount_yuan, market_state=market_state, st_state="unknown",
        reference_state="unknown", reference_price=None,
    )


def normalize_raw_market_frame(frame: pd.DataFrame, *, instrument_id: str, signal_start: date,
                               signal_end: date, execution_end: date,
                               history_bars: int = 20) -> RawMarketWindow:
    """校验一份单标的 raw 日线并裁出所需历史、信号期和执行/buffer期。"""
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"frame must be a pandas DataFrame, got {type(frame)!r}")  # noqa: TRY004
    if not instrument_id or not isinstance(instrument_id, str):
        raise ValueError(f"instrument_id must be non-empty, got {instrument_id!r}")
    if any(type(day) is not date for day in (signal_start, signal_end, execution_end)):
        raise ValueError("signal_start, signal_end and execution_end must be pure dates")
    if signal_end < signal_start or execution_end < signal_end:
        raise ValueError("date window must satisfy signal_start <= signal_end <= execution_end")
    if isinstance(history_bars, bool) or not isinstance(history_bars, int) or history_bars < 1:
        raise ValueError(f"history_bars must be a positive integer, got {history_bars!r}")
    missing = sorted(set(_REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"raw market frame missing required columns: {missing}")
    raw_rows = [(row, _to_date(row["kline_time"])) for row in frame.to_dict(orient="records")]
    keys = [(str(row["code"]), day) for row, day in raw_rows]
    if len(keys) != len(set(keys)):
        raise ValueError("raw market frame contains duplicate (code, date) keys")
    if {code for code, _ in keys} != {instrument_id}:
        raise ValueError(f"raw market frame codes must equal {instrument_id!r}")
    raw_rows.sort(key=lambda item: item[1])
    records = tuple(_raw_record(row, instrument_id, day)
                    for row, day in raw_rows if day <= execution_end)
    signal = tuple(record for record in records if signal_start <= record.trading_date <= signal_end)
    execution_buffer = tuple(record for record in records
                             if signal_end < record.trading_date <= execution_end)
    if not signal:
        raise ValueError(f"no raw market rows for {instrument_id} in requested period")
    candidates = tuple(record for record in records if record.trading_date < signal_start
                       and _has_valid_raw_bar(record))
    return RawMarketWindow(instrument_id, candidates[-history_bars:], signal, execution_buffer)


def _has_valid_raw_bar(record: RawMarketRecord) -> bool:
    """只判数值完整性以保留历史参考；未知状态仍不能作为执行授权。"""
    return (record.market_state != "suspended"
            and record.open is not None and record.high is not None and record.low is not None
            and record.close is not None and record.volume_shares is not None
            and record.volume_shares > 0 and record.amount_yuan is not None)


def read_raw_market_inputs(path: str | Path, *, instrument_id: str, signal_start: date,
                           signal_end: date, execution_end: date,
                           history_bars: int = 20) -> RawMarketWindow:
    """按代码和截止日分批扫描parquet，只在内存保留所需窗口行。"""
    if not instrument_id or any(type(day) is not date
                                for day in (signal_start, signal_end, execution_end)):
        raise ValueError("instrument_id and all date boundaries must be valid")
    if signal_end < signal_start or execution_end < signal_end:
        raise ValueError("date window must satisfy signal_start <= signal_end <= execution_end")
    if isinstance(history_bars, bool) or not isinstance(history_bars, int) or history_bars < 1:
        raise ValueError(f"history_bars must be a positive integer, got {history_bars!r}")
    parquet_path = Path(path)
    dataset = ds.dataset(parquet_path, format="parquet")
    schema_columns = set(dataset.schema.names)
    missing = sorted(set(_REQUIRED_COLUMNS) - schema_columns)
    if missing:
        raise ValueError(f"raw parquet missing required columns: {missing}")
    columns: list[str] = list(_REQUIRED_COLUMNS)
    if "is_trading" in schema_columns:
        columns.append("is_trading")
    time_type = dataset.schema.field("kline_time").type
    if not pa.types.is_timestamp(time_type):
        raise ValueError(f"raw parquet kline_time must be a timestamp, got {time_type}")
    cutoff = datetime.combine(execution_end + timedelta(days=1), time.min)
    if time_type.tz:
        cutoff = cutoff.replace(tzinfo=ZoneInfo(time_type.tz))
    expression = (ds.field("code") == instrument_id) & (ds.field("kline_time") < cutoff)
    scanner = dataset.scanner(columns=columns, filter=expression, batch_size=4096)
    previous_day: date | None = None
    history: list[RawMarketRecord] = []
    signal: list[RawMarketRecord] = []
    execution_buffer: list[RawMarketRecord] = []
    for batch in scanner.to_batches():
        for row in batch.to_pylist():
            day = _to_date(row["kline_time"])
            if previous_day is not None and day <= previous_day:
                if day == previous_day:
                    raise ValueError(f"raw parquet contains duplicate (code, date) key: {(instrument_id, day)!r}")
                raise ValueError(f"raw parquet rows must be sorted by date: {day} follows {previous_day}")
            previous_day = day
            record = _raw_record(row, instrument_id, day)
            if day < signal_start and _has_valid_raw_bar(record):
                history.append(record)
                history.sort(key=lambda item: item.trading_date)
                del history[:-history_bars]
            elif signal_start <= day <= signal_end:
                signal.append(record)
            elif signal_end < day <= execution_end:
                execution_buffer.append(record)
    if not signal:
        raise ValueError(f"no raw market rows for {instrument_id} in requested signal period")
    return RawMarketWindow(instrument_id, tuple(history), tuple(signal), tuple(execution_buffer))
