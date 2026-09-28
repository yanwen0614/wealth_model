"""Realistic account-level backtest V3 (T+1, lots, per-trade fees, cash accounting).

V3 = copy of backtest/account_engine_v2.py (S1/S2/slippage/limit logic intact)
plus OPT_EXEC2 extensions (defaults reproduce v2 bit-for-bit):
  --exec new modes:
    dayclose-15min: signal-day close as base + slip_rate x1.5 (cap x1.5),
      semi-executable, needs end-of-day pipeline ("需尾盘管线"半可执行).
    mid: signal-day (high+low)/2 as base, slip x1.0,
      semi-executable, needs intraday pipeline ("需盘中均价管线"半可执行).
    t1open=tradable (可交易); close=same-bar (同bar, not claimable).
  --min-edge E: fee-aware BUY filter. 0 disables (default). When E>0, target
    names ranked in bottom 30% of the target list AND score < E are skipped
    (counted in skipped_min_edge). Rationale: marginal names whose predicted
    5d gain proxy (score) cannot cover round-trip cost proxy E.
  Legacy V3 guardrails kept (defaults disable): --min-amount, --max-participation.
  account.json adds min_amount/max_participation params, skipped_min_amount,
  skipped_max_participation, max_participation (max of executed trades).
  S1 fix: holdings not in signal full-domain (no score row that day) are force-sold
    at T+1 open via market direct lookup (not pred exec_map), reason=forced_exit,
    counted in forced_exits. Holdings cap no longer inflates via zombies.
  S2 fix: buy budget iterative reallocation (second-pass sweep). First pass equal-weight
    floor to 100-share lots; leftover cash redistributed to underweight names
    (gap = target_eq - current_base_amount) in rounds until cash cannot buy any
    further 100-share lot or no progress. Counts realloc_passes (total extra rounds
    with >=1 lot added across all rebalances).
  Slippage: volume-based participation with unit correction (see UNIT NOTE below),
    slip_rate = min(0.03*sqrt(participation)+0.0005, 0.03). Buys x(1+slip),
    sells x(1-slip). trades.csv adds slip_cost/slip_rate/participation;
    account.json adds slip_total/slip_drag/avg_participation (+spread/impact split).
  Limit skip (simple): prev-trading-close based bands (688/300 prefix +-20%,
    else +-10%; ST not special, noted). Buy open >= limit_up*0.999 skipped
    (skipped_limit, cash stays for realloc pool). Sell at limit-down still sells
    normally when price exists; missing-price sells counted in locked.

CLI compatible with v1 (all v1 flags, same defaults). Defaults reproduce v1
methodology except the four fixes above (so default 50w final WILL differ from
v1 547592.90 by forced exits + realloc + slip + limits -- intended).

UNIT NOTE (verified by sampling data/train_data.parquet, code in comments):
  amount is nominal CNY (e.g. 000001.SZ 2024-06 ~1.1-2.3e9, matches real daily
  turnover), volume is shares (e.g. 1e8), TOT_SHARE is ~1e4 shares
  (000001.SZ 1.94e6 -> x1e4 = 19.4e9 vs real ~18.2e9). open/close are BACK-ADJUSTED
  (post-split/dividend scaled) prices: ratio = amount/(volume*close) is ~=1 for
  young stocks (688683.SH ~0.99, price ~17 real) but <<1 for old high-dividend
  names (000001.SZ 2024-06 ~0.014, 600519.SH ~0.127, 600654.SH ~0.00066 with
  obvious upstream price anomaly ~3400, see AUDIT D1). Ratio drifts over time
  for the same code (000001.SZ 2013 ~0.045 -> 2024 ~0.014), signature of cumulative
  adjustment factor, not a fixed unit like lot-size or wanyuan.
  Consequence: literal participation = (adj_price*shares)/day_amount overstates
  true participation by the adjustment factor (up to ~1500x for 600654.SH,
  typically 2-70x). Correct participation = nominal_trade/day_amount
  = shares/day_volume * (open_adj/close_adj) ~= shares/day_volume.
  Implementation: ratio_day = amt_day/(vol_day*close_day_adj); nominal_trade =
  base_price*shares*ratio_day; participation = nominal_trade/amt_day.
  Slip is applied to the adjusted execution price (cash accounting stays in
  adjusted scale like v1 for comparability; returns are ratio-correct, absolute
  cross-stock cash weights inherit v1's adjusted-scale limitation, disclosed).

Usage (mirrors v1):
  python account_engine_v2.py --capital 500000 --topn 50 --out artifacts/.../
  python account_engine_v2.py --capital 2000000 --topn 100 --exec t1open --freq 20 \
      --sell-buffer 50 --out artifacts/opt_exec/v2_slip/
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

COMM_RATE = 0.00025
COMM_MIN = 5.0
STAMP_RATE = 0.0005  # sell only
TRANSFER_RATE = 0.00001  # both sides
RF_ANNUAL = 0.02
TRADING_DAYS = 252
HOLD = 5  # nominal holding length per rebalance, matches engine.py

SPREAD_BASE = 0.0005
IMPACT_COEF = 0.03
SLIP_CAP = 0.03


def fee_buy(amount: float) -> float:
    return max(COMM_RATE * amount, COMM_MIN) + TRANSFER_RATE * amount


def fee_sell(amount: float) -> float:
    return max(COMM_RATE * amount, COMM_MIN) + STAMP_RATE * amount + TRANSFER_RATE * amount


def annualize(total_ret: float, n_days: int) -> float:
    nav = 1.0 + total_ret
    if nav <= 0 or n_days <= 0:
        return float("-inf")
    return float(nav ** (TRADING_DAYS / n_days) - 1.0)


def period_sharpe(period_rets: np.ndarray, hold: int = HOLD) -> float:
    if len(period_rets) < 2:
        return 0.0
    rf_p = (1.0 + RF_ANNUAL) ** (hold / TRADING_DAYS) - 1.0
    ex = period_rets - rf_p
    sd = ex.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(ex.mean() / sd * np.sqrt(TRADING_DAYS / hold))


def max_drawdown(nav: np.ndarray) -> float:
    if len(nav) == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    dd = (peak - nav) / np.maximum(peak, 1e-12)
    return float(np.max(dd))


def slip_rate_from_participation(part: float) -> float:
    if part is None or not np.isfinite(part) or part < 0:
        part = 0.0
    return float(min(IMPACT_COEF * np.sqrt(part) + SPREAD_BASE, SLIP_CAP))


def limit_pct(code: str) -> float:
    # Simple version: 688/300 prefix +-20%, else +-10%.
    # ST stocks NOT specially handled (disclosed注记 per task).
    prefix = code[:3]
    if prefix in ("688", "300"):
        return 0.20
    return 0.10


def load_pred(pred_path: str) -> pd.DataFrame:
    df = pd.read_parquet(pred_path, columns=["code", "kline_time", "score", "future_ret_5d"])
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    df["sig_date"] = df["kline_time"].dt.normalize()
    return df


def load_market(train_path: str, min_date: pd.Timestamp, codes: set) -> pd.DataFrame:
    """Chunked pyarrow projection; keep rows >= min_date and codes in universe.

    V2 additionally loads volume/amount/close for participation + limit bands.
    V3 adds high/low for mid executive proxy.
    """
    pf = pq.ParquetFile(train_path)
    parts: list[pd.DataFrame] = []
    for batch in pf.iter_batches(
        columns=["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"],
        batch_size=500_000,
    ):
        b = batch.to_pandas()
        b["kline_time"] = pd.to_datetime(b["kline_time"])
        b = b[b["kline_time"] >= min_date]
        if len(b) == 0:
            continue
        b = b[b["code"].isin(codes)]
        if len(b) == 0:
            continue
        parts.append(b)
    mkt = pd.concat(parts, ignore_index=True)
    mkt["mkt_date"] = mkt["kline_time"].dt.normalize()
    return mkt


def attach_exec(pred: pd.DataFrame, mkt: pd.DataFrame, exec_mode: str = "t1open") -> pd.DataFrame:
    """Execution price map (v1 semantics unchanged, base/mid prices).

    t1open: per-code next-trading-open AFTER signal date (tradable).
    close: signal-day close itself (same-bar).
    dayclose-15min: signal-day close as base (semi-executable, slip x1.5
      applied at trade time, not in this map).
    mid: signal-day (high+low)/2 (semi-executable intraday proxy).
    Returns pred copy with exec_price / exec_date (NaT/NaN when no row).
    """
    pred = pred.copy()
    if exec_mode in ("close", "dayclose-15min", "mid"):
        t = cast(pd.DataFrame, mkt[mkt["is_trading"] == True].copy())
        t["mkt_int"] = t["mkt_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        if exec_mode == "mid":
            base_map: dict[tuple, tuple] = {}
            for r in cast(Any, t.itertuples(index=False)):
                if np.isfinite(r.high) and np.isfinite(r.low):
                    base_map[(r.code, int(r.mkt_int))] = (float((r.high + r.low) / 2.0), r.mkt_date)
                elif np.isfinite(r.close):
                    base_map[(r.code, int(r.mkt_int))] = (float(r.close), r.mkt_date)
        else:  # close / dayclose-15min share signal-day close
            base_map = {}
            for r in cast(Any, t.itertuples(index=False)):
                base_map[(r.code, int(r.mkt_int))] = (float(r.close), r.mkt_date)
        pred_int = pred["sig_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        out_price = np.full(len(pred), np.nan)
        out_date = np.full(len(pred), np.datetime64("NaT", "D"))
        for i, (c, s) in enumerate(zip(pred["code"].to_numpy(), pred_int)):
            hit = base_map.get((c, int(s)))
            if hit is not None:
                out_price[i] = hit[0]
                out_date[i] = np.datetime64(pd.to_datetime(hit[1]).date())
        pred["exec_price"] = out_price
        pred["exec_date"] = pd.to_datetime(out_date)
        return pred
    t = cast(pd.DataFrame, mkt[mkt["is_trading"] == True].copy())
    t = t.sort_values(["code", "mkt_date"])
    out_price = np.full(len(pred), np.nan)
    out_date = np.full(len(pred), np.datetime64("NaT", "D"))
    pred_codes = pred["code"].to_numpy()
    pred_day = pred["sig_date"].to_numpy(dtype="datetime64[D]").astype("int64")
    for code, g in t.groupby("code", sort=False):
        md = g["mkt_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        mo = g["open"].to_numpy(dtype=float)
        mdates = g["mkt_date"].to_numpy(dtype="datetime64[D]")
        mask = pred_codes == code
        if not mask.any():
            continue
        pos = np.searchsorted(md, pred_day[mask], side="right")
        ok = pos < len(md)
        idx = np.where(mask)[0]
        ok_idx = idx[ok]
        out_price[ok_idx] = mo[pos[ok]]
        out_date[ok_idx] = mdates[pos[ok]]
    pred = pred.copy()
    pred["exec_price"] = out_price
    pred["exec_date"] = pd.to_datetime(out_date)
    return pred


def build_market_lookup(mkt: pd.DataFrame, exec_mode: str = "t1open") -> dict:
    """Per-code sorted trading-only arrays for direct execution lookup.

    Returns dict code -> dict(dates_int, dates, open, high, low, close,
    volume, amount). Used for S1 forced exits (market direct, not
    pred-dependent), participation (exec-day volume/amount) and limit bands
    (prev trading close). For exec_mode==close/dayclose-15min/mid, lookup is
    same-day; else next trading day after signal.
    """
    t = cast(pd.DataFrame, mkt[mkt["is_trading"] == True].copy())
    t = t.sort_values(["code", "mkt_date"])
    lookup: dict = {}
    for code, g in t.groupby("code", sort=False):
        g = g.sort_values("mkt_date")
        d = g["mkt_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        lookup[code] = {
            "dates_int": d,
            "dates": g["mkt_date"].to_numpy(dtype="datetime64[D]"),
            "open": g["open"].to_numpy(dtype=float),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "volume": g["volume"].to_numpy(dtype=float),
            "amount": g["amount"].to_numpy(dtype=float),
        }
    return lookup


def slip_mult_for_exec(exec_mode: str) -> float:
    return 1.5 if exec_mode == "dayclose-15min" else 1.0


def slip_cap_for_exec(exec_mode: str) -> float:
    return SLIP_CAP * slip_mult_for_exec(exec_mode)


def slip_eff(part: float, exec_mode: str) -> float:
    m = slip_mult_for_exec(exec_mode)
    return float(min(IMPACT_COEF * np.sqrt(max(part, 0.0)) * m + SPREAD_BASE * m,
                     SLIP_CAP * m)) if m != 1.0 else slip_rate_from_participation(part)


def lookup_exec(lookup: dict, code: str, sig_int: int, exec_mode: str = "t1open"):
    """Return (base_price, exec_date, vol_day, amt_day, close_day, prev_close).

    base_price = T+1 open (t1open), same-day close (close/dayclose-15min),
      or same-day (high+low)/2 (mid).
    prev_close = previous trading row close before exec row (NaN if none).
    Missing -> (nan, NaT, nan, nan, nan, nan).
    """
    g = lookup.get(code)
    if g is None:
        return (np.nan, pd.NaT, np.nan, np.nan, np.nan, np.nan)
    di = g["dates_int"]
    if exec_mode in ("close", "dayclose-15min", "mid"):
        pos = np.searchsorted(di, sig_int, side="left")
        # need exact match on signal date
        if pos >= len(di) or int(di[pos]) != int(sig_int):
            return (np.nan, pd.NaT, np.nan, np.nan, np.nan, np.nan)
    else:
        pos = np.searchsorted(di, sig_int, side="right")
        if pos >= len(di):
            return (np.nan, pd.NaT, np.nan, np.nan, np.nan, np.nan)
    if exec_mode == "mid":
        hi, lo = float(g["high"][pos]), float(g["low"][pos])
        if np.isfinite(hi) and np.isfinite(lo):
            base = float((hi + lo) / 2.0)
        else:
            base = float(g["close"][pos])
    elif exec_mode in ("close", "dayclose-15min"):
        base = float(g["close"][pos])
    else:
        base = float(g["open"][pos])
    ed = pd.to_datetime(g["dates"][pos])
    vol = float(g["volume"][pos]) if np.isfinite(g["volume"][pos]) else np.nan
    amt = float(g["amount"][pos]) if np.isfinite(g["amount"][pos]) else np.nan
    close_day = float(g["close"][pos]) if np.isfinite(g["close"][pos]) else np.nan
    prev_close = float(g["close"][pos - 1]) if pos > 0 and np.isfinite(g["close"][pos - 1]) else np.nan
    return (base, ed, vol, amt, close_day, prev_close)


def participation_corrected(base_price: float, shares: int, vol_day: float,
                            amt_day: float, close_day: float) -> float:
    """Scale-corrected participation (see UNIT NOTE).

    nominal_trade = base_price*shares*ratio_day, ratio_day=amt/(vol*close_adj).
    participation = nominal_trade/amt = shares/vol*(base/close).
    Falls back to shares/vol when amt/close invalid; 0 when vol invalid.
    """
    try:
        if vol_day is None or not np.isfinite(vol_day) or vol_day <= 0:
            return 0.0
        if shares <= 0:
            return 0.0
        if (amt_day is not None and np.isfinite(amt_day) and amt_day > 0
                and close_day is not None and np.isfinite(close_day) and close_day > 0
                and np.isfinite(base_price) and base_price > 0):
            ratio_day = amt_day / (vol_day * close_day)
            if np.isfinite(ratio_day) and ratio_day > 0:
                nominal_trade = base_price * shares * ratio_day
                return float(nominal_trade / amt_day)
        return float(shares / vol_day)
    except Exception:  # noqa: BLE001 -- 参与度退化保底 0.0，收窄会改变成交行为
        return 0.0


def paper_curves(pred: pd.DataFrame, rb_dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Paper Q5 / market-benchmark NAV on the SAME rb_dates (engine.py caliber)."""
    grouped = {d: g for d, g in pred[pred["sig_date"].isin(cast(Any, rb_dates))].groupby("sig_date")}
    q5_gross, bench_gross, turns = [], [], []
    prev: set = set()
    for i, d in enumerate(rb_dates):
        g = grouped[d].copy()
        g["q"] = cast(Any, pd.qcut(g["score"], 5, labels=[1, 2, 3, 4, 5])).astype(int)
        q5 = g[g["q"] == 5]
        q5_gross.append(float(cast(float, q5["future_ret_5d"].mean())))
        bench_gross.append(float(cast(float, g["future_ret_5d"].mean())))
        cur = set(q5["code"].tolist())
        turns.append(1.0 if i == 0 else 1.0 - len(cur & prev) / max(len(cur), 1))
        prev = cur
    q5_gross = np.asarray(q5_gross)
    bench_gross = np.asarray(bench_gross)
    q5_costs = np.zeros_like(q5_gross)
    q5_costs[0] = 0.0003
    q5_costs[1:] = np.asarray(turns[1:]) * 0.0016
    bench_costs = np.zeros_like(bench_gross)
    bench_costs[0] = 0.0003
    nav_q5 = np.cumprod(1.0 + q5_gross - q5_costs)
    nav_b = np.cumprod(1.0 + bench_gross - bench_costs)
    return nav_q5, nav_b


def main() -> None:
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=500000)
    ap.add_argument("--topn", type=int, default=50)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pred", default="artifacts/pred_test.parquet")
    ap.add_argument("--train", default="data/train_data.parquet")
    ap.add_argument("--exec", dest="exec_mode",
                    choices=["t1open", "close", "dayclose-15min", "mid"],
                    default="t1open",
                    help="t1open=next trading open AFTER signal (tradable); "
                         "close=signal-day close same-bar (needs pre-close signal); "
                         "dayclose-15min=signal-day close +slip x1.5 (semi, needs EOD pipe); "
                         "mid=signal-day (H+L)/2 (semi, needs intraday pipe)")
    ap.add_argument("--freq", type=int, default=5,
                    help="rebalance every N signal dates (default 5 reproduces baseline)")
    ap.add_argument("--sell-buffer", dest="sell_buffer", type=int, default=0,
                    help="hold names ranked within topn+B (default 0 reproduces baseline)")
    ap.add_argument("--min-amount", dest="min_amount", type=float, default=0.0,
                    help="V3 BUY guardrail: skip candidates with exec-day amount < X "
                         "(nominal CNY; default 0 disables)")
    ap.add_argument("--max-participation", dest="max_participation", type=float, default=1.0,
                    help="V3 BUY guardrail: skip final BUY lots with participation > P "
                         "(default 1.0 disables; sells never skipped)")
    ap.add_argument("--min-edge", dest="min_edge", type=float, default=0.0,
                    help="OPT_EXEC2 fee-aware BUY filter: 0 disables. When >0, target "
                         "names in bottom 30%% of target rank with score < E are skipped "
                         "(counted in skipped_min_edge; e.g. 0.01)")
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "figs").mkdir(parents=True, exist_ok=True)

    capital = float(args.capital)
    topn = int(args.topn)
    exec_mode: str = args.exec_mode
    freq: int = int(args.freq)
    sell_buffer: int = int(args.sell_buffer)
    min_amount: float = float(args.min_amount)
    max_part: float = float(args.max_participation)
    min_edge: float = float(args.min_edge)
    assert freq >= 1 and topn >= 1 and sell_buffer >= 0
    assert min_amount >= 0 and max_part > 0 and min_edge >= 0

    pred = load_pred(args.pred)
    rb_dates = pd.DatetimeIndex(sorted(pred["sig_date"].unique()))[0::freq]
    n_rb = len(rb_dates)
    print(f"[1/5] pred rows={len(pred)} codes={pred['code'].nunique()} "
          f"dates={pred['sig_date'].nunique()} rebalances={n_rb} "
          f"[{cast(Any, rb_dates[0]).date()}..{cast(Any, rb_dates[-1]).date()}] "
           f"exec={exec_mode} freq={freq} topn={topn} sell_buffer={sell_buffer} "
            f"min_amount={min_amount} max_part={max_part} min_edge={min_edge} "
            f"({time.time()-t0:.1f}s)")

    codes = set(pred["code"].unique().tolist())
    mkt = load_market(args.train, cast(pd.Timestamp, pred["sig_date"].min()), codes)
    print(f"[2/5] market rows(>=min_date, in-universe)={len(mkt)} "
          f"trading={int((mkt['is_trading'] == True).sum())} ({time.time()-t0:.1f}s)")

    pred = attach_exec(pred, mkt, exec_mode=exec_mode)
    pred["sig_int"] = pred["sig_date"].to_numpy(dtype="datetime64[D]").astype("int64")
    exec_map: dict[tuple, tuple] = {}
    for r in cast(Any, pred.itertuples(index=False)):
        exec_map[(r.code, r.sig_int)] = (r.exec_price, r.exec_date)
    mt = cast(pd.DataFrame, mkt[mkt["is_trading"] == True])
    last_close = (
        mt.sort_values("mkt_date").groupby("code").tail(1).set_index("code")["close"].to_dict()
    )
    mkt_lookup = build_market_lookup(mkt, exec_mode=exec_mode)
    print(f"[2b/5] market lookup codes={len(mkt_lookup)} ({time.time()-t0:.1f}s)")

    targets: list[list[str]] = []
    allowed: list[set] = []
    grouped_sig = {d: g for d, g in pred.groupby("sig_date")}
    signal_sets: list[set] = []
    target_scores: list[dict] = []
    for d in rb_dates:
        g = grouped_sig[d].sort_values("score", ascending=False)
        top = g.head(topn)
        targets.append(top["code"].tolist())
        target_scores.append(dict(zip(top["code"].tolist(), top["score"].tolist())))
        allowed.append(set(g.head(topn + sell_buffer)["code"].tolist()))
        signal_sets.append(set(g["code"].tolist()))

    rb_ints = rb_dates.to_numpy(dtype="datetime64[D]").astype("int64")
    cash = round(capital, 2)
    holdings: dict[str, dict] = {}
    trades: list[dict] = []
    nav_post: list[float] = []
    cash_ratio: list[float] = []
    held_count: list[int] = []
    skipped_no_price = 0
    zero_lot = 0
    # V2 new counters
    forced_exits = 0
    realloc_passes_total = 0
    skipped_limit = 0
    locked = 0
    # V3 guardrail counters (BUY side only)
    skipped_min_amount = 0
    skipped_max_part = 0
    skipped_min_edge = 0
    slip_total = 0.0
    slip_spread_total = 0.0
    slip_impact_total = 0.0
    part_list: list[float] = []
    prev_target: set = set()
    turnovers: list[float] = []
    sell_pnls: list[float] = []
    hold_days: list[float] = []

    def mark_price(code: str, sig_int: int, fallback: float) -> float:
        p, _ = exec_map.get((code, sig_int), (np.nan, pd.NaT))
        return fallback if pd.isna(p) else float(p)

    for i, d in enumerate(rb_dates):
        sig_int = int(rb_ints[i])
        tgt = targets[i]
        tgt_set = set(tgt)
        allow_set = allowed[i]
        sig_set = signal_sets[i]
        turnovers.append(1.0 if i == 0 else 1.0 - len(tgt_set & prev_target) / max(len(tgt_set), 1))
        prev_target = tgt_set

        # --- sells first (buffered: sell only when outside topn+B) ---
        # S1 FIX: out-of-signal-domain holdings force-sold via market direct.
        for code in [c for c in list(holdings.keys()) if c not in allow_set]:
            in_signal = code in sig_set
            base_m, ed_m, vol_m, amt_m, close_m, prev_close_m = lookup_exec(
                mkt_lookup, code, sig_int, exec_mode=exec_mode)
            if pd.isna(base_m):
                # cannot sell: no market row (halt/delist/tail).
                # Simple-version locked accounting: limit-down missing counts as locked;
                # other missing-price sells also counted as locked to avoid silent zombies.
                locked += 1
                continue
            base_m = float(base_m)
            # SELL limit check (simple): limit-down still sells when price exists.
            # Only missing-price limit-down would have hit `locked` above.
            if prev_close_m is not None and np.isfinite(prev_close_m) and prev_close_m > 0:
                pct = limit_pct(code)
                limit_down = prev_close_m * (1 - pct)
                # touch detection (informational; execution proceeds normally)
                _is_limit_down = base_m <= limit_down * 1.001
            h = holdings.pop(code)
            part = participation_corrected(base_m, h["shares"], vol_m, amt_m, close_m)
            sr = slip_eff(part, exec_mode)
            slip_cost = sr * base_m * h["shares"]
            exec_price = base_m * (1 - sr)
            amount = exec_price * h["shares"]
            fee = fee_sell(amount)
            cash = round(cash + amount - fee, 2)
            buy_cost = h["buy_price"] * h["shares"] + h["buy_fee"]
            sell_pnls.append((amount - fee) - buy_cost)
            exec_d = pd.to_datetime(cast(Any, ed_m))
            hold_days.append((exec_d - h["buy_exec"]).days)
            reason = "drop_out" if in_signal else "forced_exit"
            if not in_signal:
                forced_exits += 1
            m = slip_mult_for_exec(exec_mode)
            slip_total += float(slip_cost)
            slip_spread_total += float(SPREAD_BASE * m * base_m * h["shares"])
            slip_impact_total += float(max(sr - SPREAD_BASE * m, 0.0) * base_m * h["shares"])
            part_list.append(float(part))
            trades.append({"date": exec_d.date().isoformat(), "code": code, "side": "SELL",
                           "price": round(float(exec_price), 4), "shares": h["shares"],
                           "amount": round(float(amount), 2), "fee": round(float(fee), 2),
                           "cash_after": cash, "reason": reason,
                           "slip_cost": round(float(slip_cost), 2),
                           "slip_rate": round(float(sr), 6),
                           "participation": round(float(part), 6)})

        # --- buys ---
        new_names = [c for c in tgt if c not in holdings]
        # OPT_EXEC2 min-edge (BUY only): bottom-30% target rank + score<E -> skip.
        if min_edge > 0:
            cutoff_rank = int(len(tgt) * 0.7)
            rank_of = {c: k for k, c in enumerate(tgt)}
            scmap = target_scores[i]
            kept = []
            for c in new_names:
                r = rank_of.get(c, 0)
                s = float(scmap.get(c, float("inf")))
                if r >= cutoff_rank and s < min_edge:
                    skipped_min_edge += 1
                    continue
                kept.append(c)
            new_names = kept
        # resolve market-direct exec for each candidate (base + volume/amount/prev_close)
        priced = []
        for c in new_names:
            base_c, ed_c, vol_c, amt_c, close_c, prev_close_c = lookup_exec(
                mkt_lookup, c, sig_int, exec_mode=exec_mode)
            if pd.isna(base_c):
                skipped_no_price += 1
                continue
            base_c = float(base_c)
            # V3 GUARDRAIL 1 (BUY only): exec-day amount < min_amount -> drop
            # before allocation. NaN amount kept (cannot verify illiquidity).
            if min_amount > 0 and np.isfinite(amt_c) and amt_c < min_amount:
                skipped_min_amount += 1
                continue
            # BUY limit-up skip (simple): open >= limit_up*0.999 -> skip, cash stays.
            if (prev_close_c is not None and np.isfinite(prev_close_c) and prev_close_c > 0):
                pct = limit_pct(c)
                limit_up = prev_close_c * (1 + pct)
                if base_c >= limit_up * 0.999:
                    skipped_limit += 1
                    continue
            priced.append((c, base_c, pd.to_datetime(cast(Any, ed_c)), vol_c, amt_c, close_c))
        n_new = len(priced)
        if n_new > 0:
            cash_before_buys = cash
            target_eq = cash_before_buys / n_new
            budget = target_eq

            def total_outlay(base_p: float, sh: int, vol_d, amt_d, close_d):
                if sh <= 0:
                    return 0.0, 0.0, 0.0, 0.0
                part = participation_corrected(base_p, sh, vol_d, amt_d, close_d)
                sr = slip_eff(part, exec_mode)
                slip_c = sr * base_p * sh
                px = base_p * (1 + sr)
                amt = px * sh
                fee = fee_buy(amt)
                return px, amt, fee, slip_c

            # first pass: equal-weight floor to lots
            shares_map: dict[str, int] = {}
            meta: dict[str, tuple] = {}
            for (c, base_p, ed, vol_d, amt_d, close_d) in priced:
                meta[c] = (base_p, ed, vol_d, amt_d, close_d)
                sh0 = int(budget // base_p // 100 * 100) if base_p > 0 else 0
                shares_map[c] = sh0
            # deduct first-pass costs with slip included (affordability-checked)
            # process in target rank order; unaffordable first-pass lots -> 0 (realloc may retry)
            for (c, base_p, ed, vol_d, amt_d, close_d) in priced:
                sh0 = shares_map[c]
                if sh0 <= 0:
                    continue
                px, amt, fee, slip_c = total_outlay(base_p, sh0, vol_d, amt_d, close_d)
                outlay = amt + fee
                if cash >= outlay:
                    cash = round(cash - outlay, 2)
                else:
                    # cannot afford even first-pass size (slip-inclusive): reset to 0,
                    # leave for realloc loop (likely still unaffordable -> zero_lot).
                    shares_map[c] = 0
            # iterative reallocation over underweight names
            passes = 0
            while True:
                gap = []
                for (c, base_p, ed, vol_d, amt_d, close_d) in priced:
                    cur = shares_map[c]
                    cur_base_amt = cur * base_p
                    if cur_base_amt < target_eq - 1e-9:
                        gap.append((target_eq - cur_base_amt, c, base_p, ed, vol_d, amt_d, close_d))
                if not gap:
                    break
                # cheapest incremental lot delta across gap (slip-inclusive)
                min_delta = None
                for (_, c, base_p, ed, vol_d, amt_d, close_d) in gap:
                    cur = shares_map[c]
                    new = cur + 100
                    _px_n, amt_n, fee_n, _ = total_outlay(base_p, new, vol_d, amt_d, close_d)
                    _px_o, amt_o, fee_o, _ = total_outlay(base_p, cur, vol_d, amt_d, close_d)
                    delta = (amt_n + fee_n) - (amt_o + fee_o)
                    if min_delta is None or delta < min_delta:
                        min_delta = delta
                if min_delta is None or cash < min_delta:
                    break
                gap.sort(key=lambda x: -x[0])  # largest underweight first
                progressed = False
                for (_, c, base_p, ed, vol_d, amt_d, close_d) in gap:
                    cur = shares_map[c]
                    new = cur + 100
                    _px_n, amt_n, fee_n, _ = total_outlay(base_p, new, vol_d, amt_d, close_d)
                    _px_o, amt_o, fee_o, _ = total_outlay(base_p, cur, vol_d, amt_d, close_d)
                    delta = (amt_n + fee_n) - (amt_o + fee_o)
                    if cash >= delta:
                        cash = round(cash - delta, 2)
                        shares_map[c] = new
                        progressed = True
                if progressed:
                    passes += 1
                    if passes > 1000:
                        break
                else:
                    break
            realloc_passes_total += passes
            # commit: one BUY trade per name with final shares (slip-inclusive).
            # Sequential cash_after replay for an exact cash chain (v1 semantics):
            # running starts at cash_before_buys, subtract each final outlay in
            # target-rank order; final running overwrites cash (differs from the
            # incremental-deduction path only by cent-rounding order).
            running = cash_before_buys
            pending_buys = []
            for (c, base_p, ed, vol_d, amt_d, close_d) in priced:
                sh = shares_map[c]
                if sh <= 0:
                    zero_lot += 1
                    continue
                part = participation_corrected(base_p, sh, vol_d, amt_d, close_d)
                # V3 GUARDRAIL 2 (BUY only): final-lot participation > P ->
                # skip this ticket, cash stays (not reallocated this round).
                if np.isfinite(part) and part > max_part:
                    skipped_max_part += 1
                    continue
                sr = slip_eff(part, exec_mode)
                slip_c = sr * base_p * sh
                px = base_p * (1 + sr)
                amt = px * sh
                fee_fin = fee_buy(amt)
                outlay = amt + fee_fin
                running = round(running - outlay, 2)
                pending_buys.append((c, base_p, ed, sh, part, sr, slip_c, px, amt, fee_fin, running))
            cash = running
            for (c, base_p, ed, sh, part, sr, slip_c, px, amt, fee_fin, cash_after) in pending_buys:
                holdings[c] = {"shares": sh, "buy_price": float(px), "buy_fee": float(fee_fin),
                               "buy_exec": ed, "buy_sig": pd.to_datetime(d)}
                m = slip_mult_for_exec(exec_mode)
                slip_total += float(slip_c)
                slip_spread_total += float(SPREAD_BASE * m * base_p * sh)
                slip_impact_total += float(max(sr - SPREAD_BASE * m, 0.0) * base_p * sh)
                part_list.append(float(part))
                trades.append({"date": ed.date().isoformat(), "code": c, "side": "BUY",
                               "price": round(float(px), 4), "shares": sh,
                               "amount": round(float(amt), 2), "fee": round(float(fee_fin), 2),
                               "cash_after": cash_after, "reason": "rebalance_in",
                               "slip_cost": round(float(slip_c), 2),
                               "slip_rate": round(float(sr), 6),
                               "participation": round(float(part), 6)})
        # post-trade NAV at T+1 exec marks (base/mid marks like v1; slip stays sunk in cash)
        nav = cash + sum(h["shares"] * mark_price(c, sig_int, h["buy_price"])
                         for c, h in holdings.items())
        nav_post.append(round(nav, 2))
        cash_ratio.append(round(cash / nav, 6) if nav > 0 else 1.0)
        held_count.append(len(holdings))

    def final_mark(code: str, h: dict) -> float:
        v = last_close.get(code, np.nan)
        return h["buy_price"] if pd.isna(v) else float(v)

    final_hold_val = sum(h["shares"] * final_mark(c, h) for c, h in holdings.items())
    final_nav = round(cash + final_hold_val, 2)

    nav_arr = np.asarray(nav_post, dtype=float)
    rets = nav_arr[1:] / nav_arr[:-1] - 1.0 if len(nav_arr) > 1 else np.asarray([])
    total = final_nav / capital - 1.0
    n_days = n_rb * freq
    fee_sum = float(sum(t["fee"] for t in trades))
    slip_sum = float(slip_total)
    res = {
        "initial": round(capital, 2),
        "final": final_nav,
        "total": round(float(total), 6),
        "annual": round(float(annualize(total, n_days)), 6),
        "sharpe": round(float(period_sharpe(rets, hold=freq)), 4),
        "maxdd": round(float(max_drawdown(nav_arr / capital)), 6),
        "n_trades": len(trades),
        "n_rebalances": n_rb,
        "fee_total": round(fee_sum, 2),
        "fee_drag": round(fee_sum / capital, 6),
        "win_rate_hold": round(float(np.mean([p > 0 for p in sell_pnls])) if sell_pnls else 0.0, 4),
        "avg_hold_days": round(float(np.mean(hold_days)) if hold_days else 0.0, 2),
        "skipped_no_price": int(skipped_no_price),
        "turnover": round(float(np.mean(turnovers[1:])) if n_rb > 1 else 0.0, 6),
        "exec": exec_mode,
        "freq": int(freq),
        "topn": int(topn),
        "sell_buffer": int(sell_buffer),
        "annual_days_basis": n_days,
        "first_signal": cast(Any, rb_dates[0]).date().isoformat(),
        "last_signal": cast(Any, rb_dates[-1]).date().isoformat(),
        "n_sells_completed": len(sell_pnls),
        "zero_lot_skips": int(zero_lot),
        "open_positions_end": len(holdings),
        "cash_end": cash,
        "avg_cash_ratio": round(float(np.mean(cash_ratio)) if cash_ratio else 0.0, 4),
        "avg_held_count": round(float(np.mean(held_count)) if held_count else 0.0, 2),
        # V2 extras
        "forced_exits": int(forced_exits),
        "realloc_passes": int(realloc_passes_total),
        "skipped_limit": int(skipped_limit),
        "locked": int(locked),
        "slip_total": round(slip_sum, 2),
        "slip_drag": round(slip_sum / capital, 6),
        "slip_spread": round(float(slip_spread_total), 2),
        "slip_impact": round(float(slip_impact_total), 2),
        "avg_participation": round(float(np.mean(part_list)) if part_list else 0.0, 6),
        "max_participation": round(float(np.max(part_list)) if part_list else 0.0, 6),
        "min_amount": float(min_amount),
        "max_participation_param": float(max_part),
        "skipped_min_amount": int(skipped_min_amount),
        "skipped_max_participation": int(skipped_max_part),
        "min_edge": float(min_edge),
        "skipped_min_edge": int(skipped_min_edge),
        "slip_mult": float(slip_mult_for_exec(exec_mode)),
        "slip_cap": float(slip_cap_for_exec(exec_mode)),
        "final_cash_ratio": round(float(cash / final_nav), 6) if final_nav > 0 else 1.0,
        "engine": "account_engine_v3",
    }
    with open(outdir / "account.json", "w") as f:
        json.dump(res, f, indent=2)
    tdf = pd.DataFrame(trades, columns=["date", "code", "side", "price", "shares",
                                        "amount", "fee", "cash_after", "reason",
                                        "slip_cost", "slip_rate", "participation"])
    tdf.to_csv(outdir / "trades.csv", index=False)

    nav_q5, nav_b = paper_curves(pred, rb_dates)
    x = np.arange(1, n_rb + 1)
    plt.figure(figsize=(10, 5.5))
    _labels = {"t1open": "T+1 open (tradable)",
               "close": "signal-day CLOSE same-bar (needs pre-close signal!)",
               "dayclose-15min": "signal-day CLOSE +slip x1.5 (semi, needs EOD pipe)",
               "mid": "signal-day (H+L)/2 (semi, needs intraday pipe)"}
    exec_label = _labels.get(exec_mode, exec_mode)
    plt.plot(x, nav_arr / capital, label=f"Account V3 ({exec_label}, lots, fees, slip)")
    plt.plot(x, nav_q5, label="Paper Q5 (gross quintile, paper fees)")
    plt.plot(x, nav_b, label="Market EW bench (paper)")
    plt.xlabel(f"Rebalance index ({freq} signal-days each)")
    plt.ylabel("NAV (start=1)")
    plt.title(f"Account V3 equity vs paper Q5 vs benchmark [{exec_label} | "
              f"freq={freq} topn={topn} buf={sell_buffer} min_amt={min_amount:g} max_p={max_part:g} edge={min_edge:g}]")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    fig_path = outdir / "figs" / "account_equity.png"
    plt.savefig(fig_path, dpi=120)
    plt.close()

    if outdir.as_posix().endswith("artifacts/account"):
        root = outdir.parent.parent
        (root / "artifacts" / "trades.csv").write_bytes((outdir / "trades.csv").read_bytes())
        (root / "figs").mkdir(exist_ok=True)
        (root / "figs" / "account_equity.png").write_bytes(fig_path.read_bytes())
        print("copies: artifacts/trades.csv, figs/account_equity.png")

    first_buys = [t for t in trades if t["side"] == "BUY"][:topn]
    print(f"\nFirst rebalance {cast(Any, rb_dates[0]).date()} signal -> exec sample: "
          f"{len(first_buys)} buys (target top{topn})")
    print(f"{'code':<10}{'price':>10}{'shares':>8}{'amount':>12}{'fee':>8}  exec_date")
    for t in first_buys:
        print(f"{t['code']:<10}{t['price']:>10.4f}{t['shares']:>8d}"
              f"{t['amount']:>12.2f}{t['fee']:>8.2f}  {t['date']}")

    elapsed = time.time() - t0
    print(f"\n{json.dumps(res, indent=2)}")
    print(f"done in {elapsed:.1f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
