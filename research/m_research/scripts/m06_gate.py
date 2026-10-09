"""m06: 门控离线核算 + block-bootstrap CI + 输出2024-25逐日门信号.
最佳方向模型=xgb_clf(H5/EXT). bootstrap: 循环块长20天 B=2000.
用法: uv run --project . python m06_gate.py
"""
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
F18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
       "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
       "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
       "dd60", "m_lag1", "m_ma5"]
EXT = list(dict.fromkeys(F18 + ["ret_skew", "tail_up", "tail_dn", "vol20_mean",
       "amihud_med", "vr5_med", "amt_ratio20", "breadth_ma60", "disp_ma20",
       "rv5", "rv20", "downvol20", "m_ema10", "ma_gap5", "ma_gap10",
       "dow", "month", "is_month_end"]))
H = 5
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
lab, fwd = f"ew_up{H}", f"ew_fwd{H}"
d = daily.dropna(subset=EXT + [lab, fwd]).copy()
dd = np.sort(d["day"].unique())
P, Y, L, DD = [], [], [], []
for y in range(2019, 2026):
    te_days = dd[pd.to_datetime(dd).year == y]
    pos = int(np.searchsorted(dd, te_days[0]))
    tr = d[d["day"].isin(dd[:max(0, pos - H)])]
    te = d[d["day"].isin(te_days)]
    m = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05,
        reg_lambda=1.0, subsample=0.8, colsample_bytree=0.8, device="cuda",
        random_state=42, n_jobs=0, eval_metric="logloss")
    m.fit(tr[EXT].values, tr[lab].values)
    p = m.predict_proba(te[EXT].values)[:, 1]
    P.append(p); Y.append(te[fwd].values); L.append(te[lab].values)
    DD.append(te["day"].values)
    g = p > 0.5
    print(f"fold {y}: long%={g.mean():.2f} long_fwd={te.loc[g, fwd].mean():+.5f} "
          f"flat_fwd={te.loc[~g, fwd].mean():+.5f} base_up={te[lab].mean():.3f}", flush=True)
p, y, l, dys = map(np.concatenate, (P, Y, L, DD))
pd.DataFrame({"day": pd.to_datetime(dys), "p": p, fwd: y,
              lab: l}).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_signals.csv", index=False)
print(f"pooled AUC={roc_auc_score(l, p):.4f} acc={float((((p>0.5)==(l>0))).mean()):.4f}")
# block-bootstrap: 按天循环块(块长20)B=2000, 对pooled AUC与long-flat edge
rng = np.random.default_rng(0)
ud = np.sort(pd.to_datetime(dys).unique())
per_day_p = {t: p[pd.to_datetime(dys) == t].mean() for t in ud}
day_y = {t: y[pd.to_datetime(dys) == t][0] for t in ud}
day_l = {t: l[pd.to_datetime(dys) == t][0] for t in ud}
B, BL = 2000, 20
aucs, edges = [], []
P1 = np.array([per_day_p[t] for t in ud])
Y1 = np.array([day_y[t] for t in ud])
L1 = np.array([day_l[t] for t in ud])
n = len(ud)
for _ in range(B):
    idx = np.concatenate([(np.arange(s, s + BL) % n)
                          for s in rng.integers(0, n, size=n // BL + 1)])[:n]
    try: aucs.append(roc_auc_score(L1[idx], P1[idx]))
    except ValueError: continue
    g = P1[idx] > 0.5
    if g.sum() > 0 and (~g).sum() > 0:
        edges.append(Y1[idx][g].mean() - Y1[idx][~g].mean())
aucs, edges = map(np.array, (aucs, edges))
print(f"BOOT AUC mean={aucs.mean():.4f} 95%CI=[{np.quantile(aucs, .025):.4f},"
      f"{np.quantile(aucs, .975):.4f}] P(AUC>0.5)={(aucs > 0.5).mean():.3f}")
print(f"BOOT edge mean={edges.mean():+.5f} 95%CI=[{np.quantile(edges, .025):+.5f},"
      f"{np.quantile(edges, .975):+.5f}] P(edge>0)={(edges > 0).mean():.3f}")
pd.DataFrame({"auc": aucs}).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_boot_auc.csv", index=False)
print("WROTE m06_signals.csv + m06_boot_auc.csv")
