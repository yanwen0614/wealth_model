"""Evaluate a daily continuous policy as a lot-sized account.

阶段 3 G02 决策：训练后评估链仅 legacy（opt-in 可达），不接 adapter——
torch checkpoint 接线（新策略类 + runner 接线超收口范围），daily 订单路径
已由 goal_adapter/daily_policy 覆盖。
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

import numpy as np
import pandas as pd
import torch

from backtest.account_engine_v6 import limit_pct
from backtest.continuous_daily_executor import execute_target_weights
from models.train_daily_continuous import _action, resolve_device


def _market_rows(sidecar: pd.DataFrame) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    required = {"code", "open", "close", "volume", "amount", "is_trading", "prev_close"}
    missing = required.difference(sidecar.columns)
    if missing:
        raise ValueError(f"execution_sidecar is missing columns: {sorted(missing)}")
    for values in sidecar.to_dict(orient="records"):
        code = str(values["code"])
        if not code:
            continue
        row = dict(values)
        previous_close = row.get("prev_close")
        try:
            previous_close = float(cast(float, previous_close))
        except (TypeError, ValueError):
            previous_close = np.nan
        if np.isfinite(previous_close) and previous_close > 0:
            band = limit_pct(code)
            row["limit_up"] = previous_close * (1.0 + band)
            row["limit_down"] = previous_close * (1.0 - band)
        else:
            row["limit_up"] = np.nan
            row["limit_down"] = np.nan
        rows[code] = row
    return rows


def _marked_weights(cash: float, holdings: dict[str, Any], market_rows: dict[str, dict[str, Any]]):
    values: dict[str, float] = {}
    for code, shares in holdings.items():
        row = market_rows.get(code)
        if row and bool(row.get("is_trading", False)):
            try:
                close = float(cast(float, row.get("close")))
            except (TypeError, ValueError):
                close = np.nan
            if np.isfinite(close):
                values[code] = float(shares) * close
    equity = float(cash) + sum(values.values())
    if equity <= 0:
        return {}, 0.0
    return {code: value / equity for code, value in values.items()}, equity


def rollout_policy(
    records: Iterable[Any],
    model,
    initial_cash: float = 2_000_000,
    device: str = "auto",
    lot_size: int = 100,
) -> dict[str, Any]:
    """Consume ordered daily records through the continuous lot account."""
    resolved_device = resolve_device(device)
    if not np.isfinite(initial_cash) or initial_cash < 0:
        raise ValueError("initial_cash must be finite and non-negative")
    model.to(resolved_device)
    model.eval()

    cash = float(initial_cash)
    holdings: dict[str, Any] = {}
    nav_points: list[float] = []
    trades: list[dict[str, Any]] = []
    fee_total = slip_total = 0.0
    locked_or_unpriced_count = 0
    previous_date = None

    with torch.no_grad():
        for record in records:
            if record.execution_sidecar is None:
                raise ValueError("rollout requires record.execution_sidecar")
            signal_date = pd.Timestamp(record.signal_date)
            if previous_date is not None and signal_date < previous_date:
                raise ValueError("records must be ordered by signal_date")
            previous_date = signal_date

            rows = _market_rows(record.execution_sidecar)
            previous_by_code, _ = _marked_weights(cash, holdings, rows)
            weights, _, _ = _action(model, record, previous_by_code, resolved_device)
            target_weights = {
                str(code): float(weight)
                for code, weight in zip(record.codes, weights.detach().cpu().numpy())
                if code
            }
            weight_total = sum(target_weights.values())
            if target_weights and weight_total > 0:
                target_weights = {
                    code: weight / weight_total for code, weight in target_weights.items()
                }

            execution = execute_target_weights(
                cash, holdings, target_weights, rows, record.buy_date, lot_size=lot_size
            )
            cash = execution["cash"]
            holdings = execution["holdings"]
            trades.extend(execution["trades"])
            fee_total += float(execution["fees"])
            slip_total += float(execution["slip"])

            marked = {}
            for code, shares in holdings.items():
                row = rows.get(code)
                if row and bool(row.get("is_trading", False)):
                    try:
                        close = float(cast(float, row.get("close")))
                    except (TypeError, ValueError):
                        close = np.nan
                    if np.isfinite(close):
                        marked[code] = float(shares) * close
                        continue
                locked_or_unpriced_count += 1
            nav_points.append(float(cash + sum(marked.values())))

    nav = np.asarray(nav_points, dtype=np.float64)
    if len(nav):
        peak = np.maximum.accumulate(nav)
        maxdd = float(np.max((peak - nav) / np.maximum(peak, 1e-12)))
        final = float(nav[-1])
    else:
        maxdd = 0.0
        final = float(initial_cash)
    daily_returns = nav[1:] / nav[:-1] - 1.0 if len(nav) > 1 else np.asarray([])
    risk_free_daily = (1.02 ** (1.0 / 252.0)) - 1.0
    excess = daily_returns - risk_free_daily
    sharpe = float(np.sqrt(252.0) * excess.mean() / excess.std(ddof=1)) if len(excess) > 1 and excess.std(ddof=1) > 0 else 0.0
    return {
        "account_mode": "continuous_lot_account",
        "initial": float(initial_cash),
        "final": final,
        "total": final / float(initial_cash) - 1.0 if initial_cash else 0.0,
        "maxdd": maxdd,
        "sharpe": sharpe,
        "n_records": len(nav_points),
        "n_trades": len(trades),
        "fee_total": round(fee_total, 2),
        "slip_total": slip_total,
        "cash_end": float(cash),
        "locked_or_unpriced_count": locked_or_unpriced_count,
        "device": str(resolved_device),
        "test_opened": False,
        "nav_points": nav_points,
        "trades": trades,
    }
