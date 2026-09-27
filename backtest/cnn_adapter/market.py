"""cnn 行情提供者（B02）：train_data parquet 直读 → core MarketBar 标准契约。

数据源无 DB（parquet 直读，cnn 无触库问题）；OHLC 为后复权价、volume/amount
已是真实股/真实元（导出侧已 ÷100/÷100000 还原，见单位实证注释）。
"""
from __future__ import annotations

import math
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, NamedTuple, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts.market import MarketBar
from backtest_core.engine.market_state import MarketState

from backtest.cnn_adapter.cache import validate_ohlc_path_arrays

__all__ = ["AMOUNT_UNIT", "VOLUME_UNIT", "CnnMarketDataProvider", "MarketDataCounters"]

# 单位实证（2026-09-11，train_data_v1_F60_20130101-20260831_26c3db036a26.parquet）：
# 000001.SZ 2026-08-31 volume=90885655.0 amount=1063281431.47 → amount/volume≈11.7 元，
# 与该股 raw 现价（约 12 元）吻合；OHLC≈1000 元为后复权价。证实 parquet 已是真实股/
# 真实元，无需再除（quant 导出侧 _normalize_volume/_normalize_amount 已还原）。
VOLUME_UNIT = 1.0
AMOUNT_UNIT = 1.0


@dataclass(frozen=True)
class MarketDataCounters:
    """计数快照：停牌合成 / 缺数（键名稳定，供 B05 provenance 消费）。"""

    missing_bar_count: int = 0
    suspended_bar_count: int = 0
    limit_unknown_count: int = 0


class _RawRow(NamedTuple):
    """归一化行：价格后复权口径，volume/amount 已为真实股/元（除数为 1 不缩放）。"""

    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None
    is_trading: bool


@dataclass
class _CodeCache:
    """单标的归一化缓存：日期升序 + 位置索引 + bar 记忆化（重复调用不重复读源）。"""

    dates: tuple[date, ...] = ()
    rows: tuple[_RawRow, ...] = ()
    positions: dict[date, int] = field(default_factory=dict)
    bars: dict[date, MarketBar] = field(default_factory=dict)
    suspended_bars: dict[date, MarketBar] = field(default_factory=dict)
    missing_dates: set[date] = field(default_factory=set)


_READ_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]

# 价格网格口径与 quant A01 同源（cnn 原生实现，不 import quant）：
# 主板 ±10%、创业/科创 ±20%、北交所 ±30%、主板 ST ±5%（20%/30% 板块 ST 不降幅）；
# 限制价经 Decimal ROUND_HALF_UP 量化到分，深市补最小一跳（差不足 1 分取前收 ±0.01）。
_TICK = Decimal("0.01")
_ONE = Decimal(1)
_MAIN_BOARD_PCT = Decimal("0.10")
_STAR_CHINEXT_PCT = Decimal("0.20")
_BSE_PCT = Decimal("0.30")
_ST_PCT = Decimal("0.05")


def _finite_decimal(value: float | None) -> Decimal | None:
    """float → 精确 Decimal（经 str 规避二进制尾差）；None/非有限/bool 返回 None。"""
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        return None
    parsed = Decimal(str(value))
    return parsed if parsed.is_finite() else None


def _market_and_pct(instrument_id: str) -> tuple[str, Decimal] | None:
    """按代码后缀/前缀识别市场与板块默认幅度；无法识别返回 None（unknown）。"""
    code, sep, market = instrument_id.partition(".")
    if not sep or not code:
        return None
    market = market.upper()
    if market == "BJ":
        return market, _BSE_PCT
    if market in ("SH", "SZ"):
        growth = code.startswith(("688", "689")) if market == "SH" else code.startswith(("300", "301"))
        return market, _STAR_CHINEXT_PCT if growth else _MAIN_BOARD_PCT
    return None


def _limit_price(prev_close: Decimal, pct: Decimal, *, up: bool, min_tick_rule: bool) -> Decimal:
    """单侧限制价：后复权价比较比值，复权因子在分子分母相消，网格口径对 adj/raw 同效。"""
    factor = _ONE + pct if up else _ONE - pct
    price = (prev_close * factor).quantize(_TICK, rounding=ROUND_HALF_UP)
    if min_tick_rule and abs(price - prev_close) < _TICK:
        price = prev_close + _TICK if up else prev_close - _TICK
        price = price.quantize(_TICK, rounding=ROUND_HALF_UP)
    return max(price, _TICK)


def _to_cents(price: Decimal) -> int:
    """价格 → 整数分；命中判定一律在分网格上，禁浮点比值。"""
    return int(price.quantize(_TICK, rounding=ROUND_HALF_UP) * 100)


def _build_ohlc_index(ohlc_path: str | os.PathLike[str] | Mapping | None,
                      ) -> dict[tuple[str, date], tuple[float, float, float]] | None:
    """ohlc 路径表 npz 路径/映射 → (code, date) 索引；缺键/长度不一致显式 ValueError。"""
    if ohlc_path is None:
        return None
    if isinstance(ohlc_path, (str, os.PathLike)):
        with np.load(ohlc_path, allow_pickle=False) as z:
            arrays: Mapping = {key: z[key] for key in z.files}
    elif isinstance(ohlc_path, Mapping):
        arrays = ohlc_path
    else:
        raise TypeError(f"ohlc_path 必须为 npz 路径或映射，got {type(ohlc_path)!r}")
    validate_ohlc_path_arrays(arrays, "OHLC 路径表")
    codes = [str(code) for code in arrays["codes"].tolist()]
    dates = [cast(date, pd.Timestamp(day).date()) for day in arrays["dates"].tolist()]
    return {(code, day): (float(t), float(o1), float(o6)) for code, day, t, o1, o6
            in zip(codes, dates, arrays["t_close"].tolist(),
                   arrays["open_t1"].tolist(), arrays["open_t6"].tolist())}


def _optional_float(value: Any) -> float | None:
    """标量 → float | None：None/NaN/bool/非数值一律 None。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_frame(frame: pd.DataFrame) -> _CodeCache:
    """parquet 行 → 按日期升序的位置化缓存（重复日期 keep=last，非法时间丢弃）。"""
    parsed = frame.copy()
    parsed["_parsed_time"] = pd.to_datetime(parsed["kline_time"], errors="coerce")
    parsed = parsed.dropna(subset=["_parsed_time"]).sort_values("_parsed_time", kind="stable")
    parsed = parsed.drop_duplicates(subset=["_parsed_time"], keep="last")
    dates = tuple(timestamp.date() for timestamp in parsed["_parsed_time"].tolist())
    length = len(dates)
    columns = (
        tuple(_optional_float(value) for value in parsed["open"].tolist()),
        tuple(_optional_float(value) for value in parsed["high"].tolist()),
        tuple(_optional_float(value) for value in parsed["low"].tolist()),
        tuple(_optional_float(value) for value in parsed["close"].tolist()),
        tuple(_optional_float(value) for value in parsed["volume"].tolist()),
        tuple(_optional_float(value) for value in parsed["amount"].tolist()),
        tuple(bool(value) for value in parsed["is_trading"].tolist()),
    )
    rows: list[_RawRow] = []
    for position in range(length):
        volume = columns[4][position]
        amount = columns[5][position]
        rows.append(_RawRow(open=columns[0][position], high=columns[1][position], low=columns[2][position],
                            close=columns[3][position],
                            volume=None if volume is None else volume / VOLUME_UNIT,
                            amount=None if amount is None else amount / AMOUNT_UNIT,
                            is_trading=columns[6][position]))
    return _CodeCache(dates=dates, rows=tuple(rows), positions={d: i for i, d in enumerate(dates)})


class CnnMarketDataProvider:
    """train_data parquet 包装为 core MarketDataProvider（B02）。"""

    def __init__(self, parquet_path: str, ohlc_path=None, *, start=None, end=None,
                 st_codes: Collection[str] | None = None) -> None:
        self._parquet_path = parquet_path
        self._ohlc_path = ohlc_path
        self._start = start
        self._end = end
        # cnn 无 history_status 源：ST 名单由调用方注入（默认空，即全部非 ST）
        self._st_codes = frozenset(st_codes) if st_codes is not None else frozenset()
        # ohlc 路径表构造期即校验（坏表 fail-fast，不等首次查询才暴露）
        self._ohlc_index = _build_ohlc_index(ohlc_path)
        self._codes: dict[str, _CodeCache] = {}
        self._missing_bar_count = 0
        self._suspended_bar_count = 0
        self._limit_unknown_count = 0

    @property
    def counters(self) -> MarketDataCounters:
        """计数快照。"""
        return MarketDataCounters(missing_bar_count=self._missing_bar_count,
                                  suspended_bar_count=self._suspended_bar_count,
                                  limit_unknown_count=self._limit_unknown_count)

    @property
    def amount_basis(self) -> str:
        """成交额口径：真实元（parquet 已还原，见 VOLUME_UNIT/AMOUNT_UNIT 实证）。"""
        return "yuan"

    def get_bar(self, instrument_id: str, trading_date: date) -> MarketBar | None:
        """返回指定标的和交易日的标准行情；缺失时返回 None。

        三态：行存在且 is_trading → 正常 bar；行存在但停牌合成行 → 全 None 合成 bar；
        日期无行 → None + missing 计数（禁止伪装停牌）。
        """
        if not instrument_id or not isinstance(trading_date, date):
            raise ValueError(f"非法参数 instrument_id={instrument_id!r} trading_date={trading_date!r}")
        if not self._in_window(trading_date):
            return None
        cache = self._ensure_loaded(instrument_id)
        position = cache.positions.get(trading_date)
        if position is None:
            self._record_missing(cache, trading_date)
            return None
        row = cache.rows[position]
        if not row.is_trading:
            return self._suspended_bar(instrument_id, cache, trading_date)
        return self._trading_bar(instrument_id, cache, position)

    def _in_window(self, trading_date: date) -> bool:
        before_start = self._start is not None and trading_date < self._start
        after_end = self._end is not None and trading_date > self._end
        return not (before_start or after_end)

    def _ensure_loaded(self, instrument_id: str) -> _CodeCache:
        """per-code 懒加载：pyarrow 按 code 下推过滤，只读必需 9 列。"""
        cache = self._codes.get(instrument_id)
        if cache is not None:
            return cache
        table = pq.read_table(self._parquet_path, columns=_READ_COLS, filters=[("code", "=", instrument_id)])
        cache = _normalize_frame(table.to_pandas())
        self._codes[instrument_id] = cache
        return cache

    def _trading_bar(self, instrument_id: str, cache: _CodeCache, position: int) -> MarketBar:
        """由归一化行构造正常 bar（记忆化；缺价字段保持 None + 缺数计数）。"""
        trading_date = cache.dates[position]
        cached = cache.bars.get(trading_date)
        if cached is not None:
            return cached
        row = cache.rows[position]
        if row.open is None or row.high is None or row.low is None or row.close is None:
            self._record_missing(cache, trading_date)
        if row.volume is None or row.amount is None:
            self._record_missing(cache, trading_date)
        limit_up, limit_down = self._derive_limits(instrument_id, cache, position)
        bar = MarketBar(instrument_id=instrument_id, trading_date=trading_date, open=row.open, high=row.high,
                        low=row.low, close=row.close, volume=row.volume, amount=row.amount,
                        is_trading=True, limit_up=limit_up, limit_down=limit_down)
        cache.bars[trading_date] = bar
        return bar

    def _derive_limits(self, instrument_id: str, cache: _CodeCache, position: int) -> tuple[bool, bool]:
        """派生涨跌停：prev_close=上一有效 bar close（跨停牌合成行回退到更早有效行）。

        无法判定（无前收/缺收/无法识别市场）不静默 False：计入 limit_unknown_count，
        返回 (False, False) 仅供 MarketBar bool 契约占位。
        """
        row = cache.rows[position]
        prev_close: float | None = None
        for back in range(position - 1, -1, -1):
            candidate = cache.rows[back].close
            if candidate is not None:
                prev_close = candidate
                break
        market_and_pct = _market_and_pct(instrument_id)
        prev = _finite_decimal(prev_close)
        last = _finite_decimal(row.close)
        if market_and_pct is None or prev is None or prev <= 0 or last is None or last <= 0:
            self._limit_unknown_count += 1
            return False, False
        market, board_pct = market_and_pct
        pct = _ST_PCT if instrument_id in self._st_codes and board_pct == _MAIN_BOARD_PCT else board_pct
        min_tick_rule = market == "SZ"
        up_price = _limit_price(prev, pct, up=True, min_tick_rule=min_tick_rule)
        down_price = _limit_price(prev, pct, up=False, min_tick_rule=min_tick_rule)
        return _to_cents(last) >= _to_cents(up_price), _to_cents(last) <= _to_cents(down_price)

    def _suspended_bar(self, instrument_id: str, cache: _CodeCache, trading_date: date) -> MarketBar:
        """停牌合成行 → 全 None bar（禁 0.0 冒充，记忆化，去重计数）。"""
        cached = cache.suspended_bars.get(trading_date)
        if cached is not None:
            return cached
        bar = MarketBar(instrument_id=instrument_id, trading_date=trading_date, open=None, high=None,
                        low=None, close=None, volume=None, amount=None,
                        is_trading=False, limit_up=False, limit_down=False)
        cache.suspended_bars[trading_date] = bar
        self._suspended_bar_count += 1
        return bar

    def _record_missing(self, cache: _CodeCache, trading_date: date) -> None:
        """缺数按 (code 缓存, date) 去重计数。"""
        if trading_date in cache.missing_dates:
            return
        cache.missing_dates.add(trading_date)
        self._missing_bar_count += 1

    def get_history(self, instrument_id: str, end_date, lookback_days) -> Sequence[MarketBar]:
        """历史窗口（升序、防前视）；缺失日期不填充，停牌合成行占位保留。

        双模式：第三参为 int → core 协议（end_date 及之前 lookback_days 个 present 日，
        MarketState 批量消费走此口）；第三参为 date → 右闭区间 [end_date, lookback_days]
        （参数名按协议，语义为 start/end，单测前视边界走此口）。
        """
        if not instrument_id:
            raise ValueError(f"非法 instrument_id={instrument_id!r}")
        if isinstance(lookback_days, bool):
            raise TypeError(f"lookback_days 必须为正整数，got {lookback_days!r}")
        if isinstance(lookback_days, int):
            if not isinstance(end_date, date):
                raise TypeError(f"非法 end_date={end_date!r}")
            if lookback_days <= 0:
                raise ValueError(f"lookback_days 必须为正整数，got {lookback_days!r}")
            return self._history_protocol(instrument_id, end_date, lookback_days)
        if isinstance(end_date, date) and isinstance(lookback_days, date):
            start, end = end_date, lookback_days
            if end < start:
                raise ValueError(f"end 必须 >= start，got start={start!r} end={end!r}")
            return self._history_range(instrument_id, start, end)
        raise ValueError(f"非法参数 end_date={end_date!r} lookback_days={lookback_days!r}")

    def _history_protocol(self, instrument_id: str, end_date: date, lookback_days: int) -> tuple[MarketBar, ...]:
        """core 协议：end 及之前最近 lookback_days 个 present 日（含停牌合成行），升序。"""
        upper = end_date if self._end is None else min(end_date, self._end)
        if self._start is not None and upper < self._start:
            return ()
        cache = self._ensure_loaded(instrument_id)
        days = [d for d in cache.dates if d <= upper and (self._start is None or d >= self._start)]
        return tuple(self._bar_at(instrument_id, cache, day) for day in days[-lookback_days:])

    def _history_range(self, instrument_id: str, start: date, end: date) -> tuple[MarketBar, ...]:
        """右闭区间 [start, end] present 日序列，升序；未来数据绝不返回。"""
        if self._start is not None:
            start = max(start, self._start)
        if self._end is not None:
            end = min(end, self._end)
        if end < start:
            return ()
        cache = self._ensure_loaded(instrument_id)
        return tuple(self._bar_at(instrument_id, cache, day)
                     for day in cache.dates if start <= day <= end)

    def _bar_at(self, instrument_id: str, cache: _CodeCache, trading_date: date) -> MarketBar:
        """present 日期 → bar（停牌合成行走合成路径，计数去重由各路径承担）。"""
        position = cache.positions[trading_date]
        if not cache.rows[position].is_trading:
            return self._suspended_bar(instrument_id, cache, trading_date)
        return self._trading_bar(instrument_id, cache, position)

    def to_market_state(self, dates=None) -> MarketState:
        """产出 core MarketState：批量 get_bars 复用本 provider，不重复加载。"""
        return MarketState(self)

    def get_ohlc_path(self, instrument_id: str, trading_date: date) -> tuple[float, float, float] | None:
        """返回 ohlc 路径表 (t_close, open_t1, open_t6)；无表或缺行返回 None。"""
        if self._ohlc_index is None:
            return None
        return self._ohlc_index.get((instrument_id, trading_date))
