import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch

from models.daily_continuous_policy import DailyContinuousPolicy
from models.daily_portfolio_data import DailyRecord
from models.run_daily_test_once import create_test_guard, run_frozen_test


def make_record():
    codes = ("A",) + ("",) * 999
    sidecar = pd.DataFrame({
        "code": ["A"], "open": [10.0], "close": [10.1],
        "volume": [1_000_000.0], "amount": [10_000_000.0],
        "is_trading": [True], "prev_close": [10.0],
    })
    reward = pd.DataFrame({
        "code": codes, "buy_open": np.ones(1000), "sell_open": np.ones(1000),
        "buy_amount": np.ones(1000), "reward_valid": np.zeros(1000, dtype=bool),
    })
    return DailyRecord(
        cast(pd.Timestamp, pd.Timestamp("2026-01-05")), cast(pd.Timestamp, pd.Timestamp("2026-01-06")),
        cast(pd.Timestamp, pd.Timestamp("2026-01-12")), codes, np.zeros((1000, 49), dtype=np.float32),
        tuple(f"f{i}" for i in range(49)), reward, sidecar,
    )


def write_checkpoint(directory, selection=None):
    model = DailyContinuousPolicy(hidden_dim=8)
    checkpoint = {
        "architecture": {"name": "DailyContinuousPolicy", "input_dim": 50, "hidden_dim": 8},
        "model_state": model.state_dict(),
    }
    checkpoint_path = Path(directory) / "checkpoint.pt"
    torch.save(checkpoint, checkpoint_path)
    (Path(directory) / "selection.json").write_text(json.dumps(selection or {
        "test_opened": False, "account_mode": "continuous_lot_account",
    }))
    return checkpoint_path


class RunDailyTestOnceTests(unittest.TestCase):
    def test_create_test_guard_is_atomic_and_rejects_existing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = Path(directory) / "guard.json"
            digest = "a" * 64
            create_test_guard(guard, "run", digest)
            self.assertEqual(json.loads(guard.read_text())["input_sha256"], digest)
            with self.assertRaises(FileExistsError):
                create_test_guard(guard, "run", digest)

    def test_run_requires_explicit_single_use_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = write_checkpoint(directory)
            with self.assertRaises(PermissionError):
                run_frozen_test([make_record()], checkpoint, Path(directory) / "out",
                                Path(directory) / "guard")

    def test_run_rejects_unselected_or_incompatible_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            selection = {"test_opened": False, "account_mode": "continuous_proxy"}
            checkpoint = write_checkpoint(directory, selection)
            with self.assertRaises(PermissionError):
                run_frozen_test([], checkpoint, Path(directory) / "out",
                                Path(directory) / "guard", allow_test_once=True)

    def test_run_creates_guard_before_consuming_records_and_writes_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = write_checkpoint(root)
            records = iter([make_record()])
            guard = root / "guard.json"
            outdir = root / "out"
            run_frozen_test(records, checkpoint, outdir, guard, allow_test_once=True, device="cpu")
            account = json.loads((outdir / "account.json").read_text())
            guard_data = json.loads((outdir / "test_once_guard.json").read_text())
            self.assertTrue(account["test_opened"])
            self.assertEqual(account["test_runs"], 1)
            self.assertEqual(account["device"], "cpu")
            self.assertEqual(account["source_checkpoint_sha256"], hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            self.assertEqual(guard_data["input_sha256"], guard.read_text() and guard_data["input_sha256"])
            self.assertTrue(json.loads((root / "selection.json").read_text())["test_opened"])

    def test_run_rejects_repeated_guard_without_consuming_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = write_checkpoint(root)
            guard = root / "guard.json"
            create_test_guard(guard, "already", "b" * 64)
            consumed = []

            def records():
                consumed.append(True)
                yield make_record()

            with self.assertRaises(FileExistsError):
                run_frozen_test(records(), checkpoint, root / "out", guard, allow_test_once=True)
            self.assertEqual(consumed, [])

    def test_iter_test_records_uses_only_open_ended_2026_test_split(self):
        from models.run_daily_test_once import _iter_test_records

        schema = type("Schema", (), {"names": ["code", "kline_time", *[f"f{i}" for i in range(45)]]})()
        with patch("models.run_daily_test_once.pq.read_schema", return_value=schema), patch(
            "models.run_daily_test_once.iter_daily_records", return_value=iter(())
        ) as iterator:
            list(_iter_test_records("raw", "features", stride=3, max_records=2))
        kwargs = iterator.call_args.kwargs
        self.assertEqual(kwargs["split_start"], "2026-01-01")
        self.assertIsNone(kwargs["split_end"])
        self.assertEqual(kwargs["stride"], 3)


if __name__ == "__main__":
    unittest.main()
