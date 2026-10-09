"""m00: 市场日频面板. 本地parquet->日频特征+双口径m_t.
口径A(xs,H)=当日有效股return_H截面均值; 口径B(ew)=m_ret累乘再fwd.
用法: uv run --project . python m00_build.py (在m_research目录)
"""
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

P = r"D:\code\cnn_full_20260905\cnn\data\test\train_data\train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
OUT = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
COLS = ["code", "kline_time", "close", "volume", "amount", "is_trading",
        "return_1d", "return_5d", "return_10d", "return_20d",
        "volatility_5d", "volatility_20d", "amihud",
        "volume_ratio_5d", "std_5", "std_20"]
print("reading...", flush=True)
df = pq.read_table(P, columns=COLS).to_pandas()
print("rows", len(df), flush=True)
df = df[df["is_trading"] & np.isfinite(df["return_1d"].values)]
df["day"] = pd.to_datetime(df["kline_time"].dt.normalize())
print("trading rows", len(df), "days", df["day"].nunique(), flush=True)
g = df.groupby("day", sort=True)
daily = pd.DataFrame({
    "m_ret": g["return_1d"].mean(),
    "xs_m5": g["return_5d"].mean(), "xs_m10": g["return_10d"].mean(),
    "xs_m20": g["return_20d"].mean(),
    "ret_std": g["return_1d"].std(), "ret_skew": g["return_1d"].skew(),
    "breadth": g["return_1d"].apply(lambda s: float((s > 0).mean())),
    "tail_up": g["return_1d"].apply(lambda s: float((s > 0.095).mean())),
    "tail_dn": g["return_1d"].apply(lambda s: float((s < -0.095).mean())),
    "vol5_med": g["volatility_5d"].median(),
    "vol5_mean": g["volatility_5d"].mean(),
    "vol20_mean": g["volatility_20d"].mean(),
    "amihud_med": g["amihud"].median(),
    "vr5_med": g["volume_ratio_5d"].median(),
    "volume_sum": g["volume"].sum(), "amount_sum": g["amount"].sum(),
    "n_codes": g.size(),
}).reset_index().sort_values("day").reset_index(drop=True)
print(daily.head(2).to_string(), flush=True)
daily["ew_index"] = (1.0 + daily["m_ret"]).cumprod()
for w in (5, 10, 20, 40, 60):
    daily[f"ma{w}"] = daily["ew_index"].rolling(w).mean()
    daily[f"mom{w}"] = daily["ew_index"] / daily["ew_index"].shift(w) - 1.0
    daily[f"ma_gap{w}"] = daily["ew_index"] / daily[f"ma{w}"] - 1.0
    daily[f"vol_ratio{w}"] = daily["volume_sum"] / daily["volume_sum"].rolling(w).mean() - 1.0
    daily[f"amt_ratio{w}"] = daily["amount_sum"] / daily["amount_sum"].rolling(w).mean() - 1.0
    daily[f"breadth_ma{w}"] = daily["breadth"].rolling(w).mean()
    daily[f"disp_ma{w}"] = daily["ret_std"].rolling(w).mean()
daily["ret_std_ma20"] = daily["ret_std"].rolling(20).mean()
daily["vol5_ma20"] = daily["vol5_mean"].rolling(20).mean()
daily["dd60"] = daily["ew_index"] / daily["ew_index"].rolling(60).max() - 1.0
daily["m_lag1"] = daily["m_ret"].shift(1)
daily["m_ma5"] = daily["m_ret"].rolling(5).mean()
daily["m_ema10"] = daily["m_ret"].ewm(span=10).mean()
daily["rv5"] = daily["m_ret"].rolling(5).std()
daily["rv20"] = daily["m_ret"].rolling(20).std()
daily["downvol20"] = daily["m_ret"].rolling(20).apply(
    lambda s: float(s[s < 0].std()) if (s < 0).sum() >= 2 else np.nan, raw=False)
daily["dow"] = daily["day"].dt.dayofweek
daily["month"] = daily["day"].dt.month
daily["is_month_end"] = (daily["day"] == daily["day"] + pd.offsets.MonthEnd(0)).astype(float)
for H in (1, 5, 10, 20):
    daily[f"ew_fwd{H}"] = daily["ew_index"].shift(-H) / daily["ew_index"] - 1.0
    daily[f"ew_up{H}"] = (daily[f"ew_fwd{H}"] > 0).astype(float)
daily.to_parquet(OUT, index=False)
print("saved", OUT, daily.shape, flush=True)
print(daily[["day", "m_ret", "xs_m5", "ew_fwd5"]].tail(8).to_string())
c = daily[["xs_m5", "ew_fwd5"]].corr(method="spearman")
print("spearman(xs_m5,ew_fwd5)=", round(float(c.iloc[0, 1]), 4))
