"""逐元素归一化纯函数内核：三处 transform_code 的单事实源（T07）。

收敛 `data/scaler.py`（Relative/PerCode）与 `data/rolling_scaler.py` 非 scope 列的
逐元素语义：relative/asinh/clip01/fixed_clip + clip + 缺失填 0 + 共享 mask OR。
本模块零依赖 scaler/rolling/schema（仅 duck-type rule），由两侧单向导入，防循环。

正典顺序（与 scaler 一致，见 spec §4）：变换 →（P robust）→ clip →
缺失填 0 → 非有限填 0。rolling 旧 relative 分支为 fill→clip，仅在变换溢出为
inf 的病态输入下差 ±5（真实价格比值恒有限），其余输入逐位一致。
"""
from __future__ import annotations

from typing import Any

import numpy as np

IQR_TO_SIGMA = 1.349  # 正态下 IQR → σ 换算（robust 标准化分母；scaler 侧 re-export）
KERNEL_EPS = 1e-8  # robust 分母保护；scaler 侧以 EPS 别名 re-export


def relative_transform(values: np.ndarray, close: np.ndarray | None) -> np.ndarray:
    """P 组相对变换 x/close[t-1]-1；分母非有限/为 0/首行 → NaN；close 为空透传。"""
    vals = np.asarray(values, dtype=np.float64)
    if close is None:
        return vals
    helper = np.asarray(close, dtype=np.float64)
    previous = np.roll(helper, 1)
    previous[0] = np.nan
    valid = np.isfinite(previous) & (previous != 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.divide(vals, previous, out=np.full(vals.shape, np.nan), where=valid) - 1.0


def apply_column_rule(
    raw: np.ndarray,
    finite: np.ndarray | None,
    rule: Any,
    *,
    close: np.ndarray | None = None,
    stat: Any | None = None,
) -> np.ndarray:
    """逐元素应用单列规则；stat={median,iqr} 仅 P-robust（per-code 装配）时传入。"""
    vals = np.asarray(raw, dtype=np.float64)
    is_finite = np.asarray(finite, dtype=bool) if finite is not None else np.isfinite(vals)
    missing = ~is_finite
    transform = rule.transform
    if transform == "relative":
        transformed = relative_transform(vals, close)
        if stat is not None and getattr(rule, "robust", False):
            transformed = (transformed - float(stat["median"])) / (
                float(stat["iqr"]) / IQR_TO_SIGMA + KERNEL_EPS
            )
    elif transform == "asinh":
        transformed = np.arcsinh(vals * rule.scale)
    elif transform in ("clip01", "fixed_clip", "passthrough"):
        transformed = vals
    else:
        raise ValueError(f"未知 transform: {transform!r}")
    if rule.clip is not None:
        transformed = np.clip(transformed, rule.clip[0], rule.clip[1])
    transformed = np.where(missing, 0.0, transformed)
    return np.where(np.isfinite(transformed), transformed, 0.0)


def append_shared_mask(out: np.ndarray, observed: np.ndarray | None) -> np.ndarray:
    """out [N,F] 后追加一列共享 mask（observed OR；None → 全 0）。"""
    mat = np.asarray(out)
    count = mat.shape[0]
    if observed is None:
        mask = np.zeros(count, dtype=bool)
    else:
        mask = np.asarray(observed, dtype=bool).reshape(count)
    return np.concatenate([mat, mask.astype(np.float32).reshape(-1, 1)], axis=1)
