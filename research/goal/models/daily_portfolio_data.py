"""Leakage-safe daily candidate pools and execution sidecars."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import cast

import numpy as np
import pandas as pd

HAND_FEATURE_COLUMNS = ("mean_5", "mean_20", "vol_20", "ret_20")
POOL_SIZE = 1000


@dataclass(frozen=True)
class DailyRecord:
    signal_date: pd.Timestamp
    buy_date: pd.Timestamp
    sell_date: pd.Timestamp
    codes: tuple[str, ...]
    features: np.ndarray
    feature_columns: tuple[str, ...]
    reward_sidecar: pd.DataFrame
    execution_sidecar: pd.DataFrame | None = None

    @property
    def reward_valid(self) -> np.ndarray:
        return self.reward_sidecar["reward_valid"].to_numpy(dtype=bool)


def _positive_integer(value, name: str, allow_zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")  # noqa: TRY004 -- 对外保持 ValueError 口径
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be a {qualifier} integer")


def make_daily_signal_dates(
    dates,
    warmup=60,
    split_start=None,
    split_end=None,
    horizon=5,
    stride=1,
) -> pd.DatetimeIndex:
    """Return daily signal dates whose horizon fits the supplied calendar/split."""
    _positive_integer(warmup, "warmup", allow_zero=True)
    _positive_integer(horizon, "horizon")
    _positive_integer(stride, "stride")
    calendar = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values().unique()
    if split_start is not None:
        split_start = pd.Timestamp(split_start)
    if split_end is not None:
        split_end = pd.Timestamp(split_end)
    eligible = calendar[warmup : len(calendar) - horizon]
    if split_start is not None:
        eligible = eligible[eligible >= split_start]
    if split_end is not None:
        eligible = eligible[eligible + pd.Timedelta(0) <= split_end]
        eligible = eligible[
            [calendar.get_loc(date) + horizon < len(calendar) and calendar[calendar.get_loc(date) + horizon] <= split_end for date in eligible]
        ]
    return pd.DatetimeIndex(eligible[::stride])


def _past_hand_features(closes: np.ndarray) -> np.ndarray:
    closes = np.asarray(closes, dtype=np.float64)
    previous, current = closes[:-1], closes[1:]
    returns = np.divide(
        current,
        previous,
        out=np.full_like(current, np.nan),
        where=np.isfinite(previous) & (previous != 0) & np.isfinite(current),
    ) - 1.0
    returns = np.nan_to_num(returns, nan=0.0)
    trailing_20 = returns[-20:]
    return np.asarray(
        [
            returns[-5:].mean(),
            trailing_20.mean(),
            np.sqrt(max(np.mean(trailing_20 * trailing_20) - trailing_20.mean() ** 2, 0.0)),
            closes[-1] / closes[-20] - 1.0
            if np.isfinite(closes[-20]) and closes[-20] != 0
            else 0.0,
        ],
        dtype=np.float32,
    )


def _valid_trade_window(name_rows, signal_index, horizon, exchange_dates) -> bool:
    sell_index = signal_index + horizon
    if signal_index < 0 or sell_index >= len(name_rows):
        return False
    window = name_rows.iloc[signal_index : sell_index + 1]
    expected = exchange_dates[exchange_dates.get_loc(pd.Timestamp(name_rows.iloc[signal_index]["kline_time"])) : exchange_dates.get_loc(pd.Timestamp(name_rows.iloc[signal_index]["kline_time"])) + horizon + 1]
    if not pd.DatetimeIndex(pd.to_datetime(window["kline_time"])).equals(expected):
        return False
    if not bool(window["is_trading"].astype(bool).all()):
        return False
    buy_row, sell_row = name_rows.iloc[signal_index + 1], name_rows.iloc[sell_index]
    values = (buy_row["open"], sell_row["open"], buy_row["amount"])
    return bool(np.isfinite(values).all() and buy_row["open"] > 0 and sell_row["open"] > 0 and buy_row["amount"] > 0)


def assemble_daily_record(
    frame,
    signal_date,
    feature_columns,
    candidate_limit=1000,
    horizon=5,
    split_end=None,
    include_execution_sidecar: bool | None = None,
) -> DailyRecord:
    """Assemble a fixed 1000-name pool from one signal-date cross-section."""
    _positive_integer(candidate_limit, "candidate_limit")
    _positive_integer(horizon, "horizon")
    if candidate_limit > POOL_SIZE:
        raise ValueError("candidate_limit cannot exceed 1000")
    feature_columns = tuple(feature_columns)
    if len(feature_columns) != 45 or len(set(feature_columns)) != 45:
        raise ValueError("feature_columns must contain exactly 45 columns")
    required = {"code", "kline_time", "close", "open", "amount", "is_trading", *feature_columns}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"frame is missing columns: {sorted(missing)}")

    signal_date = pd.Timestamp(signal_date)
    split_end = pd.Timestamp(split_end) if split_end is not None else None
    times = pd.to_datetime(frame["kline_time"])
    calendar = pd.DatetimeIndex(times.unique()).sort_values()
    positions = np.flatnonzero(calendar == signal_date)
    if len(positions) != 1 or positions[0] + horizon >= len(calendar):
        raise ValueError("reward window is unavailable")
    signal_position = int(positions[0])
    buy_date, sell_date = calendar[signal_position + 1], calendar[signal_position + horizon]
    signal_rows = frame.loc[times == signal_date].copy()
    signal_rows = signal_rows.loc[
        signal_rows["is_trading"].astype(bool)
        & np.isfinite(signal_rows["amount"])
        & (signal_rows["amount"] > 0)
        & np.isfinite(signal_rows[list(feature_columns)]).all(axis=1)
    ].sort_values(["amount", "code"], ascending=[False, True], kind="stable")
    candidates = signal_rows["code"].astype(str).head(candidate_limit).tolist()
    signal_row_by_code = {}
    for _, row in signal_rows.iterrows():
        signal_row_by_code.setdefault(str(row["code"]), row)
    name_groups = {
        code: group
        for code, group in frame.groupby(frame["code"].astype(str), sort=False)
    }

    feature_rows = []
    rewards = []
    has_execution_sidecar = (
        "volume" in frame.columns
        if include_execution_sidecar is None
        else include_execution_sidecar and "volume" in frame.columns
    )
    for code in candidates:
        signal_row = signal_row_by_code[code]
        name_rows = name_groups[code].sort_values("kline_time").reset_index(drop=True)
        name_dates = pd.DatetimeIndex(pd.to_datetime(name_rows["kline_time"]))
        name_positions = np.flatnonzero(name_dates == signal_date)
        if len(name_positions) != 1:
            continue
        signal_index = int(name_positions[0])
        closes = name_rows.loc[:signal_index, "close"].to_numpy(dtype=np.float64)
        if len(closes) < 20:
            hand = np.zeros(4, dtype=np.float32)
        else:
            hand = _past_hand_features(closes)
        feature_rows.append(np.concatenate([signal_row[list(feature_columns)].to_numpy(dtype=np.float32), hand]))
        valid = split_end is None or sell_date <= split_end
        valid = valid and _valid_trade_window(name_rows, signal_index, horizon, calendar)
        if valid:
            buy_row, sell_row = name_rows.iloc[signal_index + 1], name_rows.iloc[signal_index + horizon]
            values = (float(buy_row["open"]), float(sell_row["open"]), float(buy_row["amount"]))
        else:
            values = (0.0, 0.0, 0.0)
        rewards.append({"code": code, "buy_open": values[0], "sell_open": values[1], "buy_amount": values[2], "reward_valid": bool(valid)})
    padding = POOL_SIZE - len(feature_rows)
    feature_rows.extend(np.zeros((padding, 49), dtype=np.float32))
    rewards.extend({"code": "", "buy_open": 0.0, "sell_open": 0.0, "buy_amount": 0.0, "reward_valid": False} for _ in range(padding))
    codes = tuple(item["code"] for item in rewards)
    if has_execution_sidecar:
        buy_rows = frame[times == buy_date].copy()
        buy_rows["code"] = buy_rows["code"].astype(str)
        buy_rows = buy_rows.drop_duplicates("code", keep="first")
        buy_codes = set(buy_rows["code"])
        sidecar_codes = list(dict.fromkeys(code for code in codes if code and code in buy_codes))
        sidecar_codes.extend(sorted(buy_codes.difference(sidecar_codes)))
        previous_rows = frame[times < buy_date][["code", "kline_time", "close"]].copy()
        previous_rows["code"] = previous_rows["code"].astype(str)
        previous_rows = (
            previous_rows.sort_values(["code", "kline_time"], kind="stable")
            .groupby("code", sort=False)
            .tail(1)
            .rename(columns={"close": "prev_close"})
            [["code", "prev_close"]]
        )
        execution_rows = (
            buy_rows.merge(previous_rows, on="code", how="left", sort=False)
            .set_index("code")
            .reindex(sidecar_codes)
            .reset_index()
            [["code", "open", "close", "volume", "amount", "is_trading", "prev_close"]]
            .assign(is_trading=lambda rows: rows["is_trading"].astype(bool))
            .to_dict(orient="records")
        )
    return DailyRecord(
        signal_date=cast(pd.Timestamp, signal_date),
        buy_date=cast(pd.Timestamp, buy_date),
        sell_date=cast(pd.Timestamp, sell_date),
        codes=codes,
        features=np.asarray(feature_rows, dtype=np.float32),
        feature_columns=feature_columns + HAND_FEATURE_COLUMNS,
        reward_sidecar=pd.DataFrame(rewards, columns=["buy_open", "sell_open", "buy_amount", "reward_valid", "code"]),
        execution_sidecar=(
            pd.DataFrame(
                execution_rows,
                columns=["code", "open", "close", "volume", "amount", "is_trading", "prev_close"],
            )
            if has_execution_sidecar
            else None
        ),
    )
