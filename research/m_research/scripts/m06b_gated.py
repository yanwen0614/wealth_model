"""m06b: 构造滞后一日门控npz (执行时点无泄漏: 交易日d用d-1信号).
用法: uv run --project . python m06b_gated.py
"""
import numpy as np
import pandas as pd

SIG = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m06_signals.csv"
INP = r"D:\code\cnn_full_20260905\cnn\logs\preds_fullB_2025.npz"
OUT = r"D:\code\cnn_full_20260905\cnn\logs\m_research\preds_B2025_xgbgate.npz"
sig = pd.read_csv(SIG, parse_dates=["day"])
sig["day"] = sig["day"].dt.normalize()
p_by_day = dict(zip(sig["day"], sig["p"]))
d = np.load(INP, allow_pickle=True)
dates = pd.to_datetime(d["dates"]).normalize()
tdays = np.sort(dates.unique())
prev = {t: tdays[i - 1] if i > 0 else None for i, t in enumerate(tdays)}
long = np.array([True if prev[t] is None or prev[t] not in p_by_day
                 else bool(p_by_day[prev[t]] > 0.5) for t in dates])
exp = d["exp_ret"].astype(np.float64).copy()
exp[~long] = -1.0
np.savez(OUT, exp_ret=exp, true_ret=d["true_ret"], dates=d["dates"], codes=d["codes"])
print(f"rows={len(exp)} riskoff_rows={int((~long).sum())} "
      f"riskoff_days={len(set(dates[~long]))} saved={OUT}")
