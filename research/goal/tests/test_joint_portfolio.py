import json
import sys
import tempfile
import unittest
from itertools import pairwise
from pathlib import Path
from typing import cast
from unittest import mock

import numpy as np
import pandas as pd
import torch

from backtest.account_engine_joint import (
    append_final_nav_metrics,
    create_test_guard,
    final_liquidation,
    postprocess_account,
)
from models.joint_portfolio import (
    NEW_SCALER,
    JointPortfolioPolicy,
    _code_aligned_previous_weights,
    _mark_to_market_holdings,
    _write_episodes,
    assemble_episode,
    is_valid_episode_window,
    joint_episode_loss,
    main,
    make_rebalance_dates,
    past_hand_features,
    policy_weights,
    project_policy_scores,
    proxy_episode_return,
    train_joint_policy,
)
from models.run_joint_e2e import advance_projected_holdings, select_trial


class JointPortfolioTests(unittest.TestCase):
    @staticmethod
    def _episode_frame():
        dates = pd.bdate_range("2023-01-02", periods=65)
        rows = []
        for code_index, code in enumerate(("A", "B", "C")):
            for index, date in enumerate(dates):
                row = {
                    "code": code,
                    "kline_time": date,
                    "close": 10.0 + code_index + index,
                    "open": 10.5 + code_index + index,
                    "amount": float((code_index + 1) * 1_000 + index),
                    "is_trading": True,
                    "_roll_valid": True,
                }
                row.update({f"feature_{column}": float(index + column) for column in range(45)})
                rows.append(row)
        return pd.DataFrame(rows), dates

    def test_assemble_episode_keeps_signal_features_separate_from_rewards(self):
        frame, dates = self._episode_frame()
        feature_columns = [f"feature_{column}" for column in range(45)]

        episode = assemble_episode(
            frame, dates[60], feature_columns, horizon=2, split_end=dates[-1], candidate_limit=2
        )

        self.assertEqual(episode.features.shape, (2, 49))
        self.assertEqual(episode.signal_date, dates[60])
        self.assertLess(episode.signal_date, episode.buy_date)
        self.assertLess(episode.buy_date, episode.sell_date)
        self.assertEqual(episode.reward_sidecar["code"].tolist(), ["C", "B"])
        self.assertEqual(set(episode.reward_columns), {"buy_open", "sell_open", "buy_amount"})
        self.assertTrue(set(episode.reward_columns).isdisjoint(episode.feature_columns))
        self.assertFalse(np.isin(episode.reward_sidecar.to_numpy(), episode.features).all())

    def test_assemble_episode_rejects_reward_window_crossing_split(self):
        frame, dates = self._episode_frame()
        feature_columns = [f"feature_{column}" for column in range(45)]

        self.assertFalse(
            is_valid_episode_window(frame, "A", dates[62], horizon=2, split_end=dates[63])
        )
        with self.assertRaises(ValueError):
            assemble_episode(
                frame, dates[62], feature_columns, horizon=2, split_end=dates[63]
            )

    def test_past_hand_features_use_only_closes_through_signal(self):
        closes = np.arange(1.0, 22.0)

        got = past_hand_features(closes)

        returns = closes[1:] / closes[:-1] - 1.0
        self.assertTrue(np.allclose(got[:2], [returns[-5:].mean(), returns[-20:].mean()]))
        self.assertAlmostEqual(got[3], closes[-1] / closes[-20] - 1.0)

    def test_future_data_cannot_change_signal_candidate_pool_or_features(self):
        frame, dates = self._episode_frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        before = assemble_episode(frame, dates[60], feature_columns, horizon=2, candidate_limit=2)
        future = frame.copy()
        future.loc[
            (future["code"] == "C") & (future["kline_time"] > dates[60]),
            ["open", "is_trading", "amount"],
        ] = [np.nan, False, np.nan]

        after = assemble_episode(future, dates[60], feature_columns, horizon=2, candidate_limit=2)

        self.assertEqual(after.codes, before.codes)
        self.assertTrue(np.array_equal(after.features, before.features))
        self.assertFalse(after.reward_valid[0])
        self.assertTrue(np.isfinite(after.reward_sidecar.loc[0, ["buy_open", "sell_open", "buy_amount"]]).all())

    def test_invalid_future_reward_is_retained_and_candidate_pool_is_padded(self):
        frame, dates = self._episode_frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        frame.loc[(frame["code"] == "C") & (frame["kline_time"] == dates[61]), "is_trading"] = False

        episode = assemble_episode(frame, dates[60], feature_columns, horizon=2, candidate_limit=4)

        self.assertEqual(episode.features.shape, (4, 49))
        self.assertEqual(episode.codes[:3], ("C", "B", "A"))
        self.assertEqual(episode.codes[3], "")
        self.assertFalse(episode.reward_valid[0])
        self.assertFalse(episode.reward_valid[3])
        self.assertTrue(np.array_equal(episode.features[3], np.zeros(49, dtype=np.float32)))
        self.assertTrue(np.isfinite(episode.reward_sidecar[["buy_open", "sell_open", "buy_amount"]].to_numpy()).all())

    def test_assemble_episode_rejects_reward_fields_and_wrong_feature_width(self):
        frame, dates = self._episode_frame()
        features = [f"feature_{column}" for column in range(45)]
        for invalid_features in (features[:-1], features + ["buy_open"], features + ["sell_open"]):
            with self.subTest(invalid_features=invalid_features[-2:]), self.assertRaises(ValueError):
                assemble_episode(frame, dates[60], invalid_features, horizon=2)

    def test_write_episodes_pads_variable_candidate_inputs_and_round_trips_schema(self):
        frame, dates = self._episode_frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        full = assemble_episode(frame, dates[60], feature_columns, horizon=2, candidate_limit=3)
        sparse_frame = frame.copy()
        sparse_frame.loc[
            (sparse_frame["code"] != "C") & (sparse_frame["kline_time"] == dates[60]), "amount"
        ] = 0.0
        sparse = assemble_episode(sparse_frame, dates[60], feature_columns, horizon=2, candidate_limit=3)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.npz"
            _write_episodes(path, [full, sparse])
            with np.load(path, allow_pickle=False) as saved:
                self.assertEqual(
                    set(saved.files),
                    {"features", "codes", "feature_columns", "signal_dates", "buy_dates", "sell_dates", "buy_open", "sell_open", "buy_amount", "reward_valid"},
                )
                self.assertEqual(saved["features"].shape, (2, 3, 49))
                self.assertEqual(saved["codes"].shape, (2, 3))
                self.assertEqual(saved["feature_columns"].shape, (49,))
                self.assertEqual(saved["reward_valid"].dtype, np.dtype(bool))
                self.assertTrue(np.array_equal(saved["features"][1, 1:], np.zeros((2, 49), dtype=np.float32)))

    def test_rebalance_dates_leave_horizon_inside_split(self):
        dates = pd.bdate_range("2023-01-02", periods=150)
        got = make_rebalance_dates(dates, warmup=60, horizon=41, stride=40)
        self.assertEqual(list(got), [dates[60], dates[100]])

    def test_episode_signals_do_not_precede_prior_sell_date(self):
        dates = pd.bdate_range("2023-01-02", periods=200)
        signals = make_rebalance_dates(dates, warmup=60, horizon=41, stride=41)

        for previous, current in pairwise(signals):
            self.assertGreaterEqual(current, previous + pd.offsets.BDay(41))

    def test_projection_keeps_topn_and_is_deterministic(self):
        pred = project_policy_scores(codes=["A", "B", "C"], scores=[3, 2, 1], topn=2)

        self.assertEqual(pred["code"].tolist(), ["A", "B"])
        self.assertEqual(pred["score"].tolist(), [3.0, 2.0])
        self.assertEqual(pred["future_ret_5d"].tolist(), [0.0, 0.0])

    def test_projection_marks_prior_target_to_market_before_code_alignment(self):
        prior = {"A": 0.5, "B": 0.5}
        got = advance_projected_holdings(
            prior, np.asarray(["A", "B"]), np.asarray([True, True]),
            np.asarray([10.0, 10.0]), np.asarray([20.0, 10.0]),
        )

        self.assertAlmostEqual(got["A"], 2.0 / 3.0)
        self.assertAlmostEqual(got["B"], 1.0 / 3.0)

    def test_select_trial_uses_objective_before_annual(self):
        winner = select_trial([
            {"id": "high_annual", "annual": 0.30, "maxdd": 0.30, "sharpe": 3.0},
            {"id": "better_objective", "annual": 0.29, "maxdd": 0.02, "sharpe": 1.0},
        ])

        self.assertEqual(winner["id"], "better_objective")

    def test_final_liquidation_charges_v6_costs_and_uses_final_open(self):
        result = final_liquidation(
            holdings={"A": {"shares": 100, "buy_price": 10.0, "buy_fee": 5.0}}, cash=0.0,
            final_rows={"A": {"open": 12.0, "volume": 1_000_000.0, "amount": 12_000_000.0, "close": 12.0}},
            final_date=cast(pd.Timestamp, pd.Timestamp("2026-06-10")),
        )

        self.assertEqual(result["trades"][0]["date"], "2026-06-10")
        self.assertLess(result["cash"], 1200.0)
        self.assertGreater(result["fee_total"], 0.0)
        self.assertGreater(result["slip_total"], 0.0)

    def test_final_liquidation_locks_missing_open_at_last_close_before_cutoff(self):
        result = final_liquidation(
            holdings={"HALT": {"shares": 100, "buy_price": 10.0, "buy_fee": 5.0}}, cash=0.0,
            final_rows={}, final_date=cast(pd.Timestamp, pd.Timestamp("2026-06-10")),
            last_marks={"HALT": {"date": pd.Timestamp("2026-06-09"), "close": 11.0}},
        )

        self.assertEqual(result["locked_final"][0]["code"], "HALT")
        self.assertEqual(result["locked_final"][0]["last_mark_date"], "2026-06-09")
        self.assertEqual(result["locked_final"][0]["value"], 1100.0)

    def test_final_nav_point_is_included_in_risk_metrics(self):
        account = append_final_nav_metrics({"initial": 100.0, "final": 110.0}, [100.0, 120.0], 90.0)

        self.assertEqual(account["nav_points"], [100.0, 120.0, 90.0])
        self.assertTrue(account["final_mark_included"])
        self.assertAlmostEqual(account["maxdd"], 0.25)

    def test_postprocess_adds_final_point_without_touching_trade_or_guard_paths(self):
        result = postprocess_account(
            {"initial": 100.0, "annual_days_basis": 81}, [100.0, 120.0], 90.0, [], "trade-hash", "2026-08-06"
        )

        self.assertTrue(result["final_mark_included"])
        self.assertTrue(result["postprocessed_no_new_test_run"])
        self.assertEqual(result["source_trade_csv_sha256"], "trade-hash")
        self.assertAlmostEqual(result["maxdd"], 0.25)

    def test_test_guard_refuses_existing_and_records_reproducibility(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = Path(directory) / "test_once_guard.json"
            create_test_guard(guard, ["wrapper", "--pred", "test.parquet"], "abc")
            with self.assertRaises(FileExistsError):
                create_test_guard(guard, ["wrapper", "--pred", "test.parquet"], "abc")
            payload = json.loads(guard.read_text(encoding="ascii"))
            self.assertEqual(payload["input_sha256"], "abc")
            self.assertIn("timestamp_utc", payload)

    def test_rebalance_dates_include_exact_end_and_exclude_overflow(self):
        dates = pd.bdate_range("2023-01-02", periods=101)
        self.assertEqual(
            list(make_rebalance_dates(dates, warmup=60, horizon=40, stride=40)),
            [dates[60]],
        )
        self.assertEqual(
            list(make_rebalance_dates(dates[:-1], warmup=60, horizon=40, stride=40)),
            [],
        )

    def test_rebalance_dates_are_empty_when_horizon_exceeds_available_dates(self):
        dates = pd.bdate_range("2023-01-02", periods=20)
        for horizon in (21, 41):
            with self.subTest(horizon=horizon):
                self.assertEqual(
                    list(make_rebalance_dates(dates, warmup=0, horizon=horizon, stride=1)),
                    [],
                )

    def test_rebalance_date_parameters_are_valid(self):
        dates = pd.bdate_range("2023-01-02", periods=101)
        for kwargs in (
            {"warmup": -1},
            {"horizon": -1},
            {"horizon": 0},
            {"stride": 0},
            {"stride": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                make_rebalance_dates(dates, **kwargs)

    def test_policy_weights_are_long_only_and_sum_to_one(self):
        previous = torch.tensor([0.5, 0.5])
        weights, turnover = policy_weights(
            torch.tensor([2.0, 1.0]), previous, 1.0, 0.2
        )
        self.assertTrue(torch.all(weights >= 0))
        self.assertTrue(torch.isclose(weights.sum(), torch.tensor(1.0)))
        self.assertTrue(torch.isfinite(turnover))
        self.assertTrue(torch.isclose(turnover, (weights - previous).abs().sum()))

    def test_policy_weights_opens_first_episode_from_cash(self):
        logits = torch.tensor([2.0, 1.0])
        weights, turnover = policy_weights(logits, torch.zeros(2), 0.0, 0.2)
        self.assertTrue(torch.isclose(weights.sum(), torch.tensor(1.0)))
        self.assertTrue(torch.allclose(weights, torch.softmax(logits / 0.2, dim=-1)))
        self.assertTrue(torch.isclose(turnover, torch.tensor(1.0)))

    def test_policy_weights_accepts_float_rounding_in_partial_holdings(self):
        weights, _ = policy_weights(
            torch.tensor([1.0, 0.0]), torch.tensor([0.50000006, 0.50000006]),
            0.5, 1.0, allow_partial_previous=True,
        )

        self.assertTrue(torch.isclose(weights.sum(), torch.tensor(1.0)))

    def test_policy_weights_reject_invalid_vectors_and_scalars(self):
        valid_previous = torch.tensor([0.5, 0.5])
        invalid_calls = [
            (torch.zeros(2, 1), valid_previous, 1.0, 0.2),
            (torch.zeros(2), torch.zeros(1, 2), 1.0, 0.2),
            (torch.zeros(3), valid_previous, 1.0, 0.2),
            (torch.zeros(2), torch.tensor([-0.1, 1.1]), 1.0, 0.2),
            (torch.zeros(2), torch.tensor([0.4, 0.4]), 1.0, 0.2),
            (torch.zeros(2), torch.tensor([float("nan"), 1.0]), 1.0, 0.2),
            (torch.zeros(2), valid_previous, -0.1, 0.2),
            (torch.zeros(2), valid_previous, 1.1, 0.2),
            (torch.zeros(2), valid_previous, float("nan"), 0.2),
            (torch.zeros(2), valid_previous, 1.0, 0.0),
            (torch.zeros(2), valid_previous, 1.0, float("inf")),
        ]
        for args in invalid_calls:
            with self.subTest(args=args), self.assertRaises(ValueError):
                policy_weights(*args)

    def test_proxy_return_uses_replacement_and_execution_amount(self):
        logits = torch.tensor([1.0, 0.0])
        previous = torch.tensor([0.5, 0.5])
        returns = torch.tensor([0.1, -0.1])
        small_amount = torch.tensor([1.0, 1.0])
        large_amount = torch.tensor([100.0, 100.0])

        held = proxy_episode_return(
            logits, previous, returns, small_amount, replacement=0.0
        )
        traded_small = proxy_episode_return(
            logits, previous, returns, small_amount, replacement=1.0
        )
        traded_large = proxy_episode_return(
            logits, previous, returns, large_amount, replacement=1.0
        )

        self.assertTrue(torch.isclose(held, torch.dot(previous, returns)))
        self.assertLess(traded_small.item(), traded_large.item())

    def test_proxy_return_matches_two_asset_cost_formula(self):
        logits = torch.log(torch.tensor([3.0, 1.0], dtype=torch.float64))
        previous = torch.tensor([0.5, 0.5], dtype=torch.float64)
        returns = torch.tensor([0.1, -0.2], dtype=torch.float64)
        amount = torch.tensor([100.0, 200.0], dtype=torch.float64)
        notional, fee_rate, impact_rate, eps = 1000.0, 0.01, 0.02, 1e-6

        value = proxy_episode_return(
            logits,
            previous,
            returns,
            amount,
            replacement=1.0,
            temperature=1.0,
            notional=notional,
            fee_rate=fee_rate,
            impact_rate=impact_rate,
            eps=eps,
        )
        weights = torch.tensor([0.75, 0.25], dtype=torch.float64)
        delta = weights - previous
        expected = torch.dot(weights, returns) - fee_rate * delta.abs().sum()
        expected -= impact_rate * torch.sum(
            torch.sqrt(delta.abs() * notional / amount + eps) * delta.abs()
        )
        self.assertTrue(torch.isclose(value, expected, atol=1e-12, rtol=1e-12))

    def test_proxy_return_rejects_misaligned_or_invalid_amounts(self):
        args = (torch.zeros(2), torch.tensor([0.5, 0.5]), torch.zeros(2))
        for amount in (torch.ones(3), torch.tensor([1.0, 0.0]), torch.tensor([1.0, float("nan")])):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                proxy_episode_return(*args, amount)

    def test_proxy_return_rejects_invalid_controls_and_returns(self):
        logits = torch.zeros(2)
        previous = torch.tensor([0.5, 0.5])
        amount = torch.ones(2)
        invalid_calls = [
            (torch.zeros(3), amount, {}),
            (torch.tensor([0.0, float("nan")]), amount, {}),
            (torch.zeros(2), amount, {"notional": 0.0}),
            (torch.zeros(2), amount, {"notional": float("nan")}),
            (torch.zeros(2), amount, {"fee_rate": -0.001}),
            (torch.zeros(2), amount, {"fee_rate": float("inf")}),
            (torch.zeros(2), amount, {"impact_rate": -0.001}),
            (torch.zeros(2), amount, {"impact_rate": float("nan")}),
            (torch.zeros(2), amount, {"eps": 0.0}),
            (torch.zeros(2), amount, {"eps": float("inf")}),
        ]
        for returns, execution_amount, kwargs in invalid_calls:
            with self.subTest(returns=returns, kwargs=kwargs), self.assertRaises(ValueError):
                proxy_episode_return(
                    logits, previous, returns, execution_amount, **kwargs
                )

    def test_proxy_return_cost_has_nonzero_finite_gradient(self):
        logits = torch.tensor([1.0, 0.0], requires_grad=True)
        value = proxy_episode_return(
            logits,
            torch.tensor([0.5, 0.5]),
            torch.zeros(2),
            torch.tensor([10.0, 10.0]),
        )
        value.backward()
        self.assertTrue(torch.isfinite(cast(torch.Tensor, logits.grad)).all())
        self.assertGreater(cast(torch.Tensor, logits.grad).abs().sum().item(), 0.0)

    def test_proxy_return_promotes_cpu_inputs_without_losing_gradient(self):
        for logits_dtype, expected_dtype in (
            (torch.float16, torch.float32),
            (torch.float64, torch.float64),
        ):
            with self.subTest(logits_dtype=logits_dtype):
                logits = torch.tensor([1.0, 0.0], dtype=logits_dtype, requires_grad=True)
                value = proxy_episode_return(
                    logits,
                    torch.tensor([0.5, 0.5], dtype=torch.float32),
                    torch.tensor([0.1, -0.1], dtype=torch.float32),
                    torch.tensor([10.0, 10.0], dtype=torch.float32),
                )
                value.backward()
                self.assertEqual(value.dtype, expected_dtype)
                self.assertTrue(torch.isfinite(value))
                self.assertTrue(torch.isfinite(cast(torch.Tensor, logits.grad)).all())

    def test_policy_outputs_joint_selection_and_bounded_replacement(self):
        model = JointPortfolioPolicy(n_features=49)

        logits, replacement = model(torch.zeros(7, 49))

        self.assertEqual(logits.shape, (7,))
        self.assertEqual(replacement.shape, ())
        self.assertGreaterEqual(replacement.item(), 0.0)
        self.assertLessEqual(replacement.item(), 1.0)

    def test_joint_loss_forces_padding_to_zero_weight(self):
        logits = torch.tensor([1.0, 100.0], requires_grad=True)
        loss, weights, proxy_return = joint_episode_loss(
            logits=logits,
            replacement=torch.tensor(1.0),
            previous_weights=torch.zeros(2),
            codes=np.asarray(["A", ""]),
            reward_valid=np.asarray([True, False]),
            buy_open=np.asarray([10.0, 0.0]),
            sell_open=np.asarray([11.0, 0.0]),
            buy_amount=np.asarray([1e8, 0.0]),
            temperature=0.5,
            turnover_penalty=0.0,
        )

        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(torch.isfinite(proxy_return))
        self.assertTrue(torch.allclose(weights, torch.tensor([1.0, 0.0])))

    def test_joint_loss_assigns_invalid_nonpadding_name_minus_one_return(self):
        kwargs = {
            "replacement": torch.tensor(1.0),
            "previous_weights": torch.zeros(2),
            "codes": np.asarray(["GOOD", "BAD"]),
            "reward_valid": np.asarray([True, False]),
            "buy_open": np.asarray([10.0, 10.0]),
            "sell_open": np.asarray([11.0, 0.0]),
            "buy_amount": np.asarray([1e8, 1e8]),
            "temperature": 0.5,
            "turnover_penalty": 0.0,
        }

        _, _, good_proxy = joint_episode_loss(logits=torch.tensor([8.0, 0.0]), **kwargs)
        _, _, invalid_proxy = joint_episode_loss(logits=torch.tensor([0.0, 8.0]), **kwargs)

        self.assertLess(invalid_proxy.item(), good_proxy.item())

    def test_joint_loss_has_finite_gradient_and_carries_previous_weights(self):
        logits = torch.tensor([1.0, 0.0, 9.0], requires_grad=True)
        loss, weights, _ = joint_episode_loss(
            logits=logits,
            replacement=torch.tensor(0.5),
            previous_weights=torch.tensor([0.5, 0.5, 0.0]),
            codes=np.asarray(["A", "B", ""]),
            reward_valid=np.asarray([True, True, False]),
            buy_open=np.asarray([10.0, 10.0, 0.0]),
            sell_open=np.asarray([11.0, 9.0, 0.0]),
            buy_amount=np.asarray([1e8, 1e8, 0.0]),
            temperature=0.5,
            turnover_penalty=0.001,
        )
        loss.backward()

        self.assertTrue(torch.isfinite(loss))
        self.assertTrue(torch.isfinite(cast(torch.Tensor, logits.grad)).all())
        self.assertEqual(weights[2].item(), 0.0)
        self.assertTrue(torch.isclose(weights.sum(), torch.tensor(1.0)))

    @staticmethod
    def _training_npz(path, signal_date, buy_date, sell_date):
        np.savez_compressed(
            path,
            features=np.ones((2, 2, 49), dtype=np.float32),
            codes=np.asarray([["A", "B"], ["B", "C"]]),
            reward_valid=np.ones((2, 2), dtype=bool),
            feature_columns=np.asarray([f"feature_{index}" for index in range(49)]),
            buy_open=np.full((2, 2), 10.0, dtype=np.float32),
            sell_open=np.full((2, 2), 11.0, dtype=np.float32),
            buy_amount=np.full((2, 2), 1e8, dtype=np.float32),
            signal_dates=np.asarray([signal_date, signal_date], dtype="datetime64[ns]"),
            buy_dates=np.asarray([buy_date, buy_date], dtype="datetime64[ns]"),
            sell_dates=np.asarray([sell_date, sell_date], dtype="datetime64[ns]"),
        )

    @staticmethod
    def _replace_npz_field(path, field, value):
        with np.load(path, allow_pickle=False) as source:
            fields = {name: source[name] for name in source.files}
        fields[field] = value
        np.savez_compressed(path, **fields)

    def test_code_aligned_previous_weights_preserve_names_and_charge_exits(self):
        previous_by_code = {"A": torch.tensor(0.4), "B": torch.tensor(0.6)}

        previous, exited = _code_aligned_previous_weights(
            previous_by_code, np.asarray(["C", "B", ""])
        )

        self.assertTrue(torch.allclose(previous, torch.tensor([0.0, 0.6, 0.0])))
        self.assertTrue(torch.isclose(exited, torch.tensor(0.4)))
        _, _, without_exit = joint_episode_loss(
            logits=torch.tensor([0.0, 8.0, 0.0]), replacement=torch.tensor(1.0),
            previous_weights=previous, codes=np.asarray(["C", "B", ""]),
            reward_valid=np.asarray([True, True, False]),
            buy_open=np.asarray([10.0, 10.0, 0.0]), sell_open=np.asarray([11.0, 11.0, 0.0]),
            buy_amount=np.asarray([1e8, 1e8, 0.0]), temperature=0.5, turnover_penalty=0.01,
        )
        _, _, with_exit = joint_episode_loss(
            logits=torch.tensor([0.0, 8.0, 0.0]), replacement=torch.tensor(1.0),
            previous_weights=previous, exit_turnover=cast(float, exited), codes=np.asarray(["C", "B", ""]),
            reward_valid=np.asarray([True, True, False]),
            buy_open=np.asarray([10.0, 10.0, 0.0]), sell_open=np.asarray([11.0, 11.0, 0.0]),
            buy_amount=np.asarray([1e8, 1e8, 0.0]), temperature=0.5, turnover_penalty=0.01,
        )
        self.assertLess(with_exit.item(), without_exit.item())

    def test_train_rejects_test_dates_disguised_as_train(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self._training_npz(directory / "episodes_train.npz", "2026-01-02", "2026-01-05", "2026-02-27")
            self._training_npz(directory / "episodes_val.npz", "2024-01-02", "2024-01-03", "2024-02-28")
            with self.assertRaisesRegex(ValueError, "train episode dates"):
                train_joint_policy(smoke=True, episodes_dir=directory, outdir=directory / "out")

    def test_train_rejects_train_artifact_with_future_buy_date(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self._training_npz(directory / "episodes_train.npz", "2023-01-02", "2026-01-05", "2023-02-28")
            self._training_npz(directory / "episodes_val.npz", "2024-01-02", "2024-01-03", "2024-02-28")
            with self.assertRaisesRegex(ValueError, "train episode dates"):
                train_joint_policy(smoke=True, episodes_dir=directory, outdir=directory / "out")

    def test_train_rejects_same_day_or_reversed_episode_dates(self):
        for buy_date, sell_date in (("2023-01-02", "2023-02-28"), ("2023-02-03", "2023-01-03")):
            with self.subTest(buy_date=buy_date, sell_date=sell_date), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                self._training_npz(directory / "episodes_train.npz", "2023-01-02", buy_date, sell_date)
                self._training_npz(directory / "episodes_val.npz", "2024-01-02", "2024-01-03", "2024-02-28")
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    train_joint_policy(smoke=True, episodes_dir=directory, outdir=directory / "out")

    def test_train_rejects_mismatched_feature_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self._training_npz(directory / "episodes_train.npz", "2023-01-02", "2023-01-03", "2023-02-28")
            self._training_npz(directory / "episodes_val.npz", "2024-01-02", "2024-01-03", "2024-02-28")
            self._replace_npz_field(
                directory / "episodes_val.npz", "feature_columns",
                np.asarray([f"other_{index}" for index in range(49)]),
            )
            with self.assertRaisesRegex(ValueError, "feature_columns"):
                train_joint_policy(smoke=True, episodes_dir=directory, outdir=directory / "out")

    def test_exit_turnover_includes_impact_cost(self):
        kwargs = {
            "logits": torch.tensor([0.0, 0.0]), "previous_weights": torch.tensor([0.5, 0.5]),
            "realized_returns": torch.zeros(2), "execution_amount": torch.full((2,), 100.0),
            "replacement": 0.0, "temperature": 1.0, "fee_rate": 0.01, "impact_rate": 0.1,
        }
        without_exit = proxy_episode_return(**kwargs)
        with_exit = proxy_episode_return(**kwargs, exit_turnover=0.4, exit_amount=100.0)

        self.assertGreater(without_exit.item() - with_exit.item(), 0.01 * 0.4)

    def test_mark_to_market_holdings_changes_continuing_name_weights(self):
        got = _mark_to_market_holdings(
            codes=np.asarray(["A", "B", ""]), weights=torch.tensor([0.5, 0.5, 0.0]),
            reward_valid=np.asarray([True, True, False]),
            buy_open=np.asarray([10.0, 10.0, 0.0]), sell_open=np.asarray([20.0, 10.0, 0.0]),
        )

        self.assertAlmostEqual(got["A"].item(), 2.0 / 3.0)
        self.assertAlmostEqual(got["B"].item(), 1.0 / 3.0)
        self.assertNotIn("", got)

    def test_smoke_checkpoint_contains_training_and_split_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self._training_npz(directory / "episodes_train.npz", "2023-01-02", "2023-01-03", "2023-02-28")
            self._training_npz(directory / "episodes_val.npz", "2024-01-02", "2024-01-03", "2024-02-28")
            metrics = train_joint_policy(smoke=True, episodes_dir=directory, outdir=directory / "out")
            checkpoint_path = directory / "out" / "checkpoint.pt"
            checkpoint = torch.load(checkpoint_path, weights_only=True)

            self.assertEqual(metrics["checkpoint_path"], str(checkpoint_path))
            self.assertTrue({"model_state", "optimizer_state", "epoch", "temperature", "turnover_penalty", "architecture", "split_metadata", "feature_columns", "preprocessing_identity"}.issubset(checkpoint))
            self.assertEqual(checkpoint["feature_columns"], [f"feature_{index}" for index in range(49)])
            self.assertEqual(checkpoint["preprocessing_identity"]["rolling_normalization"], "feat_roll_new.parquet")
            self.assertRegex(checkpoint["preprocessing_identity"]["rolling_artifact_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(checkpoint["preprocessing_identity"]["new_scaler_path"], str(NEW_SCALER))
            self.assertRegex(checkpoint["preprocessing_identity"]["new_scaler_sha256"], r"^[0-9a-f]{64}$")

    def test_train_cli_missing_episode_files_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            sys, "argv", ["joint_portfolio.py", "train", "--episodes-dir", directory]
        ), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)
