# 加权IC评价：等权/加权Spearman+top20精度/利差四指标库
# 输入：单日exp预测向量与H10标签向量(重算ret，见a02_build_labels)
# 输出：spearman_eq/w值、head_stats精度与利差(供a04日度/a05汇总消费)
# 已验证：w_excl均值极低、月均IC与月均top20收益相关性落盘(a06)
import numpy as np
from scipy.stats import rankdata


def spearman_eq(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 3:
        return np.nan
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def spearman_w(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    w = np.abs(y)
    valid = np.isfinite(w) & (w > 0)
    excl = 1.0 - valid.mean() if len(y) else np.nan
    x, y, w = x[valid], y[valid], w[valid]
    if len(x) < 3:
        return np.nan, excl
    rx, ry = rankdata(x), rankdata(y)
    wn = w / w.sum()
    mx, my = (wn * rx).sum(), (wn * ry).sum()
    dx, dy = rx - mx, ry - my
    vx, vy = (wn * dx * dx).sum(), (wn * dy * dy).sum()
    if vx <= 0 or vy <= 0:
        return np.nan, excl
    return float((wn * dx * dy).sum() / np.sqrt(vx * vy)), excl


def head_stats(exp, true, k=20):
    m = np.isfinite(exp) & np.isfinite(true)
    exp, true = exp[m], true[m]
    if len(exp) < k:
        return np.nan, np.nan
    idx = np.argpartition(-exp, k - 1)[:k]
    prec = float((true[idx] > 0).mean())
    spread = float(true[idx].mean() - true.mean())
    return prec, spread
