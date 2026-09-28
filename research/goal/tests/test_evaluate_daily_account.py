import unittest
from typing import cast

import numpy as np
import pandas as pd
import torch

from models.daily_portfolio_data import DailyRecord
from models.evaluate_daily_account import rollout_policy


class FixedPolicy(torch.nn.Module):
    def forward(self, inputs, valid_mask=None):
        return inputs[..., 0], torch.ones(inputs.shape[:-1], device=inputs.device)


class Float32SoftmaxPolicy(torch.nn.Module):
    def forward(self, inputs, valid_mask=None):
        logits = torch.linspace(-1.0, 1.0, inputs.shape[-2], dtype=torch.float32, device=inputs.device)
        return logits, torch.ones(inputs.shape[:-1], dtype=torch.float32, device=inputs.device)


def record(signal_date, codes, opens, closes, prev_closes, logits=None, sidecar_codes=None,
           sidecar_opens=None, sidecar_closes=None, sidecar_prev_closes=None):
    codes = tuple(codes)
    sidecar_codes = codes if sidecar_codes is None else tuple(sidecar_codes)
    sidecar_opens = opens if sidecar_opens is None else sidecar_opens
    sidecar_closes = closes if sidecar_closes is None else sidecar_closes
    sidecar_prev_closes = prev_closes if sidecar_prev_closes is None else sidecar_prev_closes
    features = np.zeros((len(codes), 49), dtype=np.float32)
    features[:, 0] = np.arange(len(codes), dtype=np.float32) if logits is None else logits
    sidecar = pd.DataFrame({
        "code": sidecar_codes,
        "open": sidecar_opens,
        "close": sidecar_closes,
        "volume": [1_000_000.0] * len(sidecar_codes),
        "amount": [10_000_000.0] * len(sidecar_codes),
        "is_trading": [True] * len(sidecar_codes),
        "prev_close": sidecar_prev_closes,
    })
    reward = pd.DataFrame({
        "code": codes,
        "buy_open": opens,
        "sell_open": closes,
        "buy_amount": [10_000_000.0] * len(codes),
        "reward_valid": [True] * len(codes),
    })
    signal_date = cast(pd.Timestamp, pd.Timestamp(signal_date))
    return DailyRecord(
        signal_date, cast(pd.Timestamp, signal_date + pd.Timedelta(days=1)),
        cast(pd.Timestamp, signal_date + pd.Timedelta(days=5)),
        codes, features, tuple(f"feature_{i}" for i in range(49)), reward, sidecar,
    )


class EvaluateDailyAccountTests(unittest.TestCase):
    def test_rollout_executes_on_t1_buy_date_in_lots_and_carries_account_state(self):
        records = [
            record("2026-01-05", ("A",), [10.0], [11.0], [10.0]),
            record("2026-01-06", ("A", "B"), [20.0, 10.0], [21.0, 10.0], [11.0, 10.0], logits=[-10.0, 10.0]),
        ]

        result = rollout_policy(records, FixedPolicy(), initial_cash=2_000.0, device="cpu")

        self.assertEqual(result["account_mode"], "continuous_lot_account")
        self.assertFalse(result["test_opened"])
        self.assertEqual(result["n_records"], 2)
        self.assertEqual(result["n_trades"], len(result["trades"]))
        self.assertTrue(result["trades"])
        self.assertEqual(result["trades"][0]["date"], "2026-01-06")
        self.assertEqual(
            [(trade["side"], trade["code"]) for trade in result["trades"]],
            [("BUY", "A"), ("SELL", "A"), ("BUY", "B")],
        )
        self.assertEqual(result["trades"][-1]["date"], "2026-01-07")
        self.assertTrue(all(trade["shares"] % 100 == 0 for trade in result["trades"]))
        self.assertGreater(result["fee_total"], 0.0)
        self.assertGreater(result["slip_total"], 0.0)
        self.assertEqual(len(result["nav_points"]), 2)
        self.assertLess(result["cash_end"], result["initial"])
        self.assertEqual(result["locked_or_unpriced_count"], 0)
        self.assertNotEqual(result["final"], result["initial"])

    def test_rollout_sells_holding_from_previous_target_pool_using_full_sidecar(self):
        records = [
            record("2026-01-05", ("A",), [10.0], [11.0], [10.0]),
            record("2026-01-06", ("B",), [10.0], [11.0], [10.0],
                   logits=[1.0], sidecar_codes=("A", "B"), sidecar_opens=[10.0, 10.0],
                   sidecar_closes=[10.0, 11.0], sidecar_prev_closes=[10.0, 10.0]),
        ]

        result = rollout_policy(records, FixedPolicy(), initial_cash=2_000.0, device="cpu")

        self.assertEqual(
            [(trade["side"], trade["code"]) for trade in result["trades"]],
            [("BUY", "A"), ("SELL", "A"), ("BUY", "B")],
        )
        self.assertEqual(result["locked_or_unpriced_count"], 0)

    def test_rollout_rejects_a_record_without_execution_sidecar(self):
        valid = record("2026-01-05", ("A",), [10.0], [10.0], [10.0])
        invalid = DailyRecord(
            cast(pd.Timestamp, valid.signal_date + pd.Timedelta(days=1)), valid.buy_date, valid.sell_date,
            valid.codes, valid.features, valid.feature_columns, valid.reward_sidecar,
        )

        with self.assertRaises(ValueError):
            rollout_policy([valid, invalid], FixedPolicy(), device="cpu")

    def test_cpu_device_is_used_for_auto_gpu_parameter(self):
        result = rollout_policy(
            [record("2026-01-05", ("A",), [10.0], [10.0], [10.0])],
            FixedPolicy(), initial_cash=2_000.0, device="cpu",
        )

        self.assertEqual(result["device"], "cpu")

    def test_rollout_normalizes_float32_softmax_weights_before_execution(self):
        codes = tuple(f"S{i:04d}" for i in range(1000))
        prices = [10.0] * 1000

        result = rollout_policy(
            [record("2026-01-05", codes, prices, prices, prices)],
            Float32SoftmaxPolicy(),
            initial_cash=2_000_000.0,
            device="cpu",
        )

        self.assertEqual(result["n_records"], 1)


if __name__ == "__main__":
    unittest.main()
