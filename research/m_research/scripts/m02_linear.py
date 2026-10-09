"""m02: 线性 sweep. Ridge/Lasso/EN/PLS x {18,EXT} x H={1,5,10,20}.
expanding年WF(2019-25), purge=H. 指标: pooled SpearmanIC/OOS-R2/AUC/acc.
用法: uv run --project . python m02_linear.py
"""
import numpy as np
import pandas as pd
from sklearn.cross_decomposition import PLSRegression
from sklearn.linear_model import ElasticNet, Lasso, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
F18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
       "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
       "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
       "dd60", "m_lag1", "m_ma5"]
EXT = F18 + ["ret_skew", "tail_up", "tail_dn", "vol20_mean", "amihud_med",
       "vr5_med", "amt_ratio20", "breadth_ma60", "disp_ma20", "rv5",
       "rv20", "downvol20", "m_ema10", "ma_gap5", "ma_gap10", "mom5",
       "dow", "month", "is_month_end"]
EXT = list(dict.fromkeys(EXT))
def mk(name):
    if name == "ridge": return ("ridge", Ridge(alpha=1.0))
    if name == "lasso": return ("lasso", Lasso(alpha=1e-4, max_iter=5000))
    if name == "en": return ("en", ElasticNet(alpha=1e-4, l1_ratio=0.5, max_iter=5000))
    return ("pls", PLSRegression(n_components=3))
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
days = np.sort(daily["day"].unique())
rows = []
for H in (1, 5, 10, 20):
    lab, fwd = f"ew_up{H}", f"ew_fwd{H}"
    feats = EXT
    d = daily.dropna(subset=feats + [lab, fwd]).copy()
    dd = np.sort(d["day"].unique())
    dd = np.sort(d["day"].unique())
    per = {m: ([], [], []) for m in ("ridge", "lasso", "en", "pls")}
    for y in range(2019, 2026):
        te_days = dd[pd.to_datetime(dd).year == y]
        if len(te_days) == 0: continue
        pos = int(np.searchsorted(dd, te_days[0]))
        tr = d[d["day"].isin(dd[:max(0, pos - H)])]
        te = d[d["day"].isin(te_days)]
        assert tr["day"].max() < te["day"].min()
        for mname in per:
            _, m = mk(mname)
            sc = StandardScaler().fit(tr[feats].values)
            m.fit(sc.transform(tr[feats].values), tr[fwd].values)
            p = np.asarray(m.predict(sc.transform(te[feats].values)), float)
            per[mname][0].append(p)
            per[mname][1].append(te[fwd].values)
            per[mname][2].append(te[lab].values)
    for mname, (pl, yl, ll) in per.items():
        p, y, l = map(np.concatenate, (pl, yl, ll))
        ic = pd.Series(p).corr(pd.Series(y), method="spearman")
        ss = 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        auc = roc_auc_score(l, p)
        acc = float((((p > 0) == (l > 0))).mean())
        print(f"H={H:2d} {mname:5s} n={len(y)} IC={ic:+.4f} "
              f"OOS_R2={ss:+.4f} AUC={auc:.4f} acc={acc:.4f} base={l.mean():.3f}",
              flush=True)
        rows.append({"H": H, "model": mname, "feats": "EXT", "n": len(y),
                     "IC": round(float(ic), 4), "R2": round(float(ss), 4),
                     "AUC": round(float(auc), 4), "acc": round(float(acc), 4),
                     "base": round(float(l.mean()), 4)})
pd.DataFrame(rows).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m02_linear.csv", index=False)
print("WROTE m02_linear.csv")
