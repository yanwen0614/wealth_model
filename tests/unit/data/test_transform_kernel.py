"""data/transform_kernel.py 纯函数内核：与三处 transform_code 的 parity 契约（T07）。"""
import unittest

import numpy as np
import pandas as pd

from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import PerCodeGroupedScaler, RelativeScaler, _relative_transform, column_rule
from data.transform_kernel import append_shared_mask, apply_column_rule, relative_transform


def _fit_per_code(close, **columns) -> PerCodeGroupedScaler:
    frame = pd.DataFrame({"code": ["A"] * len(close),
                          "kline_time": pd.date_range("2020-01-01", periods=len(close)),
                          "close": close})
    for name, values in columns.items():
        frame[name] = values
    return PerCodeGroupedScaler(add_mask=False).fit(frame, list(columns))


class TestRelativeParity(unittest.TestCase):
    def test_formula_first_row_and_bad_denominator_match_scaler(self):
        vals = np.array([10.0, 10.0, 11.0])
        close = np.array([10.0, 11.0, 12.0])
        np.testing.assert_allclose(relative_transform(vals, close),
                                   _relative_transform(vals, close), rtol=0, atol=0)
        self.assertTrue(np.isnan(relative_transform(vals, close)[0]))
        bad = _relative_transform(np.array([1.0, 1.0]), np.array([np.inf, 0.0]))
        np.testing.assert_array_equal(relative_transform(np.array([1.0, 1.0]),
                                                         np.array([np.inf, 0.0])), bad)


class TestApplyParity(unittest.TestCase):
    def test_p_robust_matches_per_code_scaler(self):
        close = np.array([10.0, 10.0, 10.0, 10.0])
        raw = np.array([10.0, 12.0, 14.0, 16.0])
        scaler = _fit_per_code(close, open=raw)
        stat = scaler.per_code_stats["A"]["open"]
        expected = scaler.transform_code("A", raw.reshape(-1, 1), ["open"], close)[:, 0]
        np.testing.assert_allclose(
            apply_column_rule(raw, np.isfinite(raw), column_rule("open"),
                              close=close, stat=stat), expected, rtol=0, atol=1e-6)

    def test_rng_matches_relative_scaler(self):
        cases = {"amihud": np.array([0.0, 1e-13]),
                 "roe": np.array([1.0, 100.0]),
                 "margin_balance_ratio_ts": np.array([-0.5, 0.3]),
                 "margin_net_buy_ratio_raw": np.array([-3.0, 0.5])}
        for column, raw in cases.items():
            with self.subTest(column=column):
                expected = RelativeScaler([column]).transform_code(
                    "x", raw.reshape(-1, 1), [column])[:, 0]
                actual = apply_column_rule(raw, np.isfinite(raw), column_rule(column))
                np.testing.assert_allclose(actual.astype(np.float32),
                                           expected, rtol=0, atol=0)

    def test_missing_fills_zero_and_unknown_transform_raises(self):
        raw = np.array([np.nan, np.inf])
        out = apply_column_rule(raw, np.isfinite(raw), column_rule("roe"))
        np.testing.assert_array_equal(out, [0.0, 0.0])
        with self.assertRaises(ValueError):
            apply_column_rule(np.array([1.0]), np.array([True]),
                              column_rule("roe").__class__("X", "nope", None))


class TestRollingNonscopeParity(unittest.TestCase):
    def test_nonscope_matches_relative_scaler(self):
        cols = ["gross_margin", "margin_balance_ratio", "close"]
        values = np.array([[2.5, np.nan, 10.0], [np.inf, 1.5, 11.0], [-3.0, 0.25, 12.0]])
        close = np.array([10.0, 10.0, 11.0])
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope="e0"))
        rolling = normalizer.transform_code(values, cols, close).values
        expected = RelativeScaler(cols).transform_code("x", values, cols, close=close)
        self.assertEqual(rolling.shape, expected.shape)
        np.testing.assert_allclose(rolling, expected, rtol=0, atol=0)


class TestSharedMask(unittest.TestCase):
    def test_or_semantics_none_gives_zeros_and_empty_out(self):
        out = np.zeros((3, 0))
        observed = np.array([False, True, True])
        np.testing.assert_array_equal(append_shared_mask(out, observed)[:, 0], [0.0, 1.0, 1.0])
        np.testing.assert_array_equal(append_shared_mask(np.zeros((2, 2)), None)[:, 2], [0.0, 0.0])


class TestKernelHasNoScalerDependency(unittest.TestCase):
    def test_source_imports_neither_scaler_nor_rolling(self):
        import pathlib
        source = pathlib.Path("data/transform_kernel.py").read_text()
        self.assertNotIn("data.scaler", source)
        self.assertNotIn("data.rolling_scaler", source)
        self.assertNotIn("data.schema", source)


if __name__ == "__main__":
    unittest.main()
