"""只读复核固定的两条 Z 源公司行动并生成逐日 pretax 账务证据。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from backtest_core.contracts.account import AccountState
from backtest_core.engine.account import apply_account_actions, mark_to_market, release_pending_cash

from backtest.cnn_adapter.corporate_actions import CorporateActionEvent, CorporateActionProvider
from backtest.cnn_adapter.raw_market_inputs import read_raw_market_inputs

EVENTS = (("000001.SZ", date(2021, 5, 14)), ("300896.SZ", date(2021, 3, 16)))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_date(value: int | None) -> date | None:
    return None if value is None else datetime.strptime(str(value), "%Y%m%d").date()


def git_identity(root: Path) -> dict[str, object]:
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], text=True)
    return {"root": str(root), "head": head, "dirty": bool(status.strip())}


def load_event(connection: sqlite3.Connection, code: str, ex_date: date):
    rows = list(connection.execute(
        "SELECT * FROM dividend WHERE 证券代码=? AND 除权除息日=? ORDER BY id",
        (code, int(ex_date.strftime("%Y%m%d"))),
    ))
    if len(rows) != 1:
        raise ValueError(f"{code} {ex_date}: expected one row, found {len(rows)}; refusing selection")
    columns = [item[1] for item in connection.execute("PRAGMA table_info(dividend)")]
    raw = dict(zip(columns, rows[0]))
    if str(raw["方案进度"]) != "3" or raw["方案是否变更"] not in (0, None):
        raise ValueError(f"{code} {ex_date}: event is not implemented and unchanged")
    meta = connection.execute("SELECT last_updated FROM metadata WHERE table_name='dividend'").fetchone()
    return raw, hashlib.sha256(repr(rows[0]).encode()).hexdigest(), meta[0] if meta else "unknown"


def make_event(raw: dict, row_hash: str, snapshot: str) -> CorporateActionEvent:
    record, ex_day = source_date(raw["股权登记日"]), source_date(raw["除权除息日"])
    pay, listing = source_date(raw["派息日"]), source_date(raw["红股上市日"])
    ratio = raw["每股转增比例"] if raw["每股转增比例"] is not None else raw["每股送转"]
    if record is None or ex_day is None or raw["每股派息税前"] is None:
        raise ValueError(f"event {raw['id']}: missing record/ex date or gross cash")
    shares_ratio = None if ratio in (None, 0, 0.0) else float(ratio)
    if shares_ratio is not None and listing is None:
        raise ValueError(f"event {raw['id']}: share listing date missing")
    return CorporateActionEvent(
        event_id=f"dividend:{raw['id']}", instrument_id=raw["证券代码"],
        kind="capitalization" if shares_ratio else "cash_dividend", source_table="dividend",
        source_row_id=str(raw["id"]), source_snapshot_hash=snapshot, source_version=row_hash,
        record_date=record, ex_date=ex_day, pay_date=pay, listing_date=listing,
        gross_cash_per_share=float(raw["每股派息税前"]), share_ratio=shares_ratio,
        announced_date=source_date(raw["分红实施公告日"]),
        known_at=source_date(raw["分红实施公告日"]), known_at_quality="date_only",
        ratio_denominator=1 if shares_ratio else None,
        rounding_rule="exact_integer_fixture_only" if shares_ratio else None,
    )


def run_case(event: CorporateActionEvent, row_hash: str, snapshot: str, raw: dict,
             db: Path, raw_dir: Path, shares: int, period_id: str) -> dict:
    parquet = raw_dir / f"{event.instrument_id}.parquet"
    if not parquet.is_file():
        raise FileNotFoundError(f"raw source missing: {parquet}")
    end_day = max(day for day in (event.pay_date, event.listing_date, event.ex_date) if day is not None)
    window = read_raw_market_inputs(
        parquet, instrument_id=event.instrument_id, signal_start=event.record_date,
        signal_end=event.pay_date or event.ex_date, execution_end=end_day + timedelta(days=10), history_bars=5,
    )
    bars = {bar.trading_date: bar for bar in window.records}
    days = sorted(day for day in bars if event.record_date <= day <= end_day + timedelta(days=10))
    if event.ex_date not in bars or bars[event.ex_date].close is None:
        raise ValueError(f"{event.instrument_id} {event.ex_date}: raw ex-date close missing")
    code = event.instrument_id
    state = AccountState(
        cash=100_000_000.0, available_cash=100_000_000.0, positions={code: float(shares)},
        locked={}, cost={code: 1.0}, last_marks={code: bars[event.record_date].close},
    )
    provider = CorporateActionProvider([event])
    snapshots = []
    for day in days:
        operations = provider.account_operations_for_day(day, period_id=period_id)
        if operations:
            state = apply_account_actions(state, operations, day)
        bar = bars[day]
        if bar.close is None:
            raise ValueError(f"{code} {day}: raw close missing")
        close = float(bar.close)
        unlisted_value = sum(item.shares * close for item in state.unlisted_entitlements.values())
        receivable_value = sum(item.amount for item in state.cash_receivables.values())
        nav = mark_to_market(state, {code: close}) + unlisted_value + receivable_value
        expected = state.cash + sum(qty * close for qty in state.positions.values()) + unlisted_value + receivable_value
        if abs(nav - expected) > 1e-6:
            raise AssertionError(f"{code} {day}: NAV component mismatch {nav} != {expected}")
        snapshots.append({
            "date": day.isoformat(), "operation_ids": [op.operation_id for op in operations],
            "cash": state.cash, "available_cash": state.available_cash, "positions": dict(state.positions),
            "receivables": {key: item.amount for key, item in state.cash_receivables.items()},
            "unlisted": {key: item.shares for key, item in state.unlisted_entitlements.items()},
            "raw_close": close, "expanded_nav": nav, "market_state": bar.market_state,
            "st_state": bar.st_state, "reference_state": bar.reference_state,
        })
        if state.pending_cash:
            state = release_pending_cash(state)
    return {
        "instrument_id": code, "fixture_initial_shares": shares, "source_row_id": raw["id"],
        "source_row_sha256": row_hash, "source_snapshot_updated": snapshot,
        "raw_parquet": str(parquet), "raw_parquet_sha256": sha256(parquet),
        "event": {"record_date": event.record_date.isoformat(), "ex_date": event.ex_date.isoformat(),
                  "pay_date": event.pay_date.isoformat() if event.pay_date else None,
                  "listing_date": event.listing_date.isoformat() if event.listing_date else None,
                  "gross_cash_per_share": event.gross_cash_per_share, "share_ratio": event.share_ratio,
                  "cash_tax_policy": "pretax", "cash_tax_amount": 0.0,
                  "share_tax_status": "unknown" if event.share_ratio else "not_applicable"},
        "snapshots": snapshots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("Z:/dev/quant_data_dev.db"))
    parser.add_argument("--raw-dir", type=Path, default=Path("Z:/dev/kline/day"))
    parser.add_argument("--output", type=Path, default=Path("docs/research/20261026/z_corporate_actions_audit.json"))
    parser.add_argument("--core-root", type=Path, default=Path("../backtest-core"))
    args = parser.parse_args()
    if not args.db.is_file():
        raise FileNotFoundError(f"SQLite source missing: {args.db}")
    cases = []
    connection = sqlite3.connect(f"file:{args.db.absolute().as_posix()}?mode=ro", uri=True)
    try:
        for code, ex_date in EVENTS:
            raw, row_hash, snapshot = load_event(connection, code, ex_date)
            event = make_event(raw, row_hash, snapshot)
            for shares in (100, 1000):
                cases.append(run_case(event, row_hash, snapshot, raw, args.db, args.raw_dir,
                                      shares, f"fixture-{code}-{shares}"))
    finally:
        connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "scope": "read_only_pretax_corporate_action_accounting_fixture; no orders or performance",
        "sqlite": str(args.db), "sqlite_sha256": sha256(args.db), "raw_directory": str(args.raw_dir),
        "audit_script": str(Path(__file__).resolve()), "audit_script_sha256": sha256(Path(__file__).resolve()),
        "repository_identity": {"cnn": git_identity(Path.cwd()), "backtest_core": git_identity(args.core_root)},
        "cases": cases,
        "limitations": [
            "Fixture positions/cash do not establish executable purchases; market/ST/reference states are unknown.",
            "Cash is pretax gross receivable/payment; actual personal tax is not modeled.",
            "20% cash dividend withholding is a stress scenario only, not actual tax or a guaranteed return floor.",
            "Share-tax classification and legal rounding are unverified; unknown tax is not assumed zero.",
            "NAV is an accounting reconciliation, not strategy performance.",
        ],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
