import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import numpy as np
import torch

from models.daily_portfolio_data import DailyRecord
from models.train_daily_continuous import (
    aligned_current_weights,
    evaluate_policy,
    make_synthetic_records,
    resolve_device,
    take_records,
    train_policy,
)


class TrainDailyContinuousTests(unittest.TestCase):
    def test_resolve_device_auto_uses_cuda_when_available(self):
        with patch("models.train_daily_continuous.torch.cuda.is_available", return_value=True):
            self.assertEqual(resolve_device(), torch.device("cuda"))

    def test_resolve_device_auto_falls_back_to_cpu(self):
        with patch("models.train_daily_continuous.torch.cuda.is_available", return_value=False):
            self.assertEqual(resolve_device(), torch.device("cpu"))

    def test_resolve_device_cuda_requires_cuda(self):
        with patch("models.train_daily_continuous.torch.cuda.is_available", return_value=False), self.assertRaisesRegex(RuntimeError, "CUDA"):
            resolve_device("cuda")

    def test_resolve_device_rejects_unknown_device(self):
        with self.assertRaises(ValueError):
            resolve_device("mps")

    def test_aligned_current_weights_uses_codes_and_zero_padding(self):
        got = aligned_current_weights({"B": 0.2, "A": 0.7}, ("A", "", "B"))
        np.testing.assert_allclose(got, [0.7, 0.0, 0.2])

    def test_training_consumes_ordered_records_and_updates_parameters(self):
        records = make_synthetic_records(n_days=4, candidate_limit=3, seed=4)
        model_before = train_policy(make_synthetic_records(n_days=0), epochs=1, hidden_dim=8, device="cpu")[0]
        before = [parameter.detach().clone() for parameter in model_before.parameters()]
        model, metrics = train_policy(iter(records), epochs=1, hidden_dim=8, device="cpu")
        self.assertEqual(metrics["n_records"], 4)
        self.assertGreater(metrics["n_reward_valid"], 0)
        self.assertEqual(metrics["device"], "cpu")
        self.assertEqual(metrics["cuda_available"], torch.cuda.is_available())
        self.assertTrue(any(not torch.equal(old, new.detach()) for old, new in zip(before, model.parameters())))

    def test_policy_input_does_not_include_future_sidecar_fields(self):
        records = make_synthetic_records(n_days=2, candidate_limit=2, seed=8)
        original = records[0].features.copy()
        train_policy(records, epochs=1, hidden_dim=8, device="cpu")
        np.testing.assert_array_equal(records[0].features, original)
        self.assertNotIn("buy_open", records[0].feature_columns)
        self.assertNotIn("sell_open", records[0].feature_columns)

    def test_evaluation_returns_continuous_proxy_metrics(self):
        records = make_synthetic_records(n_days=5, candidate_limit=3, seed=9)
        model, _ = train_policy(records, epochs=1, hidden_dim=8, device="cpu")
        metrics = evaluate_policy(iter(records), model, device="cpu")
        self.assertEqual(metrics["account_mode"], "continuous_proxy")
        for key in ("total", "maxdd", "sharpe", "n_records", "turnover"):
            self.assertIn(key, metrics)
        self.assertEqual(metrics["device"], "cpu")
        self.assertEqual(metrics["n_records"], 5)
        self.assertIn("total", json.loads(json.dumps(metrics)))

    def test_synthetic_records_have_expected_shape(self):
        record = next(iter(make_synthetic_records(n_days=1, candidate_limit=2)))
        self.assertIsInstance(record, DailyRecord)
        self.assertEqual(record.features.shape, (1000, 49))
        self.assertEqual(len(record.codes), 1000)

    def test_take_records_consumes_only_the_requested_prefix_without_caching(self):
        consumed = []

        def source():
            for value in range(5):
                consumed.append(value)
                yield value

        records = take_records(cast(Any, source()), max_records=2)
        self.assertEqual(next(records), 0)
        self.assertEqual(consumed, [0])
        self.assertEqual(list(records), [1])
        self.assertEqual(consumed, [0, 1])

    def test_iter_split_records_passes_stride_to_daily_records(self):
        from models import daily_dataset
        from models.train_daily_continuous import iter_split_records

        with patch("models.train_daily_continuous.pq.read_schema") as read_schema:
            read_schema.return_value.names = ["code", "kline_time", *[f"f{i}" for i in range(45)]]
            with patch.object(daily_dataset, "iter_daily_records", return_value=iter(())) as iter_daily:
                list(iter_split_records("raw", "features", "val", stride=3))

        self.assertEqual(iter_daily.call_args.kwargs["stride"], 3)

    def test_iter_split_records_passes_execution_sidecar_setting(self):
        from models import daily_dataset
        from models.train_daily_continuous import iter_split_records

        with patch("models.train_daily_continuous.pq.read_schema") as read_schema:
            read_schema.return_value.names = ["code", "kline_time", *[f"f{i}" for i in range(45)]]
            with patch.object(daily_dataset, "iter_daily_records", return_value=iter(())) as iter_daily:
                list(iter_split_records("raw", "features", "val", include_execution_sidecar=True))

        self.assertTrue(iter_daily.call_args.kwargs["include_execution_sidecar"])

    def test_cli_records_stride_and_max_records_in_metrics(self):
        from models.train_daily_continuous import main

        model = torch.nn.Sequential(torch.nn.Linear(1, 2))
        cast(Any, model).shared = [type("Layer", (), {"out_features": 2})()]
        records = make_synthetic_records(n_days=1, candidate_limit=2)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "argv", [
                "train_daily_continuous.py", "--split", "val", "--stride", "3",
                "--max-records", "7", "--outdir", directory,
            ]), patch("models.train_daily_continuous.iter_split_records", return_value=iter(records)) as split_records, patch(
                "models.train_daily_continuous.train_policy", return_value=(model, {"n_records": 1})
            ) as train:
                main()

            metrics = json.loads(Path(directory, "metrics.json").read_text(encoding="utf-8"))

        self.assertEqual(split_records.call_args.kwargs["stride"], 3)
        self.assertEqual(metrics["stride"], 3)
        self.assertEqual(metrics["max_records"], 7)
        self.assertEqual(train.call_args.kwargs["device"], "auto")

    def test_cli_passes_explicit_device_to_training(self):
        from models.train_daily_continuous import main

        model = torch.nn.Sequential(torch.nn.Linear(1, 2))
        cast(Any, model).shared = [type("Layer", (), {"out_features": 2})()]
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, "argv", [
            "train_daily_continuous.py", "--split", "val", "--device", "cpu",
            "--outdir", directory,
        ]), patch("models.train_daily_continuous.iter_split_records", return_value=iter(())), patch(
            "models.train_daily_continuous.train_policy", return_value=(model, {"n_records": 0})
        ) as train:
            main()

        self.assertEqual(train.call_args.kwargs["device"], "cpu")

    def test_cli_keeps_test_split_rejected(self):
        from models.train_daily_continuous import main

        with patch.object(sys, "argv", ["train_daily_continuous.py", "--split", "test"]), self.assertRaises(SystemExit):
            main()


if __name__ == "__main__":
    unittest.main()
