"""Deterministic synthetic smoke loop for the daily continuous portfolio path."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.continuous_daily_executor import execute_target_weights
from models.daily_continuous_policy import DailyContinuousPolicy, target_weights
from models.daily_portfolio_data import DailyRecord


def _synthetic_records(seed: int, n_days: int, candidate_limit: int) -> list[DailyRecord]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-05", periods=n_days, freq="B")
    codes = tuple(f"S{index:04d}" for index in range(candidate_limit))
    padded_codes = codes + tuple("" for _ in range(1000 - candidate_limit))
    records = []
    for index, signal_date in enumerate(dates):
        sell_date = cast(pd.Timestamp, dates[index + 5] if index + 5 < n_days else signal_date + pd.offsets.BDay(5))
        features = np.zeros((1000, 49), dtype=np.float32)
        features[:candidate_limit] = rng.normal(size=(candidate_limit, 49)).astype(np.float32)
        rewards = pd.DataFrame(
            {
                "code": padded_codes,
                "buy_open": [10.0 + code_index * 0.01 for code_index in range(candidate_limit)]
                + [0.0] * (1000 - candidate_limit),
                "sell_open": [10.0 + code_index * 0.01 + 0.02 for code_index in range(candidate_limit)]
                + [0.0] * (1000 - candidate_limit),
                "buy_amount": [10_000_000.0] * candidate_limit + [0.0] * (1000 - candidate_limit),
                "reward_valid": [True] * candidate_limit + [False] * (1000 - candidate_limit),
            }
        )
        records.append(
            DailyRecord(
                signal_date=signal_date,
                buy_date=signal_date + pd.Timedelta(days=1),
                sell_date=sell_date,
                codes=padded_codes,
                features=features,
                feature_columns=tuple(f"feature_{i}" for i in range(49)),
                reward_sidecar=rewards,
            )
        )
    return records


def _market_rows(record: DailyRecord, date: pd.Timestamp) -> dict[str, dict[str, Any]]:
    rows = {}
    for index, code in enumerate(record.codes):
        if not code:
            continue
        close = 10.0 + index * 0.01 + date.dayofyear * 0.001
        rows[code] = {
            "open": close,
            "close": close,
            "volume": 1_000_000.0,
            "amount": 10_000_000.0,
            "is_trading": True,
            "limit_up": 100.0,
            "limit_down": 1.0,
        }
    return rows


def _current_weights(cash: float, holdings: dict[str, Any], record: DailyRecord,
                     rows: dict[str, dict[str, Any]]) -> np.ndarray:
    values = np.zeros(1000, dtype=np.float32)
    for index, code in enumerate(record.codes):
        if code in holdings:
            values[index] = float(holdings[code]) * float(rows[code]["close"])
    equity = cash + float(values.sum())
    return values / equity if equity > 0 else values


def run_smoke(seed: int = 7, n_days: int = 12, candidate_limit: int = 20) -> dict[str, Any]:
    """Run only synthetic records through policy, delayed rewards, and executor."""
    if n_days < 1:
        raise ValueError("n_days must be positive")
    if candidate_limit < 1 or candidate_limit > 1000:
        raise ValueError("candidate_limit must be between 1 and 1000")

    torch.manual_seed(seed)
    policy = DailyContinuousPolicy(hidden_dim=32).eval()
    records = _synthetic_records(seed, n_days, candidate_limit)
    cash = 1_000_000.0
    holdings: dict[str, Any] = {}
    pending: list[dict[str, Any]] = []
    reward_queue: list[dict[str, Any]] = []
    reward_events: list[dict[str, Any]] = []
    state_trace = []
    n_trades = 0

    for index, record in enumerate(records):
        date = record.signal_date
        for event in list(reward_queue):
            if event["sell_date"] == date.isoformat():
                reward_queue.remove(event)
                event["realized_date"] = date.isoformat()
                reward_events.append(event)

        if pending:
            action = pending.pop(0)
            execution_record = records[action["index"]]
            result = execute_target_weights(
                cash, holdings, action["target_weights"],
                _market_rows(execution_record, date), date,
            )
            cash, holdings = result["cash"], result["holdings"]
            n_trades += len(result["trades"])

        rows = _market_rows(record, date)
        current = _current_weights(cash, holdings, record, rows)
        inputs = torch.from_numpy(np.concatenate([record.features, current[:, None]], axis=1))
        valid_mask = torch.tensor([bool(code) for code in record.codes])
        with torch.no_grad():
            alpha, gate = policy(inputs, valid_mask=valid_mask)
            weights = target_weights(alpha, gate, torch.from_numpy(current), valid_mask=valid_mask)
        target = {code: float(weights[index]) for index, code in enumerate(record.codes) if code}
        target_total = sum(target.values())
        target = {code: weight / target_total for code, weight in target.items()}
        reward = float(sum(
            float(weights[index]) * (row["sell_open"] / row["buy_open"] - 1.0)
            for index, row in record.reward_sidecar.iloc[:candidate_limit].iterrows()
        ))
        reward_queue.append({
            "signal_date": record.signal_date.isoformat(),
            "sell_date": record.sell_date.isoformat(),
            "reward": reward,
        })
        pending.append({"index": index, "target_weights": target})
        state_trace.append({
            "signal_date": date.isoformat(),
            "current_weight_sum": float(current.sum()),
            "held_names": len(holdings),
            "pending_actions": len(pending),
            "rewards_waiting": len(reward_queue),
        })

    return {
        "synthetic_only": True,
        "test_opened": False,
        "split_metadata": {"TRAIN": "synthetic", "VAL": "synthetic", "TEST": "synthetic"},
        "n_signal_days": n_days,
        "n_rewards_realized": len(reward_events),
        "final_cash": cash,
        "n_trades": n_trades,
        "reward_events": reward_events,
        "state_trace": state_trace,
    }


def write_smoke_json(result: dict[str, Any], outdir: str | Path) -> Path:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir / "daily_continuous_smoke.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/daily_continuous_smoke"))
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-days", type=int, default=12)
    parser.add_argument("--candidate-limit", type=int, default=20)
    args = parser.parse_args()
    output = write_smoke_json(run_smoke(args.seed, args.n_days, args.candidate_limit), args.outdir)
    print(output)


if __name__ == "__main__":
    main()
