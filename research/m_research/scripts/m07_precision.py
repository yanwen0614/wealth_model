"""m07: 只看涨精确率. 门槛越高/只取最高信心天数, 精确率能否超过base?"""
import pandas as pd

s = pd.read_csv(r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_signals.csv",
                parse_dates=["day"]).sort_values("day").reset_index(drop=True)
base = s["ew_up5"].mean()
print(f"天数={len(s)} 无脑说涨精确率base={base:.4f}")
for thr in (0.5, 0.55, 0.6, 0.65, 0.7):
    g = s["p"] > thr
    print(f"thr>{thr}: 说涨{int(g.sum())}天 覆盖{g.mean():.2%} "
          f"精确率={s.loc[g, 'ew_up5'].mean():.4f} 后续收益={s.loc[g, 'ew_fwd5'].mean():+.5f}")
for q in (0.9, 0.8):
    cut = s["p"].quantile(q)
    g = s["p"] >= cut
    print(f"top{int((1 - q) * 100)}pct: {int(g.sum())}天 "
          f"精确率={s.loc[g, 'ew_up5'].mean():.4f} 后续收益={s.loc[g, 'ew_fwd5'].mean():+.5f}")
for y in range(2019, 2026):
    d = s[s["day"].dt.year == y]
    g = d["p"] >= d["p"].quantile(0.8)
    print(f"{y}: top20pct精确率={d.loc[g, 'ew_up5'].mean():.3f} "
          f"年base={d['ew_up5'].mean():.3f} n={int(g.sum())}")
