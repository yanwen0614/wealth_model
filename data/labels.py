"""训练标签的纯函数。"""

import numpy as np


def _future_ret_open_open(open_arr: np.ndarray, horizon: int) -> np.ndarray:
    """计算 open[t+1+horizon] / open[t+1] - 1 的未来收益。"""
    n = len(open_arr)
    future_ret = np.full(n, np.nan, dtype=np.float64)
    if horizon < 1 or n <= horizon + 1:
        return future_ret
    valid = ~np.isnan(open_arr)
    base = open_arr[1: n - horizon]
    target = open_arr[1 + horizon:]
    valid_pair = valid[1: n - horizon] & valid[1 + horizon:] & (base > 0)
    values = np.full(len(base), np.nan, dtype=np.float64)
    values[valid_pair] = target[valid_pair] / base[valid_pair] - 1.0
    future_ret[: n - horizon - 1] = values
    return future_ret


def _cross_sectional_excess(
    dates: np.ndarray,
    future_ret: np.ndarray,
    min_count: int = 1,
) -> np.ndarray:
    """按 kline_time 日期分组，返回 `future_ret - 当日截面均值`（截面超额收益）。

    - 截面均值按 `dates` 逐日统计，仅纳入有限（非 NaN）标签，`is_trading=False`
      行已在上游过滤，不参与均值。
    - NaN 标签输出仍为 NaN（与原始 future_ret 的 NaN 位置一致）。
    - `min_count` 为当日有效标签数下限；不足则该日输出 NaN（默认 1，单股当日超额=0）。
    """
    dates = np.asarray(dates)
    future_ret = np.asarray(future_ret, dtype=np.float64)
    if dates.shape != future_ret.shape:
        raise ValueError(f"dates/future_ret 形状不一致: {dates.shape} vs {future_ret.shape}")
    if min_count < 1:
        raise ValueError("min_count 必须 >= 1")
    finite = np.isfinite(future_ret)
    if not finite.any():
        return np.full(future_ret.shape, np.nan, dtype=np.float64)
    day = dates[finite]
    valid_ret = future_ret[finite]
    # np.unique 的 inverse 与原数组同序：uniq[inverse] == day
    uniq, inverse, counts = np.unique(day, return_inverse=True, return_counts=True)
    means = np.bincount(inverse, weights=valid_ret, minlength=len(uniq)) / counts
    means = np.where(counts >= min_count, means, np.nan)
    mapped = np.empty(future_ret.shape, dtype=np.float64)
    mapped[finite] = means[inverse]
    mapped[~finite] = np.nan
    return future_ret - mapped
