"""信号稳定性 + 换手/成本联合诊断工具（只读分析，不干预训练/回测流程）。

用法：
  # 单缓存分析
  uv run python scripts/signal_diagnostics.py <pred_cache.npz> [--output_dir ./diagnostics]

  # 多 seed 对比
  uv run python scripts/signal_diagnostics.py --multi_seed <p1.npz,p2.npz,p3.npz> --output_dir ./diagnostics

模块设计：
  - 核心计算函数均为纯 numpy/pandas，无副作用
  - 绘图使用 matplotlib（Agg 后端），输出 PNG 至 ``output_dir``
  - 汇总指标写 ``{output_dir}/summary.json``
  - 只读：不修改 npz 缓存、不写回测状态、不导入训练模块
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.use("Agg")

# ── CJK 字体 —— 自动检测 Noto Sans CJK（服务器已安装），无则静默回退 DejaVu ──
import matplotlib.font_manager as _fm

_cjk_fonts = [f.name for f in _fm.fontManager.ttflist
              if "noto" in f.name.lower() and "cjk" in f.name.lower()]
if _cjk_fonts:
    plt.rcParams["font.sans-serif"] = [_cjk_fonts[0]] + plt.rcParams["font.sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# ── 常量 ────────────────────────────────────────────────────────────────────
UNIFIED_COMMISSION_RATE = 0.0002  # 佣万 2 双边
UNIFIED_STAMP_RATE = 0.0005  # 印花税卖万 5
UNIFIED_TRANSFER_RATE = 0.00001  # 过户费万 0.1 双边
UNIFIED_MIN_COMMISSION = 5.0  # 最低佣金 5 元

# 查询窗口：衰减分析中检查 T+1/T+2/T+5 的索引偏移
DECAY_HORIZONS = (1, 2, 5)


# ═════════════════════════════════════════════════════════════════════════════
# 1. 信号稳定性 — RankIC 时序
# ═════════════════════════════════════════════════════════════════════════════


def _spearman_rank(x: np.ndarray) -> np.ndarray:
    """返回数组的排名（1..N），处理 NaN 和 ties。"""
    # scipy.stats.rankdata 的纯 numpy 替代
    order = np.argsort(x)
    ranks = np.empty_like(order, dtype=np.float64)
    ranks[order] = np.arange(1, len(x) + 1, dtype=np.float64)
    # 处理 ties：相同值取平均排名
    unique_vals, counts = np.unique(x, return_counts=True)
    if np.any(counts > 1):
        for val, cnt in zip(unique_vals, counts):
            if cnt > 1:
                mask = x == val
                avg_rank = float(np.mean(ranks[mask]))
                ranks[mask] = avg_rank
    return ranks


def _spearmanr(a: np.ndarray, b: np.ndarray) -> float:
    """Spearman 秩相关系数（无 scipy 依赖）。"""
    n = len(a)
    if n < 3:
        return 0.0
    rk_a = _spearman_rank(a)
    rk_b = _spearman_rank(b)
    # Pearson on ranks
    diff = rk_a - np.mean(rk_a)
    diff_b = rk_b - np.mean(rk_b)
    num = np.sum(diff * diff_b)
    den = np.sqrt(np.sum(diff ** 2) * np.sum(diff_b ** 2))
    if den == 0.0:
        return 0.0
    return float(num / den)


def compute_rankic_series(
    exp_ret: np.ndarray,
    true_ret: np.ndarray,
    dates: np.ndarray,
    min_cross_section: int = 30,
) -> dict:
    """逐日 RankIC，返回均值/std/IR/时序数组。

    Parameters
    ----------
    exp_ret : np.ndarray
        预测收益（一维）。
    true_ret : np.ndarray
        真实收益（一维，与 exp_ret 对齐）。
    dates : np.ndarray
        逐样本日期（与 exp_ret 等长）。
    min_cross_section : int
        截面最小样本数，低于此跳过。

    Returns
    -------
    dict
        ``{"ic_mean", "ic_std", "ic_ir", "ic_series", "dates_series", "ic_positive_pct"}``。
    """
    unique_dates = np.unique(dates)
    ic_series: list[float] = []
    date_series: list[str] = []
    for d in unique_dates:
        mask = dates == d
        sz = int(mask.sum())
        if sz < min_cross_section:
            continue
        e = exp_ret[mask].astype(np.float64)
        r = true_ret[mask].astype(np.float64)
        # 过滤非有限值
        finite = np.isfinite(e) & np.isfinite(r)
        if finite.sum() < min_cross_section:
            continue
        ic = _spearmanr(e[finite], r[finite])
        ic_series.append(ic)
        date_series.append(str(d))

    arr = np.array(ic_series, dtype=np.float64)
    mean_ic = float(np.mean(arr)) if len(arr) > 0 else 0.0
    std_ic = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    ir = mean_ic / std_ic if std_ic > 0 else 0.0
    pos_pct = float(np.mean(arr > 0)) if len(arr) > 0 else 0.0
    return {
        "ic_mean": mean_ic,
        "ic_std": std_ic,
        "ic_ir": ir,
        "ic_series": arr.tolist(),
        "dates_series": date_series,
        "ic_positive_pct": pos_pct,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 2. 信号稳定性 — Top-K 重合率
# ═════════════════════════════════════════════════════════════════════════════


def _topk_codes(
    exp_ret: np.ndarray,
    codes: np.ndarray,
    k: int,
) -> set:
    """返回当日前 k 个最大 exp_ret 对应的 code 集合。"""
    if len(exp_ret) < k:
        # 截面样本不足 k 时返回全部有限
        return set(codes[np.isfinite(exp_ret)])
    # 降序取前 k
    order = np.argsort(-exp_ret)
    return set(codes[order[:k]])


def compute_topk_overlap(
    exp_ret: np.ndarray,
    codes: np.ndarray,
    dates: np.ndarray,
    k_values: list[int] | None = None,
) -> dict:
    """前后日 top-k Jaccard 相似度。

    Parameters
    ----------
    exp_ret : np.ndarray
        预测收益。
    codes : np.ndarray
        标的代码。
    dates : np.ndarray
        日期。
    k_values : list[int], optional
        要计算的 k 列表，默认 ``[10, 20, 50]``。

    Returns
    -------
    dict
        ``{"k_values": ..., "mean_overlaps": {k: mean}, "std_overlaps": {k: std},
            "overlap_series": {k: [float,...]}, "dates_series": [str,...]}``。
    """
    if k_values is None:
        k_values = [10, 20, 50]

    unique_dates = np.unique(dates)
    if len(unique_dates) < 2:
        return {
            "k_values": k_values,
            "mean_overlaps": {k: 0.0 for k in k_values},
            "std_overlaps": {k: 0.0 for k in k_values},
            "overlap_series": {k: [] for k in k_values},
            "dates_series": [],
        }

    # 预先计算每日 top-k 集合
    daily_topk: dict[str, dict[int, set]] = {}
    for d in unique_dates:
        mask = dates == d
        e = exp_ret[mask].astype(np.float64)
        c = codes[mask]
        finite = np.isfinite(e)
        e, c = e[finite], c[finite]
        if len(e) < min(k_values):
            # 当日样本太少，跳过
            continue
        daily_topk[str(d)] = {k: _topk_codes(e, c, k) for k in k_values}

    sorted_dates = sorted(daily_topk.keys())
    if len(sorted_dates) < 2:
        return {
            "k_values": k_values,
            "mean_overlaps": {k: 0.0 for k in k_values},
            "std_overlaps": {k: 0.0 for k in k_values},
            "overlap_series": {k: [] for k in k_values},
            "dates_series": sorted_dates,
        }

    overlap_series: dict[int, list[float]] = {k: [] for k in k_values}
    for i in range(1, len(sorted_dates)):
        prev_d = sorted_dates[i - 1]
        curr_d = sorted_dates[i]
        for k in k_values:
            s1 = daily_topk[prev_d][k]
            s2 = daily_topk[curr_d][k]
            if len(s1 | s2) == 0:
                jaccard = 0.0
            else:
                jaccard = len(s1 & s2) / len(s1 | s2)
            overlap_series[k].append(jaccard)

    mean_overlaps = {
        k: float(np.mean(overlap_series[k])) if overlap_series[k] else 0.0
        for k in k_values
    }
    std_overlaps = {
        k: float(np.std(overlap_series[k], ddof=1)) if len(overlap_series[k]) > 1 else 0.0
        for k in k_values
    }

    return {
        "k_values": k_values,
        "mean_overlaps": mean_overlaps,
        "std_overlaps": std_overlaps,
        "overlap_series": overlap_series,
        "dates_series": sorted_dates[1:],  # 与 overlap_series 对齐
    }


# ═════════════════════════════════════════════════════════════════════════════
# 3. 信号漂移 — Top-K 掉出比例
# ═════════════════════════════════════════════════════════════════════════════


def compute_signal_drift(
    exp_ret: np.ndarray,
    codes: np.ndarray,
    dates: np.ndarray,
    top_k: int = 10,
    drift_k: int = 50,
) -> dict:
    """逐日 top-k 中次日掉出 drift_k 的比例。

    Parameters
    ----------
    exp_ret : np.ndarray
        预测收益。
    codes : np.ndarray
        标的代码。
    dates : np.ndarray
        日期。
    top_k : int
        关注的前 k 个（默认 10）。
    drift_k : int
        掉出判断阈值（默认 50）。

    Returns
    -------
    dict
        ``{"mean_drift_rate", "std_drift_rate", "drift_series", "dates_series"}``。
    """
    unique_dates = np.unique(dates)
    if len(unique_dates) < 2:
        return {
            "mean_drift_rate": 0.0,
            "std_drift_rate": 0.0,
            "drift_series": [],
            "dates_series": [],
        }

    # 预计算每日 top-k 和 top-drift_k 的 code 集合
    daily_topk: dict[str, set] = {}
    daily_top_drift: dict[str, set] = {}
    for d in unique_dates:
        mask = dates == d
        e = exp_ret[mask].astype(np.float64)
        c = codes[mask]
        finite = np.isfinite(e)
        e, c = e[finite], c[finite]
        if len(e) < drift_k:
            continue
        daily_topk[str(d)] = _topk_codes(e, c, top_k)
        daily_top_drift[str(d)] = _topk_codes(e, c, drift_k)

    sorted_dates = sorted(daily_topk.keys())
    drift_series: list[float] = []
    date_series: list[str] = []
    for i in range(len(sorted_dates) - 1):
        curr_d = sorted_dates[i]
        next_d = sorted_dates[i + 1]
        curr_top = daily_topk[curr_d]
        next_drift = daily_top_drift[next_d]
        if len(curr_top) == 0:
            continue
        dropped = curr_top - next_drift
        rate = len(dropped) / len(curr_top)
        drift_series.append(rate)
        date_series.append(curr_d)

    arr = np.array(drift_series, dtype=np.float64)
    mean_drift = float(np.mean(arr)) if len(arr) > 0 else 0.0
    std_drift = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    return {
        "mean_drift_rate": mean_drift,
        "std_drift_rate": std_drift,
        "drift_series": drift_series,
        "dates_series": date_series,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 4. 多 Seed 稳定性
# ═════════════════════════════════════════════════════════════════════════════


def _daily_rank_matrix(caches: list[dict]) -> dict:
    """构建各 cache 每日排序矩阵用于 Kendall's W 计算。

    返回 ``{"dates": [str,...], "codes": [...], "ranks": {date: np.ndarray (n_seed, n_codes)}}``。
    仅取各 cache 每日共有的 code。
    """
    # 收集所有 cache 的 daily codes
    cache_daily_codes: list[dict[str, set]] = []
    for cache in caches:
        exp = np.asarray(cache["exp_ret"], dtype=np.float64)
        cd = np.asarray(cache["codes"])
        dt = np.asarray(cache["dates"])
        daily: dict[str, set] = {}
        for d in np.unique(dt):
            mask = dt == d
            e = exp[mask]
            c = cd[mask]
            finite = np.isfinite(e)
            daily[str(d)] = set(c[finite])
        cache_daily_codes.append(daily)

    # 取公共日期
    common_dates = sorted(
        set.intersection(*[set(d.keys()) for d in cache_daily_codes])
    )

    result: dict[str, list | np.ndarray | dict] = {"dates": common_dates}
    n_seed = len(caches)

    for d in common_dates:
        # 取所有 cache 当日共有的 code
        common_codes = sorted(
            set.intersection(*[cache_daily_codes[i][d] for i in range(n_seed)])
        )
        code_to_idx = {code: i for i, code in enumerate(common_codes)}
        n_codes = len(common_codes)
        if n_codes < 3:
            continue

        rank_mat = np.zeros((n_seed, n_codes), dtype=np.float64)
        valid = True
        for s_idx, cache in enumerate(caches):
            exp = np.asarray(cache["exp_ret"], dtype=np.float64)
            cd = np.asarray(cache["codes"])
            dt = np.asarray(cache["dates"])
            mask = dt == d
            e_day = exp[mask]
            c_day = cd[mask]
            finite = np.isfinite(e_day)
            e_day, c_day = e_day[finite], c_day[finite]
            # 构建该 seed 当日排序
            day_ranks = np.argsort(np.argsort(-e_day)) + 1  # 1..n
            day_code_map = dict(zip(c_day, day_ranks))
            for code in common_codes:
                r = day_code_map.get(code)
                if r is None:
                    valid = False
                    break
                rank_mat[s_idx, code_to_idx[code]] = r
            if not valid:
                break

        if not valid:
            continue

        if "ranks" not in result:
            result["ranks"] = {}
        result["ranks"][d] = rank_mat

    return result


def _kendall_w(rank_matrix: np.ndarray) -> float:
    """Kendall's W（协和系数）：多 raters 排序一致性。

    取值 0..1，1 表示完全一致。
    """
    n_raters, n_items = rank_matrix.shape
    if n_items < 2 or n_raters < 2:
        return 0.0
    # 各 item 的秩和
    R = np.sum(rank_matrix, axis=0)
    # 秩和均值
    R_mean = np.mean(R)
    # 离差平方和
    S = np.sum((R - R_mean) ** 2)
    # Kendall's W = 12*S / (n_raters^2 * (n_items^3 - n_items))
    denom = n_raters ** 2 * (n_items ** 3 - n_items)
    if denom == 0:
        return 0.0
    w = 12.0 * S / denom
    return min(float(w), 1.0)


def compute_seed_stability(
    caches: list[dict],
    k: int = 10,
) -> dict:
    """多 seed 稳定性分析。

    Parameters
    ----------
    caches : list[dict]
        ``load_prediction_cache`` 产出的缓存列表。
    k : int
        top-k 重合分析用的 k 值（默认 10）。

    Returns
    -------
    dict
        ``{"n_seeds", "cross_seed_ic_corr", "topk_intersection_ratio",
            "kendall_w_mean", "kendall_w_std", "return_spread_mean",
            "topk_agreement_series", "kendall_w_series", "dates_series"}``。
    """
    n_seeds = len(caches)
    if n_seeds < 2:
        return {"n_seeds": n_seeds, "error": "至少需要 2 个 seed 进行分析"}

    # ── 跨 seed RankIC 相关 ──
    ic_series_list = []
    for cache in caches:
        ic_info = compute_rankic_series(
            np.asarray(cache["exp_ret"], dtype=np.float64),
            np.asarray(cache["true_ret"], dtype=np.float64),
            np.asarray(cache["dates"]),
        )
        ic_series_list.append(ic_info["ic_series"])

    # 取公共日期长度
    min_len = min(len(s) for s in ic_series_list)
    ic_arr = np.array([s[:min_len] for s in ic_series_list], dtype=np.float64)

    # 两两 Pearson 相关
    ic_corr_matrix = np.corrcoef(ic_arr)
    # 取上三角均值
    triu_vals = ic_corr_matrix[np.triu_indices(n_seeds, k=1)]
    mean_ic_corr = float(np.mean(triu_vals)) if len(triu_vals) > 0 else 0.0

    # ── Top-K 跨 seed 重合 ──
    # 每日：各 seed 取 top-k，计算交集/并集
    common_dates = sorted(
        set.intersection(
            *[
                set(np.unique(np.asarray(cache["dates"])))
                for cache in caches
            ]
        )
    )

    topk_agreement_series: list[float] = []
    kendall_w_series: list[float] = []
    date_series: list[str] = []

    for d in common_dates:
        seed_topk: list[set] = []
        for cache in caches:
            exp = np.asarray(cache["exp_ret"], dtype=np.float64)
            cd = np.asarray(cache["codes"])
            dt = np.asarray(cache["dates"])
            mask = dt == d
            e = exp[mask]
            c = cd[mask]
            finite = np.isfinite(e)
            e, c = e[finite], c[finite]
            if len(e) < k:
                seed_topk.append(set())
            else:
                seed_topk.append(_topk_codes(e, c, k))
        # 只取全都有 top-k 的日期
        if any(len(s) == 0 for s in seed_topk):
            continue
        # 交集 / 并集
        inter = set.intersection(*seed_topk) if len(seed_topk) > 1 else seed_topk[0]
        union = set.union(*seed_topk)
        ratio = len(inter) / len(union) if len(union) > 0 else 0.0
        topk_agreement_series.append(ratio)
        date_series.append(str(d))

    # ── Kendall's W ──
    rank_data = _daily_rank_matrix(caches)
    if "ranks" in rank_data:
        for d in rank_data["ranks"]:
            w = _kendall_w(rank_data["ranks"][d])
            kendall_w_series.append(w)

    w_arr = np.array(kendall_w_series, dtype=np.float64)
    w_mean = float(np.mean(w_arr)) if len(w_arr) > 0 else 0.0
    w_std = float(np.std(w_arr, ddof=1)) if len(w_arr) > 1 else 0.0

    # ── 收益差异（组合收益 spread） ──
    # 用 top-k 等权组合日均收益
    returns_list: list[list[float]] = []
    for cache in caches:
        exp = np.asarray(cache["exp_ret"], dtype=np.float64)
        true = np.asarray(cache["true_ret"], dtype=np.float64)
        dt = np.asarray(cache["dates"])
        cd = np.asarray(cache["codes"])
        daily_rets: list[float] = []
        for d in common_dates:
            mask = dt == d
            e = exp[mask]
            r = true[mask]
            c = cd[mask]
            finite = np.isfinite(e) & np.isfinite(r)
            e, r, c = e[finite], r[finite], c[finite]
            if len(e) < k:
                continue
            order = np.argsort(-e)[:k]
            daily_rets.append(float(np.mean(r[order])))
        returns_list.append(daily_rets)

    if all(len(r) > 0 for r in returns_list):
        min_ret_len = min(len(r) for r in returns_list)
        ret_arr = np.array([r[:min_ret_len] for r in returns_list], dtype=np.float64)
        # 每日 max-min spread
        spreads = np.max(ret_arr, axis=0) - np.min(ret_arr, axis=0)
        return_spread_mean = float(np.mean(spreads))
    else:
        return_spread_mean = 0.0

    return {
        "n_seeds": n_seeds,
        "cross_seed_ic_corr": mean_ic_corr,
        "topk_intersection_ratio": (
            float(np.mean(topk_agreement_series)) if topk_agreement_series else 0.0
        ),
        "kendall_w_mean": w_mean,
        "kendall_w_std": w_std,
        "return_spread_mean": return_spread_mean,
        "topk_agreement_series": topk_agreement_series,
        "kendall_w_series": kendall_w_series,
        "dates_series": date_series,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. 换手/成本诊断
# ═════════════════════════════════════════════════════════════════════════════


def _estimate_transaction_cost(
    buy_amount: float,
    sell_amount: float,
    buy_rate: float = UNIFIED_COMMISSION_RATE,
    sell_rate: float = UNIFIED_COMMISSION_RATE,
    stamp_rate: float = UNIFIED_STAMP_RATE,
    transfer_rate: float = UNIFIED_TRANSFER_RATE,
    min_commission: float = UNIFIED_MIN_COMMISSION,
) -> float:
    """估计交易成本。

    买入成本 = max(买入额 * 佣金率, 最低佣金) + 买入额 * 过户费率
    卖出成本 = max(卖出额 * 佣金率, 最低佣金) + 卖出额 * 印花税率 + 卖出额 * 过户费率
    """
    buy_commission = max(buy_amount * buy_rate, min_commission)
    sell_commission = max(sell_amount * sell_rate, min_commission)
    buy_cost = buy_commission + buy_amount * transfer_rate
    sell_cost = sell_commission + sell_amount * stamp_rate + sell_amount * transfer_rate
    return buy_cost + sell_cost


def compute_turnover_diagnostics(
    exp_ret: np.ndarray,
    codes: np.ndarray,
    dates: np.ndarray,
    top_n: int = 10,
    avg_price: float | None = None,
) -> dict:
    """换手/成本诊断。

    Parameters
    ----------
    exp_ret : np.ndarray
        预测收益。
    codes : np.ndarray
        标的代码。
    dates : np.ndarray
        日期。
    top_n : int
        组合规模（默认 10）。
    avg_price : float, optional
        平均股价（元），用于估计交易金额。None 时用默认 15.0 元。

    Returns
    -------
    dict
        ``{"daily_turnover_mean", "daily_turnover_std", "daily_turnover_series",
            "cost_per_trade_mean", "cost_per_trade_std",
            "total_cost_est", "cost_as_pct_of_nav",
            "avg_holding_days", "holding_days_distribution",
            "dates_series"}``。
    """
    if avg_price is None:
        avg_price = 15.0

    unique_dates = np.unique(dates)
    if len(unique_dates) < 2:
        return {
            "daily_turnover_mean": 0.0,
            "daily_turnover_std": 0.0,
            "daily_turnover_series": [],
            "cost_per_trade_mean": 0.0,
            "cost_per_trade_std": 0.0,
            "total_cost_est": 0.0,
            "cost_as_pct_of_nav": 0.0,
            "avg_holding_days": 0.0,
            "holding_days_distribution": {},
            "dates_series": [],
        }

    # ── 逐日组合成分 ──
    daily_portfolio: dict[str, set] = {}
    for d in unique_dates:
        mask = dates == d
        e = exp_ret[mask].astype(np.float64)
        c = codes[mask]
        finite = np.isfinite(e)
        e, c = e[finite], c[finite]
        if len(e) < top_n:
            continue
        order = np.argsort(-e)[:top_n]
        daily_portfolio[str(d)] = set(c[order])

    sorted_dates = sorted(daily_portfolio.keys())
    if len(sorted_dates) < 2:
        return {
            "daily_turnover_mean": 0.0,
            "daily_turnover_std": 0.0,
            "daily_turnover_series": [],
            "cost_per_trade_mean": 0.0,
            "cost_per_trade_std": 0.0,
            "total_cost_est": 0.0,
            "cost_as_pct_of_nav": 0.0,
            "avg_holding_days": 0.0,
            "holding_days_distribution": {},
            "dates_series": [],
        }

    # ── 日均换手率 ──
    turnover_series: list[float] = []
    cost_series: list[float] = []
    for i in range(1, len(sorted_dates)):
        prev = daily_portfolio[sorted_dates[i - 1]]
        curr = daily_portfolio[sorted_dates[i]]
        turnover = len(curr - prev) / top_n  # 新进比例
        turnover_series.append(turnover)

        # 成本估计：进出各 turnover * top_n 只
        new_entries = len(curr - prev)
        exited = len(prev - curr)
        # 假设每只买入 avg_price 元，买入股数归一化到等权 1/组合规模
        # 交易金额 = 数量 * avg_price，每笔假设投资组合净值的 1/top_n
        assumed_nav = top_n * avg_price  # 简化 NAV = 满仓 with avg_price
        amount_per_stock = assumed_nav / top_n
        buy_amt = new_entries * amount_per_stock
        sell_amt = exited * amount_per_stock
        cost = _estimate_transaction_cost(buy_amt, sell_amt)
        cost_series.append(cost)

    turnover_arr = np.array(turnover_series, dtype=np.float64)
    cost_arr = np.array(cost_series, dtype=np.float64)

    avg_turnover = float(np.mean(turnover_arr)) if len(turnover_arr) > 0 else 0.0
    std_turnover = float(np.std(turnover_arr, ddof=1)) if len(turnover_arr) > 1 else 0.0
    avg_cost = float(np.mean(cost_arr)) if len(cost_arr) > 0 else 0.0
    std_cost = float(np.std(cost_arr, ddof=1)) if len(cost_arr) > 1 else 0.0
    total_cost = float(np.sum(cost_arr))
    assumed_nav_total = len(sorted_dates) * top_n * avg_price
    cost_pct = total_cost / assumed_nav_total if assumed_nav_total > 0 else 0.0

    # ── 持仓稳定性 ──
    # 记录每只 code 连续在组合中的天数
    code_holding: dict[str, int] = {}
    code_streaks: list[int] = []
    for code in set.union(*daily_portfolio.values()):
        in_portfolio = [
            1 if code in daily_portfolio.get(d, set()) else 0
            for d in sorted_dates
        ]
        # 找最长连续持有
        max_streak = 0
        current = 0
        for v in in_portfolio:
            if v == 1:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        if max_streak > 0:
            code_streaks.append(max_streak)
            code_holding[code] = max_streak

    avg_holding = float(np.mean(code_streaks)) if code_streaks else 0.0

    # 分布
    holding_dist: dict[str, int] = {}
    for s in code_streaks:
        if s <= 1:
            key = "1天"
        elif s <= 3:
            key = "2-3天"
        elif s <= 7:
            key = "4-7天"
        elif s <= 14:
            key = "8-14天"
        else:
            key = "15天+"
        holding_dist[key] = holding_dist.get(key, 0) + 1

    return {
        "daily_turnover_mean": avg_turnover,
        "daily_turnover_std": std_turnover,
        "daily_turnover_series": turnover_series,
        "cost_per_trade_mean": avg_cost,
        "cost_per_trade_std": std_cost,
        "total_cost_est": total_cost,
        "cost_as_pct_of_nav": cost_pct,
        "avg_holding_days": avg_holding,
        "holding_days_distribution": holding_dist,
        "dates_series": sorted_dates[1:],
    }


# ═════════════════════════════════════════════════════════════════════════════
# 6. 信号衰减速度 — 分组位置随时间的演变
# ═════════════════════════════════════════════════════════════════════════════


def compute_signal_decay(
    exp_ret: np.ndarray,
    true_ret: np.ndarray,
    codes: np.ndarray,
    dates: np.ndarray,
    top_n: int = 10,
    n_groups: int = 10,
    horizons: tuple[int, ...] | None = None,
) -> dict:
    """信号衰减：当日 top-N 在 T+h 日的分组位置。

    将截面股票按 exp_ret 等分为 n_groups 组，记录当日 top-N 股票
    在 T+1, T+2, T+5 日所属分组序号（1=最高分组, n_groups=最低）。

    Parameters
    ----------
    exp_ret : np.ndarray
        预测收益（T 日）。
    true_ret : np.ndarray
        真实收益（与 exp_ret 对齐），用于分组排序。
    codes : np.ndarray
        标的代码。
    dates : np.ndarray
        日期。
    top_n : int
        关注的 top-N（默认 10）。
    n_groups : int
        分组数（默认 10）。
    horizons : tuple[int, ...], optional
        衰减检查的 horizon（索引偏移），默认 ``(1, 2, 5)``。

    Returns
    -------
    dict
        ``{"top_n", "n_groups", "horizons",
            "mean_group_positions": {h: float}, "std_group_positions": {h: float},
            "relative_rank_by_horizon": {h: {"series": [...], "mean": float}}}``。
    """
    if horizons is None:
        horizons = DECAY_HORIZONS

    unique_dates_str = [str(d) for d in np.unique(dates)]
    if len(unique_dates_str) < max(horizons) + 1:
        return {
            "top_n": top_n,
            "n_groups": n_groups,
            "horizons": list(horizons),
            "error": "日期数不足，无法计算衰减",
        }

    # 构建日期→索引映射
    date_to_idx: dict[str, int] = {
        d: i for i, d in enumerate(unique_dates_str)
    }

    # 逐日预计算所有股票的分组
    daily_groups: dict[str, dict[str, int]] = {}
    for d in unique_dates_str:
        mask = dates == d
        r = true_ret[mask].astype(np.float64)
        c = codes[mask]
        finite = np.isfinite(r)
        r, c = r[finite], c[finite]
        if len(c) < n_groups:
            continue
        # 按 true_ret 降序分 n_groups 组
        order = np.argsort(-r)
        sorted_codes = c[order]
        group_size = len(sorted_codes) // n_groups
        groups: dict[str, int] = {}
        for g in range(n_groups):
            start = g * group_size
            end = start + group_size if g < n_groups - 1 else len(sorted_codes)
            for code in sorted_codes[start:end]:
                groups[str(code)] = g + 1  # 1=最高收益组
        daily_groups[d] = groups

    # 对每个 horizon 计算衰减
    result = {}
    for h in horizons:
        pos_series: list[float] = []
        for d in unique_dates_str:
            idx = date_to_idx[d]
            target_idx = idx + h
            if target_idx >= len(unique_dates_str):
                continue
            target_d = unique_dates_str[target_idx]

            # 当天 top-N 的 code
            mask = dates == d
            e = exp_ret[mask].astype(np.float64)
            c = codes[mask]
            finite = np.isfinite(e)
            e, c = e[finite], c[finite]
            if len(e) < top_n:
                continue
            order = np.argsort(-e)[:top_n]
            top_codes = set(c[order])

            # 检查这些 code 在 T+h 日的分组位置
            target_groups = daily_groups.get(target_d, {})
            positions = [
                target_groups.get(str(code))
                for code in top_codes
                if str(code) in target_groups
            ]
            if len(positions) < 2:
                continue
            avg_pos = float(np.mean(positions))
            pos_series.append(avg_pos)

        arr = np.array(pos_series, dtype=np.float64)
        result[h] = {
            "series": pos_series,
            "mean": float(np.mean(arr)) if len(arr) > 0 else float("nan"),
        }

    # 计算各 horizon 的均值/标准差
    mean_positions = {}
    std_positions = {}
    for h in horizons:
        info = result.get(h, {})
        series = info.get("series", [])
        mean_positions[h] = info.get("mean", float("nan"))
        s = np.array(series, dtype=np.float64)
        std_positions[h] = float(np.std(s, ddof=1)) if len(s) > 1 else 0.0

    return {
        "top_n": top_n,
        "n_groups": n_groups,
        "horizons": list(horizons),
        "mean_group_positions": mean_positions,
        "std_group_positions": std_positions,
        "relative_rank_by_horizon": result,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 绘图函数
# ═════════════════════════════════════════════════════════════════════════════


def _ensure_output_dir(path: str) -> str:
    """确保输出目录存在。"""
    os.makedirs(path, exist_ok=True)
    return path


def plot_rankic_series(rankic: dict, output_dir: str) -> str:
    """绘制 RankIC 时序图，返回文件路径。"""
    series = np.array(rankic.get("ic_series", []))
    dates_s = rankic.get("dates_series", [])
    if len(series) < 2 or len(dates_s) < 2:
        # 数据不足，生成空图说明
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(0.5, 0.5, "RankIC 数据不足，无法绘图", ha="center", va="center", fontsize=14)
        ax.set_title("RankIC 时序")
        path = os.path.join(output_dir, "rankic_series.png")
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return path

    # 累积和
    cumsum = np.cumsum(series)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    x = range(len(series))
    ax1.plot(x, series, color="steelblue", linewidth=0.8, label="日度 RankIC")
    ax1.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax1.axhline(
        y=rankic.get("ic_mean", 0), color="red", linestyle=":", linewidth=0.8,
        label=f"均值={rankic['ic_mean']:.4f}",
    )
    ax1.set_ylabel("RankIC")
    ax1.set_title(f"RankIC 时序 (均值={rankic['ic_mean']:.4f}, IR={rankic['ic_ir']:.4f}, IC>0={rankic['ic_positive_pct']:.1%})")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.plot(x, cumsum, color="darkgreen", linewidth=1.0, label="累积 RankIC")
    ax2.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax2.set_ylabel("累积 RankIC")
    ax2.set_xlabel("交易日序号")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # 标注日期刻度（稀疏）
    n = len(dates_s)
    step = max(1, n // 10)
    tick_positions = list(range(0, n, step))
    tick_labels = [dates_s[i] if i < n else "" for i in tick_positions]
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, rotation=45, fontsize=8)

    plt.tight_layout()
    path = os.path.join(output_dir, "rankic_series.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_topk_overlap(overlap: dict, output_dir: str) -> str:
    """绘制 Top-K 重合率时序图，返回文件路径。"""
    k_values = overlap.get("k_values", [10, 20, 50])
    dates_s = overlap.get("dates_series", [])

    fig, axes = plt.subplots(len(k_values), 1, figsize=(12, 3 * len(k_values)), sharex=True)
    if len(k_values) == 1:
        axes = [axes]

    for idx, k in enumerate(k_values):
        series = overlap.get("overlap_series", {}).get(k, [])
        mean_val = overlap.get("mean_overlaps", {}).get(k, 0)
        ax = axes[idx]
        if len(series) > 0:
            x = range(len(series))
            ax.plot(x, series, color="steelblue", linewidth=0.7)
            ax.axhline(y=mean_val, color="red", linestyle=":", linewidth=0.8,
                       label=f"均值={mean_val:.3f}")
        ax.set_ylabel(f"Top-{k} Jaccard")
        ax.set_title(f"Top-{k} 前后日重合率 (均值={mean_val:.3f})")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    if len(dates_s) > 0:
        n = len(dates_s)
        step = max(1, n // 10)
        tick_positions = list(range(0, n, step))
        tick_labels = [dates_s[i] if i < n else "" for i in tick_positions]
        axes[-1].set_xticks(tick_positions)
        axes[-1].set_xticklabels(tick_labels, rotation=45, fontsize=8)

    axes[-1].set_xlabel("交易日序号")
    plt.tight_layout()
    path = os.path.join(output_dir, "topk_overlap.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_seed_comparison(seed_result: dict, output_dir: str) -> str:
    """绘制多 seed 对比图，返回文件路径。"""
    n_seeds = seed_result.get("n_seeds", 0)
    topk_series = seed_result.get("topk_agreement_series", [])
    kendall_series = seed_result.get("kendall_w_series", [])
    dates_s = seed_result.get("dates_series", [])

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Top-K 重合率
    ax1 = axes[0]
    if topk_series:
        x = range(len(topk_series))
        ax1.plot(x, topk_series, color="steelblue", linewidth=0.8,
                 label=f"Top-K 重合率 (均值={seed_result.get('topk_intersection_ratio', 0):.3f})")
    ax1.set_ylabel("Top-K 重合率")
    ax1.set_title(f"跨 Seed Top-K 重合率 (n_seeds={n_seeds})")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Kendall's W
    ax2 = axes[1]
    if kendall_series:
        x = range(len(kendall_series))
        ax2.plot(x, kendall_series, color="darkgreen", linewidth=0.8,
                 label=f"Kendall's W (均值={seed_result.get('kendall_w_mean', 0):.3f})")
    ax2.set_ylabel("Kendall's W")
    ax2.set_title(f"排序一致性 Kendall's W (均值={seed_result.get('kendall_w_mean', 0):.3f})")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    if len(dates_s) > 0:
        n = len(dates_s)
        step = max(1, n // 10)
        tick_positions = list(range(0, n, step))
        tick_labels = [dates_s[i] if i < n else "" for i in tick_positions]
        axes[-1].set_xticks(tick_positions)
        axes[-1].set_xticklabels(tick_labels, rotation=45, fontsize=8)

    axes[-1].set_xlabel("交易日序号")
    plt.tight_layout()
    path = os.path.join(output_dir, "seed_comparison.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_cost_analysis(turnover: dict, output_dir: str) -> str:
    """绘制换手/成本分析图，返回文件路径。"""
    turnover_series = turnover.get("daily_turnover_series", [])
    holding_dist = turnover.get("holding_days_distribution", {})

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # 换手率时序
    ax1 = axes[0]
    if turnover_series:
        x = range(len(turnover_series))
        ax1.plot(x, turnover_series, color="coral", linewidth=0.8,
                 label=f"日均换手={turnover.get('daily_turnover_mean', 0):.3f}")
        ax1.axhline(y=turnover.get("daily_turnover_mean", 0), color="red", linestyle=":", linewidth=0.8)
    ax1.set_ylabel("日换手率")
    ax1.set_title("组合日换手率")
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # 成本时序
    ax2 = axes[1]
    ax2.bar(
        ["日均成本"],
        [turnover.get("cost_per_trade_mean", 0)],
        color="lightcoral",
        alpha=0.7,
    )
    ax2.set_ylabel("每笔交易成本 (元)")
    ax2.set_title(f"交易成本估计\n总成本={turnover.get('total_cost_est', 0):.2f}元, "
                  f"占NAV={turnover.get('cost_as_pct_of_nav', 0):.4%}")

    # 持仓天数分布
    ax3 = axes[2]
    if holding_dist:
        labels = list(holding_dist.keys())
        values = list(holding_dist.values())
        colors = plt.cm.Blues(np.linspace(0.4, 0.8, len(labels)))
        ax3.bar(labels, values, color=colors, alpha=0.7)
        ax3.set_xlabel("持仓天数")
        ax3.set_ylabel("出现次数")
        ax3.set_title(f"持仓天数分布\n平均={turnover.get('avg_holding_days', 0):.1f}天")
        for label in ax3.get_xticklabels():
            label.set_rotation(30)

    plt.tight_layout()
    path = os.path.join(output_dir, "cost_analysis.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_signal_decay(decay: dict, output_dir: str) -> str:
    """绘制信号衰减图，返回文件路径。"""
    horizons = decay.get("horizons", [])
    means = decay.get("mean_group_positions", {})

    fig, ax = plt.subplots(figsize=(8, 5))

    if means:
        h_labels = [f"T+{h}" for h in horizons]
        values = [means.get(h, float("nan")) for h in horizons]
        valid = [(l, v) for l, v in zip(h_labels, values) if not np.isnan(v)]
        if valid:
            labels, vals = zip(*valid)
            ax.plot(labels, vals, marker="o", color="darkorange", linewidth=2, markersize=8)
            ax.axhline(y=1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5, label="最佳分组=1")
            for l, v in zip(labels, vals):
                ax.annotate(f"{v:.2f}", (l, v), textcoords="offset points",
                            xytext=(0, 10), ha="center", fontsize=10)
            ax.set_ylabel("平均分组位置 (1=最佳)")
            ax.set_title(f"信号衰减：Top-{decay.get('top_n', 10)} 在各 Horizon 的分组位置")
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(output_dir, "signal_decay.png")
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# 汇总输出
# ═════════════════════════════════════════════════════════════════════════════


def _serialize(obj):
    """JSON 序列化辅助：处理 NumPy 类型和 NaN。"""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        if np.isnan(val) or np.isinf(val):
            return None
        return val
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return _serialize(obj.tolist())
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    return obj


def write_summary(summary: dict, output_dir: str) -> str:
    """写 summary.json，返回文件路径。"""
    path = os.path.join(output_dir, "summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_serialize(summary), f, indent=2, ensure_ascii=False)
    return path


# ═════════════════════════════════════════════════════════════════════════════
# CLI 入口
# ═════════════════════════════════════════════════════════════════════════════


def _load_cache(path: str) -> dict:
    """加载预测缓存 npz（复用 backtest.cnn_adapter.cache 的 load_prediction_cache）。"""
    from backtest.cnn_adapter.cache import load_prediction_cache

    cache = load_prediction_cache(path)
    return {
        "exp_ret": np.asarray(cache["exp_ret"], dtype=np.float64),
        "true_ret": (
            np.asarray(cache["true_ret"], dtype=np.float64)
            if cache.get("true_ret") is not None
            else np.zeros(len(cache["exp_ret"]), dtype=np.float64)
        ),
        "dates": np.asarray(cache["dates"]),
        "codes": np.asarray(cache["codes"]),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="信号稳定性 + 换手/成本联合诊断工具",
    )
    p.add_argument("pred_cache", nargs="?", default=None,
                   help="预测缓存 npz 路径")
    p.add_argument("--multi_seed", default=None,
                   help="多 seed 对比：逗号分隔的 npz 路径列表")
    p.add_argument("--output_dir", default="./diagnostics",
                   help="输出目录（默认 ./diagnostics）")
    p.add_argument("--top_n", type=int, default=10,
                   help="组合规模（默认 10）")
    p.add_argument("--min_cross_section", type=int, default=30,
                   help="截面最小样本数（默认 30）")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    output_dir = _ensure_output_dir(args.output_dir)

    multi_seed = args.multi_seed
    single_cache = args.pred_cache

    if multi_seed:
        # 多 seed 模式
        paths = [p.strip() for p in multi_seed.split(",")]
        if len(paths) < 2:
            print("错误：--multi_seed 至少需要 2 个 npz 路径")
            sys.exit(1)

        print(f"加载 {len(paths)} 个预测缓存...")
        caches = [_load_cache(p) for p in paths]
        print(f"  各缓存样本数: {[len(c['exp_ret']) for c in caches]}")

        # 单 seed 诊断（第一个作为代表）
        print("\n=== 信号稳定性分析（首个 seed）===")
        rankic = compute_rankic_series(
            caches[0]["exp_ret"], caches[0]["true_ret"],
            caches[0]["dates"], args.min_cross_section,
        )
        print(f"  RankIC: 均值={rankic['ic_mean']:.4f}, 标准差={rankic['ic_std']:.4f}, "
              f"IR={rankic['ic_ir']:.4f}, IC>0={rankic['ic_positive_pct']:.1%}")
        overlap = compute_topk_overlap(
            caches[0]["exp_ret"], caches[0]["codes"],
            caches[0]["dates"],
        )
        for k in overlap["k_values"]:
            print(f"  Top-{k} 重合率: 均值={overlap['mean_overlaps'][k]:.4f}")
        drift = compute_signal_drift(
            caches[0]["exp_ret"], caches[0]["codes"],
            caches[0]["dates"],
        )
        print(f"  信号漂移(Top-{args.top_n}→50): 均值={drift['mean_drift_rate']:.4f}")
        turnover = compute_turnover_diagnostics(
            caches[0]["exp_ret"], caches[0]["codes"],
            caches[0]["dates"], args.top_n,
        )
        print(f"  日均换手率: {turnover['daily_turnover_mean']:.4f}")
        print(f"  总成本估计: {turnover['total_cost_est']:.2f}元")
        print(f"  平均持仓: {turnover['avg_holding_days']:.1f}天")
        decay = compute_signal_decay(
            caches[0]["exp_ret"], caches[0]["true_ret"],
            caches[0]["codes"], caches[0]["dates"], args.top_n,
        )
        if "error" not in decay:
            for h in decay["horizons"]:
                m = decay["mean_group_positions"].get(h, float("nan"))
                print(f"  T+{h} 分组位置: {m:.2f}")

        # 多 seed 诊断
        print("\n=== 多 Seed 稳定性分析 ===")
        seed_stab = compute_seed_stability(caches, k=args.top_n)
        print(f"  Seed 数: {seed_stab['n_seeds']}")
        print(f"  跨 seed IC 相关: {seed_stab.get('cross_seed_ic_corr', 0):.4f}")
        print(f"  Top-K 重合率: {seed_stab.get('topk_intersection_ratio', 0):.4f}")
        print(f"  Kendall's W: {seed_stab.get('kendall_w_mean', 0):.4f}")
        print(f"  收益 spread: {seed_stab.get('return_spread_mean', 0):.6f}")

        # 绘图
        plot_rankic_series(rankic, output_dir)
        plot_topk_overlap(overlap, output_dir)
        plot_seed_comparison(seed_stab, output_dir)
        plot_cost_analysis(turnover, output_dir)
        plot_signal_decay(decay, output_dir)
        print(f"\n图表已保存至: {output_dir}")

        # 汇总
        summary = {
            "mode": "multi_seed",
            "n_seeds": len(caches),
            "seed_paths": paths,
            "rankic": rankic,
            "overlap": overlap,
            "drift": drift,
            "turnover": turnover,
            "decay": decay,
            "seed_stability": seed_stab,
        }
        write_summary(summary, output_dir)
        print(f"汇总已保存: {os.path.join(output_dir, 'summary.json')}")

    elif single_cache:
        # 单缓存模式
        path = single_cache
        print(f"加载预测缓存: {path}")
        cache = _load_cache(path)
        print(f"  样本数: {len(cache['exp_ret'])}")
        print(f"  日期范围: {np.min(cache['dates'])} ~ {np.max(cache['dates'])}")

        # 信号稳定性
        print("\n=== 信号稳定性分析 ===")
        rankic = compute_rankic_series(
            cache["exp_ret"], cache["true_ret"],
            cache["dates"], args.min_cross_section,
        )
        print(f"  RankIC: 均值={rankic['ic_mean']:.4f}, 标准差={rankic['ic_std']:.4f}, "
              f"IR={rankic['ic_ir']:.4f}, IC>0={rankic['ic_positive_pct']:.1%}")

        overlap = compute_topk_overlap(
            cache["exp_ret"], cache["codes"],
            cache["dates"],
        )
        print("\n  Top-K 前后日重合率:")
        for k in overlap["k_values"]:
            print(f"    Top-{k}: 均值={overlap['mean_overlaps'][k]:.4f}, "
                  f"标准差={overlap['std_overlaps'][k]:.4f}")

        drift = compute_signal_drift(
            cache["exp_ret"], cache["codes"],
            cache["dates"],
        )
        print(f"  信号漂移(Top-{args.top_n}→50): 均值={drift['mean_drift_rate']:.4f}, "
              f"标准差={drift['std_drift_rate']:.4f}")

        # 换手/成本
        print("\n=== 换手/成本诊断 ===")
        turnover = compute_turnover_diagnostics(
            cache["exp_ret"], cache["codes"],
            cache["dates"], args.top_n,
        )
        print(f"  日均换手率: {turnover['daily_turnover_mean']:.4f} "
              f"(标准差={turnover['daily_turnover_std']:.4f})")
        print(f"  日均交易成本: {turnover['cost_per_trade_mean']:.2f}元")
        print(f"  总成本估计: {turnover['total_cost_est']:.2f}元 "
              f"(占 NAV {turnover['cost_as_pct_of_nav']:.4%})")
        print(f"  平均持仓天数: {turnover['avg_holding_days']:.1f}天")
        print(f"  持仓分布: {turnover['holding_days_distribution']}")

        # 信号衰减
        print("\n=== 信号衰减分析 ===")
        decay = compute_signal_decay(
            cache["exp_ret"], cache["true_ret"],
            cache["codes"], cache["dates"], args.top_n,
        )
        if "error" in decay:
            print(f"  {decay['error']}")
        else:
            for h in decay["horizons"]:
                m = decay["mean_group_positions"].get(h, float("nan"))
                s = decay["std_group_positions"].get(h, 0.0)
                if not np.isnan(m):
                    print(f"  T+{h} 分组位置: 均值={m:.2f}, 标准差={s:.4f}")

        # 绘图
        print("\n=== 生成图表 ===")
        plot_rankic_series(rankic, output_dir)
        print("  rankic_series.png")
        plot_topk_overlap(overlap, output_dir)
        print("  topk_overlap.png")
        plot_cost_analysis(turnover, output_dir)
        print("  cost_analysis.png")
        plot_signal_decay(decay, output_dir)
        print("  signal_decay.png")
        print(f"图表已保存至: {output_dir}")

        # 汇总
        summary = {
            "mode": "single",
            "cache_path": path,
            "n_samples": int(len(cache["exp_ret"])),
            "date_range": [
                str(np.min(cache["dates"])),
                str(np.max(cache["dates"])),
            ],
            "rankic": rankic,
            "overlap": overlap,
            "drift": drift,
            "turnover": turnover,
            "decay": decay,
        }
        write_summary(summary, output_dir)
        print(f"\n汇总已保存: {os.path.join(output_dir, 'summary.json')}")

    else:
        print("错误：请指定预测缓存 npz 路径或 --multi_seed")
        sys.exit(1)


if __name__ == "__main__":
    main()
