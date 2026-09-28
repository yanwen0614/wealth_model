"""Pure portfolio-policy helpers for joint selection and execution."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pickle
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
RAW_DATA = ROOT / "data" / "new" / "train_data_20260831.parquet"
ROLLING_FEATURES = ROOT / "artifacts" / "new_split" / "feat_roll_new.parquet"
NEW_SCALER = ROOT / "artifacts" / "new_split" / "scaler_2013_2023.pkl"
JOINT_OUTDIR = ROOT / "artifacts" / "joint_e2e_gate_off"
SPLITS = {
    "train": (None, pd.Timestamp("2023-12-31")),
    "val": (pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")),
    "test": (pd.Timestamp("2026-01-01"), None),
}


@dataclass(frozen=True)
class Episode:
    """One fixed candidate pool observed at a signal-date close."""

    signal_date: pd.Timestamp
    buy_date: pd.Timestamp
    sell_date: pd.Timestamp
    codes: tuple[str, ...]
    features: np.ndarray
    feature_columns: tuple[str, ...]
    reward_sidecar: pd.DataFrame

    @property
    def reward_columns(self) -> tuple[str, ...]:
        return ("buy_open", "sell_open", "buy_amount")

    @property
    def reward_valid(self) -> np.ndarray:
        return self.reward_sidecar["reward_valid"].to_numpy(dtype=bool)


def past_hand_features(closes) -> np.ndarray:
    """Four close-only trailing statistics ending at the signal date."""
    closes = np.asarray(closes, dtype=np.float64)
    if closes.ndim != 1 or closes.size < 20:
        raise ValueError("closes must be a one-dimensional vector with at least 20 values")
    previous, current = closes[:-1], closes[1:]
    returns = np.divide(
        current,
        previous,
        out=np.full_like(current, np.nan),
        where=np.isfinite(previous) & (previous != 0) & np.isfinite(current),
    ) - 1.0
    returns = np.nan_to_num(returns, nan=0.0)
    trailing_20 = returns[-20:]
    return np.asarray(
        [
            returns[-5:].mean(),
            trailing_20.mean(),
            np.sqrt(np.maximum(np.mean(trailing_20 * trailing_20) - trailing_20.mean() ** 2, 0.0)),
            closes[-1] / closes[-20] - 1.0 if np.isfinite(closes[-20]) and closes[-20] != 0 else 0.0,
        ],
        dtype=np.float32,
    )


def is_valid_episode_window(frame, code, signal_date, horizon=41, split_end=None) -> bool:
    """Whether one name has an unbroken, in-split history and reward window."""
    if isinstance(horizon, bool) or not isinstance(horizon, Integral) or horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    signal_date = pd.Timestamp(signal_date)
    split_end = pd.Timestamp(split_end) if split_end is not None else None
    name_rows = frame.loc[frame["code"].astype(str) == str(code)].sort_values("kline_time")
    dates = pd.DatetimeIndex(pd.to_datetime(name_rows["kline_time"]))
    positions = np.flatnonzero(dates == signal_date)
    if len(positions) != 1:
        return False
    signal_index = int(positions[0])
    sell_index = signal_index + horizon
    if signal_index < 59 or sell_index >= len(name_rows):
        return False
    window = name_rows.iloc[signal_index - 59:sell_index + 1]
    # The input frame supplies the exchange calendar, so public holidays are not
    # mistaken for missing trading rows.
    expected_dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["kline_time"]).unique()))
    expected_dates = expected_dates[(expected_dates >= dates[signal_index - 59]) & (expected_dates <= dates[sell_index])]
    if not pd.DatetimeIndex(pd.to_datetime(window["kline_time"])).equals(expected_dates):
        return False
    if split_end is not None and pd.Timestamp(window["kline_time"].iloc[-1]) > split_end:
        return False
    if not bool(window["is_trading"].astype(bool).all()):
        return False
    buy_row, sell_row = name_rows.iloc[signal_index + 1], name_rows.iloc[sell_index]
    values = (buy_row["open"], sell_row["open"], buy_row["amount"])
    return bool(np.isfinite(values).all() and buy_row["open"] > 0 and sell_row["open"] > 0 and buy_row["amount"] > 0)


def assemble_episode(frame, signal_date, feature_columns, horizon=41, split_end=None, candidate_limit=300) -> Episode:
    """Build one leakage-safe candidate pool using only signal-date inputs."""
    if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, Integral) or candidate_limit <= 0:
        raise ValueError("candidate_limit must be a positive integer")
    reward_fields = {"buy_open", "sell_open", "buy_amount", "reward_valid"}
    if len(feature_columns) != 45 or reward_fields.intersection(feature_columns):
        raise ValueError("feature_columns must contain exactly 45 non-reward columns")
    required = {"code", "kline_time", "close", "open", "amount", "is_trading", *feature_columns}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"frame is missing columns: {sorted(missing)}")
    signal_date = pd.Timestamp(signal_date)
    split_end = pd.Timestamp(split_end) if split_end is not None else None
    signal_rows = frame.loc[pd.to_datetime(frame["kline_time"]) == signal_date].copy()
    if split_end is not None and signal_date > split_end:
        raise ValueError("signal date is outside the split")
    exchange_dates = pd.DatetimeIndex(sorted(pd.to_datetime(frame["kline_time"]).unique()))
    signal_positions = np.flatnonzero(exchange_dates == signal_date)
    if len(signal_positions) != 1 or signal_positions[0] + horizon >= len(exchange_dates):
        raise ValueError("reward window is unavailable")
    buy_date = exchange_dates[signal_positions[0] + 1]
    sell_date = exchange_dates[signal_positions[0] + horizon]
    if split_end is not None and sell_date > split_end:
        raise ValueError("reward window crosses split boundary")
    if "_roll_valid" in signal_rows:
        signal_rows = signal_rows.loc[signal_rows["_roll_valid"].astype(bool)]
    signal_rows = signal_rows.loc[
        signal_rows["is_trading"].astype(bool)
        & np.isfinite(signal_rows["amount"])
        & (signal_rows["amount"] > 0)
        & np.isfinite(signal_rows[list(feature_columns)]).all(axis=1)
    ].sort_values(["amount", "code"], ascending=[False, True], kind="stable")
    candidates = signal_rows["code"].astype(str).head(candidate_limit).tolist()
    if not candidates:
        raise ValueError("no signal-date candidates for episode")
    pool = signal_rows.set_index("code").loc[candidates]
    reward_rows = []
    feature_rows = []
    for code in candidates:
        name_rows = frame.loc[frame["code"].astype(str) == str(code)].sort_values("kline_time").reset_index(drop=True)
        signal_index = int(np.flatnonzero(pd.to_datetime(name_rows["kline_time"]) == signal_date)[0])
        feature_rows.append(
            np.concatenate(
                [pool.loc[code, list(feature_columns)].to_numpy(dtype=np.float32),
                 past_hand_features(name_rows.loc[:signal_index, "close"].to_numpy())]
            )
        )
        reward_valid = is_valid_episode_window(frame, code, signal_date, horizon, split_end)
        if reward_valid:
            buy_row, sell_row = name_rows.iloc[signal_index + 1], name_rows.iloc[signal_index + horizon]
            buy_open, sell_open, buy_amount = float(buy_row["open"]), float(sell_row["open"]), float(buy_row["amount"])
        else:
            buy_open = sell_open = buy_amount = 0.0
        reward_rows.append({
            "code": str(code),
            "buy_open": buy_open,
            "sell_open": sell_open,
            "buy_amount": buy_amount,
            "reward_valid": reward_valid,
        })
    padding = candidate_limit - len(candidates)
    if padding:
        feature_rows.extend([np.zeros(49, dtype=np.float32) for _ in range(padding)])
        reward_rows.extend([
            {"code": "", "buy_open": 0.0, "sell_open": 0.0, "buy_amount": 0.0, "reward_valid": False}
            for _ in range(padding)
        ])
        candidates.extend([""] * padding)
    return Episode(
        signal_date=cast(pd.Timestamp, signal_date),
        buy_date=cast(pd.Timestamp, buy_date),
        sell_date=cast(pd.Timestamp, sell_date),
        codes=tuple(map(str, candidates)),
        features=np.vstack(feature_rows).astype(np.float32, copy=False),
        feature_columns=tuple(feature_columns) + ("mean_5", "mean_20", "vol_20", "ret_20"),
        reward_sidecar=pd.DataFrame(reward_rows),
    )


def make_rebalance_dates(dates, warmup=60, horizon=41, stride=40):
    """Return signal dates whose full reward horizon remains in the split."""
    for name, value, allow_zero in (
        ("warmup", warmup, True),
        ("horizon", horizon, False),
        ("stride", stride, False),
    ):
        if isinstance(value, bool) or not isinstance(value, Integral) or (value < 0 or not allow_zero and value == 0):
            raise ValueError(f"{name} must be a {'non-negative' if allow_zero else 'positive'} integer")
    stop = len(dates) - horizon
    if stop <= warmup:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(dates[warmup:stop:stride])


def _vector(value, name, device=None, dtype=None):
    vector = torch.as_tensor(value)
    if vector.ndim != 1 or vector.numel() == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional vector")
    if not torch.is_floating_point(vector):
        vector = vector.to(dtype=torch.get_default_dtype())
    if not torch.isfinite(vector).all().item():
        raise ValueError(f"{name} must contain only finite values")
    if device is not None or dtype is not None:
        vector = vector.to(device=device or vector.device, dtype=dtype or vector.dtype)
    return vector


def _scalar(value, name, reference):
    scalar = torch.as_tensor(value, device=reference.device, dtype=reference.dtype)
    if scalar.numel() != 1 or not torch.isfinite(scalar).all().item():
        raise ValueError(f"{name} must be a finite scalar")
    return scalar.reshape(())


def policy_weights(logits, previous_weights, replacement, temperature, allow_partial_previous=False):
    """Mix long-only target weights with existing holdings."""
    logits = _vector(logits, "logits")
    compute_dtype = torch.promote_types(logits.dtype, torch.float32)
    logits = logits.to(dtype=compute_dtype)
    previous_weights = _vector(
        previous_weights,
        "previous_weights",
        device=logits.device,
        dtype=compute_dtype,
    )
    if logits.shape != previous_weights.shape:
        raise ValueError("logits and previous_weights must have matching shapes")
    if (previous_weights < 0).any().item():
        raise ValueError("previous_weights must be non-negative")
    is_cash = (previous_weights == 0).all().item()
    previous_total = previous_weights.sum()
    if not is_cash and not allow_partial_previous and not torch.isclose(
        previous_total,
        torch.ones((), device=previous_weights.device, dtype=previous_weights.dtype),
        atol=1e-6,
        rtol=1e-5,
    ).item():
        raise ValueError("previous_weights must sum to one")
    replacement = _scalar(replacement, "replacement", logits)
    temperature = _scalar(temperature, "temperature", logits)
    if (replacement < 0).item() or (replacement > 1).item():
        raise ValueError("replacement must be in [0, 1]")
    if (temperature <= 0).item():
        raise ValueError("temperature must be greater than zero")
    if allow_partial_previous and (previous_total > 1).item():
        if (previous_total > 1 + 1e-6).item():
            raise ValueError("partial previous_weights must sum to no more than one")
        # Mark-to-market state is carried in float32; absorb its final rounding
        # error without accepting a genuinely over-allocated portfolio.
        previous_weights = previous_weights / previous_total
        previous_total = previous_weights.sum()
    target = torch.softmax(logits / temperature, dim=-1)
    if is_cash:
        weights = target
    elif allow_partial_previous:
        retained = (1 - replacement) * previous_weights
        weights = retained + (1 - retained.sum()) * target
    else:
        weights = (1 - replacement) * previous_weights + replacement * target
    weights = weights / weights.sum().clamp_min(1e-8)
    return weights, (weights - previous_weights).abs().sum()


def project_policy_scores(codes, scores, topn=None):
    """Make deterministic engine-schema scores from policy target weights.

    ``future_ret_5d`` is deliberately a zero-valued schema shim.  It must not
    be used for a paper curve because target weights are not future returns.
    """
    codes = np.asarray(codes).astype(str)
    scores = np.asarray(scores, dtype=np.float64)
    if codes.ndim != 1 or scores.ndim != 1 or len(codes) != len(scores):
        raise ValueError("codes and scores must be aligned one-dimensional vectors")
    if not np.isfinite(scores).all():
        raise ValueError("scores must be finite")
    if topn is not None and (isinstance(topn, bool) or not isinstance(topn, Integral) or topn <= 0):
        raise ValueError("topn must be a positive integer or None")
    pred = pd.DataFrame({"code": codes, "score": scores})
    pred = pred.loc[pred["code"] != ""].sort_values(
        ["score", "code"], ascending=[False, True], kind="stable"
    )
    if topn is not None:
        pred = pred.head(topn)
    pred["future_ret_5d"] = 0.0
    return pred.reset_index(drop=True)


def proxy_episode_return(
    logits,
    previous_weights,
    realized_returns,
    execution_amount,
    replacement=1.0,
    temperature=0.2,
    notional=1.0,
    fee_rate=0.0003,
    impact_rate=0.001,
    eps=1e-12,
    exit_turnover=0.0,
    exit_amount=1.0,
    allow_partial_previous=False,
):
    """Return gross portfolio return less turnover and participation costs."""
    weights, turnover = policy_weights(
        logits, previous_weights, replacement, temperature,
        allow_partial_previous=allow_partial_previous,
    )
    previous_weights = _vector(
        previous_weights,
        "previous_weights",
        device=weights.device,
        dtype=weights.dtype,
    )
    realized_returns = _vector(
        realized_returns,
        "realized_returns",
        device=weights.device,
        dtype=weights.dtype,
    )
    execution_amount = _vector(
        execution_amount,
        "execution_amount",
        device=weights.device,
        dtype=weights.dtype,
    )
    if weights.shape != realized_returns.shape:
        raise ValueError("policy weights and realized_returns must have matching shapes")
    if realized_returns.shape != execution_amount.shape:
        raise ValueError("realized_returns and execution_amount must have matching shapes")
    if (execution_amount <= 0).any().item():
        raise ValueError("execution_amount must be positive")
    notional = _scalar(notional, "notional", weights)
    fee_rate = _scalar(fee_rate, "fee_rate", weights)
    impact_rate = _scalar(impact_rate, "impact_rate", weights)
    eps = _scalar(eps, "eps", weights)
    exit_turnover = _scalar(exit_turnover, "exit_turnover", weights)
    exit_amount = _scalar(exit_amount, "exit_amount", weights)
    if (notional <= 0).item() or (fee_rate < 0).item() or (impact_rate < 0).item() or (eps <= 0).item() or (exit_turnover < 0).item() or (exit_amount <= 0).item():
        raise ValueError("notional and eps must be positive; rates must be non-negative")
    delta = weights - previous_weights
    gross = torch.dot(weights, realized_returns)
    impact = torch.sum(
        torch.sqrt(delta.abs() * notional / execution_amount + eps) * delta.abs()
    )
    # Names that left the pool are sold against this episode's conservative
    # liquidity estimate, so their turnover receives the same impact treatment.
    impact = impact + torch.sqrt(exit_turnover * notional / exit_amount + eps) * exit_turnover
    cost = fee_rate * (turnover + exit_turnover) + impact_rate * impact
    return gross - cost


class JointPortfolioPolicy(nn.Module):
    """Shared signal-only policy for name scores and replacement intensity."""

    def __init__(self, n_features=49):
        super().__init__()
        if n_features != 49:
            raise ValueError("JointPortfolioPolicy requires exactly 49 signal features")
        self.shared = nn.Sequential(
            nn.Linear(n_features, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
        )
        self.score = nn.Linear(32, 1)
        self.replacement = nn.Linear(32, 1)

    def forward(self, features):
        features = torch.as_tensor(features)
        if features.ndim != 2 or features.shape[1] != 49:
            raise ValueError("features must have shape (names, 49)")
        hidden = self.shared(features)
        logits = self.score(hidden).squeeze(-1)
        # Padding has an all-zero signal row; this is inferred from signal inputs,
        # not from a reward-side marker or code identity.
        signal_rows = features.abs().sum(dim=-1) > 0
        pooled = hidden[signal_rows].mean(dim=0) if signal_rows.any() else hidden.mean(dim=0)
        return logits, torch.sigmoid(self.replacement(pooled)).squeeze()


def joint_episode_loss(
    *, logits, replacement, previous_weights, codes, reward_valid, buy_open,
    sell_open, buy_amount, temperature, turnover_penalty, hhi_penalty=0.001, exit_turnover=0.0, exit_amount=1.0,
):
    """Loss for one fixed candidate pool without exposing reward metadata to policy."""
    logits = _vector(logits, "logits")
    dtype, device = logits.dtype, logits.device
    codes = np.asarray(codes).astype(str)
    if codes.ndim != 1 or len(codes) != logits.numel():
        raise ValueError("codes must align with logits")
    padding = torch.as_tensor(codes == "", device=device)
    active = ~padding
    if not active.any().item():
        raise ValueError("episode must contain at least one non-padding candidate")
    reward_valid = torch.as_tensor(reward_valid, device=device, dtype=torch.bool)
    if reward_valid.ndim != 1 or reward_valid.shape != logits.shape:
        raise ValueError("reward_valid must align with logits")
    previous_weights = _vector(previous_weights, "previous_weights", device=device, dtype=dtype)
    if previous_weights.shape != logits.shape or (previous_weights < 0).any().item():
        raise ValueError("previous_weights must be non-negative and align with logits")
    previous_active = previous_weights[active]
    buy_open = _vector(buy_open, "buy_open", device=device, dtype=dtype)
    sell_open = _vector(sell_open, "sell_open", device=device, dtype=dtype)
    buy_amount = _vector(buy_amount, "buy_amount", device=device, dtype=dtype)
    if any(value.shape != logits.shape for value in (buy_open, sell_open, buy_amount)):
        raise ValueError("reward sidecar vectors must align with logits")
    valid_active = reward_valid[active]
    active_returns = torch.where(
        valid_active,
        sell_open[active] / buy_open[active].clamp_min(1e-8) - 1.0,
        torch.full_like(buy_open[active], -1.0),
    )
    # Invalid future rewards remain candidates but cannot provide an execution amount.
    active_amount = torch.where(valid_active, buy_amount[active], torch.ones_like(buy_amount[active]))
    active_amount = active_amount.clamp_min(1.0)
    active_weights, _ = policy_weights(
        logits[active], previous_active, replacement, temperature, allow_partial_previous=True,
    )
    proxy_return = proxy_episode_return(
        logits[active], previous_active, active_returns, active_amount,
        replacement=replacement, temperature=temperature,
        fee_rate=turnover_penalty, exit_turnover=exit_turnover, exit_amount=exit_amount,
        allow_partial_previous=True,
    )
    weights = torch.zeros_like(logits).masked_scatter(active, active_weights)
    loss = -proxy_return + _scalar(hhi_penalty, "hhi_penalty", logits) * weights.square().sum()
    if not torch.isfinite(loss).item():
        raise ValueError("joint episode loss is not finite")
    return loss, weights, proxy_return


def _code_aligned_previous_weights(previous_by_code, codes):
    """Map prior holdings into this pool and total weights forced out of the pool."""
    codes = np.asarray(codes).astype(str)
    if codes.ndim != 1:
        raise ValueError("codes must be one-dimensional")
    current_codes = {code for code in codes if code}
    values = {str(code): torch.as_tensor(weight, dtype=torch.float32) for code, weight in previous_by_code.items() if code}
    if any(weight.numel() != 1 or not torch.isfinite(weight).item() or weight.item() < 0 for weight in values.values()):
        raise ValueError("previous_by_code must contain finite non-negative scalar weights")
    previous = torch.tensor([values.get(code, torch.tensor(0.0)).item() if code else 0.0 for code in codes])
    exited = sum((weight for code, weight in values.items() if code not in current_codes), torch.tensor(0.0))
    return previous, exited


def _mark_to_market_holdings(codes, weights, reward_valid, buy_open, sell_open):
    """Carry non-padding holdings at their realized end-of-episode values."""
    codes = np.asarray(codes).astype(str)
    weights = _vector(weights, "weights")
    if codes.ndim != 1 or len(codes) != weights.numel():
        raise ValueError("codes must align with weights")
    valid = torch.as_tensor(reward_valid, dtype=torch.bool, device=weights.device)
    buy = _vector(buy_open, "buy_open", device=weights.device, dtype=weights.dtype)
    sell = _vector(sell_open, "sell_open", device=weights.device, dtype=weights.dtype)
    if valid.shape != weights.shape or buy.shape != weights.shape or sell.shape != weights.shape:
        raise ValueError("reward sidecar vectors must align with weights")
    returns = torch.where(valid, sell / buy.clamp_min(1e-8) - 1.0, torch.full_like(weights, -1.0))
    values = weights * (1.0 + returns)
    total = values.sum()
    if total <= 0:
        return {}
    return {
        code: (value / total).detach().cpu()
        for code, value in zip(codes, values) if code
    }


def _load_episode_npz(path):
    """Load and validate an episode artifact needed for signal-only training."""
    required = {"features", "codes", "reward_valid", "feature_columns", "buy_open", "sell_open", "buy_amount", "signal_dates", "buy_dates", "sell_dates"}
    with np.load(path, allow_pickle=False) as source:
        missing = required.difference(source.files)
        if missing:
            raise ValueError(f"episode artifact missing fields: {sorted(missing)}")
        episodes = {name: source[name].copy() for name in required}
    if episodes["features"].ndim != 3 or episodes["features"].shape[2] != 49:
        raise ValueError("episode features must have shape (episodes, names, 49)")
    shape = episodes["features"].shape[:2]
    if episodes["codes"].shape != shape or any(episodes[name].shape != shape for name in ("reward_valid", "buy_open", "sell_open", "buy_amount")):
        raise ValueError("episode fields do not share (episodes, names) shape")
    if episodes["feature_columns"].shape != (49,):
        raise ValueError("episode feature schema must contain 49 fields")
    if any(episodes[name].shape != (shape[0],) for name in ("signal_dates", "buy_dates", "sell_dates")):
        raise ValueError("episode date fields must align with episodes")
    return episodes


def _run_proxy_epoch(model, episodes, temperature, turnover_penalty, optimizer=None):
    training = optimizer is not None
    model.train(training)
    previous_by_code = {}
    values = []
    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for index in range(episodes["features"].shape[0]):
            features = torch.from_numpy(episodes["features"][index]).float()
            logits, replacement = model(features)
            codes = episodes["codes"][index]
            previous, exit_turnover = _code_aligned_previous_weights(previous_by_code, codes)
            valid_amounts = episodes["buy_amount"][index][episodes["reward_valid"][index]]
            exit_amount = float(np.median(valid_amounts)) if len(valid_amounts) else 1.0
            exit_amount = max(exit_amount, 1.0)
            loss, weights, proxy_return = joint_episode_loss(
                logits=logits, replacement=replacement, previous_weights=previous,
                exit_turnover=cast(float, exit_turnover), exit_amount=exit_amount, codes=codes, reward_valid=episodes["reward_valid"][index],
                buy_open=episodes["buy_open"][index], sell_open=episodes["sell_open"][index],
                buy_amount=episodes["buy_amount"][index], temperature=temperature,
                turnover_penalty=turnover_penalty,
            )
            if training:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            previous_by_code = _mark_to_market_holdings(
                codes, weights, episodes["reward_valid"][index],
                episodes["buy_open"][index], episodes["sell_open"][index],
            )
            values.append(float(proxy_return.detach()))
    return values


def _validate_training_dates(episodes, split):
    """Reject artifacts whose reward dates do not belong to their declared split."""
    dates = {name: pd.DatetimeIndex(pd.to_datetime(episodes[name])) for name in ("signal_dates", "buy_dates", "sell_dates")}
    strictly_increasing = ((dates["signal_dates"] < dates["buy_dates"]) & (dates["buy_dates"] < dates["sell_dates"])).all()
    if not strictly_increasing:
        raise ValueError(f"{split} episode dates must be strictly increasing: signal < buy < sell")
    if split == "train":
        valid = all((values <= pd.Timestamp("2023-12-31")).all() for values in dates.values())
        if not valid:
            raise ValueError("train episode dates must have signal and sell dates on or before 2023-12-31")
    elif split == "val":
        start, end = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-12-31")
        valid = all(((values >= start) & (values <= end)).all() for values in dates.values())
        if not valid:
            raise ValueError("val episode dates must have signal, buy, and sell dates within 2024-01-01 through 2025-12-31")
    else:
        raise ValueError(f"unknown training split: {split}")


def train_joint_policy(smoke=False, episodes_dir=JOINT_OUTDIR, outdir=JOINT_OUTDIR):
    """Select a signal-only policy using TRAIN fitting and VAL proxy objective only."""
    episodes_dir, outdir = Path(episodes_dir), Path(outdir)
    train_path, val_path = episodes_dir / "episodes_train.npz", episodes_dir / "episodes_val.npz"
    if not train_path.exists() or not val_path.exists():
        raise FileNotFoundError("training requires episodes_train.npz and episodes_val.npz; run build --full first")
    train_episodes, val_episodes = _load_episode_npz(train_path), _load_episode_npz(val_path)
    if train_episodes["feature_columns"].shape != (49,) or not np.array_equal(
        train_episodes["feature_columns"], val_episodes["feature_columns"]
    ):
        raise ValueError("train and val feature_columns must match exactly with 49 columns")
    _validate_training_dates(train_episodes, "train")
    _validate_training_dates(val_episodes, "val")
    if not smoke and train_episodes["features"].shape[0] <= 2:
        raise ValueError("episodes_train.npz contains only smoke episodes; run build --full before training")
    if smoke and (train_episodes["features"].shape[0] != 2 or val_episodes["features"].shape[0] != 2):
        raise ValueError("--smoke requires two train and two val episodes")
    outdir.mkdir(parents=True, exist_ok=True)
    if not ROLLING_FEATURES.is_file():
        raise FileNotFoundError(f"training requires rolling normalization artifact: {ROLLING_FEATURES}")
    scaler_sha256 = hashlib.sha256(NEW_SCALER.read_bytes()).hexdigest()
    rolling_sha256 = hashlib.sha256(ROLLING_FEATURES.read_bytes()).hexdigest()
    trials, epochs = [], (2 if smoke else 20)
    for temperature in (0.25, 0.5):
        for turnover_penalty in (0.0005, 0.001):
            torch.manual_seed(20260905)
            model = JointPortfolioPolicy()
            optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
            history, best = [], None
            for epoch in range(1, epochs + 1):
                train_series = _run_proxy_epoch(model, train_episodes, temperature, turnover_penalty, optimizer)
                val_series = _run_proxy_epoch(model, val_episodes, temperature, turnover_penalty)
                record = {"epoch": epoch, "train_proxy_return": float(np.mean(train_series)), "val_proxy_return": float(np.mean(val_series)), "train_proxy_series": train_series, "val_proxy_series": val_series}
                history.append(record)
                if best is None or record["val_proxy_return"] > best["val_proxy_return"]:
                    best = record.copy()
                    best["checkpoint"] = {
                        "model_state": {name: value.detach().cpu().clone() for name, value in model.state_dict().items()},
                        "optimizer_state": copy.deepcopy(optimizer.state_dict()),
                        "epoch": epoch,
                        "temperature": temperature,
                        "turnover_penalty": turnover_penalty,
                        "architecture": {"n_features": 49, "shared_layers": [64, 32]},
                        "split_metadata": {"fit_source": str(train_path), "selection_source": str(val_path), "test_opened": False},
                        "feature_columns": train_episodes["feature_columns"].astype(str).tolist(),
                        "preprocessing_identity": {
                            "rolling_normalization": ROLLING_FEATURES.name,
                            "rolling_artifact_sha256": rolling_sha256,
                            "new_scaler_path": str(NEW_SCALER),
                            "new_scaler_sha256": scaler_sha256,
                        },
                    }
            trial_id = f"temp_{temperature:g}_turnover_{turnover_penalty:g}"
            checkpoint_path = outdir / f"{trial_id}.pt"
            torch.save(cast(Any, best).pop("checkpoint"), checkpoint_path)
            trials.append({"id": trial_id, "temperature": temperature, "turnover_penalty": turnover_penalty, "checkpoint_path": str(checkpoint_path), "best": best, "epochs": history})
    selected = max(trials, key=lambda trial: trial["best"]["val_proxy_return"])
    selected_checkpoint = outdir / "checkpoint.pt"
    torch.save(torch.load(selected["checkpoint_path"], weights_only=True), selected_checkpoint)
    metrics = {
        "smoke": bool(smoke), "acceptance": "smoke artifact is not eligible for account or 2026 acceptance" if smoke else "proxy-only model selection; no account engine executed",
        "selected_trial": selected["id"], "selection_reason": "highest VAL proxy return at its best epoch; TEST artifact was not opened",
        "checkpoint_path": str(selected_checkpoint),
        "trials": trials,
        "execution_cost_assumption": {"exit_notional": "notional * exit_turnover", "exit_liquidity_amount": "median valid buy_amount per episode; fallback 1.0"},
        "split_audit": {"fit_source": str(train_path), "selection_source": str(val_path), "opened_splits": ["train", "val"], "test_opened": False, "reward_metadata_not_model_input": True, "padding_from_codes_masked_in_loss": True},
    }
    with (outdir / "metrics.json").open("w", encoding="ascii") as handle:
        json.dump(metrics, handle, indent=2)
    return metrics


def _load_episode_frame(dates, feature_columns):
    """Read only one episode's market calendar from the two source parquets."""
    date_filter = [("kline_time", "in", list(pd.DatetimeIndex(dates)))]
    raw_columns = ["code", "kline_time", "close", "open", "amount", "is_trading"]
    feature_columns_in = ["code", "kline_time", *feature_columns, "_roll_valid"]
    raw = pd.read_parquet(RAW_DATA, columns=raw_columns, filters=date_filter)
    rolling = pd.read_parquet(ROLLING_FEATURES, columns=feature_columns_in, filters=date_filter)
    return raw.merge(rolling, on=["code", "kline_time"], how="inner", validate="one_to_one", suffixes=("", "_feature"))


def _write_episodes(path, episodes):
    """Persist numeric episode tensors without pickled Python objects."""
    if not episodes:
        raise ValueError("cannot write an empty episode collection")
    features = np.stack([episode.features for episode in episodes])
    codes = np.asarray([episode.codes for episode in episodes], dtype="U32")
    if features.ndim != 3 or features.shape[2] != 49 or codes.shape != features.shape[:2]:
        raise ValueError("episodes must have identically padded (candidates, 49) features")
    feature_columns = np.asarray(episodes[0].feature_columns, dtype="U64")
    if feature_columns.shape != (49,) or any(tuple(episode.feature_columns) != tuple(feature_columns) for episode in episodes):
        raise ValueError("episodes must have one 49-column feature schema")
    sidecars = [episode.reward_sidecar for episode in episodes]
    if any(len(sidecar) != features.shape[1] for sidecar in sidecars):
        raise ValueError("reward sidecars must align with padded candidates")
    np.savez_compressed(
        path,
        features=features,
        codes=codes,
        feature_columns=feature_columns,
        signal_dates=np.asarray([episode.signal_date for episode in episodes], dtype="datetime64[ns]"),
        buy_dates=np.asarray([episode.buy_date for episode in episodes], dtype="datetime64[ns]"),
        sell_dates=np.asarray([episode.sell_date for episode in episodes], dtype="datetime64[ns]"),
        buy_open=np.stack([sidecar["buy_open"].to_numpy(np.float32) for sidecar in sidecars]),
        sell_open=np.stack([sidecar["sell_open"].to_numpy(np.float32) for sidecar in sidecars]),
        buy_amount=np.stack([sidecar["buy_amount"].to_numpy(np.float32) for sidecar in sidecars]),
        reward_valid=np.stack([sidecar["reward_valid"].to_numpy(bool) for sidecar in sidecars]),
    )
    expected_keys = {"features", "codes", "feature_columns", "signal_dates", "buy_dates", "sell_dates", "buy_open", "sell_open", "buy_amount", "reward_valid"}
    with np.load(path, allow_pickle=False) as saved:
        if set(saved.files) != expected_keys or saved["features"].shape != features.shape:
            raise ValueError("episode artifact round-trip validation failed")
        if saved["feature_columns"].shape != (49,) or saved["reward_valid"].shape != features.shape[:2]:
            raise ValueError("episode artifact schema validation failed")


def build_episodes(smoke=False, outdir=JOINT_OUTDIR):
    """Create split-isolated 40-day, T+1-open episode artifacts."""
    import pyarrow.parquet as pq

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    all_dates = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_parquet(RAW_DATA, columns=["kline_time"])["kline_time"].unique())))
    with NEW_SCALER.open("rb") as handle:
        feature_columns = list(pickle.load(handle)["feature_cols_out"])
    if len(feature_columns) != 45:
        raise ValueError(f"scaler must declare exactly 45 feature_cols_out, found {len(feature_columns)}")
    rolling_columns = set(pq.ParquetFile(ROLLING_FEATURES).schema.names)
    if not set(feature_columns).issubset(rolling_columns):
        raise ValueError("scaler feature_cols_out are not present in rolling features")
    # The rolling feature named open collides with raw open after the merge.
    source_feature_columns = [f"{column}_feature" if column == "open" else column for column in feature_columns]
    summary = {"smoke": bool(smoke), "horizon": 41, "feature_columns": source_feature_columns + ["mean_5", "mean_20", "vol_20", "ret_20"], "splits": {}}
    for split, (start, end) in SPLITS.items():
        split_dates = all_dates
        if start is not None:
            split_dates = split_dates[split_dates >= start]
        if end is not None:
            split_dates = split_dates[split_dates <= end]
        signals = make_rebalance_dates(split_dates, warmup=60, horizon=41, stride=41)
        episodes = []
        for signal_date in signals:
            signal_index = cast(Any, split_dates.get_loc(signal_date))
            window_dates = split_dates[signal_index - 59:signal_index + 42]
            frame = _load_episode_frame(window_dates, feature_columns)
            try:
                episode = assemble_episode(
                    frame, signal_date, source_feature_columns, horizon=41, split_end=split_dates[-1], candidate_limit=300
                )
            except ValueError as error:
                if str(error) == "no signal-date candidates for episode":
                    continue
                raise
            if episode.sell_date > split_dates[-1]:
                raise AssertionError("reward date crossed split boundary")
            if set(episode.reward_columns).intersection(episode.feature_columns):
                raise AssertionError("reward columns leaked into features")
            episodes.append(episode)
            if smoke and len(episodes) == 2:
                break
        if smoke and len(episodes) != min(2, len(signals)):
            raise ValueError(f"{split} did not yield two smoke episodes")
        if not episodes:
            raise ValueError(f"{split} did not yield any episodes")
        output = outdir / f"episodes_{split}.npz"
        _write_episodes(output, episodes)
        summary["splits"][split] = {
            "episodes": len(episodes),
            "candidate_samples": sum(len(episode.codes) for episode in episodes),
            "candidates_per_episode": len(episodes[0].codes),
            "path": str(output),
        }
    with (outdir / "build_stats.json").open("w", encoding="ascii") as handle:
        json.dump(summary, handle, indent=2)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Build and train a leakage-safe joint policy")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--smoke", action="store_true")
    build.add_argument("--full", action="store_true", help="explicit full build (the default)")
    build.add_argument("--outdir", type=Path, default=JOINT_OUTDIR)
    train = subparsers.add_parser("train")
    train.add_argument("--smoke", action="store_true")
    train.add_argument("--episodes-dir", type=Path, default=JOINT_OUTDIR)
    train.add_argument("--outdir", type=Path, default=JOINT_OUTDIR)
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build_episodes(smoke=args.smoke, outdir=args.outdir), indent=2))
    elif args.command == "train":
        try:
            result = train_joint_policy(
                smoke=args.smoke, episodes_dir=args.episodes_dir, outdir=args.outdir
            )
        except FileNotFoundError as error:
            parser.error(str(error))
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
