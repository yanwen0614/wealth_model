"""Run the frozen daily policy against TEST exactly once.

阶段 3 G02 决策：训练后评估链仅 legacy（opt-in 可达），不接 adapter——
torch checkpoint 接线超收口范围（见 evaluate_daily_account 注释）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import pyarrow.parquet as pq
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.daily_continuous_policy import DailyContinuousPolicy
from models.daily_dataset import iter_daily_records
from models.evaluate_daily_account import rollout_policy


def create_test_guard(path, command, input_sha256):
    """Create a JSON guard with O_EXCL, refusing an existing guard atomically."""
    guard_path = Path(path)
    guard_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "command": str(command),
        "input_sha256": str(input_sha256),
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(guard_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
    except BaseException:
        try:
            guard_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return payload


def _checkpoint_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selection_path(checkpoint_path: Path, outdir: Path) -> Path:
    candidates = (checkpoint_path.parent / "selection.json", outdir.parent / "selection.json")
    for candidate in candidates:
        if candidate.is_file():
            try:
                selection = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if selection.get("test_opened") is False and selection.get("account_mode") == "continuous_lot_account":
                return candidate
    raise PermissionError("selection.json is missing beside checkpoint or under outdir parent")


def _load_frozen_model(checkpoint_path: Path, device: str):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or "architecture" not in checkpoint or "model_state" not in checkpoint:
        raise PermissionError("checkpoint must contain architecture and model_state")
    architecture = checkpoint["architecture"]
    if not isinstance(architecture, dict) or architecture.get("name") != "DailyContinuousPolicy":
        raise PermissionError("checkpoint architecture is not DailyContinuousPolicy")
    if architecture.get("input_dim") != 50 or not isinstance(architecture.get("hidden_dim"), int):
        raise PermissionError("checkpoint architecture is incompatible")
    if not isinstance(checkpoint["model_state"], dict):
        raise PermissionError("checkpoint model_state is invalid")
    model = DailyContinuousPolicy(hidden_dim=architecture["hidden_dim"])
    try:
        model.load_state_dict(checkpoint["model_state"], strict=True)
    except (RuntimeError, TypeError) as exc:
        raise PermissionError("checkpoint model_state does not match architecture") from exc
    return model


def run_frozen_test(
    records: Iterable,
    checkpoint_path,
    outdir,
    guard_path,
    allow_test_once: bool = False,
    capital: float = 2_000_000,
    lot_size: int = 100,
    device: str = "auto",
):
    """Open the frozen TEST account once, after all preflight checks pass."""
    if not allow_test_once:
        raise PermissionError("frozen TEST requires allow_test_once=True")
    checkpoint = Path(checkpoint_path)
    output_dir = Path(outdir)
    guard = Path(guard_path)
    if guard.exists():
        raise FileExistsError(guard)
    source_sha256 = _checkpoint_sha256(checkpoint)
    model = _load_frozen_model(checkpoint, device)
    selection_path = _selection_path(checkpoint, output_dir)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))

    guard_data = create_test_guard(guard, "run_frozen_test", source_sha256)
    result = rollout_policy(
        records, model, initial_cash=capital, lot_size=lot_size, device=device,
    )
    result.update({
        "test_opened": True,
        "test_runs": 1,
        "source_checkpoint_sha256": source_sha256,
    })
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "account.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8",
    )
    (output_dir / "test_once_guard.json").write_text(
        json.dumps(guard_data, indent=2, sort_keys=True), encoding="utf-8",
    )
    selection["test_opened"] = True
    selection_path.write_text(
        json.dumps(selection, indent=2, sort_keys=True), encoding="utf-8",
    )
    return result


def _iter_test_records(raw_path, feature_path, stride=1, max_records=0):
    feature_columns = [
        name for name in pq.read_schema(feature_path).names
        if name not in {"code", "kline_time", "_roll_valid"}
    ]
    if len(feature_columns) != 45:
        raise ValueError(f"feature parquet must contain exactly 45 features, found {len(feature_columns)}")
    records = (
        record for record, _ in iter_daily_records(
            raw_path, feature_path, feature_columns,
            split_start="2026-01-01", split_end=None,
            stride=stride, candidate_limit=1000,
        )
    )
    if max_records <= 0:
        yield from records
        return
    for index, record in enumerate(records):
        if index >= max_records:
            break
        yield record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--guard", type=Path, required=True)
    parser.add_argument("--allow-test-once", action="store_true")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--capital", type=float, default=2_000_000)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-records", type=int, default=0)
    args = parser.parse_args()
    if not args.allow_test_once:
        parser.error("--allow-test-once is required")
    run_frozen_test(
        _iter_test_records(args.raw, args.features, args.stride, args.max_records),
        args.checkpoint, args.outdir, args.guard,
        allow_test_once=True, capital=args.capital, lot_size=args.lot_size,
        device=args.device,
    )


if __name__ == "__main__":
    main()
