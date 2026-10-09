"""m08: 非对称loss对照. 同一特征/同一WF, 只换正类权重, 看precision-coverage曲线
是否重合(选点)还是上移(抬天花板). 基线=m06的xgb_w1."""
import numpy as np
import pandas as pd
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
for w in (0.4, 1.0, 2.5):
    P, Y, L = [], [], []
    for y in range(2019, 2026):
        te_days = dd[pd.to_datetime(dd).year == y]
        pos = int(np.searchsorted(dd, te_days[0]))
        tr = d[d["day"].isin(dd[:max(0, pos - H)])]
        te = d[d["day"].isin(te_days)]
        m = XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05,
            reg_lambda=1.0, subsample=0.8, colsample_bytree=0.8, device="cuda",
            random_state=42, n_jobs=0, eval_metric="logloss", scale_pos_weight=w)
        m.fit(tr[EXT].values, tr[lab].values)
        P.append(m.predict_proba(te[EXT].values)[:, 1])
        Y.append(te[fwd].values); L.append(te[lab].values)
    p, y, l = map(np.concatenate, (P, Y, L))
    line = f"w={w}: "
    for cov in (0.5, 0.3, 0.2, 0.1):
        cut = np.quantile(p, 1 - cov)
        g = p >= cut
        line += f"cov{cov:.0%}精={l[g].mean():.3f} "
    print(line + f"base={l.mean():.3f}", flush=True)
