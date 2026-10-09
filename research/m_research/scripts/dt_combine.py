"""dt_combine: 双塔固定规则组合验收.
α塔=dt_alpha_oos(每日score); m塔=m06_signals(每日p). 无学习参数.
组合: (a)alpha_only topN等权; (b)dual_gate: 前一日m塔p<=0.5则空仓.
指标: 年化/Sharpe/MDD + block-bootstrap(块20,B=2000) on 日收益差.
用法: uv run --project . python dt_combine.py --N 200
"""
import argparse

import numpy as np
import pandas as pd

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\dt_data\dt_alpha_oos.npz"
SIG = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_signals.csv"
ap = argparse.ArgumentParser(); ap.add_argument("--N", type=int, default=200)
A = ap.parse_args(); N = A.N
z = np.load(D, allow_pickle=False)
date = pd.to_datetime(z["date"]).normalize()
sc = z["score"]; yo = z["y_open"].astype(np.float64)
sig = pd.read_csv(SIG, parse_dates=["day"])
sig["day"] = sig["day"].dt.normalize()
p_by_day = dict(zip(sig["day"], sig["p"]))
ud = np.sort(np.unique(date))
order = np.argsort(date, kind="stable")
d_sorted = date[order]
uniq, start = np.unique(d_sorted, return_index=True)
groups = np.split(order, start[1:])
ret_alpha, ret_gate, mday = [], [], []
for i, g in enumerate(groups):
    day = uniq[i]
    s, r = sc[g], yo[g]
    ok = np.isfinite(r) & np.isfinite(s)
    if ok.sum() < N:
        continue
    s, r = s[ok], r[ok]
    sel = np.argpartition(-s, N - 1)[:N]
    ra = float(r[sel].mean())
    prev = ud[i - 1] if i > 0 else None
    p = p_by_day.get(prev, np.nan) if prev is not None else np.nan
    long = (not np.isfinite(p)) or (p > 0.5)
    ret_alpha.append(ra)
    ret_gate.append(ra if long else 0.0)
    mday.append(day)
ra = np.array(ret_alpha); rg = np.array(ret_gate)
mday = np.array(mday)
# 非重叠: 每5个交易日取一期(禁用重叠复利)
step = 5
sel = np.arange(0, len(ra), step)
ra_n, rg_n, day_n = ra[sel], rg[sel], mday[sel]
print(f"N={N} 交易日={len(ra)} 非重叠期数={len(ra_n)}")
PER_YR = 252 / step
def stats(r, label):
    nav = np.cumprod(1 + r)
    n = len(r); ann = nav[-1] ** (PER_YR / n) - 1
    sd = r.std(ddof=1)
    sh = r.mean() / sd * np.sqrt(PER_YR) if sd > 0 else np.nan
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    print(f"{label:12s} 年化={ann:+.4f} Sharpe={sh:+.3f} MDD={dd:.4f} "
          f"期胜率={np.mean(r > 0):.3f} NAV={nav[-1]:.3f}")
    return ann, sh, dd
stats(ra_n, "alpha_only"); stats(rg_n, "dual_gate")
for y in range(2019, 2026):
    ymm = pd.to_datetime(day_n).year == y
    if ymm.sum() == 0:
        continue
    aa = np.cumprod(1 + ra_n[ymm])[-1] - 1
    gg = np.cumprod(1 + rg_n[ymm])[-1] - 1
    print(f"  {y}: alpha={aa:+.3f} dual_gate={gg:+.3f} "
          f"gate_on%={np.mean(rg_n[ymm] != 0):.2f}")
diff = rg_n - ra_n
rng = np.random.default_rng(0); BL = 4; n = len(diff); B = 2000
bs = []
for _ in range(B):
    idx = np.concatenate([(np.arange(s, s + BL) % n)
                          for s in rng.integers(0, n, size=n // BL + 1)])[:n]
    bs.append(diff[idx].mean())
bs = np.array(bs) * PER_YR
print(f"BOOT 年化差(dual-alpha) mean={bs.mean():+.4f} "
      f"95%CI=[{np.quantile(bs, .025):+.4f},{np.quantile(bs, .975):+.4f}] "
      f"P(>0)={(bs > 0).mean():.3f}")

