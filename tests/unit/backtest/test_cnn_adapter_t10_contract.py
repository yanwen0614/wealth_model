"""T10: preds 4字段契约 + OHLC parquet直读统一（合成数据，tempfile隔离）."""
import os
import shutil
import tempfile
import unittest
import warnings

import numpy as np
import pandas as pd


def _synth_preds(n=6):
    exp_ret = np.linspace(-0.04, 0.05, n)
    true_ret = np.linspace(0.03, -0.03, n)
    dates = np.array(["2025-03-03"] * n, dtype="datetime64[D]")
    codes = np.array([f"00000{i}" for i in range(n)])
    return exp_ret, true_ret, dates, codes


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="t10_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCacheCompatMissingTrueRet(_Tmp):
    def test_missing_true_ret_warns_and_returns_none(self):
        from backtest.cnn_adapter.cache import load_prediction_cache

        exp, _unused, dates, codes = _synth_preds()
        path = os.path.join(self.tmp, "legacy.npz")
        np.savez(path, exp_ret=exp, dates=dates, codes=codes)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            got = load_prediction_cache(path)
        self.assertIn("true_ret", str([str(w.message) for w in caught]))
        self.assertIsNone(got["true_ret"])
        np.testing.assert_array_equal(got["exp_ret"], exp)

    def test_missing_exp_ret_still_rejected(self):
        from backtest.cnn_adapter.cache import load_prediction_cache

        _unused, true, dates, codes = _synth_preds()
        path = os.path.join(self.tmp, "bad.npz")
        np.savez(path, true_ret=true, dates=dates, codes=codes)
        with self.assertRaises(ValueError):
            load_prediction_cache(path)


class TestAdapterCompatMissingTrueRet(_Tmp):
    def test_predictions_work_actuals_empty(self):
        from datetime import date

        from backtest.cnn_adapter.predictions import CnnPredictionAdapter

        exp, _, dates, codes = _synth_preds()
        cache = {"exp_ret": exp, "true_ret": None, "dates": dates, "codes": codes}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adapter = CnnPredictionAdapter(
                cache, model_name="m", checkpoint="c",
                bins_version="b", eval_script_version="e")
        preds = adapter.predictions_for_date(date(2025, 3, 3))
        self.assertEqual(len(preds), 6)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            actuals = adapter.actuals_for_cross_section(date(2025, 3, 3))
        self.assertEqual(actuals, {})


class TestDualScriptUnifiedWriter(unittest.TestCase):
    def test_both_eval_scripts_use_canonical_save(self):
        import inspect

        import scripts.eval_bins_mapping as m1
        import scripts.run_eval_pipeline as m2

        self.assertIn("save_prediction_cache", inspect.getsource(m1))
        self.assertIn("save_prediction_cache", inspect.getsource(m2))

    def test_canonical_roundtrip_mutually_readable(self):
        from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache

        exp, true, dates, codes = _synth_preds()
        with tempfile.TemporaryDirectory(prefix="t10x_") as tmp:
            path = os.path.join(tmp, "preds.npz")
            save_prediction_cache(path, exp, true, dates, codes)
            got = load_prediction_cache(path)
            self.assertEqual(tuple(sorted(got.keys())),
                             ("codes", "dates", "exp_ret", "true_ret"))


class TestOhlcUnified(_Tmp):
    def _write_parquet(self, path):
        rows = []
        for code in ("000001.SZ", "600000.SH"):
            for i, day in enumerate(pd.date_range("2025-01-02", periods=10, freq="B")):
                rows.append({"code": code, "kline_time": day, "open": 10.0 + i * 0.1,
                             "high": 10.5, "low": 9.8, "close": 10.2 + i * 0.1,
                             "volume": 1e6, "amount": 1e7, "is_trading": True})
        pd.DataFrame(rows).to_parquet(path, index=False)
        return path

    def test_builder_output_validated_and_matches_parquet(self):
        import inspect

        import pyarrow.parquet as pq

        import scripts.build_ohlc_path as mod
        from backtest.cnn_adapter.cache import validate_ohlc_path_arrays
        from scripts.build_ohlc_path import build_ohlc_path

        self.assertIn("validate_ohlc_path_arrays", inspect.getsource(mod))
        path = self._write_parquet(os.path.join(self.tmp, "m.parquet"))
        arrays = build_ohlc_path(path, "2025-01-06", "2025-01-10", 5)
        validate_ohlc_path_arrays(arrays, "单测")
        raw = pq.read_table(path, columns=["code"]).to_pandas()
        self.assertGreater(len(arrays["codes"]), 0)
        self.assertLessEqual(len(arrays["codes"]), len(raw))

    def test_market_ohlc_path_deprecated_warns(self):
        from backtest.cnn_adapter.market import CnnMarketDataProvider

        path = self._write_parquet(os.path.join(self.tmp, "w.parquet"))
        ohlc = os.path.join(self.tmp, "o.npz")
        dates = np.arange(np.datetime64("2025-01-02"), np.datetime64("2025-01-04"),
                          dtype="datetime64[D]")
        np.savez(ohlc, codes=np.array(["000001.SZ"] * 2), dates=dates,
                 t_close=np.array([10.2, 10.4]), open_t1=np.array([10.3, 10.5]),
                 open_t6=np.array([10.8, 11.0]))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            CnnMarketDataProvider(path, ohlc_path=ohlc)
        self.assertTrue(any("ohlc_path" in str(w.message) for w in caught))


if __name__ == "__main__":
    unittest.main()
