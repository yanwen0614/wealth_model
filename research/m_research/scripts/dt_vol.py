"""dt_vol: 波动塔 逐日预测|ew_fwd5| OOS(2019-25), HGB回归, EXT特征. 落盘per-day."""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
OUT = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m05b_volpred.csv"
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
daily["avol"] = daily[f"ew_fwd{H}"].abs()
d = daily.dropna(subset=EXT + ["avol"]).copy()
dd = np.sort(d["day"].unique())
rows = []
for y in range(2019, 2026):
    te_days = dd[pd.to_datetime(dd).year == y]
    pos = int(np.searchsorted(dd, te_days[0]))
    tr = d[d["day"].isin(dd[:max(0, pos - H)])]
    te = d[d["day"].isin(te_days)]
    m = HistGradientBoostingRegressor(max_depth=3, max_iter=300, learning_rate=0.05,
        l2_regularization=1.0, random_state=42)
    m.fit(tr[EXT].values, tr["avol"].values)
    p = m.predict(te[EXT].values)
    rows.append(pd.DataFrame({"day": te["day"].values, "avol_pred": p,
                              "avol_true": te["avol"].values}))
    print(f"fold {y}: n={len(te)} corr={pd.Series(p).corr(pd.Series(te['avol'].values), method='spearman'):+.4f}", flush=True)
pd.concat(rows).to_csv(OUT, index=False)
print("WROTE", OUT)
