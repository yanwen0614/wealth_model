"""Streaming train/evaluate entry point for the daily continuous policy."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.daily_continuous_policy import DailyContinuousPolicy, target_weights
from models.daily_portfolio_data import DailyRecord


def resolve_device(requested: str = "auto") -> torch.device:
    """Resolve a requested torch device, rejecting unavailable CUDA explicitly."""
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested not in {"cpu", "cuda"}:
        raise ValueError("device must be one of: auto, cpu, cuda")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA device requested but CUDA is not available")
    return torch.device(requested)


def aligned_current_weights(previous_by_code: dict[str, float], codes) -> np.ndarray:
    """Align named holdings to a record's slots; padding and unknown names are zero."""
    return np.asarray([float(previous_by_code.get(str(code), 0.0)) if code else 0.0 for code in codes], dtype=np.float32)


def _action(model, record: DailyRecord, previous_by_code: dict[str, float], device: str | torch.device = "auto"):
    device = resolve_device(device) if isinstance(device, str) else device
    current = aligned_current_weights(previous_by_code, record.codes)
    valid = np.asarray([bool(code) for code in record.codes], dtype=bool)
    inputs = torch.from_numpy(np.concatenate((record.features, current[:, None]), axis=1)).to(device)
    mask = torch.from_numpy(valid).to(device)
    alpha, gate = model(inputs, valid_mask=mask)
    weights = target_weights(alpha, gate, torch.from_numpy(current).to(device), valid_mask=mask)
    return weights, current, valid


def _reward(record: DailyRecord, weights: torch.Tensor, valid: np.ndarray,
            device: str | torch.device = "auto") -> torch.Tensor:
    device = resolve_device(device) if isinstance(device, str) else device
    sidecar = record.reward_sidecar
    buy = torch.from_numpy(sidecar["buy_open"].to_numpy(dtype=np.float32, copy=True)).to(device)
    sell = torch.from_numpy(sidecar["sell_open"].to_numpy(dtype=np.float32, copy=True)).to(device)
    returns = torch.where(buy > 0, sell / buy - 1.0, torch.zeros_like(buy))
    mask = torch.as_tensor(valid & record.reward_valid, device=device)
    return (weights * returns * mask).sum()


def _update_state(previous_by_code: dict[str, float], record: DailyRecord, weights: torch.Tensor) -> None:
    previous_by_code.clear()
    for code, weight in zip(record.codes, weights.detach().cpu().numpy()):
        if code:
            previous_by_code[str(code)] = float(weight)


def take_records(records: Iterable[DailyRecord], max_records: int):
    """Yield at most max_records items without materializing the input."""
    if max_records <= 0:
        yield from records
        return
    for count, record in enumerate(records, start=1):
        yield record
        if count >= max_records:
            break


def train_policy(
    records: Iterable[DailyRecord], epochs: int = 1, lr: float = 1e-3,
    hidden_dim: int = 128, turnover_penalty: float = 0.01,
    hhi_penalty: float = 0.01, model: DailyContinuousPolicy | None = None,
    device: str = "auto",
):
    """Train in record order. The iterable is consumed directly and never materialized."""
    if epochs < 1:
        raise ValueError("epochs must be positive")
    dev = resolve_device(device)
    model = (model or DailyContinuousPolicy(hidden_dim=hidden_dim)).to(dev)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    total_loss = total_reward = total_turnover = 0.0
    n_records = n_valid = 0
    for _ in range(epochs):
        previous_by_code: dict[str, float] = {}
        for record in records:
            model.train()
            weights, current, valid = _action(model, record, previous_by_code, dev)
            reward = _reward(record, weights, valid, dev)
            turnover = torch.abs(weights - torch.from_numpy(current).to(dev)).sum()
            loss = -reward + turnover_penalty * turnover + hhi_penalty * weights.square().sum()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            _update_state(previous_by_code, record, weights)
            total_loss += float(loss.detach())
            total_reward += float(reward.detach())
            total_turnover += float(turnover.detach())
            n_records += 1
            n_valid += int(valid.sum())
    return model, {
        "n_records": n_records,
        "n_reward_valid": n_valid,
        "loss": total_loss / max(n_records, 1),
        "reward": total_reward / max(n_records, 1),
        "turnover": total_turnover / max(n_records, 1),
        "device": str(dev),
        "cuda_available": torch.cuda.is_available(),
    }


def evaluate_policy(records: Iterable[DailyRecord], model: DailyContinuousPolicy,
                    turnover_penalty: float = 0.0, device: str = "auto", **_):
    """Evaluate sidecar rewards as a continuous-weight proxy account."""
    dev = resolve_device(device)
    model.to(dev)
    previous_by_code: dict[str, float] = {}
    equity = 1.0
    peak = 1.0
    maxdd = 0.0
    returns = []
    turnover_total = 0.0
    n_records = 0
    model.eval()
    with torch.no_grad():
        for record in records:
            weights, current, valid = _action(model, record, previous_by_code, dev)
            reward = float(_reward(record, weights, valid, dev))
            turnover_total += float(torch.abs(weights - torch.from_numpy(current).to(dev)).sum())
            equity *= 1.0 + reward
            peak = max(peak, equity)
            maxdd = max(maxdd, 1.0 - equity / peak)
            returns.append(reward)
            _update_state(previous_by_code, record, weights)
            n_records += 1
    returns = np.asarray(returns, dtype=np.float64)
    sharpe = float(np.sqrt(252.0) * returns.mean() / returns.std(ddof=1)) if len(returns) > 1 and returns.std(ddof=1) > 0 else 0.0
    return {
        "account_mode": "continuous_proxy",
        "total": float(equity - 1.0),
        "maxdd": float(maxdd),
        "sharpe": sharpe,
        "n_records": n_records,
        "turnover": turnover_total / max(n_records, 1),
        "device": str(dev),
    }


def make_synthetic_records(n_days: int = 12, candidate_limit: int = 20, seed: int = 7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-05", periods=n_days, freq="B")
    codes = tuple(f"S{i:04d}" for i in range(candidate_limit)) + tuple("" for _ in range(1000 - candidate_limit))
    records = []
    for i, date in enumerate(dates):
        features = np.zeros((1000, 49), dtype=np.float32)
        features[:candidate_limit] = rng.normal(size=(candidate_limit, 49)).astype(np.float32)
        buy = np.zeros(1000, dtype=np.float32) + 10.0
        sell = buy + 0.02
        records.append(DailyRecord(date, date + pd.Timedelta(days=1), date + pd.Timedelta(days=5), codes, features,
                                   tuple(f"feature_{j}" for j in range(49)),
                                   pd.DataFrame({"code": codes, "buy_open": buy, "sell_open": sell,
                                                 "buy_amount": np.where(np.arange(1000) < candidate_limit, 1e6, 0),
                                                 "reward_valid": np.arange(1000) < candidate_limit})))
    return records


def iter_split_records(raw_path: str | Path = "data/new/train_data_20260831.parquet",
                       feature_path: str | Path = "artifacts/new_split/feat_roll_new.parquet",
                       split: str = "train", candidate_limit: int = 1000, stride: int = 1,
                       include_execution_sidecar: bool | None = None) -> Iterable[DailyRecord]:
    """Build a one-pass split iterator from projected parquet windows."""
    if split not in {"train", "val"}:
        raise ValueError("only train and val splits are implemented")
    feature_columns = [name for name in pq.read_schema(feature_path).names
                       if name not in {"code", "kline_time", "_roll_valid"}]
    if len(feature_columns) != 45:
        raise ValueError(f"feature parquet must contain exactly 45 features, found {len(feature_columns)}")
    bounds = {"train": ("2013-01-01", "2023-12-31"), "val": ("2024-01-01", "2025-12-31")}
    from models.daily_dataset import iter_daily_records
    return cast("Iterable[DailyRecord]", (record for record, _ in iter_daily_records(
         raw_path, feature_path, feature_columns,
          split_start=bounds[split][0], split_end=bounds[split][1],
          candidate_limit=candidate_limit, stride=stride,
          include_execution_sidecar=include_execution_sidecar)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("train", "val", "test"), required=True)
    parser.add_argument("--allow-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/daily_continuous"))
    parser.add_argument("--raw", type=Path, default=Path("data/new/train_data_20260831.parquet"))
    parser.add_argument("--features", type=Path, default=Path("artifacts/new_split/feat_roll_new.parquet"))
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    if args.split == "test":
        if not args.allow_test:
            parser.error("--split test requires --allow-test")
        raise SystemExit("test split is not implemented")
    records = take_records(
        iter_split_records(args.raw, args.features, args.split, stride=args.stride),
        args.max_records,
    )
    model, train_metrics = train_policy(records, device=args.device)
    metrics = dict(train_metrics)
    metrics["split"] = args.split
    metrics["stride"] = args.stride
    metrics["max_records"] = args.max_records
    metrics["account_mode"] = "continuous_proxy"
    args.outdir.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state": model.state_dict(), "architecture": {"hidden_dim": model.shared[0].out_features}}, args.outdir / "checkpoint.pt")
    (args.outdir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    print(args.outdir / "metrics.json")


if __name__ == "__main__":
    main()
