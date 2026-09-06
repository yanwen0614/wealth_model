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
