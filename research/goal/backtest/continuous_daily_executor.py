"""Single-day target-weight execution using the account-engine V6 cost model.

阶段 3 G02 决策：训练后评估链仅 legacy（opt-in 可达），不接 adapter——
本执行器随 torch 链保留，daily 订单路径已由 goal_adapter/daily_policy 覆盖。
"""

from __future__ import annotations

import math
from typing import Any, cast

from backtest.account_engine_v6 import (
    fee_buy,
    fee_sell,
    participation_corrected,
    slip_eff,
)


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _shares(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("shares", 0)
    if isinstance(value, bool) or not _finite(value) or float(value) < 0 or not float(value).is_integer():
        raise ValueError("holdings shares must be finite, non-negative integers")
    return int(value)


def _tradable_price(row: dict[str, Any]) -> bool:
    return bool(row.get("is_trading", False)) and _finite(row.get("open")) and float(row["open"]) > 0


def _trade_cost(row: dict[str, Any], shares: int, side: str) -> tuple[float, float, float, float]:
    base = float(row["open"])
    participation = participation_corrected(
        base, shares, cast(float, row.get("volume")), cast(float, row.get("amount")),
        cast(float, row.get("close")),
    )
    slip_rate = slip_eff(participation, "t1open")
    slip_cost = base * shares * slip_rate
    price = base * (1.0 + slip_rate if side == "BUY" else 1.0 - slip_rate)
    amount = price * shares
    fee = fee_buy(amount) if side == "BUY" else fee_sell(amount)
    return amount, fee, slip_cost, slip_rate


def execute_target_weights(
    cash: float,
    holdings: dict[str, Any],
    target_weights: dict[str, float],
    market_rows: dict[str, dict[str, Any]],
    date: Any,
    lot_size: int = 100,
) -> dict[str, Any]:
    """Execute one daily rebalance at each symbol's supplied opening price.

    ``target_weights`` are fractions of marked portfolio equity.  Existing
    positions are marked at ``close`` for sizing, while orders execute at
    ``open``.  Orders are always whole lots and sells are completed before
    buys.  Missing/non-trading rows are ignored; a buy at ``limit_up`` is
    ignored as well.
    """
    if not _finite(cash) or float(cash) < 0:
        raise ValueError("cash must be finite and non-negative")
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise ValueError("lot_size must be a positive integer")
    if any(not _finite(weight) or float(weight) < 0 for weight in target_weights.values()):
        raise ValueError("target weights must be finite and non-negative")
    if sum(float(weight) for weight in target_weights.values()) > 1.0 + 1e-9:
        raise ValueError("target weights must sum to at most one")

    cash = float(cash)
    result_holdings = {code: _shares(value) for code, value in holdings.items() if _shares(value) > 0}
    trades: list[dict[str, Any]] = []
    fees = 0.0
    slip = 0.0
    date_text = date.date().isoformat() if hasattr(date, "date") else str(date)

    def record(code: str, side: str, shares: int, amount: float, fee: float,
               slip_cost: float, slip_rate: float, participation: float) -> None:
        nonlocal cash, fees, slip
        cash += -amount - fee if side == "BUY" else amount - fee
        fees += fee
        slip += slip_cost
        trades.append({
            "date": date_text,
            "code": code,
            "side": side,
            "shares": shares,
            "price": amount / shares,
            "amount": amount,
            "fee": fee,
            "slip_cost": slip_cost,
            "slip_rate": slip_rate,
            "participation": participation,
        })

    marked_values: dict[str, float] = {}
    for code, shares in result_holdings.items():
        row = market_rows.get(code)
        if row and bool(row.get("is_trading", False)) and _finite(row.get("close")):
            marked_values[code] = float(row["close"]) * shares
    equity = cash + sum(marked_values.values())

    # Calculate desired values before changing holdings, then execute every
    # reducible position first so sale proceeds can fund replacements.
    desired = {code: equity * float(weight) for code, weight in target_weights.items()}
    for code, current_shares in list(result_holdings.items()):
        row = market_rows.get(code)
        mark = marked_values.get(code)
        if not row or not _tradable_price(row):
            continue
        target_value = desired.get(code, 0.0)
        if mark is None:
            if target_value > 0:
                continue
            sell_shares = (current_shares // lot_size) * lot_size
        else:
            excess_value = mark - target_value
            if excess_value <= 0:
                continue
            sell_shares = min(current_shares, int(excess_value / float(row["close"]) // lot_size) * lot_size)
        if target_value <= 0:
            sell_shares = (current_shares // lot_size) * lot_size
        if sell_shares <= 0:
            continue
        amount, fee, slip_cost, slip_rate = _trade_cost(row, sell_shares, "SELL")
        participation = participation_corrected(
            float(row["open"]), sell_shares, cast(float, row.get("volume")),
            cast(float, row.get("amount")), cast(float, row.get("close")),
        )
        record(code, "SELL", sell_shares, amount, fee, slip_cost, slip_rate, participation)
        remaining = current_shares - sell_shares
        if remaining:
            result_holdings[code] = remaining
        else:
            result_holdings.pop(code)

    candidates = []
    for code, weight in desired.items():
        row = market_rows.get(code)
        if not row or not _tradable_price(row) or not _finite(row.get("close")):
            continue
        limit_up = row.get("limit_up")
        if _finite(limit_up) and float(cast(float, row["open"])) >= float(cast(float, limit_up)) * 0.999:
            continue
        current_value = float(row["close"]) * result_holdings.get(code, 0)
        gap = weight - current_value
        if gap > 0:
            candidates.append((gap, code, row))
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))

    for gap, code, row in candidates:
        current_shares = result_holdings.get(code, 0)
        wanted = int(gap / float(row["open"]) // lot_size) * lot_size
        buy_shares = wanted
        while buy_shares > 0:
            amount, fee, slip_cost, slip_rate = _trade_cost(row, buy_shares, "BUY")
            if amount + fee <= cash + 1e-9:
                break
            buy_shares -= lot_size
        if buy_shares <= 0:
            continue
        participation = participation_corrected(
            float(row["open"]), buy_shares, row.get("volume"), row.get("amount"), row.get("close")
        )
        record(code, "BUY", buy_shares, amount, fee, slip_cost, slip_rate, participation)
        result_holdings[code] = current_shares + buy_shares

    return {
        "cash": round(cash, 2),
        "holdings": result_holdings,
        "trades": trades,
        "fees": round(fees, 2),
        "slip": slip,
    }
