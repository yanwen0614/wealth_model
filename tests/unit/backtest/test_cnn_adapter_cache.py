"""B01: cnn_adapter 预测缓存/指纹/信号时间单测（TDD，合成小数据，tempfile 落盘）.

落盘隔离在 tempfile（/tmp），不写 logs/（*.npz 不入库，见 AGENTS.md）。
"""
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np

from backtest.cnn_adapter.cache import (
    OHLC_PATH_KEYS,
    cache_fingerprint,
    load_prediction_cache,
    save_prediction_cache,
    validate_ohlc_path_arrays,
)
from backtest.cnn_adapter.common import SHANGHAI_TZ, npz_fingerprint, require_keys, signal_time_for
from data.schema import PREDICTION_CACHE_KEYS


def _synth_cache(n: int = 12) -> dict:
    exp_ret = np.linspace(-0.05, 0.05, n)
    true_ret = np.linspace(0.02, -0.02, n)
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(n, "D"))
    codes = np.array([f"00000{i % 10}" for i in range(n)])
    return {"exp_ret": exp_ret, "true_ret": true_ret, "dates": dates, "codes": codes}


def _synth_ohlc(n: int = 8) -> dict:
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + np.timedelta64(n, "D"))
    codes = np.array([f"00000{i % 10}" for i in range(n)])
    base = np.linspace(10.0, 11.0, n)
    return {"codes": codes, "dates": dates, "t_close": base,
            "open_t1": base + 0.01, "open_t6": base * 1.02}


class _TempDirMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b01_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def tmp_path(self, name: str) -> str:
        return os.path.join(self.tmp, name)


class TestSaveLoadRoundTrip(_TempDirMixin):
    def test_round_trip_values_equal(self):
        src = _synth_cache()
        path = self.tmp_path("preds.npz")
        save_prediction_cache(path, src["exp_ret"], src["true_ret"], src["dates"], src["codes"])
        got = load_prediction_cache(path)
        self.assertEqual(tuple(sorted(got.keys())), tuple(sorted(PREDICTION_CACHE_KEYS)))
        np.testing.assert_array_equal(got["exp_ret"], src["exp_ret"])
        np.testing.assert_array_equal(got["true_ret"], src["true_ret"])
        np.testing.assert_array_equal(got["dates"], src["dates"])
        np.testing.assert_array_equal(got["codes"], src["codes"])

    def test_save_rejects_length_mismatch(self):
        src = _synth_cache()
        with self.assertRaises(ValueError):
            save_prediction_cache(self.tmp_path("bad.npz"), src["exp_ret"][:-1],
                                  src["true_ret"], src["dates"], src["codes"])
        self.assertFalse(os.path.exists(self.tmp_path("bad.npz")))


class TestMissingKeys(_TempDirMixin):
    def test_each_missing_key_raises(self):
        for missing in PREDICTION_CACHE_KEYS:
            with self.subTest(missing=missing):
                src = {k: v for k, v in _synth_cache().items() if k != missing}
                path = self.tmp_path(f"miss_{missing}.npz")
                np.savez(path, **src)
                with self.assertRaises(ValueError) as ctx:
                    load_prediction_cache(path)
                self.assertIn(missing, str(ctx.exception))

    def test_legacy_cache_missing_codes_hints_rebuild(self):
        src = _synth_cache()
        path = self.tmp_path("legacy.npz")
        np.savez(path, exp_ret=src["exp_ret"], true_ret=src["true_ret"], dates=src["dates"])
        with self.assertRaises(ValueError) as ctx:
            load_prediction_cache(path)
        self.assertIn("codes", str(ctx.exception))


class TestLengthMismatch(_TempDirMixin):
    def test_load_rejects_uneven_lengths(self):
        src = _synth_cache()
        path = self.tmp_path("uneven.npz")
        np.savez(path, exp_ret=src["exp_ret"][:-2], true_ret=src["true_ret"],
                 dates=src["dates"], codes=src["codes"])
        with self.assertRaises(ValueError) as ctx:
            load_prediction_cache(path)
        self.assertIn("长度不一致", str(ctx.exception))


class TestFingerprint(_TempDirMixin):
    def test_npz_fingerprint_ignores_dict_order(self):
        src = _synth_cache()
        fwd = npz_fingerprint(src)
        rev = npz_fingerprint({k: src[k] for k in reversed(list(src.keys()))})
        self.assertEqual(fwd, rev)
        self.assertEqual(len(fwd), 40)

    def test_cache_fingerprint_stable_across_rewrite(self):
        src = _synth_cache()
        p1, p2 = self.tmp_path("a.npz"), self.tmp_path("b.npz")
        save_prediction_cache(p1, src["exp_ret"], src["true_ret"], src["dates"], src["codes"])
        save_prediction_cache(p2, src["exp_ret"], src["true_ret"], src["dates"], src["codes"])
        self.assertEqual(cache_fingerprint(p1), cache_fingerprint(p2))

    def test_cache_fingerprint_changes_with_content(self):
        src = _synth_cache()
        p1, p2 = self.tmp_path("a.npz"), self.tmp_path("b.npz")
        save_prediction_cache(p1, src["exp_ret"], src["true_ret"], src["dates"], src["codes"])
        save_prediction_cache(p2, src["exp_ret"] + 1e-6, src["true_ret"], src["dates"], src["codes"])
        self.assertNotEqual(cache_fingerprint(p1), cache_fingerprint(p2))

    def test_fingerprint_normalizes_memory_layout(self):
        src = _synth_cache()
        wide = np.stack([src["exp_ret"], src["true_ret"]], axis=1)
        c_order = np.ascontiguousarray(wide[:, 0])
        f_order = np.asfortranarray(wide)[:, 0]
        self.assertEqual(npz_fingerprint({"v": c_order}), npz_fingerprint({"v": f_order}))


class TestSignalTime(unittest.TestCase):
    def test_default_t1_is_shanghai_1500(self):
        got = signal_time_for(date(2025, 6, 3))
        self.assertEqual(got, datetime(2025, 6, 3, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIsNotNone(got.tzinfo)
        offset = got.utcoffset()
        assert offset is not None
        self.assertEqual(offset.total_seconds(), 8 * 3600)
        self.assertEqual(SHANGHAI_TZ.key, "Asia/Shanghai")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            signal_time_for(date(2025, 6, 3), mode="T0")

    def test_require_keys_missing(self):
        with self.assertRaises(ValueError) as ctx:
            require_keys({"a": 1}, ("a", "b"), "单元")
        self.assertIn("b", str(ctx.exception))
        require_keys({"a": 1, "b": 2}, ("a", "b"), "单元")


class TestOhlcKeys(unittest.TestCase):
    def test_ohlc_keys_align_with_run_backtest(self):
        self.assertEqual(OHLC_PATH_KEYS, ("codes", "dates", "t_close", "open_t1", "open_t6"))

    def test_validate_ohlc_ok_and_missing(self):
        validate_ohlc_path_arrays(_synth_ohlc(), "单测")
        bad = _synth_ohlc()
        del bad["open_t6"]
        with self.assertRaises(ValueError) as ctx:
            validate_ohlc_path_arrays(bad, "单测")
        self.assertIn("open_t6", str(ctx.exception))

    def test_validate_ohlc_rejects_uneven_lengths(self):
        bad = _synth_ohlc()
        bad["open_t1"] = bad["open_t1"][:-1]
        with self.assertRaises(ValueError):
            validate_ohlc_path_arrays(bad, "单测")


if __name__ == "__main__":
    unittest.main()
