"""训练标签的纯函数（horizon 参数化：cnn 主链路默认 H10，goal H5 兼容同一入口）."""

import numpy as np


def _future_ret_open_open(open_arr: np.ndarray, horizon: int) -> np.ndarray:
    """计算 open[t+1+horizon] / open[t+1] - 1 的未来收益（可执行口径）."""
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


def future_ret_close_close(close_arr: np.ndarray, horizon: int) -> np.ndarray:
    """计算 close[t+horizon] / close[t] - 1 的未来收益（诊断/纸面口径，goal H5 同语义）.

    与 ``_future_ret_open_open`` 的区别仅在于计价点：本函数为同 bar 收盘口径
    （含隔夜缺口，不可直接执行），主链路标签仍用 open-open；跨 horizon（H5/H10）
    对比实验统一走本入口，避免各脚本自写下标。
    """
    close_arr = np.asarray(close_arr, dtype=np.float64)
    n = len(close_arr)
    future_ret = np.full(n, np.nan, dtype=np.float64)
    if horizon < 1 or n <= horizon:
        return future_ret
    base = close_arr[: n - horizon]
    target = close_arr[horizon:]
    valid_pair = np.isfinite(base) & np.isfinite(target) & (base > 0)
    values = np.full(len(base), np.nan, dtype=np.float64)
    values[valid_pair] = target[valid_pair] / base[valid_pair] - 1.0
    future_ret[: n - horizon] = values
    return future_ret


def quantile_labels(scores: np.ndarray, n_bins: int = 5) -> np.ndarray:
    """截面分位标签（goal qcut 语义的 numpy 版）：升序分位 0..n_bins-1（最高分得 n_bins-1）.

    分位边界退化（去重后不足 2 个边界）时返回全 -1（无效标记），调用方自行跳过该截面。
    """
    scores = np.asarray(scores, dtype=np.float64)
    labels = np.full(scores.shape, -1, dtype=np.int64)
    finite = np.isfinite(scores)
    if int(finite.sum()) < n_bins:
        return labels
    edges = np.quantile(scores[finite], np.linspace(0.0, 1.0, n_bins + 1))
    edges = np.unique(edges)
    if len(edges) < 3:
        return labels
    labels[finite] = np.digitize(scores[finite], edges[1:-1])
    return labels


def rank_ic(scores: np.ndarray, future_ret: np.ndarray) -> float:
    """无 scipy 依赖的 Spearman（rank 后 Pearson）；输入须无 NaN（调用方先过滤）."""
    x = np.asarray(scores, dtype=np.float64)
    y = np.asarray(future_ret, dtype=np.float64)
    xr = np.argsort(np.argsort(x)).astype(np.float64)
    yr = np.argsort(np.argsort(y)).astype(np.float64)
    xr -= xr.mean()
    yr -= yr.mean()
    denom = np.sqrt((xr ** 2).sum() * (yr ** 2).sum())
    return float((xr * yr).sum() / denom) if denom > 0 else 0.0


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
