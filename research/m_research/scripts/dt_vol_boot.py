"""dt_vol_boot: 波动缩放的Sharpe改善显著性. 循环块bootstrap(块4期,B=2000)."""
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
ud = np.sort(np.unique(date)); order = np.argsort(date, kind="stable")
ds = date[order]; uniq, start = np.unique(ds, return_index=True)
groups = np.split(order, start[1:])
ra, mday = [], []
for i, g in enumerate(groups):
    s, r = sc[g], yo[g]; ok = np.isfinite(r) & np.isfinite(s)
    if ok.sum() < N: continue
    s, r = s[ok], r[ok]; sel = np.argpartition(-s, N - 1)[:N]
    ra.append(float(r[sel].mean())); mday.append(uniq[i])
ra = np.array(ra); mday = np.array(mday)
sel = np.arange(0, len(ra), STEP); ra_n, day_n = ra[sel], mday[sel]
pv = np.array([vp.get(d, np.nan) for d in day_n]); ok = np.isfinite(pv)
exp = []
for i in range(len(pv)):
    h = pv[:i][ok[:i]]
    tgt = np.median(h) if len(h) >= 10 else np.nan
    exp.append(min(1.0, tgt / pv[i]) if (np.isfinite(tgt) and pv[i] > 0) else np.nan)
exp = np.array(exp); m = ok & np.isfinite(exp)
ra_m, exp_m = ra_n[m], exp[m]; rv = ra_m * exp_m
PER_YR = 252 / STEP
def sharpe(r): return r.mean() / r.std(ddof=1) * np.sqrt(PER_YR)
obs = sharpe(rv) - sharpe(ra_m)
rng = np.random.default_rng(0); BL, B, n = 4, 2000, len(ra_m)
bs = []
for _ in range(B):
    idx = np.concatenate([(np.arange(s, s + BL) % n)
                          for s in rng.integers(0, n, size=n // BL + 1)])[:n]
    bs.append(sharpe(rv[idx]) - sharpe(ra_m[idx]))
bs = np.array(bs)
print(f"Sharpe差 obs={obs:+.4f} boot_mean={bs.mean():+.4f} "
      f"95%CI=[{np.quantile(bs,.025):+.4f},{np.quantile(bs,.975):+.4f}] "
      f"P(>0)={(bs>0).mean():.3f}")
