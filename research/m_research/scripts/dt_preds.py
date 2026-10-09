"""dt_preds: 由dt_alpha_oos构造引擎输入npz(2025)+门控版. 口径同m06b(滞后一日)."""
import numpy as np
import pandas as pd

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\dt_data\dt_alpha_oos.npz"
SIG = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_signals.csv"
OUT = r"D:\code\cnn_full_20260905\cnn\logs\m_research"
z = np.load(D, allow_pickle=True)
date = pd.to_datetime(z["date"]).normalize()
codes_u = z["codes"]
code_str = codes_u[z["code"]]
score = z["score"]; y_open = z["y_open"].astype(np.float64)
m25 = (date.year == 2025) & np.isfinite(y_open)
d25, c25, s25, y25 = date[m25], code_str[m25], score[m25], y_open[m25]
np.savez(f"{OUT}\\preds_dualalpha_2025.npz", exp_ret=s25.astype(np.float64),
         true_ret=y25, dates=d25.to_numpy(), codes=c25.astype(str))
print("naked rows", len(s25), "days", d25.nunique())
sig = pd.read_csv(SIG, parse_dates=["day"]); sig["day"] = sig["day"].dt.normalize()
p_by_day = dict(zip(sig["day"], sig["p"]))
tdays = np.sort(np.unique(d25))
prev = {t: tdays[i - 1] if i > 0 else None for i, t in enumerate(tdays)}
long = np.array([True if (prev[t] is None or prev[t] not in p_by_day)
                 else bool(p_by_day[prev[t]] > 0.5) for t in d25])
exp = s25.astype(np.float64).copy(); exp[~long] = -1.0
np.savez(f"{OUT}\\preds_dualalpha_2025_gate.npz", exp_ret=exp, true_ret=y25,
         dates=d25.to_numpy(), codes=c25.astype(str))
print(f"gate rows={len(exp)} riskoff_rows={int((~long).sum())} "
      f"riskoff_days={len(set(d25[~long]))}")
