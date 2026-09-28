"""Realistic account-level backtest (T+1, lots, per-trade fees, cash accounting).

Contract:
  - Signal: artifacts/pred_test.parquet [code, kline_time, score, ...], TEST 2024~2025.
  - Market data: data/train_data.parquet projected cols
    (code, kline_time, open, close, is_trading), read in pyarrow batches.
  - Execution price = own next trading day's open AFTER the signal date
    (per-code searchsorted == grouped merge_asof semantics). If a selected
    name has no later trading row (halt/delist/tail) it is skipped, cash stays,
    counted in skipped_no_price.
  - Rebalance dates = sorted unique signal dates, every 5th starting at 0
    (literal dates[0::5]; 421 dates -> 85 rebalances; paper engine.py used
    dates[:n*5:5] = 84, difference disclosed in outputs/plots).
  - Each rebalance: target = top-N by score; sell held names not in target
    first (T+1 open), then buy new entrants with equal weight
    (cash_after_sells / n_new, floored to 100-share lots, zero-share dropped).
  - Cash rounded to cents after every trade.
  - Fees per trade: commission 0.025% both sides (min 5 CNY per ticket),
    stamp duty 0.05% sell-only, transfer fee 0.001% both sides.

Outputs under <out>/: account.json, trades.csv, figs/account_equity.png
(plus spec-literal copies: artifacts/trades.csv and figs/account_equity.png
when <out> is artifacts/account/).

Usage:
  python account_engine.py --capital 500000 --topn 50 --out artifacts/account/
  python account_engine.py --capital 2000000 --topn 50 --exec close --freq 10 \
      --sell-buffer 50 --out artifacts/opt_exec/...

Notes:
  - Defaults (--exec t1open --freq 5 --sell-buffer 0 --capital 500000 --topn 50)
    reproduce the original 50w baseline (annual diff must be <=0.1pp).
  - --exec close = signal-day close, same-bar: honest label
    "needs pre-close signal capability, live requires intraday pipeline".
    t1open is the only fully tradable (T+1) caliber.
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


def load_pred(pred_path: str) -> pd.DataFrame:
    df = pd.read_parquet(pred_path, columns=["code", "kline_time", "score", "future_ret_5d"])
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    # join key hygiene: date normalized to midnight (spec: int/date before merge)
    df["sig_date"] = df["kline_time"].dt.normalize()
    return df


def load_market(train_path: str, min_date: pd.Timestamp, codes: set) -> pd.DataFrame:
    """Chunked pyarrow projection; keep rows >= min_date and codes in universe."""
    pf = pq.ParquetFile(train_path)
    parts: list[pd.DataFrame] = []
    for batch in pf.iter_batches(
        columns=["code", "kline_time", "open", "close", "is_trading"], batch_size=500_000
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
    """Execution price map.

    t1open: per-code next-trading-open AFTER signal date
        (grouped merge_asof equivalent). Tradable, T+1交割.
    close: signal-day close itself (same-bar). Requires pre-close signal
        capability; live trading needs intraday pipeline. Honestly labeled.
    Returns pred copy with exec_price / exec_date (NaT/NaN when no row).
    """
    pred = pred.copy()
    if exec_mode == "close":
        t = cast(pd.DataFrame, mkt[mkt["is_trading"] == True].copy())
        t["mkt_int"] = t["mkt_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        close_map: dict[tuple, tuple] = {}
        # keep last close per (code, date) if duplicates
        for r in cast(Any, t.itertuples(index=False)):
            close_map[(r.code, int(r.mkt_int))] = (float(r.close), r.mkt_date)
        pred_int = pred["sig_date"].to_numpy(dtype="datetime64[D]").astype("int64")
        out_price = np.full(len(pred), np.nan)
        out_date = np.full(len(pred), np.datetime64("NaT", "D"))
        for i, (c, s) in enumerate(zip(pred["code"].to_numpy(), pred_int)):
            hit = close_map.get((c, int(s)))
            if hit is not None:
                out_price[i] = hit[0]
                out_date[i] = np.datetime64(pd.to_datetime(hit[1]).date())
        pred["exec_price"] = out_price
        pred["exec_date"] = pd.to_datetime(out_date)
        return pred
    # default t1open path (original semantics, unchanged)
    t = cast(pd.DataFrame, mkt[mkt["is_trading"] == True].copy())
    t = t.sort_values(["code", "mkt_date"])
    # per-code sorted arrays
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


def paper_curves(pred: pd.DataFrame, rb_dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Paper Q5 / market-benchmark NAV on the SAME 85 rb_dates (engine.py caliber).

    Gross per period = mean future_ret_5d of sleeve; costs: inception 0.03%,
    then turnover*(0.03%+0.13%) for Q5, buy-hold for bench. Mirrors engine.py.
    """
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
    ap.add_argument("--exec", dest="exec_mode", choices=["t1open", "close"],
                    default="t1open",
                    help="t1open=next trading open AFTER signal (tradable); "
                         "close=signal-day close same-bar (needs pre-close signal, "
                         "live requires intraday pipeline)")
    ap.add_argument("--freq", type=int, default=5,
                    help="rebalance every N signal dates (default 5 reproduces baseline)")
    ap.add_argument("--sell-buffer", dest="sell_buffer", type=int, default=0,
                    help="hold names ranked within topn+B (default 0 reproduces baseline)")
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "figs").mkdir(parents=True, exist_ok=True)

    capital = float(args.capital)
    topn = int(args.topn)
    exec_mode: str = args.exec_mode
    freq: int = int(args.freq)
    sell_buffer: int = int(args.sell_buffer)
    assert freq >= 1 and topn >= 1 and sell_buffer >= 0

    pred = load_pred(args.pred)
    rb_dates = pd.DatetimeIndex(sorted(pred["sig_date"].unique()))[0::freq]
    n_rb = len(rb_dates)
    print(f"[1/5] pred rows={len(pred)} codes={pred['code'].nunique()} "
          f"dates={pred['sig_date'].nunique()} rebalances={n_rb} "
          f"[{cast(Any, rb_dates[0]).date()}..{cast(Any, rb_dates[-1]).date()}] "
          f"exec={exec_mode} freq={freq} topn={topn} sell_buffer={sell_buffer} "
          f"({time.time()-t0:.1f}s)")

    codes = set(pred["code"].unique().tolist())
    mkt = load_market(args.train, cast(pd.Timestamp, pred["sig_date"].min()), codes)
    print(f"[2/5] market rows(>=min_date, in-universe)={len(mkt)} "
          f"trading={int((mkt['is_trading'] == True).sum())} ({time.time()-t0:.1f}s)")

    pred = attach_exec(pred, mkt, exec_mode=exec_mode)
    # fast per-(code,sig) exec lookup
    pred["sig_int"] = pred["sig_date"].to_numpy(dtype="datetime64[D]").astype("int64")
    exec_map: dict[tuple, tuple] = {}
    for r in cast(Any, pred.itertuples(index=False)):
        exec_map[(r.code, r.sig_int)] = (r.exec_price, r.exec_date)
    # last close per code for final mark: last is_trading row only (tail rows
    # can be non-trading with NaN close); fallback chain at valuation time.
    mt = cast(pd.DataFrame, mkt[mkt["is_trading"] == True])
    last_close = (
        mt.sort_values("mkt_date").groupby("code").tail(1).set_index("code")["close"].to_dict()
    )

    # top-N buy target + top-(N+B) hold-allowed per rebalance (rank once per date)
    # B=0 reduces exactly to original (sell held not in target).
    targets: list[list[str]] = []
    allowed: list[set] = []
    grouped_sig = {d: g for d, g in pred.groupby("sig_date")}
    for d in rb_dates:
        g = grouped_sig[d].sort_values("score", ascending=False)
        targets.append(g.head(topn)["code"].tolist())
        allowed.append(set(g.head(topn + sell_buffer)["code"].tolist()))

    rb_ints = rb_dates.to_numpy(dtype="datetime64[D]").astype("int64")
    cash = round(capital, 2)
    holdings: dict[str, dict] = {}  # code -> shares, buy_price, buy_fee, buy_exec, buy_sig
    trades: list[dict] = []
    nav_post: list[float] = []  # post-trade NAV at exec marks per rebalance
    cash_ratio: list[float] = []  # cash / NAV post-trade per rebalance
    held_count: list[int] = []
    skipped_no_price = 0
    zero_lot = 0
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
        turnovers.append(1.0 if i == 0 else 1.0 - len(tgt_set & prev_target) / max(len(tgt_set), 1))
        prev_target = tgt_set

        # --- sells first (buffered: sell only when outside topn+B) ---
        for code in [c for c in list(holdings.keys()) if c not in allow_set]:
            p, ed = exec_map.get((code, sig_int), (np.nan, pd.NaT))
            if pd.isna(p):  # halted/delisted: cannot sell, keep holding
                continue
            h = holdings.pop(code)
            price = float(p)
            amount = price * h["shares"]
            fee = fee_sell(amount)
            cash = round(cash + amount - fee, 2)
            buy_cost = h["buy_price"] * h["shares"] + h["buy_fee"]
            sell_pnls.append((amount - fee) - buy_cost)
            exec_d = pd.to_datetime(ed)
            hold_days.append((exec_d - h["buy_exec"]).days)
            trades.append({"date": exec_d.date().isoformat(), "code": code, "side": "SELL",
                           "price": round(price, 4), "shares": h["shares"],
                           "amount": round(amount, 2), "fee": round(fee, 2),
                           "cash_after": cash, "reason": "drop_out"})

        # --- buys ---
        new_names = [c for c in tgt if c not in holdings]
        priced = []
        for c in new_names:
            p, ed = exec_map.get((c, sig_int), (np.nan, pd.NaT))
            if pd.isna(p):
                skipped_no_price += 1
                continue
            priced.append((c, float(p), pd.to_datetime(ed)))
        n_new = len(priced)
        if n_new > 0:
            budget = cash / n_new
            for c, price, ed in priced:
                shares = int(budget // price // 100 * 100)
                if shares <= 0:
                    zero_lot += 1
                    continue
                amount = price * shares
                fee = fee_buy(amount)
                cash = round(cash - amount - fee, 2)
                holdings[c] = {"shares": shares, "buy_price": price, "buy_fee": fee,
                               "buy_exec": ed, "buy_sig": pd.to_datetime(d)}
                trades.append({"date": ed.date().isoformat(), "code": c, "side": "BUY",
                               "price": round(price, 4), "shares": shares,
                               "amount": round(amount, 2), "fee": round(fee, 2),
                               "cash_after": cash, "reason": "rebalance_in"})
        # post-trade NAV at T+1 exec marks
        nav = cash + sum(h["shares"] * mark_price(c, sig_int, h["buy_price"])
                         for c, h in holdings.items())
        nav_post.append(round(nav, 2))
        cash_ratio.append(round(cash / nav, 6) if nav > 0 else 1.0)
        held_count.append(len(holdings))

    # final mark at last available closes (account statement convention)
    def final_mark(code: str, h: dict) -> float:
        v = last_close.get(code, np.nan)
        return h["buy_price"] if pd.isna(v) else float(v)

    final_hold_val = sum(h["shares"] * final_mark(c, h) for c, h in holdings.items())
    final_nav = round(cash + final_hold_val, 2)

    nav_arr = np.asarray(nav_post, dtype=float)
    rets = nav_arr[1:] / nav_arr[:-1] - 1.0 if len(nav_arr) > 1 else np.asarray([])
    total = final_nav / capital - 1.0
    n_days = n_rb * freq
    res = {
        "initial": round(capital, 2),
        "final": final_nav,
        "total": round(float(total), 6),
        "annual": round(float(annualize(total, n_days)), 6),
        "sharpe": round(float(period_sharpe(rets, hold=freq)), 4),
        "maxdd": round(float(max_drawdown(nav_arr / capital)), 6),
        "n_trades": len(trades),
        "n_rebalances": n_rb,
        "fee_total": round(float(sum(t["fee"] for t in trades)), 2),
        "fee_drag": round(float(sum(t["fee"] for t in trades)) / capital, 6),
        "win_rate_hold": round(float(np.mean([p > 0 for p in sell_pnls])) if sell_pnls else 0.0, 4),
        "avg_hold_days": round(float(np.mean(hold_days)) if hold_days else 0.0, 2),
        "skipped_no_price": int(skipped_no_price),
        "turnover": round(float(np.mean(turnovers[1:])) if n_rb > 1 else 0.0, 6),
        # execution-opt config (for grid attribution)
        "exec": exec_mode,
        "freq": int(freq),
        "topn": int(topn),
        "sell_buffer": int(sell_buffer),
        # audit extras
        "annual_days_basis": n_days,
        "first_signal": cast(Any, rb_dates[0]).date().isoformat(),
        "last_signal": cast(Any, rb_dates[-1]).date().isoformat(),
        "n_sells_completed": len(sell_pnls),
        "zero_lot_skips": int(zero_lot),
        "open_positions_end": len(holdings),
        "cash_end": cash,
        "avg_cash_ratio": round(float(np.mean(cash_ratio)) if cash_ratio else 0.0, 4),
        "avg_held_count": round(float(np.mean(held_count)) if held_count else 0.0, 2),
    }
    with open(outdir / "account.json", "w") as f:
        json.dump(res, f, indent=2)
    tdf = pd.DataFrame(trades, columns=["date", "code", "side", "price", "shares",
                                        "amount", "fee", "cash_after", "reason"])
    tdf.to_csv(outdir / "trades.csv", index=False)

    # --- figure: account vs paper Q5 vs bench (same rb_dates) ---
    nav_q5, nav_b = paper_curves(pred, rb_dates)
    x = np.arange(1, n_rb + 1)
    plt.figure(figsize=(10, 5.5))
    exec_label = "T+1 open (tradable)" if exec_mode == "t1open" else \
        "signal-day CLOSE same-bar (needs pre-close signal!)"
    plt.plot(x, nav_arr / capital, label=f"Account ({exec_label}, lots, fees)")
    plt.plot(x, nav_q5, label="Paper Q5 (gross quintile, paper fees)")
    plt.plot(x, nav_b, label="Market EW bench (paper)")
    plt.xlabel(f"Rebalance index ({freq} signal-days each)")
    plt.ylabel("NAV (start=1)")
    plt.title(f"Account equity vs paper Q5 vs benchmark [{exec_label} | "
              f"freq={freq} topn={topn} buf={sell_buffer}]")
    plt.legend(fontsize=8)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    fig_path = outdir / "figs" / "account_equity.png"
    plt.savefig(fig_path, dpi=120)
    plt.close()

    # spec-literal copies when out == artifacts/account
    if outdir.as_posix().endswith("artifacts/account"):
        root = outdir.parent.parent
        (root / "artifacts" / "trades.csv").write_bytes((outdir / "trades.csv").read_bytes())
        (root / "figs").mkdir(exist_ok=True)
        (root / "figs" / "account_equity.png").write_bytes(fig_path.read_bytes())
        print("copies: artifacts/trades.csv, figs/account_equity.png")

    # --- first-rebalance buy list (decision sample) ---
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
