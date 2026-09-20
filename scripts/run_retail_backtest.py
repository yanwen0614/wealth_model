"""散户友好模型回测：综合评分选股 + 封板过滤 + 日胜率追踪。

策略流程（逐日）：
  1. 模型推理 → 每只股票 (p_bin 胜率概率, ret_pred 预期涨幅)
  2. 阈值过滤：保留 p_bin ≥ calibrated_threshold 的候选
  3. 封板排除：T+1 open 涨停不可买入的剔除
  4. 综合评分：score = α * p_bin + (1-α) * normalized(ret_pred)
  5. 按 score 降序取前 max_picks_per_day 只
  6. 若当日无候选 → 0 只持仓
  7. 计算日胜率（选中股票中实际涨幅 >0 的比例）& 均涨幅

用法：
  # 从预计算预测文件回测
  uv run --project . python -m scripts.run_retail_backtest
    --preds logs/retail_preds.npz
    --threshold 0.72 --max_picks 50

  # 加载模型在线推理+回测
  uv run --project . python -m scripts.run_retail_backtest
    --model logs/run_retail_xxx/best_model.pth
    --infer_cfg logs/run_retail_xxx/inference_config.json
    --eval_start 2026-01-01 --eval_end 2026-08-31
    --max_picks 50 --alpha 0.5
"""

import argparse
import json
import os
from typing import Optional, Tuple

import numpy as np

# ── 常量 ──
LIMIT_BASE = 1.098
LIMIT_20PCT = 1.198
LIMIT_20PCT_PREFIXES = ("300", "688")
RET_NPZ_KEYS = ("p_bin", "ret_pred", "true_ret", "dates", "codes")


# ══════════════════════════════════════════════════════
#  核心策略函数
# ══════════════════════════════════════════════════════

def _as_str(c) -> str:
    return c.decode("utf-8") if isinstance(c, bytes) else str(c)


def _norm_dates(d) -> np.ndarray:
    return np.asarray(d).astype("datetime64[D]")


def _is_limit_up(open_t1: float, prev_close: float, code: str) -> bool:
    """判断 T+1 开盘是否涨停。主板 1.098，科创/创业 1.198。"""
    thr = LIMIT_20PCT if code[:3] in LIMIT_20PCT_PREFIXES else LIMIT_BASE
    return open_t1 >= prev_close * thr


def retail_strategy_daily(
    p_bin: np.ndarray,
    ret_pred: np.ndarray,
    codes: np.ndarray,
    open_t1: np.ndarray,
    prev_close: np.ndarray,
    *,
    threshold: float = 0.65,
    alpha: float = 0.5,
    max_picks: int = 100,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """单日散户选股策略。

    Args:
        p_bin: 胜率概率 [N]
        ret_pred: 预期涨幅 [N]
        codes: 股票代码 [N]
        open_t1: T+1 open 价 [N]
        prev_close: T 日 close 价 [N]
        threshold: 决策阈值
        alpha: 综合评分权重（α * p_bin + (1-α) * norm(ret_pred)）
        max_picks: 每日最大推荐标的数

    Returns:
        picked_idx, scores, p_bin_picked, n_limit_up, n_filtered
    """
    N = len(p_bin)
    if N == 0:
        return np.array([], dtype=int), np.array([]), np.array([]), 0, 0

    # 1. 阈值过滤
    above_th = p_bin >= threshold
    n_filtered = int((~above_th).sum())

    # 2. 封板排除
    limit_up_mask = np.array([
        _is_limit_up(open_t1[i], prev_close[i], _as_str(codes[i]))
        for i in range(N)
    ], dtype=bool)
    n_limit_up = int(limit_up_mask.sum())

    candidate_mask = above_th & (~limit_up_mask)
    candidate_idx = np.where(candidate_mask)[0]
    if len(candidate_idx) == 0:
        return np.array([], dtype=int), np.array([]), np.array([]), n_limit_up, n_filtered

    # 3. 综合评分：α * p_bin + (1-α) * norm(ret_pred)
    p_vals = p_bin[candidate_idx]
    r_vals = ret_pred[candidate_idx]
    r_min, r_max = np.percentile(r_vals, [1, 99])
    r_range = max(r_max - r_min, 1e-8)
    r_norm = np.clip((r_vals - r_min) / r_range, 0.0, 1.0)
    scores = alpha * p_vals + (1.0 - alpha) * r_norm

    # 4. 排序选前 N
    order = np.argsort(-scores)
    n_pick = min(len(order), max_picks)
    top_idx = order[:n_pick]
    picked_idx = candidate_idx[top_idx]
    return picked_idx, scores[top_idx], p_vals[top_idx], n_limit_up, n_filtered


# ══════════════════════════════════════════════════════
#  预测缓存加载/保存
# ══════════════════════════════════════════════════════

def load_retail_preds(path: str) -> dict:
    """加载零售模型预测缓存并校验完整性。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"预测缓存不存在: {path}")
    data = np.load(path, allow_pickle=False)
    keys = [k for k in RET_NPZ_KEYS if k in data]
    if len(keys) != len(RET_NPZ_KEYS):
        raise ValueError(f"预测缓存缺少必需键: {set(RET_NPZ_KEYS) - set(keys)}")
    lengths = {k: len(data[k]) for k in keys}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"预测缓存字段长度不一致: {lengths}")
    return {k: data[k] for k in keys}


def save_retail_preds(path: str, p_bin, ret_pred, true_ret, dates, codes):
    """保存零售模型预测缓存。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    np.savez_compressed(path, p_bin=p_bin, ret_pred=ret_pred,
                        true_ret=true_ret, dates=dates, codes=codes)
    print(f"预测缓存已保存: {path}  ({len(p_bin)} 样本)")


# ══════════════════════════════════════════════════════
#  回测主逻辑
# ══════════════════════════════════════════════════════

def run_retail_backtest(
    p_bin: np.ndarray,
    ret_pred: np.ndarray,
    true_ret: np.ndarray,
    dates: np.ndarray,
    codes: np.ndarray,
    *,
    threshold: float = 0.65,
    alpha: float = 0.5,
    max_picks: int = 100,
    min_picks_for_winrate: int = 3,
    ohlc: Optional[dict] = None,
) -> dict:
    """执行散户策略回测。

    Args:
        p_bin: 胜率概率 [N]
        ret_pred: 预期涨幅 [N]
        true_ret: 实际收益率 [N]
        dates: 标签日期 [N]
        codes: 股票代码 [N]
        threshold: 决策阈值
        alpha: 综合评分权重
        max_picks: 每日最大推荐标的数
        min_picks_for_winrate: 计算日胜率所需最小标的数
        ohlc: OHLC 字典（含 open_t1, t_close），缺省时不检查涨停

    Returns:
        results 字典
    """
    dates_n = _norm_dates(dates)
    trade_days = np.unique(dates_n)
    n_days = len(trade_days)
    day_indices = {d: np.where(dates_n == d)[0] for d in trade_days}

    # OHLC 查询表（涨停检查）
    ohlc_lut = None
    open_t1_all = t_close_all = None
    if ohlc is not None:
        ohlc_codes = np.asarray(ohlc["codes"])
        ohlc_dates = _norm_dates(ohlc["dates"])
        open_t1_all = np.asarray(ohlc["open_t1"], dtype=np.float64)
        t_close_all = np.asarray(ohlc["t_close"], dtype=np.float64)
        ohlc_lut = {(_as_str(ohlc_codes[i]), ohlc_dates[i]): i
                     for i in range(len(ohlc_codes))}

    daily_results = []
    total_limit_up = total_filtered = total_picks = 0

    for d in trade_days:
        idx = day_indices[d]
        N_day = len(idx)
        if N_day == 0:
            daily_results.append({"date": str(d), "n_picks": 0,
                                  "win_rate": float("nan"), "avg_ret": float("nan")})
            continue

        # 本日截面
        p_day = p_bin[idx]
        r_day = ret_pred[idx]
        c_day = codes[idx]
        tr_day = true_ret[idx]

        # OHLC 涨停检查
        if ohlc_lut is not None:
            o1_arr = np.full(N_day, np.nan, dtype=np.float64)
            pc_arr = np.full(N_day, np.nan, dtype=np.float64)
            for j in range(N_day):
                row = ohlc_lut.get((_as_str(c_day[j]), d))
                if row is not None:
                    o1_arr[j] = open_t1_all[row]
                    pc_arr[j] = t_close_all[row]
        else:
            o1_arr = np.full(N_day, np.nan, dtype=np.float64)
            pc_arr = np.full(N_day, np.nan, dtype=np.float64)

        picked_idx, _, _, n_lim, n_filt = retail_strategy_daily(
            p_day, r_day, c_day, o1_arr, pc_arr,
            threshold=threshold, alpha=alpha, max_picks=max_picks,
        )
        total_limit_up += n_lim
        total_filtered += n_filt
        n_picks = len(picked_idx)
        total_picks += n_picks

        if n_picks > 0:
            picked_true_ret = tr_day[picked_idx]
            win_rate = float((picked_true_ret > 0).mean())
            avg_ret = float(picked_true_ret.mean())
        else:
            win_rate = float("nan")
            avg_ret = float("nan")

        daily_results.append({
            "date": str(d), "n_picks": n_picks,
            "win_rate": win_rate, "avg_ret": avg_ret,
            "n_eligible": int((p_day >= threshold).sum()),
            "n_limit_up": n_lim,
        })

    # ── 汇总指标 ──
    days_min3 = [r for r in daily_results if r["n_picks"] >= min_picks_for_winrate]
    days_any = [r for r in daily_results if r["n_picks"] > 0]

    if days_min3:
        wr_arr = np.array([r["win_rate"] for r in days_min3])
        ar_arr = np.array([r["avg_ret"] for r in days_min3])
        overall_wr = float(wr_arr.mean())
        overall_ar = float(ar_arr.mean())
        pct_ge75 = float((wr_arr >= 0.75).mean())
    else:
        overall_wr = float("nan")
        overall_ar = float("nan")
        pct_ge75 = 0.0

    return {
        "n_days": n_days,
        "n_days_with_picks": len(days_any),
        "pct_days_with_picks": len(days_any) / max(n_days, 1),
        "total_picks": total_picks,
        "avg_picks_per_day": total_picks / max(n_days, 1),
        "avg_picks_per_day_with_picks": total_picks / max(len(days_any), 1),
        "overall_win_rate": overall_wr,
        "overall_avg_return": overall_ar,
        "pct_days_win_rate_ge_75": pct_ge75,
        "total_limit_up_excluded": total_limit_up,
        "total_threshold_filtered": total_filtered,
        "daily_results": daily_results,
    }


# ══════════════════════════════════════════════════════
#  报告打印
# ══════════════════════════════════════════════════════

def print_retail_report(results: dict, threshold: float, alpha: float, max_picks: int):
    """打印零售策略回测报告。"""
    r = results
    print("\n" + "=" * 60)
    print("  散户友好模型回测报告")
    print("=" * 60)
    print(f"  策略: threshold={threshold:.3f}, alpha={alpha:.1f}, max_picks={max_picks}")
    print("-" * 60)
    print(f"  回测天数:              {r['n_days']}")
    print(f"  有选股天数:            {r['n_days_with_picks']}  ({r['pct_days_with_picks']:.1%})")
    print(f"  总选股次数:            {r['total_picks']}")
    print(f"  日均选股（全期）:      {r['avg_picks_per_day']:.1f}")
    print(f"  日均选股（有选股）:    {r['avg_picks_per_day_with_picks']:.1f}")

    wr = r["overall_win_rate"]
    ar = r["overall_avg_return"]
    print(f"  日胜率（均值）:        {wr:.2%}" if np.isfinite(wr) else "  日胜率（均值）:        N/A")
    print(f"  日均涨幅（选中标的）:  {ar:.4f}" if np.isfinite(ar) else "  日均涨幅（选中标的）:  N/A")
    print(f"  日胜率≥75%占比:        {r['pct_days_win_rate_ge_75']:.2%}")
    print(f"  涨停排除总数:          {r['total_limit_up_excluded']}")
    print(f"  阈值过滤总数:          {r['total_threshold_filtered']}")
    print("-" * 60)

    # 日胜率分布
    win_rates = [d["win_rate"] for d in r["daily_results"]
                 if not np.isnan(d["win_rate"]) and d["n_picks"] > 0]
    if win_rates:
        wr_arr = np.array(win_rates)
        edges = [0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.01]
        labels = ["0-25%", "25-50%", "50-60%", "60-70%",
                  "70-75%", "75-80%", "80-90%", "90-100%", "100%"]
        print("  日胜率分布（有选股日）:")
        for i in range(len(edges) - 1):
            cnt = int(((wr_arr >= edges[i]) & (wr_arr < edges[i + 1])).sum())
            if cnt > 0:
                print(f"    {labels[i]:>10}: {cnt:>4d} {'█' * min(cnt, 60)}")

    print("=" * 60)
    print("\n最近 5 个交易日详情:")
    print(f"{'日期':>12} | {'选股数':>6} | {'日胜率':>8} | {'均涨幅':>8} | {'候选':>6} | {'涨停排除':>8}")
    print("-" * 60)
    for dr in r["daily_results"][-5:]:
        wr_s = f"{dr['win_rate']:.2%}" if np.isfinite(dr["win_rate"]) else "  N/A"
        ar_s = f"{dr['avg_ret']:.4f}" if np.isfinite(dr["avg_ret"]) else "  N/A"
        print(f"{dr['date']:>12} | {dr['n_picks']:>6d} | {wr_s:>8} | {ar_s:>8} | "
              f"{dr['n_eligible']:>6d} | {dr.get('n_limit_up', 0):>8d}")


# ══════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════

def parse_args(argv: Optional[list] = None):
    p = argparse.ArgumentParser(description="散户模型回测")
    p.add_argument("--preds", type=str, default=None, help="预计算预测 .npz")
    p.add_argument("--model", type=str, default=None, help="模型 checkpoint")
    p.add_argument("--infer_cfg", type=str, default=None, help="推理配置 .json")
    p.add_argument("--parquet", type=str, default=None, help="Parquet 路径")
    p.add_argument("--eval_start", type=str, default=None)
    p.add_argument("--eval_end", type=str, default=None)
    p.add_argument("--ohlc", type=str, default=None, help="OHLC .npz（涨停检查）")
    p.add_argument("--threshold", type=float, default=0.65)
    p.add_argument("--alpha", type=float, default=0.5)
    p.add_argument("--max_picks", type=int, default=100)
    p.add_argument("--output", type=str, default=None, help="结果输出路径")
    return p.parse_args(argv)


def main():
    args = parse_args()

    # 加载预测数据
    if args.preds:
        print(f"加载预测缓存: {args.preds}")
        preds = load_retail_preds(args.preds)
    elif args.model:
        print("在线推理模式（需补充实现 dates/codes 提取）")
        # TODO: 完整在线推理链路
        raise NotImplementedError("在线推理暂需配合 eval 脚本生成 .npz 后回测")
    else:
        raise ValueError("请指定 --preds 或 --model")

    # 加载 OHLC
    ohlc_data = None
    if args.ohlc and os.path.exists(args.ohlc):
        print(f"加载 OHLC 数据: {args.ohlc}")
        ohlc_data = np.load(args.ohlc, allow_pickle=False)

    # 执行回测
    print(f"\n回测参数: threshold={args.threshold}, alpha={args.alpha}, max_picks={args.max_picks}")
    results = run_retail_backtest(
        preds["p_bin"], preds["ret_pred"], preds["true_ret"],
        preds["dates"], preds["codes"],
        threshold=args.threshold, alpha=args.alpha, max_picks=args.max_picks,
        ohlc=ohlc_data,
    )

    # 打印报告
    print_retail_report(results, args.threshold, args.alpha, args.max_picks)

    # 保存结果
    if args.output:
        import dataclasses

        # 将 NaN 转 None 以便 JSON 序列化
        def clean(v):
            if isinstance(v, float) and np.isnan(v):
                return None
            if isinstance(v, np.ndarray):
                return v.tolist()
            return v

        clean_results = {k: clean(v) for k, v in results.items()}
        clean_results.pop("daily_results", None)  # 详细数据太大
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(clean_results, f, indent=2, ensure_ascii=False)
        print(f"\n结果已保存: {args.output}")

    # 判断是否达标
    wr = results["overall_win_rate"]
    if np.isfinite(wr) and wr >= 0.75:
        print(f"\n✓ 达标！日胜率 {wr:.2%} ≥ 75%")
    elif np.isfinite(wr):
        print(f"\n✗ 未达标：日胜率 {wr:.2%} < 75%，建议提高阈值或调整 alpha")
    print()


if __name__ == "__main__":
    main()
