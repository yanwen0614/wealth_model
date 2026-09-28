"""goal backtest adapter 共享工具（C01，goal 原生实现，不搬运 cnn/quant 代码）.

只处理 numpy/parquet 输出：adapter 层禁 import torch。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Collection, Mapping
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import numpy as np

__all__ = [
    "BSE_PCT",
    "MAIN_BOARD_PCT",
    "SHANGHAI_TZ",
    "SIGNAL_HOUR",
    "STAR_CHINEXT_PCT",
    "ST_PCT",
    "default_limit_pct",
    "fingerprint_mapping",
    "limit_price",
    "require_keys",
    "signal_time_for",
]

# 与 quant/cnn 同口径：A 股收盘信号时点（Asia/Shanghai 15:00，tz-aware）
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SIGNAL_HOUR = 15


def signal_time_for(trading_date: date, mode: str = "t1") -> datetime:
    """返回交易日的收盘信号时间；默认 t1 即当日 15:00 Asia/Shanghai（tz-aware）。"""
    if mode.upper() != "T1":
        raise ValueError(f"未知信号模式 {mode!r}，仅支持 't1'")
    return datetime.combine(trading_date, time(SIGNAL_HOUR, 0), tzinfo=SHANGHAI_TZ)


def require_keys(mapping: Mapping, keys, source: str) -> None:
    """缺键显式 ValueError，避免下游 KeyError 掩盖数据口径问题。"""
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"{source} 缺少必需键 {missing}")


def fingerprint_mapping(arrays: Mapping) -> str:
    """内存映射指纹：sha1(键排序 + 形状 + dtype + C 序字节)，dict 顺序无关、跨进程稳定。"""
    digest = hashlib.sha1()
    for key in sorted(arrays.keys(), key=str):
        # 归一化内存布局：F 序/切片视图与 C 序同内容同指纹
        arr = np.ascontiguousarray(arrays[key])
        digest.update(str(key).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(arr.shape).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(arr.dtype).encode("utf-8"))
        digest.update(b"\0")
        digest.update(arr.tobytes())
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# 价格网格涨跌停（规则照抄 quant adapters/common.py，不得自创）
# ---------------------------------------------------------------------------

_TICK = Decimal("0.01")  # A 股价格最小变动单位（1 分）
_ONE = Decimal(1)
# 竞价交易涨跌幅默认表（交易所规则）：沪深主板 ±10%；
# 创业板（300/301.SZ）与科创板（688/689.SH）±20%；
# 北交所 ±30%；沪深主板 ST/*ST ±5%（创业板/科创板 ST 不降幅）
MAIN_BOARD_PCT = Decimal("0.10")
STAR_CHINEXT_PCT = Decimal("0.20")
BSE_PCT = Decimal("0.30")
ST_PCT = Decimal("0.05")


def _board_pct(code: str) -> Decimal | None:
    """按代码后缀/前缀识别板块默认幅度；无法识别返回 None（调用方显式报错）。"""
    bare, sep, market = code.partition(".")
    if not sep or not bare:
        return None
    market = market.upper()
    if market == "BJ":
        return BSE_PCT
    if market in ("SH", "SZ"):
        growth = bare.startswith(("688", "689")) if market == "SH" else bare.startswith(("300", "301"))
        return STAR_CHINEXT_PCT if growth else MAIN_BOARD_PCT
    return None


def default_limit_pct(code: str, st_codes: Collection[str] = ()) -> Decimal:
    """返回证券默认涨跌幅；主板 ST 降为 5%，20%/30% 板块的 ST 不降幅。

    st_codes 可注入（全码或裸码均可匹配），默认空即无 ST。
    """
    board_pct = _board_pct(code) if code else None
    if board_pct is None:
        raise ValueError(f"无法识别市场板块 {code!r}")
    bare = code.partition(".")[0]
    st = code in st_codes or bare in st_codes
    if st and board_pct == MAIN_BOARD_PCT:
        return ST_PCT
    return board_pct


def _finite_decimal(value: float | Decimal | None) -> Decimal | None:
    """float → 精确 Decimal（经 str 规避二进制尾差）；None/非有限/bool 返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    parsed = Decimal(str(value))
    return parsed if parsed.is_finite() else None


def limit_price(
    prev_close: float | Decimal,
    pct: float | Decimal,
    *,
    up: bool = True,
    min_tick_rule: bool = False,
) -> Decimal:
    """单侧限制价：``prev_close × (1 ± pct)`` 经 ROUND_HALF_UP 量化到分。

    min_tick_rule 为深市最小一跳（深交所交易规则 3.3.16）：限制价与前收之差
    绝对值不足一个最小变动单位时，取前收 ± 0.01；非法输入显式 ValueError
    （首 bar 无前收等 unknown 语义由 C02 消费，此处只抛错不静默）。
    """
    prev = _finite_decimal(prev_close)
    if prev is None or prev <= 0:
        raise ValueError(f"非法前收 {prev_close!r}")
    rate = _finite_decimal(pct)
    if rate is None or rate <= 0:
        raise ValueError(f"非法涨跌幅 {pct!r}")
    factor = _ONE + rate if up else _ONE - rate
    price = (prev * factor).quantize(_TICK, rounding=ROUND_HALF_UP)
    if min_tick_rule and abs(price - prev) < _TICK:
        price = prev + _TICK if up else prev - _TICK
        # 防御：前收非分网格时 ±一跳仍可能非网格，再量化保证输出恒在分网格
        price = price.quantize(_TICK, rounding=ROUND_HALF_UP)
    # A 股最低报价 0.01 元：跌停价不得落到 0
    price = max(price, _TICK)
    return price
