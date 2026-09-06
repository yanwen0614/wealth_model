"""TopN 收益折线图（按日截面统计各 TopN 档的 5 日均值真实收益）.

输入 eval 缓存的逐样本预测 npz（exp_ret/true_ret/dates，dates 为 datetime64 标签日），
按交易日截面统计 TopN（绝对只数）档的 5 日真实收益均值并绘制 TopN-收益折线图，
支持多个 npz 多线对比（如 val 上 base 与 dual；test 数据就绪后同脚本重跑出 test 线）。
截面口径与 eval_bins_mapping.py 一致：np.unique(dates) 循环，截面样本数 < min_size 跳过，
截面样本数 < N 跳过该档该日。

用法：
  uv run --project . python scripts/plot_topn_curve.py \
    --preds logs/preds_dual_ep7.npz logs/preds_base_ep4.npz \
    --labels dual-ep7 base-ep4 --out logs/topn_curve_val.png
"""
from __future__ import annotations

import argparse
import os
import sys

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.schema import PREDICTION_CACHE_KEYS, validate_prediction_cache_arrays

matplotlib.use("Agg")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """无 scipy 依赖的 Spearman（rank 后 Pearson），与 eval_bins_mapping.py 实现一致."""
    xr = np.argsort(np.argsort(x)).astype(np.float64)
    yr = np.argsort(np.argsort(y)).astype(np.float64)
    xr -= xr.mean()
    yr -= yr.mean()
    denom = np.sqrt((xr ** 2).sum() * (yr ** 2).sum())
    return float((xr * yr).sum() / denom) if denom > 0 else 0.0


def topn_stats(exp_ret: np.ndarray, true_ret: np.ndarray, dates: np.ndarray,
               topn_list: list[int], min_size: int) -> dict:
    daily_means = {n: [] for n in topn_list}
    daily_pos = {n: [] for n in topn_list}
    daily_ics: list[float] = []
    sizes: list[int] = []
    for d in np.unique(dates):
        m = dates == d
        nsz = int(m.sum())
        if nsz < min_size:
            continue
        e, r = exp_ret[m], true_ret[m]
        order = np.argsort(-e)
        sizes.append(nsz)
        daily_ics.append(spearman(e, r))
        for n in topn_list:
            if nsz < n:
                continue
            top = r[order[:n]]
            daily_means[n].append(float(top.mean()))
            daily_pos[n].append(float((top > 0).mean()))
    means = np.array([np.mean(daily_means[n]) if daily_means[n] else np.nan for n in topn_list])
    pos = np.array([np.mean(daily_pos[n]) if daily_pos[n] else np.nan for n in topn_list])
    return {"means": means, "pos": pos, "ndays": len(daily_ics),
            "avg_size": int(np.mean(sizes)) if sizes else 0,
            "ic_mean": float(np.mean(daily_ics)) if daily_ics else 0.0}


def parse_args():
    p = argparse.ArgumentParser(description="TopN 收益折线图（日截面）")
    p.add_argument("--preds", nargs="+", required=True, help="npz 路径（exp_ret/true_ret/dates/codes），每个一条线")
    p.add_argument("--labels", nargs="+", default=None, help="图例名，与 --preds 对齐，缺失用文件名 stem")
    p.add_argument("--topn_list", nargs="+", type=int, default=[5, 10, 15, 20, 25, 50, 100, 200, 500])
    p.add_argument("--min_size", type=int, default=100, help="截面样本数下限，跳过稀疏截面")
    p.add_argument("--out", default="logs/topn_curve.png")
    p.add_argument("--title", default="TopN vs 5日均值收益 (日截面, 62交易日)")
    return p.parse_args()


def main():
    args = parse_args()
    topn_list = sorted(args.topn_list)
    labels = args.labels if args.labels else [os.path.splitext(os.path.basename(p))[0] for p in args.preds]
    if len(labels) != len(args.preds):
        raise ValueError(f"--labels 数量({len(labels)})与 --preds 数量({len(args.preds)})不一致")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    results = []
    for path, label in zip(args.preds, labels):
        z = np.load(path)
        arrays = {key: z[key] for key in PREDICTION_CACHE_KEYS if key in z.files}
        validate_prediction_cache_arrays(arrays, path)
        st = topn_stats(arrays["exp_ret"].astype(np.float64), arrays["true_ret"].astype(np.float64),
                        arrays["dates"], topn_list, args.min_size)
        results.append((label, st))
        print(f"\n=== {label} ({os.path.basename(path)}) ===")
        print(f"截面数: {st['ndays']} 天 (日均样本 ~{st['avg_size']}) 截面RankIC mean={st['ic_mean']:.4f}")
        print(f"{'N':>6}  {'5日均值收益%':>14}  {'为正率%':>9}")
        for i, n in enumerate(topn_list):
            mv, pv = st["means"][i], st["pos"][i]
            if np.isnan(mv):
                print(f"{n:>6}  {'--':>14}  {'--':>9}")
            else:
                print(f"{n:>6}  {mv * 100:>14.4f}  {pv * 100:>9.2f}")
    plt.figure(figsize=(10, 6))
    for label, st in results:
        plt.plot(topn_list, st["means"] * 100, marker="o", label=label)
    plt.xscale("log")
    plt.xticks(topn_list, [str(n) for n in topn_list])
    plt.minorticks_off()
    plt.xlabel("TopN")
    plt.ylabel("5日均值收益 (%)")
    plt.title(args.title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.savefig(args.out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n[plot] 已保存: {args.out}")


if __name__ == "__main__":
    main()
