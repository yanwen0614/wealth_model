"""cnn 预测缓存读写（B01）：校验复用 data.schema，不自立第二套口径。"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping

import numpy as np

from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays

__all__ = [
    "OHLC_PATH_KEYS",
    "cache_fingerprint",
    "load_prediction_cache",
    "save_prediction_cache",
    "validate_ohlc_path_arrays",
]

# 与 scripts/run_backtest.py OHLC_KEYS 同口径（rolling 模式 ohlc 路径表）
OHLC_PATH_KEYS = ("codes", "dates", "t_close", "open_t1", "open_t6")


def save_prediction_cache(path, exp_ret, true_ret, dates, codes) -> None:
    """写预测缓存 npz；写前校验长度一致，不合格不落盘。"""
    arrays = {"exp_ret": np.asarray(exp_ret), "true_ret": np.asarray(true_ret),
              "dates": np.asarray(dates), "codes": np.asarray(codes)}
    validate_prediction_cache_arrays(arrays, str(path))
    # 显式关键字传参：**arrays 拆包会触发 pyright 对 savez 签名的误报
    np.savez(path, exp_ret=arrays["exp_ret"], true_ret=arrays["true_ret"],
             dates=arrays["dates"], codes=arrays["codes"])


def load_prediction_cache(path) -> dict:
    """读预测缓存 npz；缺键/长度不一致显式 ValueError（旧缓存缺 codes 会提示重建）。"""
    with np.load(path, allow_pickle=False) as z:
        arrays = {key: z[key] for key in z.files}
    validate_prediction_cache_arrays(arrays, str(path))
    return {key: arrays[key] for key in PREDICTION_CACHE_KEYS}


def validate_ohlc_path_arrays(arrays: Mapping, source: str = "OHLC 路径表") -> None:
    """校验 ohlc 路径表五键存在且逐行长度一致。"""
    missing = [key for key in OHLC_PATH_KEYS if key not in arrays]
    if missing:
        raise ValueError(f"{source} 缺少必需键 {missing}")
    lengths = {key: len(arrays[key]) for key in OHLC_PATH_KEYS}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{source} 字段长度不一致: {lengths}")


def cache_fingerprint(path) -> str:
    """缓存文件级稳定指纹：sha1(文件字节流)，分块读取避免大 npz 占内存。"""
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
