"""三分评估规范脚本（严格 train/val/test 评估 + 阈值样本外校准）。

职责：
  1. 从预测缓存 npz（exp_ret/true_ret/dates/codes）加载 val 与 test 逐样本预测；
     缓存缺失时可用 --run_inference 复用 scripts/eval_bins_mapping 的推理逻辑现场生成。
  2. 对两个子集分别计算：截面 RankIC/ICIR/IC>0 比例、top-decile 多空 spread、
     top-N(N=5/10/20/50/100) 选股 precision/平均收益/跑赢截面中位数比例、
     阈值策略、绝对收益(累计/日均/最大回撤)、分年度 IC 稳定性。
  3. 严格阈值校准：仅在 val 上寻找 precision≈目标(默认 75%) 的 exp_ret 阈值，
     再原样应用到 test，报告 test 上真实的样本外 precision（这才是诚实结果）。

用法：
  uv run --project . python -m scripts.eval_three_way                    # 用现有缓存
  uv run --project . python -m scripts.eval_three_way --target_precision 0.7
  uv run --project . python -m scripts.eval_three_way --run_inference \
      --checkpoint logs/relative/run_20260914_024253/best_model.pth

设计约束：
  - 不改训练链路；只读评估。
  - val 与 test 日期边界由 CLI 显式给出，默认与现有缓存一致。
  - 阈值只在 val 上定，绝不在 test 上二次择优。
"""
from __future__ import annotations

import argparse
import json
import os
from argparse import Namespace

import numpy as np

from data.schema import validate_prediction_cache_arrays

VAL_START, VAL_END = "2025-07-01", "2025-12-31"
TEST_START, TEST_END = "2026-01-01", "2026-08-31"
DEFAULT_VAL_CACHE = "logs/eval_preds_52cls.npz"
DEFAULT_TEST_CACHE = "logs/preds_relative_run_20260914_024253_2026-08-31.npz"
DEFAULT_CHECKPOINT = "logs/relative/run_20260914_024253/best_model.pth"
TOPN_LIST = (5, 10, 20, 50, 100)
MIN_CROSS_SECTION = 100
CACHE_KEYS = ("exp_ret", "true_ret", "dates", "codes")


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """无 scipy 依赖的 Spearman（rank 后 Pearson）。"""
    xr = np.argsort(np.argsort(x)).astype(np.float64)
    yr = np.argsort(np.argsort(y)).astype(np.float64)
    xr -= xr.mean()
    yr -= yr.mean()
    denom = np.sqrt((xr ** 2).sum() * (yr ** 2).sum())
    return float((xr * yr).sum() / denom) if denom > 0 else 0.0


def load_cached(path: str, start: str, end: str) -> dict:
    """读取并校验预测缓存，按 [start, end] 裁剪后返回 exp_ret/true_ret/dates/codes。"""
    z = np.load(path, allow_pickle=False)
    arrays = {key: z[key] for key in CACHE_KEYS if key in z.files}
    validate_prediction_cache_arrays(arrays, path)
    dates = np.asarray(arrays["dates"]).astype("datetime64[D]")
    mask = (dates >= np.datetime64(start, "D")) & (dates <= np.datetime64(end, "D"))
    return {
        "exp_ret": np.asarray(arrays["exp_ret"], dtype=np.float64)[mask],
        "true_ret": np.asarray(arrays["true_ret"], dtype=np.float64)[mask],
        "dates": dates[mask],
        "codes": np.asarray(arrays["codes"])[mask],
    }


def date_coverage(dates: np.ndarray) -> tuple[str, str, int]:
    """返回 (最小日, 最大日, 唯一交易日数)。"""
    uni = np.unique(np.asarray(dates).astype("datetime64[D]"))
    if uni.size == 0:
        return "-", "-", 0
    return str(uni.min()), str(uni.max()), int(uni.size)


def daily_groups(dates: np.ndarray, min_xs: int):
    """按日分组，仅保留截面样本数 >= min_xs 的日期，返回 [(date, bool_mask), ...]。"""
    groups = []
    for d in np.unique(dates):
        m = dates == d
        if int(m.sum()) >= min_xs:
            groups.append((d, m))
    return groups


def daily_series(exp: np.ndarray, true: np.ndarray, dates: np.ndarray, min_xs: int) -> list:
    """逐日截面序列：返回 [(date, rank_ic, top10%-bot10% spread, xs_size), ...]。"""
    rows = []
    for d, m in daily_groups(dates, min_xs):
        e, r = exp[m], true[m]
        hi = r[e >= np.quantile(e, 0.9)]
        lo = r[e <= np.quantile(e, 0.1)]
        spread = float(hi.mean()) - float(lo.mean()) if hi.size and lo.size else np.nan
        rows.append((np.datetime64(d, "D"), spearman(e, r), spread, int(m.sum())))
    return rows


def topn_stats(exp: np.ndarray, true: np.ndarray, dates: np.ndarray,
               topn_list=TOPN_LIST, min_xs: int = MIN_CROSS_SECTION) -> dict:
    """逐日取预测 exp_ret 最高的 N 只，宏平均 precision / 平均收益 / 跑赢截面中位数比例。"""
    acc = {n: {"prec": [], "ret": [], "beat": []} for n in topn_list}
    for _d, m in daily_groups(dates, min_xs):
        e, r = exp[m], true[m]
        order = np.argsort(-e)
        med = float(np.median(r))
        for n in topn_list:
            rr = r[order[:min(n, len(order))]]
            acc[n]["prec"].append(float((rr > 0).mean()))
            acc[n]["ret"].append(float(rr.mean()))
            acc[n]["beat"].append(float((rr > med).mean()))
    out = {}
    for n in topn_list:
        out[n] = {k: (float(np.mean(v)) if v else 0.0) for k, v in acc[n].items()}
    return out


def apply_threshold(exp: np.ndarray, true: np.ndarray, thr: float) -> dict:
    """应用固定阈值 exp_ret >= thr，返回样本数 / precision / 平均真实收益。"""
    m = exp >= thr
    n = int(m.sum())
    if n == 0:
        return {"n": 0, "precision": 0.0, "mean_ret": 0.0}
    rr = true[m]
    return {"n": n, "precision": float((rr > 0).mean()), "mean_ret": float(rr.mean())}


def threshold_sweep(exp: np.ndarray, true: np.ndarray, thresholds) -> list:
    """给定阈值网格，逐点报告样本数/precision/平均收益（仅描述，不择优）。"""
    return [{"thr": float(t), **apply_threshold(exp, true, float(t))} for t in thresholds]


def calibrate_threshold(exp: np.ndarray, true: np.ndarray,
                        target: float = 0.75, min_count: int = 100) -> dict:
    """仅在给定集合上校准阈值：找满足 precision>=target 且样本数最多的最宽松阈值。

    做法：按 exp_ret 降序累计 precision；取 idx>=min_count 且累计 precision>=target 的最大 idx。
    若达不到 target，则报告 min_count 约束下可达的最高 precision（reached=False）。
    """
    order = np.argsort(-np.asarray(exp, dtype=np.float64))
    e_sorted = np.asarray(exp, dtype=np.float64)[order]
    r_sorted = np.asarray(true, dtype=np.float64)[order]
    idxs = np.arange(1, len(e_sorted) + 1)
    prec = np.cumsum(r_sorted > 0) / idxs
    valid = np.where((prec >= target) & (idxs >= min_count))[0]
    if valid.size:
        k = int(valid.max())
        return {"reached": True, "target": float(target), "thr": float(e_sorted[k]),
                "n": k + 1, "precision": float(prec[k]),
                "mean_ret": float(r_sorted[:k + 1].mean())}
    cand = np.where(idxs >= min_count)[0]
    if cand.size == 0:
        cand = np.array([0])
    best = int(cand[np.argmax(prec[cand])])
    return {"reached": False, "target": float(target), "thr": float(e_sorted[best]),
            "n": best + 1, "precision": float(prec[best]),
            "mean_ret": float(r_sorted[:best + 1].mean())}


def absolute_return(exp: np.ndarray, true: np.ndarray, dates: np.ndarray,
                    topn: int = 20, horizon: int = 5,
                    min_xs: int = MIN_CROSS_SECTION) -> dict:
    """等权 TopN 组合绝对收益（逐决策日 + 非重叠经济口径）。

    - 逐决策日组合收益 = 当日 TopN 的 mean(true_ret)（5 日 open-open 收益）。
    - 经济口径（非重叠）：每 horizon+1 个决策日取一次，复利得净值（避免持有期重叠重复计数）。
    - 同时报告重叠口径净值仅作参考。
    """
    per_day = []
    for d, m in daily_groups(dates, min_xs):
        e, r = exp[m], true[m]
        order = np.argsort(-e)[:min(topn, len(e))]
        per_day.append((np.datetime64(d, "D"), float(r[order].mean())))
    if not per_day:
        return {"n_days": 0, "daily_mean": 0.0, "cum_return": 0.0, "annual": 0.0, "mdd": 0.0,
                "cum_return_overlap": 0.0, "mdd_overlap": 0.0}
    rets = np.array([x[1] for x in per_day], dtype=np.float64)
    stride = max(1, horizon + 1)
    rets_no = rets[::stride]
    nav_no = np.cumprod(1.0 + rets_no)
    nav_ov = np.cumprod(1.0 + rets)

    def _mdd(nav):
        peak = np.maximum.accumulate(nav)
        return float((1.0 - nav / peak).max()) if nav.size else 0.0

    days_span = int((per_day[-1][0] - per_day[0][0]).astype("timedelta64[D]").astype(int))
    years = days_span / 365.25 if days_span > 0 else 0.0
    final = float(nav_no[-1]) if nav_no.size else 1.0
    return {
        "n_days": len(per_day), "n_days_economic": len(rets_no),
        "daily_mean": float(rets.mean()), "daily_mean_economic": float(rets_no.mean()),
        "cum_return": final - 1.0,
        "annual": float(final ** (1.0 / years) - 1.0) if years > 0 and final > 0 else 0.0,
        "mdd": _mdd(nav_no),
        "cum_return_overlap": float(nav_ov[-1]) - 1.0, "mdd_overlap": _mdd(nav_ov),
    }


def yearly_ic(rows: list) -> dict:
    """按自然年切分逐日 RankIC，报告均值/为正比例/天数。"""
    by_year: dict = {}
    for d, ic, _spread, _sz in rows:
        by_year.setdefault(str(d)[:4], []).append(ic)
    out = {}
    for year, vals in sorted(by_year.items()):
        arr = np.asarray(vals, dtype=np.float64)
        out[year] = {"n_days": int(arr.size), "ic_mean": float(arr.mean()),
                     "ic_pos_rate": float((arr > 0).mean())}
    return out


def compute_set_metrics(preds: dict, target_precision: float, horizon: int,
                        min_xs: int, topn_list=TOPN_LIST, thr_grid_factor: float = 0.9) -> dict:
    """对单个子集计算全部指标，返回可 JSON 序列化的 dict。"""
    exp = np.asarray(preds["exp_ret"], dtype=np.float64)
    true = np.asarray(preds["true_ret"], dtype=np.float64)
    dates = np.asarray(preds["dates"]).astype("datetime64[D]")
    valid = np.isfinite(exp) & np.isfinite(true)
    exp, true, dates = exp[valid], true[valid], dates[valid]
    rows = daily_series(exp, true, dates, min_xs)
    ics = np.array([r[1] for r in rows], dtype=np.float64)
    spreads = np.array([r[2] for r in rows], dtype=np.float64)
    n_days = int(ics.size)
    ic_mean = float(ics.mean()) if n_days else 0.0
    ic_std = float(ics.std(ddof=1)) if n_days > 1 else 0.0
    icir = ic_mean / ic_std if ic_std > 0 else 0.0
    t_stat = icir * np.sqrt(n_days) if n_days else 0.0
    d0, d1, n_uni_days = date_coverage(dates)
    # 阈值网格：以 exp_ret 分位数为锚（0.5..0.99），提供可读的阈值-精度曲线
    qs = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]
    grid = [float(np.quantile(exp, q)) for q in qs] if exp.size else []
    return {
        "n_samples": int(exp.size), "n_dates": n_uni_days,
        "date_start": d0, "date_end": d1,
        "xs_n_days": n_days,
        "xs_avg_size": int(np.mean([r[3] for r in rows])) if rows else 0,
        "rank_ic_mean": ic_mean,
        "rank_ic_std": ic_std,
        "rank_ic_median": float(np.median(ics)) if n_days else 0.0,
        "icir": icir, "icir_annualized": icir * np.sqrt(252.0), "ic_t_stat": t_stat,
        "ic_pos_rate": float((ics > 0).mean()) if n_days else 0.0,
        "spread_top10_bot10_mean": float(np.nanmean(spreads)) if n_days else 0.0,
        "spread_median": float(np.nanmedian(spreads)) if n_days else 0.0,
        "spread_pos_rate": float(np.nanmean(spreads > 0)) if n_days else 0.0,
        "topn": topn_stats(exp, true, dates, topn_list, min_xs),
        "threshold_grid": threshold_sweep(exp, true, grid),
        "absolute_top20": absolute_return(exp, true, dates, topn=20, horizon=horizon, min_xs=min_xs),
        "yearly_ic": yearly_ic(rows),
    }


def run_inference(checkpoint: str, start: str, end: str, parquet: str, seq_len: int,
                  horizon: int, batch_size: int, num_workers: int, device, max_codes: int,
                  featurenum, scaler_path, rolling_scope, y_ret_type: str) -> dict:
    """复用 scripts/eval_bins_mapping 的推理链路，现场生成指定区间的预测缓存再加载。"""
    from scripts import eval_bins_mapping as ebm

    tmp = os.path.join("logs", f"_threeway_tmp_{start}_{end}.npz")
    ns = Namespace(
        checkpoint=checkpoint, parquet=parquet, val_start=start, val_end=end,
        feature_cols=None, seq_len=seq_len, horizon=horizon, batch_size=batch_size,
        num_workers=num_workers, preds_cache=tmp, max_codes=max_codes,
        max_windows_per_code=None, scaler_path=scaler_path, rolling_scope=rolling_scope,
        featurenum=featurenum, allow_fit_scaler=False, bins11_pct=None, bins13_pct=None,
        seed=42, device=device, out=None, y_ret_type=y_ret_type,
    )
    ebm.evaluate(ns)
    return load_cached(tmp, start, end)


def _pct(v: float) -> str:
    return f"{v * 100:6.2f}%"


def format_report(val_m: dict, test_m: dict, calib: dict, meta: dict) -> str:
    """生成可读的 val/test 对比文本报告。"""
    lines = ["=" * 78, "严格三分评估报告（train/val/test）", "=" * 78]
    lines.append(f"checkpoint : {meta.get('checkpoint', 'n/a')}")
    lines.append(f"val_cache  : {meta['val_cache']}")
    lines.append(f"test_cache : {meta['test_cache']}")
    lines.append(f"val  区间  : {val_m['date_start']} ~ {val_m['date_end']} "
                 f"({val_m['n_dates']} 交易日, {val_m['n_samples']:,} 样本)")
    lines.append(f"test 区间  : {test_m['date_start']} ~ {test_m['date_end']} "
                 f"({test_m['n_dates']} 交易日, {test_m['n_samples']:,} 样本)")

    def cmp_row(name: str, v, t, fmt="{:.4f}"):
        d = None if (v is None or t is None) else (t - v)
        dv = "   n/a" if d is None else fmt.format(d)
        return f"  {name:<20} {fmt.format(v):>12} {fmt.format(t):>12} {dv:>12}"

    lines += ["-" * 78, "核心截面指标", "-" * 78,
              f"  {'指标':<20} {'VAL':>12} {'TEST':>12} {'差值(T-V)':>12}"]
    lines.append(cmp_row("样本数", float(val_m["n_samples"]), float(test_m["n_samples"]), "{:.0f}"))
    lines.append(cmp_row("截面天数", float(val_m["n_dates"]), float(test_m["n_dates"]), "{:.0f}"))
    lines.append(cmp_row("RankIC均值", val_m["rank_ic_mean"], test_m["rank_ic_mean"]))
    lines.append(cmp_row("IC中位数", val_m["rank_ic_median"], test_m["rank_ic_median"]))
    lines.append(cmp_row("ICIR", val_m["icir"], test_m["icir"], "{:.3f}"))
    lines.append(cmp_row("ICIR(年化)", val_m["icir_annualized"], test_m["icir_annualized"], "{:.3f}"))
    lines.append(cmp_row("IC t统计量", val_m["ic_t_stat"], test_m["ic_t_stat"], "{:.2f}"))
    lines.append(cmp_row("IC>0比例", val_m["ic_pos_rate"], test_m["ic_pos_rate"], "{:.4f}"))
    lines.append(cmp_row("top-decile spread均值", val_m["spread_top10_bot10_mean"],
                         test_m["spread_top10_bot10_mean"]))
    lines.append(cmp_row("spread为正比例", val_m["spread_pos_rate"], test_m["spread_pos_rate"], "{:.4f}"))

    lines += ["-" * 78, "Top-N 选股（逐日宏平均）", "-" * 78,
              f"  {'N':>4} {'precision':>22} {'平均收益':>22} {'跑赢中位数':>22}"]
    lines.append(f"  {'':>4} {('VAL / TEST'):>22} {('VAL / TEST'):>22} {('VAL / TEST'):>22}")
    for n in sorted(val_m["topn"], key=lambda x: int(x)):
        v, t = val_m["topn"][n], test_m["topn"][n]
        lines.append(
            f"  {n:>4} {_pct(v['prec']) + ' / ' + _pct(t['prec']):>22}"
            f" {_pct(v['ret']) + ' / ' + _pct(t['ret']):>22}"
            f" {_pct(v['beat']) + ' / ' + _pct(t['beat']):>22}")

    lines += ["-" * 78, "阈值校准（仅在 VAL 上定阈值，应用到 TEST）", "-" * 78]
    cv, ct = calib["val"], calib["test"]
    reached = "是" if cv["reached"] else "否（VAL 达不到目标，取可达最高 precision）"
    lines.append(f"  目标 precision : {cv['target']:.0%}")
    lines.append(f"  VAL 达标       : {reached}")
    lines.append(f"  VAL 选定阈值   : exp_ret >= {cv['thr']:.6f}")
    lines.append(f"  VAL  : n={cv['n']:>7}  precision={_pct(cv['precision'])}  平均收益={_pct(cv['mean_ret'])}")
    lines.append(f"  TEST : n={ct['n']:>7}  precision={_pct(ct['precision'])}  平均收益={_pct(ct['mean_ret'])}"
                 "   <-- 样本外真实结果")
    lines.append(f"  precision 衰减 : {(ct['precision'] - cv['precision']) * 100:+.2f} pp")

    lines += ["-" * 78, "绝对收益（Top20 等权，非重叠经济口径 / 参考重叠口径）", "-" * 78]
    for tag, m in (("VAL", val_m), ("TEST", test_m)):
        a = m["absolute_top20"]
        lines.append(f"  {tag:<5} 累计={_pct(a['cum_return'])} 年化={_pct(a['annual'])} "
                     f"最大回撤={_pct(a['mdd'])} 日均={_pct(a['daily_mean'])} "
                     f"(经济口径天数={a['n_days_economic']}, 重叠累计={_pct(a['cum_return_overlap'])})")

    lines += ["-" * 78, "分年度 IC 稳定性", "-" * 78]
    for tag, m in (("VAL", val_m), ("TEST", test_m)):
        parts = [f"{y}:IC={v['ic_mean']:+.4f}(正{v['ic_pos_rate']:.0%},n={v['n_days']})"
                 for y, v in m["yearly_ic"].items()]
        lines.append(f"  {tag:<5} " + ("; ".join(parts) if parts else "无"))
    lines.append("=" * 78)
    return "\n".join(lines)


def parse_args():
    p = argparse.ArgumentParser(description="严格 train/val/test 三分评估 + 阈值样本外校准")
    p.add_argument("--val_start", default=VAL_START)
    p.add_argument("--val_end", default=VAL_END)
    p.add_argument("--test_start", default=TEST_START)
    p.add_argument("--test_end", default=TEST_END)
    p.add_argument("--val_cache", default=DEFAULT_VAL_CACHE)
    p.add_argument("--test_cache", default=DEFAULT_TEST_CACHE)
    p.add_argument("--run_inference", action="store_true",
                   help="忽略缓存，按 --checkpoint 现场推理 val/test 区间（慢）")
    p.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    p.add_argument("--parquet", default="Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet")
    p.add_argument("--seq_len", type=int, default=60)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--batch_size", type=int, default=1024)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--max_codes", type=int, default=0, help="0=全市场（推理模式）")
    p.add_argument("--featurenum", type=int, default=None)
    p.add_argument("--scaler_path", default=None)
    p.add_argument("--rolling_scope", choices=["e0", "e1", "e2", "e3", "e4", "e5"], default=None)
    p.add_argument("--y_ret_type", choices=["open_open", "open_close"], default="open_open")
    p.add_argument("--device", default=None)
    p.add_argument("--target_precision", type=float, default=0.75)
    p.add_argument("--min_count", type=int, default=100, help="阈值校准最少样本数")
    p.add_argument("--min_xs", type=int, default=MIN_CROSS_SECTION, help="截面最少样本数")
    p.add_argument("--topn", nargs="+", type=int, default=list(TOPN_LIST))
    p.add_argument("--out", default="logs/eval_three_way_report.json")
    p.add_argument("--report", default="logs/eval_three_way_report.txt")
    return p.parse_args()


def main():
    args = parse_args()
    if args.run_inference:
        common = {"parquet": args.parquet, "seq_len": args.seq_len, "horizon": args.horizon,
                  "batch_size": args.batch_size, "num_workers": args.num_workers, "device": args.device,
                  "max_codes": args.max_codes, "featurenum": args.featurenum,
                  "scaler_path": args.scaler_path, "rolling_scope": args.rolling_scope,
                  "y_ret_type": args.y_ret_type}
        print(f"[threeway] 现场推理 val {args.val_start}~{args.val_end} ...")
        val_preds = run_inference(args.checkpoint, args.val_start, args.val_end, **common)
        print(f"[threeway] 现场推理 test {args.test_start}~{args.test_end} ...")
        test_preds = run_inference(args.checkpoint, args.test_start, args.test_end, **common)
    else:
        val_preds = load_cached(args.val_cache, args.val_start, args.val_end)
        test_preds = load_cached(args.test_cache, args.test_start, args.test_end)
    if val_preds["exp_ret"].size == 0 or test_preds["exp_ret"].size == 0:
        raise ValueError("val 或 test 在指定区间无样本，请检查日期边界/缓存")

    print(f"[threeway] VAL  {val_preds['dates'].size} 样本; TEST {test_preds['dates'].size} 样本")
    val_m = compute_set_metrics(val_preds, args.target_precision, args.horizon, args.min_xs, args.topn)
    test_m = compute_set_metrics(test_preds, args.target_precision, args.horizon, args.min_xs, args.topn)
    calib_val = calibrate_threshold(val_preds["exp_ret"], val_preds["true_ret"],
                                    args.target_precision, args.min_count)
    calib_test = apply_threshold(test_preds["exp_ret"], test_preds["true_ret"], calib_val["thr"])
    calib = {"target_precision": args.target_precision, "min_count": args.min_count,
             "val": calib_val, "test": calib_test}
    meta = {"checkpoint": args.checkpoint if args.run_inference else "(cache)",
            "val_cache": "(inference)" if args.run_inference else args.val_cache,
            "test_cache": "(inference)" if args.run_inference else args.test_cache,
            "val_range": [args.val_start, args.val_end], "test_range": [args.test_start, args.test_end]}
    text = format_report(val_m, test_m, calib, meta)
    print(text)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    payload = {"meta": meta, "val": val_m, "test": test_m, "threshold_calibration": calib,
               "gap": {"rank_ic": test_m["rank_ic_mean"] - val_m["rank_ic_mean"],
                       "icir": test_m["icir"] - val_m["icir"],
                       "spread": test_m["spread_top10_bot10_mean"] - val_m["spread_top10_bot10_mean"]}}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[threeway] 文本报告: {args.report}")
    print(f"[threeway] JSON报告: {args.out}")


if __name__ == "__main__":
    main()
