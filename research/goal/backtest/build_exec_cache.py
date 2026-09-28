"""Precompute market-lookup cache for account_engine_v5/v6.

Builds one cache per (train file x exec mode) under
  artifacts/exec_cache/{train_fingerprint}_{exec}.parquet

Cache content: flattened trading-only market rows sorted by (code, mkt_date),
with all fields lookup_exec needs (open/high/low/close/volume/amount,
prev_close, dates). Key organization mirrors v5's build_market_lookup /
lookup_exec semantics verbatim: v6 reconstructs the identical
  lookup[code] = {dates_int, dates, open, high, low, close, volume, amount}
dict by grouping on code sorted by mkt_date, then queries with the same
searchsorted (next-trading-day for t1open, exact-match for close/dayclose/mid).

Columns:
  code, signal_date (=mkt_date, normalized; name matches task spec),
  mkt_date, dates_int (int64 days since epoch),
  open, high, low, close, volume, amount, prev_close,
  exec_base (per-exec-mode base price of that row:
    t1open->open, close/dayclose-15min->close, mid->(high+low)/2 w/ close fallback)

The lookup dict itself is exec-independent in v5 (build_market_lookup ignores
exec_mode; branching happens in lookup_exec at query time), so the four exec
caches share identical raw OHLCV/prev_close content and differ only in the
exec_base column + metadata. Four files are still written per spec.

Fingerprint inference (matches REPORT/PLAN upstream naming):
  - if basename contains _<12 hex> (e.g. ..._0faaf8c69c89.parquet), use it
  - elif basename contains 20260831 -> de850feab96a (new train, per opt_extend report)
  - elif path == data/train_data.parquet (fingerprint-less copy) -> 0faaf8c69c89
  - else --fingerprint override required (or use --fingerprint explicitly)

Usage:
  python backtest/build_exec_cache.py --train data/train_data.parquet --exec t1open
  python backtest/build_exec_cache.py --train data/train_data.parquet --exec all
  python backtest/build_exec_cache.py --train data/new/train_data_20260831.parquet --exec all

Imports load_market helpers only for column contract; the full-table scan here
is intentionally pred-independent (no code/min_date filter) so one cache serves
any pred universe. v6 filters by pred codes/min_date after load to reproduce
the filtered lookup bit-for-bit.
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

EXEC_MODES = ["t1open", "close", "dayclose-15min", "mid"]

# Known fingerprints (see REPORT.md / artifacts/opt_extend/REPORT_extend.md)
FP_OLD = "0faaf8c69c89"
FP_NEW = "de850feab96a"


def infer_fingerprint(train_path: str) -> str:
    base = Path(train_path).name
    m = re.search(r"_([0-9a-f]{12})(?=\.parquet$)", base)
    if m:
        return m.group(1)
    if "20260831" in base:
        return FP_NEW
    # goal-internal copy without suffix is a full cp of the old source
    if base == "train_data.parquet":
        return FP_OLD
    raise ValueError(
        f"cannot infer fingerprint from basename {base!r}; "
        "pass --fingerprint explicitly"
    )


def exec_base_for_mode(df: pd.DataFrame, exec_mode: str) -> np.ndarray:
    if exec_mode == "t1open":
        return df["open"].to_numpy(dtype=float)
    if exec_mode in ("close", "dayclose-15min"):
        return df["close"].to_numpy(dtype=float)
    if exec_mode == "mid":
        hi = df["high"].to_numpy(dtype=float)
        lo = df["low"].to_numpy(dtype=float)
        cl = df["close"].to_numpy(dtype=float)
        base = (hi + lo) / 2.0
        bad = ~(np.isfinite(hi) & np.isfinite(lo))
        base[bad] = cl[bad]
        return base
    raise ValueError(exec_mode)


def build_one(train_path: str, exec_mode: str, out_path: Path) -> dict:
    t0 = time.time()
    pf = pq.ParquetFile(train_path)
    parts: list[pd.DataFrame] = []
    for batch in pf.iter_batches(
        columns=["code", "kline_time", "open", "high", "low", "close",
                 "volume", "amount", "is_trading"],
        batch_size=500_000,
    ):
        b = batch.to_pandas()
        b = cast(pd.DataFrame, b[b["is_trading"] == True])
        if len(b) == 0:
            continue
        parts.append(b)
    mkt = pd.concat(parts, ignore_index=True)
    mkt["kline_time"] = pd.to_datetime(mkt["kline_time"])
    mkt["mkt_date"] = mkt["kline_time"].dt.normalize()
    mkt = mkt.sort_values(["code", "mkt_date"]).reset_index(drop=True)
    # prev trading close per code (for limit bands; NaN when none, same as lookup_exec)
    mkt["prev_close"] = mkt.groupby("code")["close"].shift(1)
    mkt["signal_date"] = mkt["mkt_date"]
    mkt["dates_int"] = (
        mkt["mkt_date"].to_numpy(dtype="datetime64[D]").astype("int64")
    )
    mkt["exec_base"] = exec_base_for_mode(mkt, exec_mode)
    out = cast(pd.DataFrame, mkt[["code", "signal_date", "mkt_date", "dates_int",
               "open", "high", "low", "close", "volume", "amount",
               "prev_close", "exec_base"]].copy())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(out_path, index=False)
    dt = time.time() - t0
    size_mb = out_path.stat().st_size / 1024 / 1024
    info = {"rows": len(out), "codes": int(cast(int, out["code"].nunique())),
            "size_mb": round(size_mb, 1), "secs": round(dt, 1),
            "path": str(out_path)}
    print(f"[cache] exec={exec_mode} rows={info['rows']} codes={info['codes']} "
          f"size={info['size_mb']}MB time={info['secs']}s -> {out_path}")
    return info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="data/train_data.parquet")
    ap.add_argument("--exec", dest="exec_mode", default="all",
                    help="t1open/close/dayclose-15min/mid or all")
    ap.add_argument("--out-dir", default="artifacts/exec_cache")
    ap.add_argument("--fingerprint", default=None)
    args = ap.parse_args()

    fp = args.fingerprint or infer_fingerprint(args.train)
    print(f"[cache] train={args.train} fingerprint={fp}")

    if args.exec_mode == "all":
        modes = EXEC_MODES
    else:
        assert args.exec_mode in EXEC_MODES, args.exec_mode
        modes = [args.exec_mode]

    # Load once is done inside build_one per mode (simple, memory-friendly);
    # modes share identical raw content except exec_base, so total ~4x scan.
    # For single-mode validation (t1open) only one scan runs.
    for m in modes:
        out_path = Path(args.out_dir) / f"{fp}_{m}.parquet"
        build_one(args.train, m, out_path)


if __name__ == "__main__":
    main()
