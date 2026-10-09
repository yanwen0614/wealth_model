"""m05: 波动/尾部/regime(Q3). 目标: |fwd5|(波动)/tail事件/down天.
方法: HGB回归+分类 expanding年WF + HMM2态(无监督,仅历史m_ret).
用法: uv run --project . python m05_risk.py
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
F18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
       "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
       "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
       "dd60", "m_lag1", "m_ma5"]
EXT = list(dict.fromkeys(F18 + ["ret_skew", "tail_up", "tail_dn", "vol20_mean",
       "amihud_med", "vr5_med", "amt_ratio20", "breadth_ma60", "disp_ma20",
       "rv5", "rv20", "downvol20", "m_ema10", "ma_gap5", "ma_gap10",
       "dow", "month", "is_month_end"]))
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
H = 5
fwd = daily[f"ew_fwd{H}"]
daily["avol"] = fwd.abs()
daily["tail"] = (fwd < -0.02).astype(float)
daily["down"] = (fwd < 0).astype(float)
print(f"tail<-2% rate={daily['tail'].mean():.3f} down rate={daily['down'].mean():.3f}")
d = daily.dropna(subset=EXT + ["avol", "tail", "down", f"ew_fwd{H}"]).copy()
dd = np.sort(d["day"].unique())
out = {}
for tgt, clf in (("avol", False), ("tail", True), ("down", True)):
    P, Y = [], []
    for y in range(2019, 2026):
        te_days = dd[pd.to_datetime(dd).year == y]
        if len(te_days) == 0: continue
        pos = int(np.searchsorted(dd, te_days[0]))
        tr = d[d["day"].isin(dd[:max(0, pos - H)])]
        te = d[d["day"].isin(te_days)]
        m = (HistGradientBoostingClassifier(max_depth=3, max_iter=300,
             learning_rate=0.05, l2_regularization=1.0, random_state=42)
             if clf else HistGradientBoostingRegressor(max_depth=3, max_iter=300,
             learning_rate=0.05, l2_regularization=1.0, random_state=42))
        m.fit(tr[EXT].values, tr[tgt].values)
        p = (m.predict_proba(te[EXT].values)[:, 1] if clf
             else np.asarray(m.predict(te[EXT].values), float))
        P.append(p); Y.append(te[tgt].values)
    p, y = map(np.concatenate, (P, Y))
    if clf:
        print(f"{tgt:4s} AUC={roc_auc_score(y, p):.4f} base={y.mean():.3f}", flush=True)
    else:
        ic = pd.Series(p).corr(pd.Series(y), method="spearman")
        ss = 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        print(f"{tgt:4s} IC={ic:+.4f} OOS_R2={ss:+.4f}", flush=True)
    out[tgt] = (p, y)
print("WROTE(内存). HMM...", flush=True)
# KMeans 2态(替代HMM, 避免新依赖): 逐折仅用训练期[m_ret,rv20]拟合, OOS分态
hrs = []
for y in range(2019, 2026):
    te_days = dd[pd.to_datetime(dd).year == y]
    if len(te_days) == 0: continue
    pos = int(np.searchsorted(dd, te_days[0]))
    tr = d[d["day"].isin(dd[:max(0, pos - H)])]
    te = d[d["day"].isin(te_days)]
    km = KMeans(2, n_init=10, random_state=0).fit(tr[["m_ret", "rv20"]].values)
    s_tr = km.labels_
    bad = int(np.argmin([tr.loc[s_tr == k, f"ew_fwd{H}"].mean() for k in (0, 1)]))
    risk_off = (km.predict(te[["m_ret", "rv20"]].values) == bad)
    hrs.append((te[f"ew_fwd{H}"].values[risk_off].mean(),
                te[f"ew_fwd{H}"].values[~risk_off].mean(), risk_off.mean()))
    print(f"KMeans-regime fold {y}: riskoff%={risk_off.mean():.2f} " f"off_fwd={hrs[-1][0]:+.5f} on_fwd={hrs[-1][1]:+.5f}", flush=True)
hrs = np.array(hrs)
print(f"KMeans-regime pooled: off={hrs[:, 0].mean():+.5f} on={hrs[:, 1].mean():+.5f}")
pd.DataFrame({
    "tail_p": out["tail"][0], "tail_y": out["tail"][1], "down_p": out["down"][0],
    "down_y": out["down"][1], "avol_p": out["avol"][0],
    "avol_y": out["avol"][1]}).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m05_risk.csv", index=False)
print("WROTE m05_risk.csv")
