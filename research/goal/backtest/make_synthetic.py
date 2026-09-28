"""Synthetic prediction generator for lightweight backtester self-test.

Generates three regimes (good/flat/inv) with schema:
  code:str, kline_time:datetime64, score:float, future_ret_5d:float, q_true:int

- Dates: business days 2024-01-01~2025-12-31 (Mon-Fri, ~523 sections).
- Stocks: 800 per section (STK0001..STK0800).
- future_ret_5d ~ N(0.002, 0.03).
- good: score = future_ret_5d + N(0, 0.60)  -> x-sec Spearman ~= +0.05
- flat: score = N(0, 1) independent        -> x-sec Spearman ~= 0
- inv:  score = -future_ret_5d + N(0, 0.60)-> x-sec Spearman ~= -0.05
- q_true: per-date quintile of future_ret_5d (1..5, via qcut).

Theory for sigma choice (good):
  score = ret + eps, Var(ret)=0.03^2=9e-4, Var(eps)=s^2.
  Pearson rho = 9e-4 / (0.03*sqrt(9e-4+s^2)) ~= 0.05 -> s ~= 0.60.
  Spearman tracks Pearson closely for Gaussian data.

Usage:
  /home/starcyan/code/cnn/.venv/bin/python backtest/make_synthetic.py [--outdir backtest] [--seed-base 42]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

START = "2024-01-01"
END = "2025-12-31"
N_STOCKS = 800
RET_MU = 0.002
RET_SD = 0.03
NOISE_SD_SIGNAL = 0.60  # gives rho ~= 0.05 (see docstring)

REGIMES = ("good", "flat", "inv")


def _build_one(dates: pd.DatetimeIndex, seed: int, regime: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_dates = len(dates)
    # (n_dates, n_stocks) blocks keep per-day noise independent ("逐日加噪")
    fut = rng.normal(RET_MU, RET_SD, size=(n_dates, N_STOCKS))
    if regime == "good":
        noise = rng.normal(0.0, NOISE_SD_SIGNAL, size=(n_dates, N_STOCKS))
        score = fut + noise
    elif regime == "flat":
        score = rng.normal(0.0, 1.0, size=(n_dates, N_STOCKS))
    elif regime == "inv":
        noise = rng.normal(0.0, NOISE_SD_SIGNAL, size=(n_dates, N_STOCKS))
        score = -fut + noise
    else:  # pragma: no cover
        raise ValueError(regime)

    codes = [f"STK{i:04d}" for i in range(1, N_STOCKS + 1)]
    # Long-form frames
    df = pd.DataFrame({
        "code": np.tile(codes, n_dates),
        "kline_time": np.repeat(dates.values, N_STOCKS),
        "score": score.ravel(),
        "future_ret_5d": fut.ravel(),
    })
    # q_true: per-section quintile of realized future_ret_5d (1..5)
    df["q_true"] = (
        df.groupby("kline_time")["future_ret_5d"]
        .transform(lambda s: pd.qcut(s, 5, labels=[1, 2, 3, 4, 5]))
        .astype(int)
    )
    df["code"] = df["code"].astype(str)
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    return cast(pd.DataFrame, df[["code", "kline_time", "score", "future_ret_5d", "q_true"]])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--seed-base", type=int, default=42)
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range(START, END)  # Mon-Fri synthetic calendar
    print(f"dates: {cast(Any, dates[0]).date()}~{cast(Any, dates[-1]).date()} n={len(dates)} stocks={N_STOCKS}")
    for i, regime in enumerate(REGIMES):
        df = _build_one(dates, args.seed_base + i, regime)
        # quick IC sanity check
        ics = df.groupby("kline_time")[["score", "future_ret_5d"]].apply(
            lambda g: g["score"].corr(g["future_ret_5d"], method="spearman")
        )
        print(f"{regime}: rows={len(df)} ic_mean={ics.mean():+.4f} ic_std={ics.std():.4f}")
        path = outdir / f"synth_{regime}.parquet"
        df.to_parquet(path, index=False)
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
