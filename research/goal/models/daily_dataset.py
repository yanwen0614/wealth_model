"""Streaming daily records from raw and feature parquet sources."""
from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from models.daily_portfolio_data import (
    DailyRecord,
    assemble_daily_record,
    make_daily_signal_dates,
)

RAW_COLUMNS = ["code", "kline_time", "close", "open", "amount", "is_trading"]


def available_dates(raw_path) -> pd.DatetimeIndex:
    """Return the sorted exchange calendar without loading other raw columns."""
    dates = pd.read_parquet(raw_path, columns=["kline_time"])["kline_time"]
    return pd.DatetimeIndex(pd.to_datetime(dates)).sort_values().unique()


def _source_feature_columns(feature_columns) -> tuple[tuple[str, ...], tuple[str, ...]]:
    requested = tuple(feature_columns)
    source = tuple("open_feature" if column == "open" else column for column in requested)
    read_columns = tuple("open" if column == "open" else column for column in requested)
    if len(requested) != 45 or len(set(requested)) != 45:
        raise ValueError("feature_columns must contain exactly 45 columns")
    return source, read_columns


def _read_window(raw_path, feature_path, window_dates, feature_columns, include_execution_sidecar=None):
    filters = [("kline_time", "in", list(window_dates))]
    raw_columns = RAW_COLUMNS + ["volume"] if include_execution_sidecar is not False else RAW_COLUMNS
    raw = pd.read_parquet(raw_path, columns=raw_columns, filters=filters)
    features = pd.read_parquet(
        feature_path,
        columns=["code", "kline_time", *feature_columns],
        filters=filters,
    )
    if "open" in feature_columns:
        features = features.rename(columns={"open": "open_feature"})
    return raw.merge(features, on=["code", "kline_time"], how="inner", validate="one_to_one")


def iter_daily_records(
    raw_path,
    feature_path,
    feature_columns,
    split_start=None,
    split_end=None,
    warmup=60,
    horizon=5,
    stride=1,
    candidate_limit=1000,
    include_execution_sidecar: bool | None = None,
) -> Iterator[tuple[DailyRecord, dict[str, object]]]:
    """Yield one assembled record and its split metadata per eligible signal day."""
    source_columns, read_columns = _source_feature_columns(feature_columns)
    calendar = available_dates(raw_path)
    signal_dates = make_daily_signal_dates(
        calendar,
        warmup=warmup,
        split_start=split_start,
        split_end=split_end,
        horizon=horizon,
        stride=stride,
    )
    calendar_positions = {date: index for index, date in enumerate(calendar)}

    for signal_date in signal_dates:
        signal_index = calendar_positions[pd.Timestamp(signal_date)]
        window_dates = calendar[
            max(0, signal_index - warmup + 1) : signal_index + horizon + 1
        ]
        frame = _read_window(
            raw_path, feature_path, window_dates, read_columns,
            include_execution_sidecar=include_execution_sidecar,
        )
        record = assemble_daily_record(
            frame,
            signal_date,
            source_columns,
            candidate_limit=candidate_limit,
            horizon=horizon,
            split_end=split_end,
            include_execution_sidecar=include_execution_sidecar,
        )
        metadata = {
            "split_start": pd.Timestamp(split_start) if split_start is not None else None,
            "split_end": pd.Timestamp(split_end) if split_end is not None else None,
            "warmup": warmup,
            "horizon": horizon,
            "stride": stride,
        }
        del frame
        yield record, metadata
