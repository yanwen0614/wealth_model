"""m03: GBDT sweep. HGB回归/分类 + XGB-GPU回归/分类 + HGB分位(0.1/0.5/0.9).
H={5,10}, EXT特征, expanding年WF(2019-25) purge=H.
用法: uv run --project . python m03_gbdt.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier, XGBRegressor

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
F18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
       "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
       "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
       "dd60", "m_lag1", "m_ma5"]
EXT = list(dict.fromkeys(F18 + ["ret_skew", "tail_up", "tail_dn", "vol20_mean",
       "amihud_med", "vr5_med", "amt_ratio20", "breadth_ma60", "disp_ma20",
       "rv5", "rv20", "downvol20", "m_ema10", "ma_gap5", "ma_gap10",
       "dow", "month", "is_month_end"]))
def mk(n):
    if n == "hgb_reg": return HistGradientBoostingRegressor(
        max_depth=3, max_iter=300, learning_rate=0.05, l2_regularization=1.0,
        random_state=42)
    if n == "hgb_clf": return HistGradientBoostingClassifier(
        max_depth=3, max_iter=300, learning_rate=0.05, l2_regularization=1.0,
        random_state=42)
    if n == "xgb_reg": return XGBRegressor(n_estimators=300, max_depth=3,
        learning_rate=0.05, reg_lambda=1.0, subsample=0.8, colsample_bytree=0.8,
        device="cuda", random_state=42, n_jobs=0)
    if n == "xgb_clf": return XGBClassifier(n_estimators=300, max_depth=3,
        learning_rate=0.05, reg_lambda=1.0, subsample=0.8, colsample_bytree=0.8,
        device="cuda", random_state=42, n_jobs=0, eval_metric="logloss")
    q = float(n.split("_q")[-1]) / 100.0
    return HistGradientBoostingRegressor(loss="quantile", quantile=q,
        max_depth=3, max_iter=300, learning_rate=0.05, l2_regularization=1.0,
        random_state=42)
NAMES = ["hgb_reg", "hgb_clf", "xgb_reg", "xgb_clf", "hgb_q10", "hgb_q50", "hgb_q90"]
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
rows = []
for H in (5, 10):
    lab, fwd = f"ew_up{H}", f"ew_fwd{H}"
    d = daily.dropna(subset=EXT + [lab, fwd]).copy()
    dd = np.sort(d["day"].unique())
    per = {n: ([], [], []) for n in NAMES}
    for y in range(2019, 2026):
        te_days = dd[pd.to_datetime(dd).year == y]
        if len(te_days) == 0: continue
        pos = int(np.searchsorted(dd, te_days[0]))
        tr = d[d["day"].isin(dd[:max(0, pos - H)])]
        te = d[d["day"].isin(te_days)]
        assert tr["day"].max() < te["day"].min()
        Xtr, Xte = tr[EXT].values, te[EXT].values
        for n in NAMES:
            m = mk(n)
            m.fit(Xtr, tr[lab].values if "clf" in n else tr[fwd].values)
            p = (m.predict_proba(Xte)[:, 1] if "clf" in n
                 else np.asarray(m.predict(Xte), float))
            per[n][0].append(p)
            per[n][1].append(te[fwd].values); per[n][2].append(te[lab].values)
    for n, (pl, yl, ll) in per.items():
        p, y, l = map(np.concatenate, (pl, yl, ll))
        if "clf" in n:
            auc = roc_auc_score(l, p); acc = float((((p > 0.5) == (l > 0))).mean())
            ic = pd.Series(p).corr(pd.Series(y), method="spearman")
            print(f"H={H:2d} {n:7s} AUC={auc:.4f} acc={acc:.4f} "
                  f"ICvsAmp={ic:+.4f} base={l.mean():.3f}", flush=True)
            rows.append({"H": H, "model": n, "AUC": round(float(auc), 4),
                         "acc": round(float(acc), 4), "IC": round(float(ic), 4)})
        else:
            ic = pd.Series(p).corr(pd.Series(y), method="spearman")
            ss = 1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()
            auc = roc_auc_score(l, p)
            print(f"H={H:2d} {n:7s} IC={ic:+.4f} OOS_R2={ss:+.4f} "
                  f"AUC={auc:.4f} base={l.mean():.3f}", flush=True)
            rows.append({"H": H, "model": n, "IC": round(float(ic), 4),
                         "R2": round(float(ss), 4), "AUC": round(float(auc), 4)})
pd.DataFrame(rows).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m03_gbdt.csv", index=False)
print("WROTE m03_gbdt.csv")
