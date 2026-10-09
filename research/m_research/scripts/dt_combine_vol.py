"""dt_combine_vol: 波动塔定仓. α塔非重叠周期收益 × clip(target/pred_vol,0,1).
target=扩展窗口历史pred_vol中位(无泄漏). 对比 α-only vs volscale.
"""
import numpy as np
import pandas as pd

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\dt_data\dt_alpha_oos.npz"
VOL = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m05b_volpred.csv"
N, STEP = 200, 5
z = np.load(D, allow_pickle=False)
date = pd.to_datetime(z["date"]).normalize(); sc = z["score"]
yo = z["y_open"].astype(np.float64)
vol = pd.read_csv(VOL, parse_dates=["day"]); vol["day"] = vol["day"].dt.normalize()
vp = dict(zip(vol["day"], vol["avol_pred"]))
ud = np.sort(np.unique(date))
order = np.argsort(date, kind="stable"); ds = date[order]
uniq, start = np.unique(ds, return_index=True)
groups = np.split(order, start[1:])
ra, mday = [], []
for i, g in enumerate(groups):
    s, r = sc[g], yo[g]; ok = np.isfinite(r) & np.isfinite(s)
    if ok.sum() < N: continue
    s, r = s[ok], r[ok]; sel = np.argpartition(-s, N - 1)[:N]
    ra.append(float(r[sel].mean())); mday.append(uniq[i])
ra = np.array(ra); mday = np.array(mday)
sel = np.arange(0, len(ra), STEP)
ra_n, day_n = ra[sel], mday[sel]
pv = np.array([vp.get(d, np.nan) for d in day_n])
ok = np.isfinite(pv)
# expanding median target (用预测日之前的预测值, 无泄漏)
exp = []
for i in range(len(pv)):
    hist = pv[:i][ok[:i]]
    tgt = np.median(hist) if len(hist) >= 10 else np.nan
    exp.append(min(1.0, tgt / pv[i]) if (np.isfinite(tgt) and pv[i] > 0) else np.nan)
exposure = np.array(exp)
mask = ok & np.isfinite(exposure)
ra_m, exp_m, day_m = ra_n[mask], exposure[mask], day_n[mask]
rv = ra_m * exp_m
print(f"期数={len(ra_m)} 平均仓位={exp_m.mean():.3f}")
PER_YR = 252 / STEP
def stats(r, label):
    nav = np.cumprod(1 + r); n = len(r)
    ann = nav[-1] ** (PER_YR / n) - 1; sd = r.std(ddof=1)
    sh = r.mean() / sd * np.sqrt(PER_YR) if sd > 0 else np.nan
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    print(f"{label:12s} 年化={ann:+.4f} Sharpe={sh:+.3f} MDD={dd:.4f} NAV={nav[-1]:.3f}")
    return ann, sh, dd
stats(ra_m, "alpha_only"); stats(rv, "alpha_volscale")
for y in range(2019, 2026):
    ym = pd.to_datetime(day_m).year == y
    if ym.sum() == 0: continue
    print(f"  {y}: alpha={np.cumprod(1+ra_m[ym])[-1]-1:+.3f} "
          f"volscale={np.cumprod(1+rv[ym])[-1]-1:+.3f} 仓={exp_m[ym].mean():.2f}")
