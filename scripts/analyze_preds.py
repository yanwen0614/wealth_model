"""深度分析 52 类 CNNTransformer 预测缓存，寻找 precision ≥ 75% 的子集."""
from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

# ── 加载数据 ──────────────────────────────────────────────────────────────
print("=" * 72)
print("加载 logs/eval_preds_52cls.npz ...")
raw = np.load("logs/eval_preds_52cls.npz", allow_pickle=True)
exp_ret: np.ndarray = raw["exp_ret"]       # (613543,)
true_ret: np.ndarray = raw["true_ret"]     # (613543,)
dates: np.ndarray = raw["dates"]           # datetime64[us]
codes: np.ndarray = raw["codes"]           # <U9
N = len(exp_ret)
print(f"总样本数: {N:,}")
print(f"日期范围: {dates.min()} ~ {dates.max()}")
print(f"股票数:   {len(np.unique(codes)):,}")
print(f"天数:     {len(np.unique(dates)):,}")

# ── 基础统计 ──────────────────────────────────────────────────────────────
true_pos = true_ret > 0
precision_global = true_pos.mean()
print(f"\n全局 precision (true_ret > 0): {precision_global:.4%}")
print(f"全局 exp_ret 均值: {exp_ret.mean():.6f}")
print(f"全局 true_ret 均值: {true_ret.mean():.6f}")
print(f"exp_ret vs true_ret corr: {np.corrcoef(exp_ret, true_ret)[0,1]:.4f}")

# ── 1. 按置信度分档 ──────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("1. 按 exp_ret 置信度分档")
print("=" * 72)

bins_edges = np.arange(0.0, 0.055, 0.005)  # 0%, 0.5%, 1%, ..., 5%
labels_bins = [f"{e*100:.1f}-{(e+0.5)*100:.1f}%" for e in bins_edges[:-1]]
labels_bins.append(">5.0%")
abs_exp = np.abs(exp_ret)
bin_indices = np.digitize(abs_exp, bins_edges) - 1  # 0..10, -1 for <0
# Clamp -1 to 0 (exp_ret near zero goes to lowest bin)
bin_indices = np.clip(bin_indices, 0, len(labels_bins) - 1)

print(f"{'分档':>12s}  {'样本数':>8s}  {'Precision':>10s}  {'AvgTrueRet':>10s}  {'AvgExpRet':>10s}")
print("-" * 56)
conf_results = []
for i, label in enumerate(labels_bins):
    mask = bin_indices == i
    cnt = mask.sum()
    if cnt == 0:
        continue
    prec = true_pos[mask].mean()
    avg_true = true_ret[mask].mean()
    avg_exp = exp_ret[mask].mean()
    conf_results.append((label, cnt, prec, avg_true, avg_exp))
    flag = " <<< 75%" if prec >= 0.75 else ""
    print(f"{label:>12s}  {cnt:>8,d}  {prec:>10.4%}  {avg_true:>10.6f}  {avg_exp:>10.6f}{flag}")

# 汇总高置信度（>3%）
mask_high = abs_exp > 0.03
if mask_high.sum() > 0:
    prec_high = true_pos[mask_high].mean()
    print(f"\nexp_ret > 3% 汇总: 样本={mask_high.sum():,}, precision={prec_high:.4%}")

mask_high2 = abs_exp > 0.05
if mask_high2.sum() > 0:
    prec_high2 = true_pos[mask_high2].mean()
    print(f"exp_ret > 5% 汇总: 样本={mask_high2.sum():,}, precision={prec_high2:.4%}")

# ── 2. 按股票代码（个股稳定性）───────────────────────────────────────────
print("\n" + "=" * 72)
print("2. 按股票代码分析（个股稳定性）")
print("=" * 72)

code_prec: dict[str, float] = {}
code_cnt: dict[str, int] = {}
code_avg_ret: dict[str, float] = {}
for code in np.unique(codes):
    m = codes == code
    c = m.sum()
    if c < 10:
        continue
    code_prec[code] = true_pos[m].mean()
    code_cnt[code] = c
    code_avg_ret[code] = true_ret[m].mean()

# 按 precision 排序
sorted_codes = sorted(code_prec.keys(), key=lambda c: code_prec[c], reverse=True)
print(f"共有 {len(code_prec):,} 只股票（样本≥10）")
print(f"\nPrecision ≥ 70% 的股票:")
hit_70 = [(c, code_prec[c], code_cnt[c], code_avg_ret[c]) for c in sorted_codes if code_prec[c] >= 0.70]
print(f"  数量: {len(hit_70)}")
if hit_70:
    print(f"  {'股票代码':>12s}  {'样本数':>8s}  {'Precision':>10s}  {'AvgTrueRet':>10s}")
    print("  " + "-" * 44)
    for c, prec, cnt, aret in hit_70[:30]:
        print(f"  {c:>12s}  {cnt:>8,d}  {prec:>10.4%}  {aret:>10.6f}")

# 精度 vs 样本数散点统计
print(f"\nPrecision 分布:")
for th in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
    n = sum(1 for c in sorted_codes if code_prec[c] >= th)
    print(f"  ≥{th:.0%}: {n:>5d} 只股票")

# 看最好的几只股票
print(f"\nTop 10 个股（按 precision 排序）：")
print(f"  {'股票代码':>12s}  {'样本数':>8s}  {'Precision':>10s}  {'AvgTrueRet':>10s}")
print("  " + "-" * 44)
for c in sorted_codes[:10]:
    print(f"  {c:>12s}  {code_cnt[c]:>8,d}  {code_prec[c]:>10.4%}  {code_avg_ret[c]:>10.6f}")

# ── 3. 按日期（择时）─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("3. 按日期分析（择时能力）")
print("=" * 72)

unique_dates = np.unique(dates)
date_prec: dict[np.datetime64, float] = {}
date_cnt: dict[np.datetime64, int] = {}
date_exp_mean: dict[np.datetime64, float] = {}
date_exp_std: dict[np.datetime64, float] = {}
date_true_mean: dict[np.datetime64, float] = {}
for d in unique_dates:
    m = dates == d
    c = m.sum()
    if c < 10:
        continue
    date_prec[d] = true_pos[m].mean()
    date_cnt[d] = c
    date_exp_mean[d] = exp_ret[m].mean()
    date_exp_std[d] = exp_ret[m].std()
    date_true_mean[d] = true_ret[m].mean()

sorted_dates = sorted(date_prec.keys(), key=lambda d: date_prec[d], reverse=True)
print(f"共有 {len(date_prec)} 天（样本≥10）")

# 高 precision 日期统计
print(f"\nPrecision ≥ 70% 的天数: {sum(1 for d in sorted_dates if date_prec[d] >= 0.70):,}")
print(f"Precision ≥ 65% 的天数: {sum(1 for d in sorted_dates if date_prec[d] >= 0.65):,}")
print(f"Precision ≥ 60% 的天数: {sum(1 for d in sorted_dates if date_prec[d] >= 0.60):,}")

# Top/Bottom 日期特征对比
n_top = min(30, len(sorted_dates))
n_bot = min(30, len(sorted_dates))
top_dates = sorted_dates[:n_top]
bot_dates = sorted_dates[-n_top:]

top_precs = [date_prec[d] for d in top_dates]
bot_precs = [date_prec[d] for d in bot_dates]
top_exp_means = [date_exp_mean[d] for d in top_dates]
bot_exp_means = [date_exp_mean[d] for d in bot_dates]
top_exp_stds = [date_exp_std[d] for d in top_dates]
bot_exp_stds = [date_exp_std[d] for d in bot_dates]
top_true_means = [date_true_mean[d] for d in top_dates]
bot_true_means = [date_true_mean[d] for d in bot_dates]

print(f"\nTop {n_top} 高 precision 日 vs Bottom {n_bot} 低 precision 日 特征对比:")
print(f"  {'指标':>20s}  {'高精确率日':>12s}  {'低精确率日':>12s}")
print("  " + "-" * 48)
print(f"  {'平均 Precision':>20s}  {np.mean(top_precs):>12.4%}  {np.mean(bot_precs):>12.4%}")
print(f"  {'平均 exp_ret 均值':>20s}  {np.mean(top_exp_means):>12.6f}  {np.mean(bot_exp_means):>12.6f}")
print(f"  {'平均 exp_ret 标准差':>20s}  {np.mean(top_exp_stds):>12.6f}  {np.mean(bot_exp_stds):>12.6f}")
print(f"  {'平均 true_ret 均值':>20s}  {np.mean(top_true_means):>12.6f}  {np.mean(bot_true_means):>12.6f}")

# 尝试：前一天 exp_ret 均值能否预测今天 precision？
dates_sorted_asc = sorted(date_prec.keys())
if len(dates_sorted_asc) >= 10:
    prec_today = []
    exp_mean_yesterday = []
    corr_exp = []
    for i in range(1, len(dates_sorted_asc)):
        d_today = dates_sorted_asc[i]
        d_yest = dates_sorted_asc[i - 1]
        prec_today.append(date_prec[d_today])
        exp_mean_yesterday.append(date_exp_mean[d_yest])
    prec_today = np.array(prec_today)
    exp_mean_yesterday = np.array(exp_mean_yesterday)
    if len(prec_today) > 5:
        corr_val = np.corrcoef(prec_today, exp_mean_yesterday)[0, 1]
        print(f"\n前一天 exp_ret 均值 vs 今天 precision 的相关性: {corr_val:.4f}")
        # 按昨天 exp_ret 均值分档看今天 precision
        bins_y = np.percentile(exp_mean_yesterday, [0, 20, 40, 60, 80, 100])
        for j in range(len(bins_y) - 1):
            m_y = (exp_mean_yesterday >= bins_y[j]) & (exp_mean_yesterday < bins_y[j + 1])
            c_y = m_y.sum()
            if c_y < 3:
                continue
            prec_y = prec_today[m_y].mean()
            print(f"  前一天 exp_ret 均值 [{bins_y[j]:.6f}, {bins_y[j+1]:.6f}): "
                  f"天数={c_y}, 今天平均 precision={prec_y:.4%}")

# ── 4. 多条件组合筛选 ────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("4. 多条件组合筛选（寻找 75%+ precision 子集）")
print("=" * 72)

# 4a. 按 exp_ret 阈值 + 个股历史 precision
print("\n4a. exp_ret 阈值 + 个股历史 precision")

# 先用全部数据计算个股历史 precision（in-sample bias 警告，但作为信号参考）
# 这里用全局数据计算个股 precision——实际使用需用 OOS 数据
code_overall_prec: dict[str, float] = {}
code_overall_cnt: dict[str, int] = {}
for code in np.unique(codes):
    m = codes == code
    code_overall_prec[code] = true_pos[m].mean()
    code_overall_cnt[code] = m.sum()

for exp_thresh in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]:
    for code_prec_thresh in [0.50, 0.55, 0.60]:
        mask = (exp_ret >= exp_thresh) & np.vectorize(
            lambda c: code_overall_prec.get(c, 0) >= code_prec_thresh
        )(codes)
        cnt = mask.sum()
        if cnt < 20:
            continue
        prec = true_pos[mask].mean()
        avg_ret = true_ret[mask].mean()
        avg_exp = exp_ret[mask].mean()
        flag = " <<< 75%" if prec >= 0.75 else (" <<< 70%" if prec >= 0.70 else "")
        if prec >= 0.65 or cnt >= 100:
            print(f"  exp>={exp_thresh:.1%} + 个股prec>={code_prec_thresh:.0%}: "
                  f"样本={cnt:>8,d}, precision={prec:>8.4%}, "
                  f"avg_true_ret={avg_ret:>8.6f}, avg_exp_ret={avg_exp:>8.6f}{flag}")

# 4b. 双阈值：最低 exp_ret + 最高 exp_ret（过滤负向极端）
print("\n4b. 双阈值（过滤负 exp_ret + 最低 exp_ret 门槛）")
for exp_min in [0.005, 0.01, 0.015, 0.02]:
    for exp_max_factor in [None, 0.05, 0.08, 0.10]:
        mask = exp_ret >= exp_min
        if exp_max_factor is not None:
            mask = mask & (exp_ret <= exp_max_factor)
        cnt = mask.sum()
        if cnt < 20:
            continue
        prec = true_pos[mask].mean()
        avg_ret = true_ret[mask].mean()
        flag = " <<< 75%" if prec >= 0.75 else ""
        desc = f"exp∈[{exp_min:.1%},{exp_max_factor:.0%}]" if exp_max_factor else f"exp>={exp_min:.1%}"
        if prec >= 0.60 or cnt >= 2000:
            print(f"  {desc:>30s}: 样本={cnt:>8,d}, precision={prec:>8.4%}, "
                  f"avg_true_ret={avg_ret:>8.6f}{flag}")

# 4c. 按 exp_ret 分位数（极端预测）
print("\n4c. 按 exp_ret 分位数筛选（只取最高置信度预测）")
for top_pct in [0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001]:
    thresh = np.percentile(exp_ret, 100 * (1 - top_pct))
    mask = exp_ret >= thresh
    cnt = mask.sum()
    if cnt < 10:
        continue
    prec = true_pos[mask].mean()
    avg_ret = true_ret[mask].mean()
    flag = " <<< 75%" if prec >= 0.75 else (" <<< 70%" if prec >= 0.70 else "")
    print(f"  top {top_pct:.1%} (exp≥{thresh:.4f})  "
          f"样本={cnt:>8,d}, precision={prec:>8.4%}, "
          f"avg_true_ret={avg_ret:>8.6f}{flag}")

# 4d. 组合：高位 exp_ret + 高个股 precision
print("\n4d. 高位 exp_ret + 个股 precision 分层组合")
for exp_top_pct in [0.05, 0.02, 0.01]:
    thresh_exp = np.percentile(exp_ret, 100 * (1 - exp_top_pct))
    for code_prec_thresh in [0.55, 0.60, 0.65, 0.70]:
        mask = (exp_ret >= thresh_exp) & np.vectorize(
            lambda c: code_overall_prec.get(c, 0) >= code_prec_thresh
        )(codes)
        cnt = mask.sum()
        if cnt < 10:
            continue
        prec = true_pos[mask].mean()
        avg_ret = true_ret[mask].mean()
        flag = " <<< 75%" if prec >= 0.75 else (" <<< 70%" if prec >= 0.70 else "")
        if prec >= 0.65 or cnt >= 50:
            print(f"  exp_top{exp_top_pct:.0%}(≥{thresh_exp:.4f}) + 个股prec≥{code_prec_thresh:.0%}: "
                  f"样本={cnt:>6,d}, precision={prec:>8.4%}, "
                  f"avg_true_ret={avg_ret:>8.6f}{flag}")

# 4e. 精确查找：连续提高门槛直到样本不足
print("\n4e. 精度门槛扫描（逐步提高 exp_ret 门槛）")
for thresh_pct in np.arange(1.0, 10.5, 0.5):
    thresh = thresh_pct / 100.0
    mask = exp_ret >= thresh
    cnt = mask.sum()
    if cnt < 5:
        continue
    prec = true_pos[mask].mean()
    avg_ret = true_ret[mask].mean()
    flag = " <<< 75%" if prec >= 0.75 else (" <<< 70%" if prec >= 0.70 else "")
    if prec >= 0.60 or (cnt >= 50 and prec >= 0.55) or cnt >= 500:
        print(f"  exp_ret≥{thresh_pct:4.1f}%: 样本={cnt:>8,d}, precision={prec:>8.4%}, "
              f"avg_true_ret={avg_ret:>8.6f}{flag}")

# 4f. 2D 热力扫描
print("\n4f. 2D 热力扫描（exp_ret 阈值 × 个股 precision 阈值）")
print(f"  {'exp阈值':>8s}  {'个股prec':>10s}  {'样本数':>8s}  {'Precision':>10s}  {'AvgTrueRet':>10s}")
print("  " + "-" * 52)
best_combos = []
for exp_th in [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05, 0.06]:
    for cp_th in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75]:
        if cp_th >= 0.75:
            # 个股 precision≥75% 本身就很苛刻
            mask_codes = np.array([code_overall_prec.get(c, 0) >= cp_th for c in codes])
        else:
            mask_codes = np.vectorize(
                lambda c: code_overall_prec.get(c, 0) >= cp_th
            )(codes)
        mask = (exp_ret >= exp_th) & mask_codes
        cnt = mask.sum()
        if cnt < 10:
            continue
        prec = true_pos[mask].mean()
        avg_ret = true_ret[mask].mean()
        best_combos.append((prec, cnt, exp_th, cp_th, avg_ret))
        if prec >= 0.65 or (cnt >= 50 and prec >= 0.60):
            flag = " <<< 75%" if prec >= 0.75 else (" <<< 70%" if prec >= 0.70 else "")
            print(f"  {exp_th:>7.1%}  {cp_th:>9.0%}  {cnt:>8,d}  {prec:>10.4%}  {avg_ret:>10.6f}{flag}")

if best_combos:
    best_combos.sort(key=lambda x: -x[0])
    print(f"\n  Top 3 组合（按 precision 排序）：")
    for prec, cnt, exp_th, cp_th, avg_ret in best_combos[:3]:
        print(f"    exp≥{exp_th:.1%}, 个股prec≥{cp_th:.0%}: "
              f"样本={cnt:,}, precision={prec:.4%}, avg_true_ret={avg_ret:.6f}")

# ── 5. 收益率大小分析 ─────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("5. 收益率大小分析（precision 高是否伴随有意义收益）")
print("=" * 72)

# 对每个 precision 门槛，看平均收益率
for prec_th in [0.65, 0.70, 0.75, 0.80]:
    # 用 exp_ret 分位扫描找出满足条件的子集
    found = False
    for exp_th in np.arange(0.005, 0.101, 0.005):
        for cp_th in [0.50, 0.55, 0.60, 0.65, 0.70]:
            mask = (exp_ret >= exp_th) & np.vectorize(
                lambda c: code_overall_prec.get(c, 0) >= cp_th
            )(codes)
            cnt = mask.sum()
            if cnt < 10:
                continue
            prec = true_pos[mask].mean()
            if prec >= prec_th:
                if not found:
                    print(f"\nPrecision ≥ {prec_th:.0%} 的子集：")
                    found = True
                avg_ret = true_ret[mask].mean()
                avg_exp = exp_ret[mask].mean()
                median_ret = np.median(true_ret[mask])
                p25 = np.percentile(true_ret[mask], 25)
                p75 = np.percentile(true_ret[mask], 75)
                pos_pnl = true_ret[mask][true_ret[mask] > 0].mean() if true_ret[mask].sum() > 0 else 0
                neg_pnl = true_ret[mask][true_ret[mask] <= 0].mean() if (true_ret[mask] <= 0).sum() > 0 else 0
                print(f"  exp≥{exp_th:.1%}, 个股prec≥{cp_th:.0%}: "
                      f"样本={cnt:>6,d}, precision={prec:>7.4%}, "
                      f"avg_ret={avg_ret:>7.4f}, median={median_ret:>7.4f}, "
                      f"[p25={p25:>7.4f}, p75={p75:>7.4f}], "
                      f"赢均={pos_pnl:>7.4f}, 输均={neg_pnl:>7.4f}")
                if cnt >= 50:
                    break  # 每个 prec_th 只找一个代表性组合
    if not found:
        print(f"\n  Precision ≥ {prec_th:.0%}: 未找到满足条件的子集")

# ── 6. 排序能力分析 ──────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("6. 排序能力补充分析")
print("=" * 72)

# exp_ret 分组看真实收益率单调性
print("\n按 exp_ret 十分位看真实收益率：")
deciles = np.percentile(exp_ret, np.arange(0, 110, 10))
for i in range(10):
    lo, hi = deciles[i], deciles[i + 1]
    mask = (exp_ret >= lo) & (exp_ret < hi) if i < 9 else (exp_ret >= lo)
    cnt = mask.sum()
    prec = true_pos[mask].mean()
    avg_true = true_ret[mask].mean()
    avg_exp = exp_ret[mask].mean()
    print(f"  D{i+1:2d} [exp∈[{lo:.4f},{hi:.4f})]: "
          f"样本={cnt:>7,d}, precision={prec:>7.4%}, "
          f"avg_true={avg_true:>8.6f}, avg_exp={avg_exp:>8.6f}")

# IC 分析
from scipy.stats import spearmanr
# 按天计算 Rank IC
daily_ic = []
for d in unique_dates:
    m = dates == d
    c = m.sum()
    if c < 30:
        continue
    ic, _ = spearmanr(exp_ret[m], true_ret[m])
    daily_ic.append(ic)
daily_ic = np.array(daily_ic)
print(f"\n日频 Rank IC: 均值={daily_ic.mean():.4f}, 标准差={daily_ic.std():.4f}, "
      f"ICIR={daily_ic.mean()/daily_ic.std():.4f}" if daily_ic.std() > 0 else "")
print(f"  IC>0 比例: {(daily_ic>0).mean():.4%}")
print(f"  日频 IC 分布: P25={np.percentile(daily_ic,25):.4f}, "
      f"P50={np.percentile(daily_ic,50):.4f}, P75={np.percentile(daily_ic,75):.4f}")

# ── 7. 总结 ──────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("7. 关键发现总结")
print("=" * 72)

# 找最佳 precision
best_prec = 0
best_desc = ""
all_combo_results = []

# Scan all combinations
for exp_th in np.arange(0.005, 0.101, 0.005):
    for cp_th in [x / 100 for x in range(50, 80, 5)]:
        mask = (exp_ret >= exp_th) & np.vectorize(
            lambda c: code_overall_prec.get(c, 0) >= cp_th
        )(codes)
        cnt = mask.sum()
        if cnt < 10:
            continue
        prec = true_pos[mask].mean()
        avg_ret = true_ret[mask].mean()
        all_combo_results.append((prec, cnt, avg_ret, exp_th, cp_th))

all_combo_results.sort(key=lambda x: -x[0])

print(f"\n所有组合中最佳 achievable precision:")
seen = set()
for prec, cnt, avg_ret, exp_th, cp_th in all_combo_results:
    if cnt >= 50 and prec >= 0.75:
        key = (round(exp_th, 4), round(cp_th, 2))
        if key not in seen:
            seen.add(key)
            print(f"  ★ precision={prec:.4%}, 样本={cnt:,}, avg_ret={avg_ret:.6f}, "
                  f"条件: exp≥{exp_th:.1%}, 个股prec≥{cp_th:.0%}")
    elif cnt >= 50 and prec >= 0.70:
        key = (round(exp_th, 4), round(cp_th, 2))
        if key not in seen:
            seen.add(key)
            print(f"  ☆ precision={prec:.4%}, 样本={cnt:,}, avg_ret={avg_ret:.6f}, "
                  f"条件: exp≥{exp_th:.1%}, 个股prec≥{cp_th:.0%}")

print(f"\n{'='*72}")
print(f"全局 baseline precision: {precision_global:.4%}")
if all_combo_results:
    best = all_combo_results[0]
    print(f"任何条件下最佳 precision（样本≥10）: {best[0]:.4%} "
          f"(样本={best[1]}, avg_ret={best[2]:.6f}, "
          f"exp≥{best[3]:.1%}, 个股prec≥{best[4]:.0%})")
    # 样本≥50 的最佳
    best50 = [r for r in all_combo_results if r[1] >= 50]
    if best50:
        print(f"样本≥50 的最佳 precision: {best50[0][0]:.4%} "
              f"(样本={best50[0][1]}, avg_ret={best50[0][2]:.6f}, "
              f"exp≥{best50[0][3]:.1%}, 个股prec≥{best50[0][4]:.0%})")
print("=" * 72)
