"""dt_build: 本地parquet -> cs16 rank特征 + y_close/y_open. 口径同tree_rebuild/build_cs."""
import json
import os
import time

import numpy as np
import pandas as pd

P = r"D:\code\cnn_full_20260905\cnn\data\test\train_data\train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
FEATS = ("dmi", "adx", "boll", "kelch", "trend_duokong_dev",
         "volatility_5d", "volatility_10d", "volatility_20d",
         "volume_ratio_5d", "volume_ratio_10d", "amihud", "macd",
         "gross_margin", "net_margin", "debt_to_equity", "roe")
OUT = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\dt_data"
os.makedirs(OUT, exist_ok=True)
t0 = time.time()
cols = ["code", "kline_time", "is_trading", "open", "close", *FEATS]
df = pd.read_parquet(P, columns=cols)
print(f"read {len(df)} {time.time()-t0:.1f}s", flush=True)
df = df[df["is_trading"] & (df["open"] > 0) & (df["close"] > 0)].copy()
df["date"] = df["kline_time"].dt.normalize()
df = df.sort_values(["code", "date"]).reset_index(drop=True)
print(f"filtered {len(df)} codes={df['code'].nunique()}", flush=True)
g = df.groupby("code", sort=False)
y_close = g["close"].transform(lambda s: s.shift(-5) / s - 1.0).to_numpy(np.float64)
y_open = g["open"].transform(lambda s: s.shift(-6) / s.shift(-1) - 1.0).to_numpy(np.float64)
X = np.empty((len(df), len(FEATS)), dtype=np.float32)
for j, f in enumerate(FEATS):
    X[:, j] = df.groupby("date", sort=False)[f].rank(pct=True).fillna(0.5).to_numpy(np.float32)
codes, cu = pd.factorize(df["code"])
dates = df["date"].to_numpy("datetime64[us]")
for n, a in (("X_cs", X), ("y_close", y_close.astype(np.float32)),
             ("y_open", y_open.astype(np.float32)), ("dates", dates),
             ("code_idx", codes.astype(np.int32))):
    np.save(os.path.join(OUT, f"{n}.npy"), a)
np.save(os.path.join(OUT, "codes.npy"), np.asarray(cu, dtype=object), allow_pickle=True)
with open(os.path.join(OUT, "features.json"), "w", encoding="utf-8") as fh:
    json.dump({"features": [f"cs_{f}" for f in FEATS]}, fh, indent=2)
print(f"saved {OUT} X={X.shape} {time.time()-t0:.1f}s", flush=True)
