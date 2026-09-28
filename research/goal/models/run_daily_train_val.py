"""Train the daily continuous policy on train records and select on validation."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.evaluate_daily_account import rollout_policy
from models.train_daily_continuous import (
    evaluate_policy,
    iter_split_records,
    take_records,
    train_policy,
)

SELECTION_RULE = "VAL continuous_proxy: total - 0.5*maxdd, tie-break sharpe"
ACCOUNT_SELECTION_RULE = (
    "VAL account: total - 0.5*maxdd, tie-break sharpe; proxy metrics diagnostic"
)


def _architecture(model: torch.nn.Module) -> dict[str, object]:
    shared = getattr(model, "shared", None)
    first = shared[0] if shared is not None and len(shared) else None
    return {
        "name": type(model).__name__,
        "input_dim": getattr(first, "in_features", None),
        "hidden_dim": getattr(first, "out_features", None),
    }


def run_train_val(
    train_records: Iterable,
    val_records: Iterable,
    outdir: str | Path,
    device: str = "auto",
    epochs: int = 1,
    account_records: Iterable | None = None,
    capital: float = 2_000_000,
    lot_size: int = 100,
    **train_kwargs,
) -> dict[str, dict]:
    """Train on train_records, then evaluate the resulting model on val_records."""
    model, train_metrics = train_policy(
        train_records, device=device, epochs=epochs, **train_kwargs
    )
    val_metrics = evaluate_policy(val_records, model, device=device)
    val_account_metrics = None
    if account_records is not None:
        val_account_metrics = rollout_policy(
            account_records, model, device=device,
            initial_cash=capital, lot_size=lot_size,
        )

    output_dir = Path(outdir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "model_state": model.state_dict(),
        "architecture": _architecture(model),
        "device": str(next(model.parameters()).device),
    }
    torch.save(checkpoint, output_dir / "checkpoint.pt")
    selection = {
        "train_metrics": train_metrics,
        "val_metrics": val_metrics,
        "selection_rule": ACCOUNT_SELECTION_RULE if val_account_metrics is not None else SELECTION_RULE,
        "test_opened": False,
        "account_mode": "continuous_lot_account" if val_account_metrics is not None else "continuous_proxy",
    }
    if val_account_metrics is not None:
        selection["val_account_metrics"] = val_account_metrics
    (output_dir / "selection.json").write_text(
        json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8"
    )
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/new/train_data_20260831.parquet"))
    parser.add_argument("--features", type=Path, default=Path("artifacts/new_split/feat_roll_new.parquet"))
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/daily_train_val"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-train-records", type=int, default=0)
    parser.add_argument("--max-val-records", type=int, default=0)
    parser.add_argument("--capital", type=float, default=2_000_000)
    parser.add_argument("--lot-size", type=int, default=100)
    args = parser.parse_args()

    train_records = take_records(
        iter_split_records(
            args.raw, args.features, split="train", stride=args.stride,
            include_execution_sidecar=False,
        ),
        args.max_train_records,
    )
    val_proxy_records = take_records(
        iter_split_records(
            args.raw, args.features, split="val", stride=args.stride,
            include_execution_sidecar=False,
        ),
        args.max_val_records,
    )
    val_account_records = take_records(
        iter_split_records(
            args.raw, args.features, split="val", stride=args.stride,
            include_execution_sidecar=True,
        ),
        args.max_val_records,
    )
    run_train_val(
        train_records, val_proxy_records, args.outdir, device=args.device,
        account_records=val_account_records, capital=args.capital,
        lot_size=args.lot_size,
    )


if __name__ == "__main__":
    main()
