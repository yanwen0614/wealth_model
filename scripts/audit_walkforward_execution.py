"""复核 W1/W2 账户执行：分别重放旧收盘判定与开盘可见判定并导出完整明细。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np

from backtest.cnn_adapter import market as market_module
from backtest.cnn_adapter.runner import run_cnn_backtest
from scripts.run_backtest import load_preds


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_value(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date) or hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, default=_json_value, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, default=_json_value, separators=(",", ":")) + "\n")


def _serialize(row):
    return asdict(row)


def _baseline_close_limits(self, instrument_id, cache, position):
    """复现修复前仅供差分审计的 close 判定，不进入生产代码路径。"""
    row = cache.rows[position]
    prev_close = next((cache.rows[i].close for i in range(position - 1, -1, -1)
                       if cache.rows[i].close is not None), None)
    market_pct = market_module._market_and_pct(instrument_id)
    prev = market_module._finite_decimal(prev_close)
    close = market_module._finite_decimal(row.close)
    if market_pct is None or prev is None or prev <= 0 or close is None or close <= 0:
        self._limit_unknown_count += 1
        return False, False
    market, board_pct = market_pct
    pct = market_module._ST_PCT if (instrument_id in self._st_codes
                                    and board_pct == market_module._MAIN_BOARD_PCT) else board_pct
    min_tick = market == "SZ"
    upper = market_module._limit_price(prev, pct, up=True, min_tick_rule=min_tick)
    lower = market_module._limit_price(prev, pct, up=False, min_tick_rule=min_tick)
    return market_module._to_cents(close) >= market_module._to_cents(upper), \
        market_module._to_cents(close) <= market_module._to_cents(lower)


def _run_one(preds, parquet: Path, out_dir: Path, label: str, baseline: bool):
    provider_cls = market_module.CnnMarketDataProvider
    original = provider_cls._derive_limits
    if baseline:
        provider_cls._derive_limits = _baseline_close_limits
    try:
        outcome = run_cnn_backtest(
            pred_cache=preds, parquet_path=str(parquet), mode="target", target_size=5,
            sell_buffer=5, initial_capital=1_000_000.0,
            commission_rate_buy=0.0002, commission_rate_sell=0.0002,
            min_commission=5.0, stamp_tax_rate=0.0005, transfer_fee_rate=0.00001,
            model_name="cnn_transformer", checkpoint="unknown",
            bins_version="unknown", eval_script_version="scripts/run_backtest@n01",
        )
    finally:
        provider_cls._derive_limits = original
    out_dir.mkdir(parents=True, exist_ok=True)
    result = outcome.result
    snapshots = []
    for snap in result.account_snapshots:
        positions = {code: {"shares": pos.shares, "cost": pos.cost, "price": pos.price,
                            "market_value": pos.market_value}
                     for code, pos in sorted(snap.positions.items())}
        snapshots.append({"date": snap.date, "nav": snap.nav, "cash": snap.cash,
                          "position_count": sum(pos["shares"] > 0 for pos in positions.values()),
                          "positions": positions})
    orders = [_serialize(item) for item in result.order_results]
    trades = [_serialize(item) for item in result.trades]
    _write_jsonl(out_dir / "daily_account.jsonl", snapshots)
    _write_jsonl(out_dir / "order_results.jsonl", orders)
    _write_jsonl(out_dir / "trade_events.jsonl", trades)
    reasons = Counter(str(item.reason) for item in result.order_results if item.reason is not None)
    statuses = Counter(str(item.status) for item in result.order_results)
    max_positions = max((row["position_count"] for row in snapshots), default=0)
    summary = {
        "label": label, "limit_basis": "execution_close (historical)" if baseline else "execution_open",
        "start": snapshots[0]["date"], "end": snapshots[-1]["date"],
        "snapshot_count": len(snapshots), "metrics": dict(outcome.account_evaluation),
        "final_nav": snapshots[-1]["nav"], "final_cash": snapshots[-1]["cash"],
        "max_position_count": max_positions, "holding_cap_pass": max_positions <= 10,
        "order_status_counts": dict(statuses), "order_reason_counts": dict(reasons),
        "trade_count": len(trades), "config_hash": outcome.config_hash,
        "prediction_fingerprint": outcome.data_fingerprint,
        "manifest": asdict(outcome.manifest),
    }
    _write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", choices=("W1", "W2"), required=True)
    parser.add_argument("--preds", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--run-config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-start", required=True)
    parser.add_argument("--expected-end", required=True)
    args = parser.parse_args()
    raw = np.load(args.preds, allow_pickle=False)
    preds = load_preds(str(args.preds))
    pred_days = np.unique(raw["dates"]).astype("datetime64[D]")
    start, end = str(pred_days[0]), str(pred_days[-1])
    if (start, end) != (args.expected_start, args.expected_end):
        raise ValueError(f"预测缓存区间 {(start, end)} != 期望区间 "
                         f"{(args.expected_start, args.expected_end)}")
    args.out.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.run_config.read_text(encoding="utf-8"))
    stat = args.parquet.stat()
    identity = {
        "window": args.window, "prediction_path": args.preds,
        "prediction_sha256": _sha256(args.preds), "prediction_rows": len(raw["dates"]),
        "prediction_start": start, "prediction_end": end,
        "checkpoint_path": args.checkpoint, "checkpoint_sha256": _sha256(args.checkpoint),
        "run_config_path": args.run_config, "run_config": config,
        "parquet_path": args.parquet, "parquet_size_bytes": stat.st_size,
        "parquet_mtime_ns": stat.st_mtime_ns, "parquet_sha256": _sha256(args.parquet),
        "strategy": {"mode": "target", "target_size": 5, "sell_buffer": 5,
                     "max_actual_holdings": 10, "exit_on_nonpositive": False,
                     "strong_buy_threshold": 0.0, "min_edge": 0.0,
                     "stop_half": None, "stop_full": None},
        "costs": {"buy_commission": 0.0002, "sell_commission": 0.0002,
                  "min_commission": 5.0, "stamp_tax": 0.0005,
                  "transfer_fee": 0.00001},
    }
    _write_json(args.out / "identity.json", identity)
    before = _run_one(preds, args.parquet, args.out / "before_close_based", args.window, True)
    after = _run_one(preds, args.parquet, args.out / "after_open_based", args.window, False)
    old_rows = [json.loads(line) for line in
                (args.out / "before_close_based" / "daily_account.jsonl").read_text().splitlines()]
    new_rows = [json.loads(line) for line in
                (args.out / "after_open_based" / "daily_account.jsonl").read_text().splitlines()]
    deltas = [{"date": old["date"], "nav_before": old["nav"], "nav_after": new["nav"],
               "nav_delta": new["nav"] - old["nav"], "cash_delta": new["cash"] - old["cash"],
               "positions_before": old["position_count"], "positions_after": new["position_count"]}
              for old, new in zip(old_rows, new_rows)]
    _write_jsonl(args.out / "daily_comparison.jsonl", deltas)
    _write_json(args.out / "comparison.json", {
        "window": args.window, "before": before, "after": after,
        "nav_change": after["final_nav"] - before["final_nav"],
        "return_change": after["metrics"]["total_return"] - before["metrics"]["total_return"],
        "annualized_return_change": after["metrics"]["annualized_return"]
                                    - before["metrics"]["annualized_return"],
        "max_abs_daily_nav_change": max(abs(row["nav_delta"]) for row in deltas),
        "days_with_nav_change": sum(row["nav_delta"] != 0 for row in deltas),
    })


if __name__ == "__main__":
    main()
