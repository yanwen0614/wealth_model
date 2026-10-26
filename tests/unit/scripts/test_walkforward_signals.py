"""无标签依赖信号窗口的合成数据测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from backtest.cnn_adapter.predictions import CnnPredictionAdapter
from config.defaults import DEFAULT_BINS, DEFAULT_CENTERS
from data.dataset import ParquetDataConfig, ParquetDataset
from data.scaler import RelativeScaler
from data.schema import APPROVED_RAW_FEATURES, FEATURE_GROUPS
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from scripts.generate_walkforward_signals import (
    F4_RAW_FEATURES,
    SignalContract,
    _checkpoint_contract,
    _prepare_code_groups,
    _read_causal_frame,
    _resolve_buffer_dates,
    _signal_record,
    _validate_decision_start,
    causal_window,
    generate_signals,
    prediction_cache_arrays,
)
from training.checkpoint import load_model_state

_FINANCIAL = {"gross_margin", "net_margin", "roe", "roa", "debt_to_equity"}
F29_RAW_FEATURES = tuple(FEATURE_GROUPS["P"]) + tuple(
    column for column in FEATURE_GROUPS["R"] if column not in _FINANCIAL
)


def _contract(feature_cols=None) -> SignalContract:
    cols = list(APPROVED_RAW_FEATURES if feature_cols is None else feature_cols)
    add_mask = tuple(cols) == tuple(APPROVED_RAW_FEATURES)
    return SignalContract("fixed", {"LABEL_MODE": "excess", "VAL_END": "2020-12-31"}, cols,
                          RelativeScaler(cols, add_mask=add_mask).feature_cols_out, 60, 10, "excess", {})


def _frame(n: int = 65) -> pd.DataFrame:
    values = np.arange(1, n + 1, dtype=np.float64)
    frame = pd.DataFrame({
        "code": ["A"] * n, "kline_time": pd.date_range("2021-01-01", periods=n),
        "open": values + 10, "close": values + 11, "is_trading": True,
        "_is_trading": True,
    })
    for column in APPROVED_RAW_FEATURES:
        if column not in frame:
            frame[column] = values + 3
    return frame


def _write_checkpoint(path: str, feature_cols=None, featurenum=None) -> ModelConfig:
    cols = list(APPROVED_RAW_FEATURES if feature_cols is None else feature_cols)
    add_mask = tuple(cols) == tuple(APPROVED_RAW_FEATURES)
    feature_count = featurenum or len(RelativeScaler(cols, add_mask=add_mask).feature_cols_out)
    model_values = {
        "featurenum": feature_count, "seq_len": 60, "num_classes": 52, "cnn_out_channels": 8,
        "cnn_kernel_sizes": [1, 3, 5], "d_model": 8, "nhead": 2,
        "num_encoder_layers": 1, "dropout_rate": 0.0, "gate_head": False,
    }
    model_config = ModelConfig(**model_values)
    torch.manual_seed(17)
    torch.save({"model": CNNTransformer(model_config).state_dict()}, path)
    run_config = {
        "SEQ_LEN": 60, "HORIZON": 10, "NORMALIZE": "relative", "LABEL_MODE": "excess",
        "TRAIN_START": "2013-01-01", "TRAIN_END": "2020-06-30",
        "VAL_START": "2020-07-01", "VAL_END": "2020-12-31",
        "CS_RANK": False, "MKT_FACTORS": False, "PURE_REG": False, "GATE_HEAD": False,
        "num_classes": 52, "BINS": DEFAULT_BINS, "CENTERS": DEFAULT_CENTERS,
        "CNNTransformerConfig": model_values,
        "preprocessing": {
            "mode": "relative", "feature_cols": cols,
            "feature_cols_out": RelativeScaler(cols, add_mask=add_mask).feature_cols_out,
            "featurenum": feature_count, "seq_len": 60, "num_classes": 52,
        },
    }
    with Path(path).with_name("config.json").open("w", encoding="utf-8") as handle:
        json.dump(run_config, handle)
    return model_config


class TestWalkforwardSignals(unittest.TestCase):
    def test_f4_schema_is_exactly_ordered_ohlc(self):
        self.assertEqual(F4_RAW_FEATURES, ("open", "high", "low", "close"))
        contract = _contract(F4_RAW_FEATURES)
        self.assertEqual(contract.feature_cols_out, list(F4_RAW_FEATURES))

    def test_f4_checkpoint_rejects_unknown_schema_and_wrong_featurenum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            unknown = Path(temp_dir) / "unknown_f4.pth"
            _write_checkpoint(str(unknown), F4_RAW_FEATURES + ("macd",))
            with self.assertRaisesRegex(ValueError, "raw feature schema"):
                _checkpoint_contract(str(unknown))
            mismatch = Path(temp_dir) / "mismatch_f4.pth"
            _write_checkpoint(str(mismatch), F4_RAW_FEATURES, featurenum=29)
            with self.assertRaisesRegex(ValueError, "featurenum"):
                _checkpoint_contract(str(mismatch))

    def test_f29_contract_has_only_the_ordered_technical_schema(self):
        self.assertEqual(len(F29_RAW_FEATURES), 29)
        self.assertEqual(F29_RAW_FEATURES[:18], FEATURE_GROUPS["P"])
        self.assertEqual(F29_RAW_FEATURES[18:], tuple(c for c in FEATURE_GROUPS["R"] if c not in _FINANCIAL))
        self.assertFalse(_FINANCIAL.intersection(F29_RAW_FEATURES))

    def test_f29_checkpoint_rejects_unknown_schema_and_wrong_featurenum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            unknown = Path(temp_dir) / "unknown.pth"
            forbidden = tuple(sorted(_FINANCIAL)) + FEATURE_GROUPS["N"] + FEATURE_GROUPS["G"]
            invalid_cols = F29_RAW_FEATURES + forbidden + ("g9_observed_mask",)
            _write_checkpoint(str(unknown), invalid_cols, featurenum=53)
            with self.assertRaisesRegex(ValueError, "raw feature schema"):
                _checkpoint_contract(str(unknown))
            mismatch = Path(temp_dir) / "mismatch.pth"
            _write_checkpoint(str(mismatch), F29_RAW_FEATURES, featurenum=53)
            with self.assertRaisesRegex(ValueError, "featurenum"):
                _checkpoint_contract(str(mismatch))

    def test_f29_checkpoint_contract_is_accepted_without_mask(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = Path(temp_dir) / "f29.pth"
            _write_checkpoint(str(checkpoint), F29_RAW_FEATURES)
            contract = _checkpoint_contract(str(checkpoint))
        self.assertEqual(contract.feature_cols, list(F29_RAW_FEATURES))
        self.assertEqual(contract.feature_cols_out, list(F29_RAW_FEATURES))

    def test_decision_start_must_follow_validation_end(self):
        contract = _contract()
        _validate_decision_start(contract, pd.Timestamp("2021-01-01"))
        with self.assertRaisesRegex(ValueError, "晚于 checkpoint 的 VAL_END"):
            _validate_decision_start(contract, pd.Timestamp("2020-12-31"))

    def test_buffer_requires_calendar_sessions(self):
        calendar = pd.DatetimeIndex(pd.date_range("2021-01-01", periods=5))
        self.assertEqual(len(_resolve_buffer_dates(calendar, 1, 3)), 3)
        with self.assertRaisesRegex(ValueError, "至少需要 1 个交易日"):
            _resolve_buffer_dates(calendar, 1, 0)
        with self.assertRaisesRegex(ValueError, "未包含完整清算 buffer"):
            _resolve_buffer_dates(calendar, 4, 1)

    def test_window_matches_shared_scaler_and_does_not_need_future_rows(self):
        contract, frame = _contract(), _frame()
        date = pd.Timestamp(frame.iloc[62]["kline_time"])
        x, status = causal_window(frame, contract, "A", date)
        self.assertEqual(status, "ready")
        observed = frame.loc[frame.kline_time <= date]
        expected = RelativeScaler(contract.feature_cols).transform_code(
            "A", observed[contract.feature_cols].to_numpy(), contract.feature_cols,
            observed["close"].to_numpy(),
        )[-60:].T.astype(np.float32)
        self.assertEqual(x.shape, expected.shape)
        np.testing.assert_array_equal(x, expected)
        changed = frame.copy()
        changed.loc[changed.kline_time > date, contract.feature_cols] = -999999
        x2, _ = causal_window(changed, contract, "A", date)
        np.testing.assert_array_equal(x, x2)

    def test_f29_window_and_dataset_tensor_have_no_mask_channel(self):
        frame = _frame(65)
        contract = _contract(F29_RAW_FEATURES)
        date = pd.Timestamp(frame.iloc[62].kline_time)
        x, status = causal_window(frame, contract, "A", date)
        self.assertEqual(status, "ready")
        self.assertEqual(x.shape, (29, 60))
        prepared = _prepare_code_groups(frame.assign(_is_trading=True), contract)["A"][1]
        self.assertEqual(prepared["features"].shape[1], 29)
        self.assertNotIn("g9_observed_mask", contract.feature_cols_out)

    def test_f29_reader_projects_no_financial_or_margin_columns(self):
        frame = _frame(65).drop(columns=["_is_trading"])
        start = pd.Timestamp(frame.iloc[59].kline_time)
        contract = _contract(F29_RAW_FEATURES)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/source.parquet"
            frame.to_parquet(path, index=False)
            parquet = pq.ParquetFile(path)
            requested_columns = []

            class RecordingParquet:
                schema = parquet.schema
                num_row_groups = parquet.num_row_groups

                @staticmethod
                def iter_batches(batch_size, columns):
                    requested_columns.extend(columns)
                    return parquet.iter_batches(batch_size=batch_size, columns=columns)

            try:
                with patch("scripts.generate_walkforward_signals.pq.ParquetFile", return_value=RecordingParquet()):
                    projected = _read_causal_frame(path, contract, start, start)
            finally:
                parquet.close()
        expected = {"code", "kline_time", "open", "close", "is_trading", "_is_trading", *F29_RAW_FEATURES}
        self.assertEqual(set(projected.columns), expected)
        self.assertFalse(_FINANCIAL.intersection(projected.columns))
        self.assertFalse(any(column.startswith("margin_") or column.startswith("short_")
                             for column in projected.columns))
        self.assertEqual(set(requested_columns), expected - {"_is_trading"})

    def test_f4_reader_projects_only_ohlc_and_required_identity_columns(self):
        frame = _frame(65).drop(columns=["_is_trading"])
        start = pd.Timestamp(frame.iloc[59].kline_time)
        contract = _contract(F4_RAW_FEATURES)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/f4_source.parquet"
            frame.to_parquet(path, index=False)
            parquet = pq.ParquetFile(path)
            requested_columns = []

            class RecordingParquet:
                schema = parquet.schema
                num_row_groups = parquet.num_row_groups

                @staticmethod
                def iter_batches(batch_size, columns):
                    requested_columns.extend(columns)
                    return parquet.iter_batches(batch_size=batch_size, columns=columns)

            try:
                with patch("scripts.generate_walkforward_signals.pq.ParquetFile", return_value=RecordingParquet()):
                    projected = _read_causal_frame(path, contract, start, start)
            finally:
                parquet.close()
        source_columns = {"code", "kline_time", "open", "close", "high", "low", "is_trading"}
        self.assertEqual(set(requested_columns), source_columns)
        self.assertEqual(set(projected.columns), source_columns | {"_is_trading"})

    def test_h10_label_absence_never_removes_signal(self):
        frame = _frame(60).assign(_is_trading=True)
        payload = _prepare_code_groups(frame, _contract())["A"][1]
        date = pd.Timestamp(frame.iloc[-1].kline_time)
        pos = payload["positions"][date]
        x = payload["features"][pos - 59:pos + 1].T
        self.assertEqual(x.shape, (53, 60))

    def test_overlap_matches_labeled_dataset_features(self):
        frame = _frame(140).drop(columns=["_is_trading"])
        frame.loc[20:50, "is_trading"] = False
        start = pd.Timestamp(frame.iloc[100]["kline_time"])
        second = pd.Timestamp(frame.iloc[101]["kline_time"])
        label_end = pd.Timestamp(frame.iloc[112]["kline_time"])
        contract = _contract()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/mini.parquet"
            frame.to_parquet(path, index=False)
            dataset = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=60, horizon=10, normalize="relative",
                label_mode="excess", feature_cols=list(APPROVED_RAW_FEATURES),
                role="evaluation", start_date=start.strftime("%Y-%m-%d"),
                end_date=label_end.strftime("%Y-%m-%d"), num_workers=0,
            ))
            causal = _read_causal_frame(path, contract, start, second)
        prepared = _prepare_code_groups(causal, contract)
        dates, payload = prepared["A"]
        positions = payload["positions"]
        self.assertEqual(len(causal.loc[causal.kline_time < start]), 59)
        self.assertEqual(dataset.groups["A"]["features"][0, 3], 0.0)
        self.assertNotEqual(dataset.groups["A"]["features"][1, 3], 0.0)
        for decision_date, window_start in ((start, 0), (second, 1)):
            self.assertTrue(dates[decision_date])
            pos = positions[decision_date]
            signal = payload["features"][pos - 59:pos + 1].T
            expected = dataset.groups["A"]["features"][window_start:window_start + 60].T
            np.testing.assert_array_equal(signal, expected)

    def test_f29_first_context_matches_labeled_dataset_warmup(self):
        frame = _frame(140).drop(columns=["_is_trading"])
        start, end = pd.Timestamp(frame.iloc[100].kline_time), pd.Timestamp(frame.iloc[101].kline_time)
        contract = _contract(F29_RAW_FEATURES)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = f"{temp_dir}/f29.parquet"
            frame.to_parquet(path, index=False)
            dataset = ParquetDataset(ParquetDataConfig(
                parquet_path=path, seq_len=60, horizon=10, normalize="relative",
                label_mode="excess", feature_cols=list(F29_RAW_FEATURES), role="evaluation",
                start_date=str(start.date()), end_date=str(frame.iloc[112].kline_time.date()),
                num_workers=0,
            ))
            causal = _read_causal_frame(path, contract, start, end)
        prepared = _prepare_code_groups(causal, contract)["A"][1]
        self.assertEqual(len(causal.loc[causal.kline_time < start]), 59)
        self.assertEqual(prepared["features"].shape[1], 29)
        for date, window_start in ((start, 0), (end, 1)):
            pos = prepared["positions"][date]
            actual = prepared["features"][pos - 59:pos + 1].T
            expected = dataset.groups["A"]["features"][window_start:window_start + 60].T
            np.testing.assert_array_equal(actual, expected)

    def test_f29_end_signal_is_kept_without_h10_label(self):
        frame = _frame(65).drop(columns=["_is_trading"])
        with tempfile.TemporaryDirectory() as temp_dir:
            parquet, checkpoint = f"{temp_dir}/mini.parquet", f"{temp_dir}/f29.pth"
            frame.to_parquet(parquet, index=False)
            _write_checkpoint(checkpoint, F29_RAW_FEATURES)
            calendar = pd.date_range(frame.iloc[0].kline_time, periods=68)
            start, end = frame.iloc[63].kline_time, frame.iloc[64].kline_time
            signals = generate_signals(checkpoint, parquet, str(start.date()), str(end.date()), calendar)
        final = signals.loc[signals.date == end].iloc[0]
        self.assertEqual(final.status, "ready")
        self.assertTrue(np.isnan(final.true_ret))
        self.assertFalse(final.buy_eligible)

    def test_f4_dataset_windows_match_writer_and_terminal_unlabeled_signal(self):
        frame = _frame(85).drop(columns=["_is_trading"])
        with tempfile.TemporaryDirectory() as temp_dir:
            parquet, checkpoint = f"{temp_dir}/f4.parquet", f"{temp_dir}/f4.pth"
            frame.to_parquet(parquet, index=False)
            model_config = _write_checkpoint(checkpoint, F4_RAW_FEATURES)
            start, end = frame.iloc[59].kline_time, frame.iloc[74].kline_time
            calendar = pd.date_range(frame.iloc[0].kline_time, periods=78)
            dataset = ParquetDataset(ParquetDataConfig(
                parquet_path=parquet, seq_len=60, horizon=10, normalize="relative",
                label_mode="excess", feature_cols=list(F4_RAW_FEATURES), role="evaluation",
                start_date=str(start.date()), end_date=str(end.date()), num_workers=0,
            ))
            captured = []
            original_forward = CNNTransformer.forward

            def capture_forward(model, x):
                captured.append(x.detach().cpu().numpy().copy())
                return original_forward(model, x)

            with patch.object(CNNTransformer, "forward", capture_forward):
                signals = generate_signals(checkpoint, parquet, str(start.date()), str(end.date()), calendar)
        self.assertEqual(model_config.featurenum, 4)
        self.assertTrue(all(batch.shape[1:] == (4, 60) for batch in captured))
        writer_windows = np.concatenate(captured)
        dataset_windows = np.stack([dataset[i][0].numpy() for i in range(len(dataset))])
        self.assertEqual(dataset_windows.shape[1:], (4, 60))
        np.testing.assert_array_equal(writer_windows[:len(dataset_windows)], dataset_windows)
        self.assertEqual(len(signals), 16)
        final = signals.loc[signals.date == end].iloc[0]
        self.assertEqual(final.status, "ready")
        self.assertTrue(np.isnan(final.true_ret))
        self.assertFalse(final.buy_eligible)

    def test_production_group_transform_is_causal_and_end_signal_is_not_buy_eligible(self):
        contract, frame = _contract(), _frame(80).assign(_is_trading=True)
        decision = pd.Timestamp(frame.iloc[65].kline_time)
        before = _prepare_code_groups(frame, contract)["A"][1]["features"]
        changed = frame.copy()
        changed.loc[changed.kline_time > decision, contract.feature_cols] = -10000
        after = _prepare_code_groups(changed, contract)["A"][1]["features"]
        pos = int(np.flatnonzero(frame.kline_time.to_numpy() == decision.to_datetime64())[0])
        np.testing.assert_array_equal(before[pos - 59:pos + 1], after[pos - 59:pos + 1])
        row = _signal_record("A", decision, 0.01, "ready", False)
        self.assertFalse(row["buy_eligible"])
        self.assertTrue(np.isnan(row["true_ret"]))

    def test_exp_ret_matches_legacy_labeled_evaluation_on_overlap(self):
        frame = _frame(140).drop(columns=["_is_trading"])
        start, end, label_end = (pd.Timestamp(frame.iloc[i].kline_time) for i in (100, 101, 112))
        with tempfile.TemporaryDirectory() as temp_dir:
            parquet = f"{temp_dir}/mini.parquet"
            checkpoint = f"{temp_dir}/best_model.pth"
            frame.to_parquet(parquet, index=False)
            model_config = _write_checkpoint(checkpoint)
            calendar = pd.DatetimeIndex(pd.date_range(frame.iloc[0].kline_time, periods=140))
            signals = generate_signals(checkpoint, parquet, str(start.date()), str(end.date()), calendar)
            dataset = ParquetDataset(ParquetDataConfig(
                parquet_path=parquet, seq_len=60, horizon=10, normalize="relative",
                label_mode="excess", feature_cols=list(APPROVED_RAW_FEATURES),
                role="evaluation", start_date=str(start.date()), end_date=str(label_end.date()),
                num_workers=0,
            ))
            model = CNNTransformer(model_config).eval()
            load_model_state(checkpoint, model, map_location="cpu", strict=True)
            with torch.no_grad():
                x = torch.stack([dataset[i][0] for i in range(2)])
                logits, _ = model(x)
                expected = torch.softmax(logits, dim=1).numpy() @ np.asarray(DEFAULT_CENTERS, dtype=np.float64)
        actual = signals.loc[signals.status == "ready"].sort_values("date").exp_ret.to_numpy()
        np.testing.assert_array_equal(actual, expected)
        self.assertTrue(signals.true_ret.isna().all())
        self.assertEqual(signals.attrs["metadata"]["exp_ret_semantics"],
                         "excess_return_expectation_from_class_centers")
        self.assertTrue(signals.date.eq(end).any())
        cache_arrays = prediction_cache_arrays(signals)
        self.assertIn(end.to_datetime64(), cache_arrays["dates"])
        adapter = CnnPredictionAdapter(
            cache_arrays, model_name="mini", checkpoint=checkpoint,
            bins_version="mini", eval_script_version="signal-only-test",
        )
        self.assertEqual(adapter.actuals_for_cross_section(start.date()), {})
        self.assertEqual(len(adapter.predictions_for_date(end.date())), 1)
        end_row = signals.loc[signals.date == end].iloc[0]
        self.assertFalse(end_row.buy_eligible)
        self.assertIn("reject BUY in post-E buffer",
                      signals.attrs["metadata"]["terminal_execution_policy"]["buy"])

    def test_listing_history_and_suspension_have_explicit_reasons(self):
        frame = _frame(20)
        x, status = causal_window(frame, _contract(), "A", pd.Timestamp(frame.iloc[-1].kline_time))
        self.assertIsNone(x)
        self.assertEqual(status, "insufficient_history")
        frame = _frame(65)
        frame.loc[frame.index[-1], "_is_trading"] = False
        x, status = causal_window(frame, _contract(), "A", pd.Timestamp(frame.iloc[-1].kline_time))
        self.assertIsNone(x)
        self.assertEqual(status, "not_trading")
