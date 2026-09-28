"""goal 行情提供者（C02）：双 parquet 拼接 → core MarketBar 标准契约。

数据源选择（2026-09-11 列实证，pyarrow 只读列子集取样）：
- 主表 ``data/train_data.parquet``（11,413,377 行，2013-01-04～2025-12-31）与
  ``data/feat_2026.parquet``（829,750 行，2026-01-05～2026-08-31）列集合完全一致
  （58 列同名同序），按 code 取样两者日期区间无交集（000001.SZ 主表止于
  2025-12-31、feat_2026 起于 2026-01-05），天然互补无重叠。
- ``data/new/train_data_20260831.parquet``（12,254,385 行，2013-01-04～2026-08-31）
  经单股校验恰为上述两表并集（000001.SZ：3157+160=3317 行全对齐、无增删），
  即预拼接全集；但默认仍用主表 + overlay 双源拼接（overlay 优先），保持增量口径
  可审计；若调用方直接传入 new 全集作 primary 且 overlay=None，行为等价。
- 拼接键 (code, kline_time 日期)：重叠键 overlay 行优先（keep=last），重叠键数计入
  ``dedup_overlap_count``（per-code 懒加载时累计，全局只增不减）。

量纲实证（000001.SZ 2026-08-31：OHLC≈1000、volume=90,885,655、amount=1,063,281,431.47，
amount/volume≈11.70 元与 raw 现价约 12 元吻合；600000.SH 同日 implied≈9.11）：
- OHLC 为后复权价（数值数百量级）；volume/amount 已是真实股/真实元，无需再除，
  故 ``VOLUME_UNIT = AMOUNT_UNIT = 1.0``，``amount_basis = "yuan"`` 锁定真实元口径。

停牌行表达实证（296,719 行 is_trading=False）：OHLC 全 NaN、volume/amount 记 0.0。
None 语义：停牌合成行 → OHLC/volume/amount 全 None（禁 0.0 冒充）；交易行缺价/
缺量字段保持 None（计数 ``missing_bar_count``，日期按 (code, date) 去重）。
code 含市场后缀（``000001.SZ``）；kline_time 为 datetime。

涨跌停复用 C01 ``default_limit_pct`` + ``limit_price``：prev_close 取上一有效 close
（跨停牌回退）；无前收/缺收/无法识别市场记 ``limit_unknown_count``，不静默 False；
``st_codes`` 可注入（全码或裸码均匹配）；深市（.SZ）补最小一跳（与 cnn B02 同口径）。
"""

from __future__ import annotations

import bisect
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts.market import MarketBar
from backtest_core.engine.market_state import MarketState

from goal_adapter.common import default_limit_pct, limit_price

__all__ = ["AMOUNT_UNIT", "VOLUME_UNIT", "GoalMarketDataProvider", "MarketDataCounters"]

# 单位实证（见模块 docstring）：parquet 已是真实股/真实元，除数为 1 即不缩放。
VOLUME_UNIT = 1.0
AMOUNT_UNIT = 1.0

_READ_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]


@dataclass(frozen=True)
class MarketDataCounters:
    """计数快照：停牌合成 / 缺数 / 涨跌停未知 / 拼接去重（键名稳定，供 C05 消费）。"""

    missing_bar_count: int = 0
    suspended_bar_count: int = 0
    limit_unknown_count: int = 0
    dedup_overlap_count: int = 0


class _RawRow:
    """归一化行：价格后复权口径，volume/amount 真实股/元（除数恒 1），停牌行全 None。"""

    __slots__ = ("amount", "close", "high", "is_trading", "low", "open", "volume")

    def __init__(
        self,
        open: float | None,
        high: float | None,
        low: float | None,
        close: float | None,
        volume: float | None,
        amount: float | None,
        is_trading: bool,
    ) -> None:
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.amount = amount
        self.is_trading = is_trading


@dataclass
class _CodeCache:
    """单标的归一化缓存：日期升序 + 位置索引 + bar 记忆化（重复调用不重复读源）。"""

    dates: tuple[date, ...] = ()
    rows: tuple[_RawRow, ...] = ()
    positions: dict[date, int] = field(default_factory=dict)
    bars: dict[date, MarketBar] = field(default_factory=dict)
    suspended_bars: dict[date, MarketBar] = field(default_factory=dict)
    missing_dates: set[date] = field(default_factory=set)


def _optional_float(value: Any) -> float | None:
    """标量 → float | None：None/NaN/bool/非数值一律 None（停牌行 0.0 由调用方按 is_trading 归一）。"""
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


def _normalize_code_frames(frames: list[pd.DataFrame]) -> tuple[_CodeCache, int]:
    """多源同 code 行 → 按日期升序的位置化缓存（后源优先去重，返回缓存与重叠键数）。

    重复日期 keep=last：overlay 帧排在后面即 overlay 优先；非法时间丢弃。
    停牌行（is_trading=False）OHLC/volume/amount 全置 None——实证停牌行 volume/amount
    记 0.0，直接透传会伪装成零成交，必须归一为 None。
    """
    merged = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0].copy()
    merged["_parsed_time"] = pd.to_datetime(merged["kline_time"], errors="coerce")
    merged = merged.dropna(subset=["_parsed_time"]).sort_values("_parsed_time", kind="stable")
    dup_mask = merged.duplicated(subset=["_parsed_time"], keep="last")
    overlap = int(dup_mask.sum())
    merged = merged.loc[~merged.duplicated(subset=["_parsed_time"], keep="last")]
    dates = tuple(timestamp.date() for timestamp in merged["_parsed_time"].tolist())
    rows: list[_RawRow] = []
    for _, record in merged.iterrows():
        trading = bool(record["is_trading"])
        if not trading:
            rows.append(_RawRow(None, None, None, None, None, None, False))
            continue
        volume = _optional_float(record["volume"])
        amount = _optional_float(record["amount"])
        rows.append(
            _RawRow(
                _optional_float(record["open"]),
                _optional_float(record["high"]),
                _optional_float(record["low"]),
                _optional_float(record["close"]),
                None if volume is None else volume / VOLUME_UNIT,
                None if amount is None else amount / AMOUNT_UNIT,
                True,
            )
        )
    return _CodeCache(dates=dates, rows=tuple(rows), positions={d: i for i, d in enumerate(dates)}), overlap


def _to_cents(price: Decimal) -> int:
    """价格 → 整数分；涨跌停命中判定一律在分网格上，禁浮点比值。"""
    return int(price.quantize(Decimal("0.01")) * 100)


class GoalMarketDataProvider:
    """双 parquet 行情包装为 core MarketDataProvider（C02，goal 原生实现）。"""

    def __init__(
        self,
        primary_path: str,
        overlay_path: str | None = None,
        *,
        start: date | None = None,
        end: date | None = None,
        st_codes: Collection[str] | None = None,
    ) -> None:
        if not primary_path:
            raise ValueError(f"非法 primary_path={primary_path!r}")
        if start is not None and end is not None and end < start:
            raise ValueError(f"end 必须 >= start，got start={start!r} end={end!r}")
        self._primary_path = primary_path
        self._overlay_path = overlay_path
        self._start = start
        self._end = end
        # goal 无 history_status 源：ST 名单由调用方注入（默认空，即全部非 ST）
        self._st_codes = frozenset(st_codes) if st_codes is not None else frozenset()
        self._codes: dict[str, _CodeCache] = {}
        self._available: tuple[date, ...] | None = None
        self._missing_bar_count = 0
        self._suspended_bar_count = 0
        self._limit_unknown_count = 0
        self._dedup_overlap_count = 0

    @property
    def counters(self) -> MarketDataCounters:
        """计数快照（键名稳定，供 C05 provenance 消费）。"""
        return MarketDataCounters(
            missing_bar_count=self._missing_bar_count,
            suspended_bar_count=self._suspended_bar_count,
            limit_unknown_count=self._limit_unknown_count,
            dedup_overlap_count=self._dedup_overlap_count,
        )

    @property
    def amount_basis(self) -> str:
        """成交额口径：真实元（parquet 已还原，见 VOLUME_UNIT/AMOUNT_UNIT 实证）。"""
        return "yuan"

    def get_bar(self, instrument_id: str, trading_date: date) -> MarketBar | None:
        """返回指定标的和交易日的标准行情；缺失时返回 None。

        三态：行存在且 is_trading → 正常 bar；行存在但停牌 → 全 None 合成 bar；
        日期无行 → None + missing 计数（禁止伪装停牌）。窗口外（start/end）不计数。
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
        if not cache.rows[position].is_trading:
            return self._suspended_bar(instrument_id, cache, trading_date)
        return self._trading_bar(instrument_id, cache, position)

    def _in_window(self, trading_date: date) -> bool:
        before_start = self._start is not None and trading_date < self._start
        after_end = self._end is not None and trading_date > self._end
        return not (before_start or after_end)

    def _ensure_loaded(self, instrument_id: str) -> _CodeCache:
        """per-code 懒加载：pyarrow 按 code 下推过滤，只读必需 9 列；双源拼接去重。"""
        cache = self._codes.get(instrument_id)
        if cache is not None:
            return cache
        frames = [
            pq.read_table(self._primary_path, columns=_READ_COLS,
                          filters=[("code", "=", instrument_id)]).to_pandas()
        ]
        if self._overlay_path is not None:
            frames.append(
                pq.read_table(self._overlay_path, columns=_READ_COLS,
                              filters=[("code", "=", instrument_id)]).to_pandas()
            )
        cache, overlap = _normalize_code_frames(frames)
        self._dedup_overlap_count += overlap
        self._codes[instrument_id] = cache
        return cache

    def _trading_bar(self, instrument_id: str, cache: _CodeCache, position: int) -> MarketBar:
        """由归一化行构造正常 bar（记忆化；缺价/缺量字段保持 None + 缺数计数）。"""
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
        bar = MarketBar(
            instrument_id=instrument_id, trading_date=trading_date, open=row.open, high=row.high,
            low=row.low, close=row.close, volume=row.volume, amount=row.amount,
            is_trading=True, limit_up=limit_up, limit_down=limit_down,
        )
        cache.bars[trading_date] = bar
        return bar

    def _derive_limits(self, instrument_id: str, cache: _CodeCache, position: int) -> tuple[bool, bool]:
        """派生涨跌停：prev_close=上一有效 close（跨停牌合成行回退到更早有效行）。

        复用 C01 default_limit_pct + limit_price；无法判定（无前收/缺收/无法识别市场）
        不静默 False：计入 limit_unknown_count，返回 (False, False) 仅供契约占位。
        """
        row = cache.rows[position]
        prev_close: float | None = None
        for back in range(position - 1, -1, -1):
            candidate = cache.rows[back].close
            if candidate is not None:
                prev_close = candidate
                break
        try:
            pct = default_limit_pct(instrument_id, self._st_codes)
        except ValueError:
            self._limit_unknown_count += 1
            return False, False
        if prev_close is None or prev_close <= 0 or row.close is None or row.close <= 0:
            self._limit_unknown_count += 1
            return False, False
        try:
            min_tick_rule = instrument_id.upper().endswith(".SZ")
            up_price = limit_price(prev_close, pct, up=True, min_tick_rule=min_tick_rule)
            down_price = limit_price(prev_close, pct, up=False, min_tick_rule=min_tick_rule)
        except ValueError:
            self._limit_unknown_count += 1
            return False, False
        last = Decimal(str(row.close))
        return _to_cents(last) >= _to_cents(up_price), _to_cents(last) <= _to_cents(down_price)

    def _suspended_bar(self, instrument_id: str, cache: _CodeCache, trading_date: date) -> MarketBar:
        """停牌行 → 全 None bar（禁 0.0 冒充，记忆化，去重计数）。"""
        cached = cache.suspended_bars.get(trading_date)
        if cached is not None:
            return cached
        bar = MarketBar(
            instrument_id=instrument_id, trading_date=trading_date, open=None, high=None,
            low=None, close=None, volume=None, amount=None,
            is_trading=False, limit_up=False, limit_down=False,
        )
        cache.suspended_bars[trading_date] = bar
        self._suspended_bar_count += 1
        return bar

    def _record_missing(self, cache: _CodeCache, trading_date: date) -> None:
        """缺数按 (code 缓存, date) 去重计数。"""
        if trading_date in cache.missing_dates:
            return
        cache.missing_dates.add(trading_date)
        self._missing_bar_count += 1

    def get_history(self, instrument_id: str, end_date: date, lookback_days: object) -> Sequence[MarketBar]:
        """历史窗口（升序、防前视）；缺失日期不填充，停牌合成行占位保留。

        双模式：第三参为 int → core 协议（end_date 及之前 lookback_days 个 present 日，
        MarketState 批量消费走此口）；第三参为 date → 右闭区间 [end_date, lookback_days]
        （参数名按协议，语义为 start/end，前视边界单测走此口）。
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
        left = bisect.bisect_left(cache.dates, start)
        right = bisect.bisect_right(cache.dates, end)
        return tuple(self._bar_at(instrument_id, cache, day) for day in cache.dates[left:right])

    def _bar_at(self, instrument_id: str, cache: _CodeCache, trading_date: date) -> MarketBar:
        """present 日期 → bar（停牌行走合成路径，计数去重由各路径承担）。"""
        position = cache.positions[trading_date]
        if not cache.rows[position].is_trading:
            return self._suspended_bar(instrument_id, cache, trading_date)
        return self._trading_bar(instrument_id, cache, position)

    def to_market_state(self) -> MarketState:
        """产出 core MarketState：批量 get_bars 复用本 provider，不重复加载。"""
        return MarketState(self)

    def available_dates(self, instrument_id: str | None = None) -> tuple[date, ...]:
        """可用交易日（升序，供 C04 fail-fast）：指定 code 走缓存，否则读双源日期列并集。"""
        if instrument_id is not None:
            return self._ensure_loaded(instrument_id).dates
        if self._available is not None:
            return self._available
        days: set[date] = set()
        for path in [self._primary_path, *( [self._overlay_path] if self._overlay_path else [])]:
            frame = pq.read_table(path, columns=["kline_time"]).to_pandas()
            days.update(pd.to_datetime(frame["kline_time"]).dt.date.tolist())
        self._available = tuple(sorted(days))
        return self._available
