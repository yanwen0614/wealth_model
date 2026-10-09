"""dt_alpha: α塔 HGB-16 expanding年WF(2019-25). 超参同p1, 标签y_close, purge=6天.
落盘 dt_alpha_oos.npz (OOS行: date/code/score/y_open/y_close)."""
import os
import time

import numpy as np

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\dt_data"
X = np.load(os.path.join(D, "X_cs.npy"))
yc = np.load(os.path.join(D, "y_close.npy")).astype(np.float64)
yo = np.load(os.path.join(D, "y_open.npy")).astype(np.float64)
dt = np.load(os.path.join(D, "dates.npy"))
ci = np.load(os.path.join(D, "code_idx.npy"))
codes = np.load(os.path.join(D, "codes.npy"), allow_pickle=True)
from sklearn.ensemble import HistGradientBoostingRegressor

ud = np.sort(np.unique(dt))
out = []
for y in range(2019, 2026):
    t0 = np.datetime64(f"{y}-01-01")
    pos = int(np.searchsorted(ud, t0))
    tr_days = ud[:max(0, pos - 6)]
    te_days = ud[(ud >= t0) & (ud < np.datetime64(f"{y + 1}-01-01"))]
    trm = np.isin(dt, tr_days) & np.isfinite(yc)
    tem = np.isin(dt, te_days)
    assert dt[trm].max() < dt[tem].min()
    lo, hi = np.percentile(yc[trm], [0.5, 99.5])
    m = HistGradientBoostingRegressor(max_iter=200, max_leaf_nodes=31,
        min_samples_leaf=50, l2_regularization=1.0, random_state=42)
    t1 = time.time()
    m.fit(X[trm], np.clip(yc[trm], lo, hi))
    sc = m.predict(X[tem]).astype(np.float64)
    print(f"fold {y}: train={int(trm.sum())} test={int(tem.sum())} "
          f"fit={time.time()-t1:.0f}s", flush=True)
    out.append((dt[tem], ci[tem], sc, yo[tem], yc[tem]))
o = [np.concatenate(a) for a in zip(*out)]
np.savez(os.path.join(D, "dt_alpha_oos.npz"), date=o[0], code=o[1],
         score=o[2], y_open=o[3], y_close=o[4], codes=codes)
print("WROTE dt_alpha_oos.npz rows=", len(o[0]))
