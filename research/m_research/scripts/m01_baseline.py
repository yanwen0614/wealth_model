"""m01: 基线复现+expanding WF. always-long/lag/OLS + 18特征logit/hgb.
WF: 年步进OOS 2019-2025, train全历史, purge=H天. 断言逐折打印.
用法: uv run --project . python m01_baseline.py --H 5
"""
import argparse

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
FEATS18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
           "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
           "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
           "dd60", "m_lag1", "m_ma5"]
ap = argparse.ArgumentParser(); ap.add_argument("--H", type=int, default=5)
A = ap.parse_args(); H = A.H
lab, fwd = f"ew_up{H}", f"ew_fwd{H}"
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
d = daily.dropna(subset=FEATS18 + [lab, fwd]).copy()
d["year"] = d["day"].dt.year
print(f"label={lab} H={H} n={len(d)} range={d['day'].min()}..{d['day'].max()}")
print(f"always-long base_up={d[lab].mean():.4f} (task4称0.675, 以本地口径为准)")
print(f"lag1 autocorr(m_ret)={d['m_ret'].corr(d['m_lag1']):+.4f}")
X0 = d[FEATS18].values; y0 = d[fwd].values
print(f"OLS全样本R2(仅参考, 有泄漏)={Ridge().fit(X0,y0).score(X0,y0):+.4f}")
days = np.sort(d["day"].unique())
res = []
for y in range(2019, 2026):
    te_days = days[pd.to_datetime(days).year == y]
    if len(te_days) == 0: continue
    t0 = te_days[0]
    pos = int(np.searchsorted(days, t0))
    tr_days = days[:max(0, pos - H)]  # purge H天
    tr = d[d["day"].isin(tr_days)]; te = d[d["day"].isin(te_days)]
    ok = len(tr_days) == 0 or tr_days.max() < t0
    gap = pos - int(np.searchsorted(days, tr_days.max())) - 1 if len(tr_days) else -1
    print(f"fold {y}: train[{tr['day'].min()}..{tr['day'].max()}]n={len(tr)} "
          f"test[{te['day'].min()}..{te['day'].max()}]n={len(te)} purge_gap={gap} "
          f"assert_max(train)<min(test)={ok}")
    assert ok, "leak!"
    for name, m in {
        "logit": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        "hgb": HistGradientBoostingClassifier(max_depth=3, max_iter=300,
              learning_rate=0.05, l2_regularization=1.0, random_state=42)}.items():
        m.fit(tr[FEATS18].values, tr[lab].values)
        p = m.predict_proba(te[FEATS18].values)[:, 1]
        auc = roc_auc_score(te[lab].values, p)
        acc = accuracy_score(te[lab].values, (p > 0.5).astype(int))
        lr, fr = te.loc[p > 0.5, fwd].mean(), te.loc[p <= 0.5, fwd].mean()
        print(f"  {name:5s} AUC={auc:.4f} acc={acc:.4f} base={te[lab].mean():.3f} "
              f"long%={(p>0.5).mean():.2f} long_fwd={lr:+.5f} flat_fwd={fr:+.5f}")
        res.append((y, name, auc, acc, float(te[lab].mean())))
r = pd.DataFrame(res, columns=["fold", "model", "auc", "acc", "base"])
print(r.groupby("model")[["auc", "acc"]].mean().round(4).to_string())
r.to_csv(r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m01_wf.csv", index=False)
print("WROTE m01_wf.csv")
