"""B03: CnnPredictionAdapter 单测（TDD，合成小缓存经 save/load 构造，零触网/cnn 无 DB）."""
import os
import shutil
import tempfile
import unittest
from datetime import date

import numpy as np

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.predictions import CnnPredictionAdapter


def _synth_arrays(n: int = 6):
    exp_ret = np.linspace(-0.04, 0.05, n)
    true_ret = np.linspace(0.03, -0.03, n)
    dates = np.array(["2025-03-03"] * n, dtype="datetime64[D]")
    codes = np.array([f"00000{i}" for i in range(n)])
    return exp_ret, true_ret, dates, codes


def _make_adapter(testcase, exp_ret=None, true_ret=None, dates=None, codes=None, **kwargs):
    exp_ret, true_ret, dates, codes = _synth_arrays() if exp_ret is None else (exp_ret, true_ret, dates, codes)
    path = os.path.join(testcase.tmp, "preds.npz")
    save_prediction_cache(path, exp_ret, true_ret, dates, codes)
    cache = load_prediction_cache(path)
    params = {"model_name": "cnn_transformer", "checkpoint": "logs/run_demo/best_model.pth",
              "bins_version": "BINS52_linspace_-0.25_0.25", "eval_script_version": "eval_bins_mapping@v1"}
    params.update(kwargs)
    return CnnPredictionAdapter(cache, **params)


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b03_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestBasicMapping(_TempDirMixin):
    def test_type_horizon_signal_time(self):
        from backtest_core.contracts import PredictionType

        adapter = _make_adapter(self)
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        self.assertEqual(len(preds), 6)
        for pred in preds:
            self.assertIs(pred.prediction_type, PredictionType.PREDICTED_RETURN)
            self.assertEqual(pred.predicted_horizon, 5)
            self.assertEqual((pred.signal_time.year, pred.signal_time.month, pred.signal_time.day,
                              pred.signal_time.hour), (2025, 3, 3, 15))
            self.assertEqual(pred.signal_time.utcoffset().total_seconds(), 8 * 3600)


class TestValuesTrackExpRet(_TempDirMixin):
    def test_prediction_values_equal_exp_ret_not_true_ret(self):
        adapter = _make_adapter(self)
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        by_code = {pred.instrument_id: pred.value for pred in preds}
        exp_ret, _, _, codes = _synth_arrays()
        for code, expected in zip(codes, exp_ret):
            self.assertAlmostEqual(by_code[str(code)], float(expected))

    def test_output_sorted_by_code(self):
        exp_ret, true_ret, dates, _ = _synth_arrays()
        codes = np.array(["000003", "000001", "000005", "000002", "000004", "000000"])
        adapter = _make_adapter(self, exp_ret=exp_ret, true_ret=true_ret, dates=dates, codes=codes)
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        self.assertEqual([pred.instrument_id for pred in preds], sorted(codes.tolist()))


class TestAnomalyDegrade(_TempDirMixin):
    def test_nan_inf_dropped_with_counts(self):
        exp_ret = np.array([0.01, float("nan"), float("inf"), 0.02, float("-inf"), float("nan")])
        true_ret = np.linspace(0.01, 0.02, 6)
        dates = np.array(["2025-03-03"] * 6, dtype="datetime64[D]")
        codes = np.array([f"00000{i}" for i in range(6)])
        adapter = _make_adapter(self, exp_ret=exp_ret, true_ret=true_ret, dates=dates, codes=codes)
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        self.assertEqual({pred.instrument_id for pred in preds}, {"000000", "000003"})
        counters = adapter.counters
        self.assertEqual(counters.dropped_nan_count, 2)
        self.assertEqual(counters.dropped_inf_count, 2)
        self.assertEqual(counters.predicted_count, 2)


class TestEmptyCrossSection(_TempDirMixin):
    def test_missing_date_returns_empty_with_count(self):
        adapter = _make_adapter(self)
        preds = adapter.predictions_for_date(date(2025, 4, 1))
        self.assertEqual(preds, ())
        self.assertEqual(adapter.counters.empty_cross_section_count, 1)


class TestTrueRetIsolation(_TempDirMixin):
    def test_actuals_available_for_cross_section(self):
        adapter = _make_adapter(self)
        actuals = adapter.actuals_for_cross_section(date(2025, 3, 3))
        _, true_ret, _, codes = _synth_arrays()
        self.assertEqual(set(actuals), {str(code) for code in codes})
        for code, expected in zip(codes, true_ret):
            self.assertAlmostEqual(actuals[str(code)], float(expected))

    def test_actuals_drops_non_finite_true_with_count(self):
        exp_ret, _, dates, codes = _synth_arrays()
        true_ret = np.array([0.01, float("nan"), 0.02, float("inf"), 0.03, 0.04])
        adapter = _make_adapter(self, exp_ret=exp_ret, true_ret=true_ret, dates=dates, codes=codes)
        actuals = adapter.actuals_for_cross_section(date(2025, 3, 3))
        self.assertEqual(set(actuals), {"000000", "000002", "000004", "000005"})
        self.assertEqual(adapter.counters.invalid_true_count, 2)

    def test_predictions_immune_to_true_ret_corruption(self):
        exp_ret, _, dates, codes = _synth_arrays()
        poisoned_true = np.full(6, float("nan"))
        adapter = _make_adapter(self, exp_ret=exp_ret, true_ret=poisoned_true, dates=dates, codes=codes)
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        self.assertEqual(len(preds), 6)
        for pred, expected in zip(sorted(preds, key=lambda pred: pred.instrument_id), sorted(exp_ret)):
            self.assertAlmostEqual(pred.value, float(expected))

    def test_actuals_immune_to_exp_ret_corruption(self):
        _, true_ret, dates, codes = _synth_arrays()
        poisoned_exp = np.full(6, float("nan"))
        adapter = _make_adapter(self, exp_ret=poisoned_exp, true_ret=true_ret, dates=dates, codes=codes)
        actuals = adapter.actuals_for_cross_section(date(2025, 3, 3))
        self.assertEqual(len(actuals), 6)

    def test_no_true_ret_to_order_data_flow(self):
        import inspect

        import backtest.cnn_adapter.predictions as module

        adapter = _make_adapter(self)
        forbidden = ("order", "fill", "account", "portfolio", "intent", "executor")
        for name in dir(adapter):
            for word in forbidden:
                self.assertNotIn(word, name.lower(), f"adapter 存在可疑成交路径成员 {name!r}")
        public_names = [name for name in dir(adapter) if not name.startswith("_")]
        for name in public_names:
            if name in ("actuals_for_cross_section", "counters", "warnings_summary"):
                continue
            self.assertNotIn("true", name.lower(), f"adapter 公开 true_ret 相关成员 {name!r}")
        source = inspect.getsource(module).lower()
        for word in forbidden:
            self.assertNotIn(word, source, f"predictions.py 存在 true_ret→成交路径可疑字串 {word!r}")
        public_true_holders = [name for name in dir(adapter) if not name.startswith("_")
                               and "actuals" not in name and "provenance" not in name
                               and "counters" not in name and "warnings" not in name
                               and "available" not in name and "predictions_for" not in name]
        self.assertEqual(public_true_holders, [])


class TestProvenance(_TempDirMixin):
    def test_provenance_passthrough(self):
        adapter = _make_adapter(self, model_name="cnn_transformer", checkpoint="logs/run_x/best_model.pth",
                                epoch=12, bins_version="BINS52_v1", eval_script_version="eval_bins_mapping@v1")
        provenance = adapter.provenance
        self.assertEqual(provenance["model_name"], "cnn_transformer")
        self.assertEqual(provenance["checkpoint"], "logs/run_x/best_model.pth")
        self.assertEqual(provenance["epoch"], "12")
        self.assertEqual(provenance["bins_version"], "BINS52_v1")
        self.assertEqual(provenance["eval_script_version"], "eval_bins_mapping@v1")
        self.assertEqual(provenance["horizon"], "5")
        self.assertIn("horizon=5", provenance["label_formula"])

    def test_provenance_rejects_empty(self):
        for field in ("model_name", "checkpoint", "bins_version", "eval_script_version"):
            with self.subTest(field=field):
                kwargs = {"model_name": "m", "checkpoint": "c", "bins_version": "b", "eval_script_version": "e"}
                kwargs[field] = "  "
                with self.assertRaises(ValueError):
                    _make_adapter(self, **kwargs)

    def test_duplicate_date_code_rejected(self):
        exp_ret, true_ret, _, _ = _synth_arrays()
        dates = np.array(["2025-03-03"] * 6, dtype="datetime64[D]")
        codes = np.array(["000000"] * 6)
        with self.assertRaises(ValueError):
            _make_adapter(self, exp_ret=exp_ret, true_ret=true_ret, dates=dates, codes=codes)


if __name__ == "__main__":
    unittest.main()
