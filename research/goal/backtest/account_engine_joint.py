"""Sparse-episode acceptance wrapper around the unmodified V6 account engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
V6 = ROOT / "backtest" / "account_engine_v6.py"


def append_final_nav_metrics(account: dict, nav_points: list[float], final_nav: float) -> dict:
    nav = [float(value) for value in nav_points] + [float(final_nav)]
    peaks = np.maximum.accumulate(nav)
    drawdowns = 1.0 - np.asarray(nav) / peaks
    returns = np.diff(nav) / np.asarray(nav[:-1])
    account["nav_points"] = [round(value, 2) for value in nav]
    account["maxdd"] = round(float(drawdowns.max()), 6)
    account["sharpe"] = round(float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0, 6)
    account["final_mark_included"] = True
    return account


def postprocess_account(account: dict, nav_points: list[float], final_nav: float, locked_final: list, trade_sha256: str, market_cutoff: str) -> dict:
    result = dict(account)
    result["final"] = round(float(final_nav), 2)
    result["total"] = round(float(final_nav) / float(result["initial"]) - 1.0, 6)
    result["annual"] = round(float((1.0 + result["total"]) ** (252.0 / result["annual_days_basis"]) - 1.0), 6)
    append_final_nav_metrics(result, nav_points, final_nav)
    result["locked_final"] = locked_final
    result["locked_final_count"] = len(locked_final)
    result["source_trade_csv_sha256"] = trade_sha256
    result["market_cutoff"] = market_cutoff
    result["postprocessed_no_new_test_run"] = True
    return result


def create_test_guard(path: Path, command: list[str], input_sha256: str) -> None:
    """Atomically reserve the single corrected TEST invocation."""
    if path.exists():
        raise FileExistsError(f"TEST guard already exists: {path}")
    payload = {"command": command, "timestamp_utc": datetime.now(timezone.utc).isoformat(), "input_sha256": input_sha256}
    try:
        with path.open("x", encoding="ascii") as target:
            json.dump(payload, target, indent=2)
    except FileExistsError:
        raise FileExistsError(f"TEST guard already exists: {path}") from None


def final_liquidation(holdings: dict, cash: float, final_rows: dict, final_date: pd.Timestamp, last_marks=None) -> dict:
    """Sell all remaining lots at final episode sell-date open with V6 costs."""
    from backtest.account_engine_v6 import fee_sell, participation_corrected, slip_eff

    trades, locked_final, fee_total, slip_total = [], [], 0.0, 0.0
    last_marks = last_marks or {}
    for code, holding in list(holdings.items()):
        row = final_rows.get(code)
        if row is None or not np.isfinite(row["open"]) or row["open"] <= 0:
            mark = last_marks.get(code)
            if mark is None or pd.Timestamp(mark["date"]) > pd.Timestamp(final_date) or not np.isfinite(mark["close"]):
                raise ValueError(f"missing final liquidation open and prior close for {code}")
            value = round(int(holding["shares"]) * float(mark["close"]), 2)
            locked_final.append({"code": code, "shares": int(holding["shares"]), "last_mark_date": pd.Timestamp(mark["date"]).date().isoformat(), "last_mark_price": float(mark["close"]), "value": value})
            continue
        shares, base = int(holding["shares"]), float(row["open"])
        part = participation_corrected(base, shares, row["volume"], row["amount"], row["close"])
        rate = slip_eff(part, "t1open")
        price = base * (1.0 - rate)
        amount, fee = price * shares, fee_sell(price * shares)
        cash = round(cash + amount - fee, 2)
        fee_total += fee
        slip_total += rate * base * shares
        trades.append({"date": pd.Timestamp(final_date).date().isoformat(), "code": code, "side": "SELL", "price": round(price, 4), "shares": shares, "amount": round(amount, 2), "fee": round(fee, 2), "cash_after": cash, "reason": "final_liquidation", "slip_cost": round(rate * base * shares, 2), "slip_rate": round(rate, 6), "participation": round(part, 6)})
    return {"cash": cash, "trades": trades, "locked_final": locked_final, "fee_total": fee_total, "slip_total": slip_total}


def annual_days_basis(pred_path: Path, market_path: Path) -> int:
    """Infer held trading days from actual sparse signal-date spacing."""
    signal_dates = pd.DatetimeIndex(sorted(pd.read_parquet(pred_path, columns=["kline_time"])["kline_time"].unique()))
    if len(signal_dates) < 2:
        raise ValueError("sparse joint acceptance requires at least two signal dates")
    market_dates = pd.DatetimeIndex(sorted(pd.read_parquet(market_path, columns=["kline_time"])["kline_time"].unique()))
    positions = market_dates.get_indexer(signal_dates)
    if (positions < 0).any():
        raise ValueError("prediction signal dates are absent from market calendar")
    intervals = np.diff(positions)
    if (intervals <= 0).any():
        raise ValueError("prediction signal dates must be strictly increasing")
    # Last episode has the same predeclared holding horizon as observed gaps.
    return int(intervals.sum() + int(np.rint(np.median(intervals))))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sparse joint policy acceptance through V6")
    parser.add_argument("--pred", required=True, type=Path)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--capital", type=float, default=2_000_000)
    parser.add_argument("--topn", type=int, default=100)
    parser.add_argument("--sell-buffer", type=int, default=200)
    parser.add_argument("--min-edge", type=float, default=0.0)
    parser.add_argument("--exec-cache", default="artifacts/exec_cache")
    parser.add_argument("--final-sell-date", required=True, type=pd.Timestamp)
    parser.add_argument("--allow-test-once", action="store_true")
    parser.add_argument("--test-guard", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    command_text = sys.argv[:]
    input_hash = hashlib.sha256(args.pred.read_bytes()).hexdigest()
    if args.test_guard is not None:
        if not args.allow_test_once:
            raise PermissionError("TEST requires explicit --allow-test-once")
        create_test_guard(args.test_guard, command_text, input_hash)
    elif args.allow_test_once:
        raise ValueError("--allow-test-once requires --test-guard")
    basis = annual_days_basis(args.pred, args.train)
    command = [
        sys.executable, str(V6), "--pred", str(args.pred), "--train", str(args.train),
        "--out", str(args.out / "v6_raw"), "--capital", str(args.capital), "--topn", str(args.topn),
        "--exec", "t1open", "--freq", "1", "--sell-buffer", str(args.sell_buffer),
        "--min-edge", str(args.min_edge), "--weight-mode", "equal", "--exec-cache", args.exec_cache,
    ]
    completed = subprocess.run(command, check=False)
    raw_account_path = args.out / "v6_raw" / "account.json"
    if completed.returncode and not raw_account_path.exists():
        raise subprocess.CalledProcessError(completed.returncode, command)
    # V6 writes account/trades before its non-acceptance paper curve. Target
    # weights can have tied zeros, so that deliberately invalid curve may fail.
    with raw_account_path.open(encoding="ascii") as source:
        raw = json.load(source)
    pre_final_nav = float(raw["final"])
    trades_path = args.out / "v6_raw" / "trades.csv"
    trades = pd.read_csv(trades_path)
    holdings = {}
    for trade in cast(Any, trades.itertuples(index=False)):
        if trade.side == "BUY":
            holdings[trade.code] = {"shares": int(trade.shares), "buy_price": float(trade.price), "buy_fee": float(trade.fee)}
        elif trade.side == "SELL":
            holdings.pop(trade.code, None)
    from backtest.account_engine_v6 import load_market
    final_market = load_market(str(args.train), args.final_sell_date, set(holdings))
    rows = final_market.loc[pd.to_datetime(final_market["mkt_date"]) == args.final_sell_date]
    final_rows = {r.code: {"open": r.open, "volume": r.volume, "amount": r.amount, "close": r.close} for r in cast(Any, rows.itertuples(index=False))}
    history = pd.read_parquet(args.train, columns=["code", "kline_time", "close"])
    history["kline_time"] = pd.to_datetime(history["kline_time"])
    hist = history[(history["code"].isin(holdings)) & (history["kline_time"] <= args.final_sell_date) & np.isfinite(history["close"])]
    history = cast(pd.DataFrame, hist).sort_values("kline_time")
    last_marks = {r.code: {"date": r.kline_time, "close": r.close} for r in cast(Any, history.groupby("code", sort=False).tail(1).itertuples(index=False))}
    liquidation = final_liquidation(holdings, float(raw["cash_end"]), final_rows, args.final_sell_date, last_marks)
    liquidation_trades = pd.DataFrame(liquidation["trades"])
    pd.concat([trades, liquidation_trades], ignore_index=True).to_csv(args.out / "trades.csv", index=False)
    locked_value = sum(item["value"] for item in liquidation["locked_final"])
    final_nav = round(liquidation["cash"] + locked_value, 2)
    raw["final"] = final_nav
    raw["cash_end"] = round(liquidation["cash"], 2)
    raw["total"] = round(final_nav / args.capital - 1.0, 6)
    append_final_nav_metrics(raw, [args.capital, pre_final_nav], final_nav)
    raw["n_trades"] = int(raw["n_trades"] + len(liquidation["trades"]))
    raw["final_liquidation_date"] = args.final_sell_date.date().isoformat()
    raw["final_liquidation_fee"] = round(liquidation["fee_total"], 2)
    raw["final_liquidation_slip"] = round(liquidation["slip_total"], 2)
    raw["locked_final_count"] = len(liquidation["locked_final"])
    raw["locked_final"] = liquidation["locked_final"]
    raw["fee_total"] = round(raw["fee_total"] + liquidation["fee_total"], 2)
    raw["slip_total"] = round(raw["slip_total"] + liquidation["slip_total"], 2)
    first_buy = pd.Timestamp(trades.loc[trades["side"] == "BUY", "date"].min())
    market_dates = pd.DatetimeIndex(sorted(pd.read_parquet(args.train, columns=["kline_time"])["kline_time"].unique()))
    basis = int(cast(Any, market_dates.get_loc(args.final_sell_date)) - cast(Any, market_dates.get_loc(first_buy)))
    total = float(raw["total"])
    raw["annual"] = round(float((1.0 + total) ** (252.0 / basis) - 1.0), 6)
    raw["annual_days_basis"] = basis
    raw["annual_days_method"] = "actual trading-day distance from first T+1 buy execution to final episode sell-date open liquidation"
    raw["engine_base_version"] = "account_engine_v6.py (unmodified; invoked with --freq 1 only because prediction dates are already sparse)"
    raw["paper_curve_valid"] = False
    raw["paper_curve_warning"] = "future_ret_5d is a zero schema shim; V6 paper curves are invalid for joint target-weight scores."
    with (args.out / "account.json").open("w", encoding="ascii") as target:
        json.dump(raw, target, indent=2)
    print(json.dumps(raw, indent=2))


if __name__ == "__main__":
    main()
