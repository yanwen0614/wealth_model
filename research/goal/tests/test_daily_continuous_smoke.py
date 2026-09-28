import json
import tempfile
import unittest
from pathlib import Path

from models.run_daily_continuous_smoke import run_smoke, write_smoke_json


class DailyContinuousSmokeTests(unittest.TestCase):
    def test_runs_twelve_consecutive_signal_days_with_delayed_rewards(self):
        result = run_smoke(seed=7, n_days=12, candidate_limit=20)

        self.assertTrue(result["synthetic_only"])
        self.assertFalse(result["test_opened"])
        self.assertEqual(result["n_signal_days"], 12)
        self.assertEqual(result["n_rewards_realized"], 7)
        self.assertGreater(result["n_trades"], 0)

    def test_reward_is_realized_on_sell_date_and_weights_carry_forward(self):
        result = run_smoke(seed=7, n_days=12, candidate_limit=20)

        rewards = result["reward_events"]
        self.assertEqual(len(rewards), 7)
        self.assertTrue(all(event["realized_date"] == event["sell_date"] for event in rewards))
        self.assertTrue(all(event["realized_date"] > event["signal_date"] for event in rewards))

        states = result["state_trace"]
        self.assertEqual(len(states), 12)
        self.assertTrue(any(state["current_weight_sum"] > 0 for state in states[1:]))
        self.assertTrue(any(state["current_weight_sum"] > 0 for state in states))

    def test_cli_json_has_explicit_synthetic_metadata_without_reading_real_data(self):
        result = run_smoke(seed=3, n_days=12, candidate_limit=10)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = write_smoke_json(result, Path(temp_dir))
            payload = json.loads(output.read_text())

        self.assertEqual(payload["split_metadata"]["TRAIN"], "synthetic")
        self.assertEqual(payload["split_metadata"]["VAL"], "synthetic")
        self.assertEqual(payload["split_metadata"]["TEST"], "synthetic")
        for key in ("n_signal_days", "n_rewards_realized", "final_cash", "n_trades"):
            self.assertIn(key, payload)
        self.assertTrue(payload["synthetic_only"])
        self.assertFalse(payload["test_opened"])


if __name__ == "__main__":
    unittest.main()
