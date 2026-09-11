"""cnn backtest adapter 共享工具（B01，cnn 原生实现，不搬运 quant 代码）.

只处理 numpy 输出：adapter 层禁 import torch。
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np

__all__ = ["SHANGHAI_TZ", "SIGNAL_HOUR", "npz_fingerprint", "require_keys", "signal_time_for"]

# 与 quant A01 / backtest-core 默认信号时区同口径：A 股收盘信号时点
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SIGNAL_HOUR = 15


def signal_time_for(trading_date: date, mode: str = "T1") -> datetime:
    """返回交易日的信号时间；默认 T1 即当日 15:00 Asia/Shanghai（tz-aware）。"""
    if mode != "T1":
        raise ValueError(f"未知信号模式 {mode!r}，仅支持 'T1'")
    return datetime.combine(trading_date, time(SIGNAL_HOUR, 0), tzinfo=SHANGHAI_TZ)


def require_keys(mapping: Mapping, keys, source: str) -> None:
    """缺键显式 ValueError，避免下游 KeyError 掩盖数据口径问题。"""
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(f"{source} 缺少必需键 {missing}")


def npz_fingerprint(arrays: Mapping) -> str:
    """NPZ 内容指纹：sha1(键排序 + 形状 + dtype + C 序字节)，dict 顺序无关、跨进程稳定。"""
    digest = hashlib.sha1()
    for key in sorted(arrays.keys()):
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
