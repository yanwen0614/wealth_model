"""data identity 单一事实源：canonical JSON + sha256（T06）。

四处旧实现（feature_cache._canonical_digest / scaler.identity_hash_for /
rolling_scaler._canonical_hash / dataset._RollingDatasetState._identity_hash）
语义均为 json(sort_keys+separators)+sha256 hex，新模块中立收敛，避免偏向任一调用方。

确定性规则：
- dict 按 sort_keys 排序；list/tuple 等价；None/float 按 JSON 原语；
- numpy 标量归一为 Python 等价值（int/float/bool），ndarray 经 tolist 归一，
  使 numpy/Python 表述 digest 一致；未知类型回退 str（沿 feature_cache default=str 兼容）。
- e1/e2 同列集异语义靠 scope 名入 digest（rolling 侧 payload 保留 scope 字段，本模块不干预）。
- CACHE_FORMAT_VERSION / SCALER_VERSION / TRANSFORM_VERSION 语义均不由本模块改变。

零依赖：仅 json/hashlib/numpy，禁止 import data.*（防循环）。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import numpy as np

__all__ = ["canonical_bytes", "canonical_hash"]


def _normalize(obj: Any) -> Any:
    """将 payload 归一为纯 JSON 值（dict/list/str/num/bool/None）。"""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return _normalize(obj.tolist())
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, Mapping):
        return {key: _normalize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(value) for value in obj]
    return str(obj)


def canonical_bytes(payload: Any) -> bytes:
    """payload 的 canonical JSON 字节（sort_keys + 紧凑分隔 + ascii）。"""
    normalized = _normalize(payload)
    return json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_hash(payload: Any) -> str:
    """唯一 canonical sha256 hex（四处旧 digest 的收敛点）。"""
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
