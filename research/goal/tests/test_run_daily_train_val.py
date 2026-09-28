import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import torch

from models.daily_continuous_policy import DailyContinuousPolicy
from models.evaluate_daily_account import rollout_policy
from models.run_daily_train_val import main, run_train_val
from models.train_daily_continuous import make_synthetic_records


class RunDailyTrainValTests(unittest.TestCase):
    def test_script_entrypoint_supports_help_from_project_root(self):
        project_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "models/run_daily_train_val.py", "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)

    def test_run_train_val_trains_only_train_and_evaluates_val(self):
        train_records = make_synthetic_records(n_days=3, candidate_limit=3, seed=1)
        val_records = make_synthetic_records(n_days=2, candidate_limit=3, seed=2)
        torch.manual_seed(123)
        initial_state = DailyContinuousPolicy(hidden_dim=8).state_dict()
        torch.manual_seed(123)
        with tempfile.TemporaryDirectory() as directory:
            result = run_train_val(
                train_records, val_records, directory, device="cpu", epochs=1,
                hidden_dim=8,
            )

            checkpoint = torch.load(Path(directory, "checkpoint.pt"), weights_only=True)
            selection = json.loads(Path(directory, "selection.json").read_text())

        self.assertGreater(result["train_metrics"]["n_records"], 0)
        self.assertEqual(result["val_metrics"]["n_records"], 2)
        self.assertEqual(checkpoint["device"], "cpu")
        self.assertIn("model_state", checkpoint)
        self.assertEqual(checkpoint["architecture"]["hidden_dim"], 8)
        self.assertTrue(
            any(
                not torch.equal(initial_state[name], checkpoint["model_state"][name])
                for name in initial_state
            )
        )
        self.assertEqual(selection["train_metrics"], result["train_metrics"])
        self.assertEqual(selection["val_metrics"], result["val_metrics"])
        self.assertEqual(
            selection["selection_rule"],
            "VAL continuous_proxy: total - 0.5*maxdd, tie-break sharpe",
        )
        self.assertFalse(selection["test_opened"])
        self.assertEqual(selection["account_mode"], "continuous_proxy")

    def test_run_train_val_passes_device_to_training_and_validation(self):
        train_records = make_synthetic_records(n_days=1, candidate_limit=2)
        val_records = make_synthetic_records(n_days=1, candidate_limit=2)
        with tempfile.TemporaryDirectory() as directory, patch(
            "models.run_daily_train_val.train_policy"
        ) as train, patch("models.run_daily_train_val.evaluate_policy") as evaluate:
            model = torch.nn.Linear(1, 1)
            train.return_value = (model, {"n_records": 1})
            evaluate.return_value = {"total": 0.0, "maxdd": 0.0, "sharpe": 0.0}
            run_train_val(train_records, val_records, directory, device="cuda", epochs=3)

        self.assertEqual(train.call_args.kwargs["device"], "cuda")
        self.assertEqual(train.call_args.kwargs["epochs"], 3)
        self.assertIs(train.call_args.args[0], train_records)
        self.assertIs(evaluate.call_args.args[0], val_records)
        self.assertEqual(evaluate.call_args.kwargs["device"], "cuda")

    def test_run_train_val_records_account_metrics_and_uses_account_selection_rule(self):
        records = make_synthetic_records(n_days=1, candidate_limit=2, seed=3)
        sidecar = pd.DataFrame({
            "code": ["S0000", "S0001"], "open": [10.0, 10.0],
            "close": [10.1, 10.0], "volume": [1_000_000.0] * 2,
            "amount": [10_000_000.0] * 2, "is_trading": [True, True],
            "prev_close": [10.0, 10.0],
        })
        account_records = [records[0].__class__(
            records[0].signal_date, records[0].buy_date, records[0].sell_date,
            records[0].codes, records[0].features, records[0].feature_columns,
            records[0].reward_sidecar, sidecar,
        )]
        with tempfile.TemporaryDirectory() as directory, patch(
            "models.run_daily_train_val.train_policy"
        ) as train, patch(
            "models.run_daily_train_val.evaluate_policy",
            return_value={"total": 0.1, "maxdd": 0.2, "sharpe": 0.4},
        ), patch(
            "models.run_daily_train_val.rollout_policy",
            wraps=rollout_policy,
        ) as rollout:
            model = DailyContinuousPolicy(hidden_dim=8)
            train.return_value = (model, {"n_records": 1})
            selection = run_train_val(
                records, records, directory, device="cpu",
                account_records=account_records, capital=1234.0, lot_size=10,
            )

        self.assertEqual(selection["val_account_metrics"]["account_mode"], "continuous_lot_account")
        self.assertEqual(selection["val_account_metrics"]["n_records"], 1)
        self.assertEqual(
            selection["selection_rule"],
            "VAL account: total - 0.5*maxdd, tie-break sharpe; proxy metrics diagnostic",
        )
        self.assertEqual(selection["account_mode"], "continuous_lot_account")
        self.assertFalse(selection["test_opened"])
        self.assertIs(rollout.call_args.args[0], account_records)
        self.assertIs(rollout.call_args.args[1], model)
        self.assertEqual(rollout.call_args.kwargs, {
            "device": "cpu", "initial_cash": 1234.0, "lot_size": 10,
        })

    def test_cli_builds_independent_val_iterators_with_shared_limits_and_no_test(self):
        records = make_synthetic_records(n_days=1, candidate_limit=2)
        with tempfile.TemporaryDirectory() as directory, patch.object(
            sys, "argv", [
                "run_daily_train_val.py", "--raw", "raw.parquet",
                "--features", "features.parquet", "--outdir", directory,
                "--stride", "3", "--max-train-records", "7",
                "--max-val-records", "5", "--device", "cpu",
                "--capital", "1234", "--lot-size", "10",
            ]
        ), patch(
            "models.run_daily_train_val.iter_split_records",
            side_effect=[iter(records), iter(records), iter(records)],
        ) as split, patch(
            "models.run_daily_train_val.take_records",
            side_effect=lambda records, max_records: records,
        ) as take, patch("models.run_daily_train_val.run_train_val") as run:
            main()

        self.assertEqual(split.call_count, 3)
        self.assertEqual(split.call_args_list[0].kwargs["split"], "train")
        self.assertEqual(split.call_args_list[1].kwargs["split"], "val")
        self.assertEqual(split.call_args_list[2].kwargs["split"], "val")
        self.assertEqual(split.call_args_list[0].kwargs["stride"], 3)
        self.assertEqual(split.call_args_list[1].kwargs["stride"], 3)
        self.assertEqual(split.call_args_list[2].kwargs["stride"], 3)
        self.assertEqual([call.args[1] for call in take.call_args_list], [7, 5, 5])
        self.assertEqual(run.call_args.args[2], Path(directory))
        self.assertEqual(run.call_args.kwargs["device"], "cpu")
        self.assertEqual(run.call_args.kwargs["capital"], 1234.0)
        self.assertEqual(run.call_args.kwargs["lot_size"], 10)
        self.assertIsNotNone(run.call_args.kwargs["account_records"])
        self.assertEqual(split.call_args_list[0].kwargs["include_execution_sidecar"], False)
        self.assertEqual(split.call_args_list[1].kwargs["include_execution_sidecar"], False)
        self.assertEqual(split.call_args_list[2].kwargs["include_execution_sidecar"], True)

    def test_cli_rejects_test_arguments(self):
        with patch.object(sys, "argv", ["run_daily_train_val.py", "--test"]), self.assertRaises(SystemExit):
            main()


if __name__ == "__main__":
    unittest.main()
