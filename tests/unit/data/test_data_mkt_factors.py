"""全市场截面因子（mkt_factors）契约测试（参考 test_data_cs_rank.py 风格）。

覆盖：
1. `DEFAULT_MKT_FACTOR_FEATURES` 默认 11 个已知因子且中性填充完备。
2. 配置默认关闭（mkt_factors=False）时输出维度与现有行为一致。
3. 开启时输出维度 = 归一化输出 + cs 列 + mkt 列，列序 [归一化, cs, mkt]。
4. 合成数据手算 breadth_up/dispersion/limit_up/down/skew。
5. 同一交易日广播值全股票相同。
6. 在 max_codes 截断之前全市场口径计算。
7. mkt 列旁路归一化（relative 下保持原始占比/统计值）。
8. 早期日期历史窗口不足填中性值；缺席原始列（volume/ma_20）填中性值。
9. 非法 mkt_factor_list 直接报错。
10. 缓存 key 对 mkt_factors 敏感，默认关闭时 key 不变；可经缓存往返一致。
11. 与 cs_rank 组合时列序正确。

全部使用 tempfile 造 mini parquet 与临时 cache_dir，不污染真实数据/缓存。
"""
import gc
import os
import shutil
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset
from data.feature_cache import compute_cache_key
from data.schema import DEFAULT_MKT_FACTOR_FEATURES, MKT_FACTOR_NEUTRAL

BINS = (np.linspace(-25, 25, 51) / 100).tolist()


def _frame(n_days: int = 4) -> pd.DataFrame:
    """A/B/C 三股同日历；每日收益恒为 A=+10%/B=-10%/C=0（mkt_ret=0）。

    手算（每日截面 ret=[0.1,-0.1,0.0]）：
    breadth_up=1/3，dispersion=std(ddof=1)=0.1，limit_up=1/3，limit_down=1/3，skew=0。
    无 volume/TOT_SHARE/ma_20 列 -> turnover=0.0、breadth_ma20=0.5（中性）。
    """
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    specs = {"A": (10.0, 11.0), "B": (10.0, 9.0), "C": (10.0, 10.0)}
    rows = []
    for code, (open_p, close_p) in specs.items():
        for t, day in enumerate(dates):
            rows.append({
                "code": code, "kline_time": day,
                "open": open_p, "high": close_p + 0.5, "low": close_p - 0.5, "close": close_p,
                "is_trading": True, "dmi": 1.0 + t * 0.1,
            })
    return pd.DataFrame(rows)


def _frame_uptrend(n_days: int = 6) -> pd.DataFrame:
    """A/B/C 每日收益恒 +5%（mkt_ret=0.05）：mom_5d 在第 5 天起 = 1.05**5-1。"""
    dates = pd.date_range("2024-01-01", periods=n_days, freq="D")
    rows = []
    for code in ("A", "B", "C"):
        for t, day in enumerate(dates):
            rows.append({
                "code": code, "kline_time": day,
                "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5,
                "is_trading": True, "dmi": 1.0 + t * 0.1,
            })
    return pd.DataFrame(rows)


def _config(path: str, **over) -> ParquetDataConfig:
    base: dict = {
        "parquet_path": path,
        "seq_len": 2,
        "horizon": 1,
        "bins": BINS,
        "feature_cols": ["dmi"],
        "normalize": "none",
        "num_workers": 0,
    }
    base.update(over)
    return ParquetDataConfig(**base)


class _parquet:
    def __init__(self, frame):
        self.frame = frame

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="mktf_")
        self.path = os.path.join(self.dir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(self.frame, preserve_index=False), self.path)
        return self.path

    def __exit__(self, *args):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestMktFactorConfig(unittest.TestCase):
    def test_default_list_is_11_unique_factors_with_neutral(self):
        factors = list(DEFAULT_MKT_FACTOR_FEATURES)
        self.assertEqual(len(factors), 11)
        self.assertEqual(len(set(factors)), 11)
        self.assertTrue(all(f.startswith("mkt_") for f in factors))
        self.assertEqual(set(MKT_FACTOR_NEUTRAL), set(factors))

    def test_config_defaults_off(self):
        cfg = ParquetDataConfig()
        self.assertFalse(cfg.mkt_factors)
        self.assertIsNone(cfg.mkt_factor_list)

    def test_default_resolver_uses_builtin_list(self):
        resolved = ParquetDataset._resolve_mkt_factor_list(None)
        self.assertEqual(resolved, list(DEFAULT_MKT_FACTOR_FEATURES))

    def test_custom_resolver_dedups_and_rejects_unknown(self):
        resolved = ParquetDataset._resolve_mkt_factor_list(
            ["mkt_breadth_up", "mkt_skew", "mkt_breadth_up"])
        self.assertEqual(resolved, ["mkt_breadth_up", "mkt_skew"])
        with self.assertRaisesRegex(ValueError, "mkt_factor_list"):
            ParquetDataset._resolve_mkt_factor_list(["mkt_nope"])


class TestMktFactorOffUnchanged(unittest.TestCase):
    def test_default_off_matches_explicit_off_and_dimension(self):
        with _parquet(_frame()) as path:
            default = ParquetDataset(_config(path))
            explicit = ParquetDataset(_config(path, mkt_factors=False, mkt_factor_list=None))
        self.assertEqual(default.num_features, 1)
        self.assertEqual(default.feature_cols_out, ["dmi"])
        self.assertEqual(default.mkt_factor_cols, [])
        for code in default.groups:
            np.testing.assert_array_equal(
                default.groups[code]["features"], explicit.groups[code]["features"]
            )


class TestMktFactorValues(unittest.TestCase):
    def test_hand_computed_breadth_dispersion_limits_skew(self):
        subset = ["mkt_breadth_up", "mkt_dispersion", "mkt_limit_up", "mkt_limit_down", "mkt_skew"]
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(path, mkt_factors=True, mkt_factor_list=subset))
        self.assertEqual(ds.feature_cols_out, ["dmi"] + subset)
        self.assertEqual(ds.num_features, 1 + len(subset))
        col = {name: ds.feature_cols_out.index(name) for name in subset}
        for code in ("A", "B", "C"):
            feat = ds.groups[code]["features"]
            np.testing.assert_allclose(feat[:, col["mkt_breadth_up"]], 1.0 / 3.0, rtol=0, atol=1e-6)
            np.testing.assert_allclose(feat[:, col["mkt_dispersion"]], 0.1, rtol=0, atol=1e-6)
            np.testing.assert_allclose(feat[:, col["mkt_limit_up"]], 1.0 / 3.0, rtol=0, atol=1e-6)
            np.testing.assert_allclose(feat[:, col["mkt_limit_down"]], 1.0 / 3.0, rtol=0, atol=1e-6)
            np.testing.assert_allclose(feat[:, col["mkt_skew"]], 0.0, rtol=0, atol=1e-6)

    def test_broadcast_same_value_across_stocks(self):
        subset = ["mkt_breadth_up", "mkt_dispersion", "mkt_mom_5d"]
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(path, mkt_factors=True, mkt_factor_list=subset))
        idx = [ds.feature_cols_out.index(name) for name in subset]
        np.testing.assert_array_equal(
            ds.groups["A"]["features"][:, idx], ds.groups["B"]["features"][:, idx])
        np.testing.assert_array_equal(
            ds.groups["B"]["features"][:, idx], ds.groups["C"]["features"][:, idx])

    def test_computed_before_max_codes(self):
        # 若先按 max_codes 截断到 A/B，breadth_up 会是 1/2；正确全市场口径应为 1/3。
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(
                path, mkt_factors=True, mkt_factor_list=["mkt_breadth_up"], max_codes=2))
        self.assertIn("A", ds.groups)
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, -1], 1.0 / 3.0, rtol=0, atol=1e-6)

    def test_mom_computed_value_after_warmup(self):
        # 全 +5% 趋势：mom_5d 前 4 行中性 0，第 5/6 行 = 1.05**5-1；vol_20 全程中性 0。
        subset = ["mkt_mom_5d", "mkt_vol_20d", "mkt_mom_20d"]
        with _parquet(_frame_uptrend()) as path:
            ds = ParquetDataset(_config(path, mkt_factors=True, mkt_factor_list=subset))
        col = {name: ds.feature_cols_out.index(name) for name in subset}
        mom = ds.groups["A"]["features"][:, col["mkt_mom_5d"]]
        np.testing.assert_allclose(mom[:4], 0.0, rtol=0, atol=1e-9)
        np.testing.assert_allclose(mom[4:], 1.05 ** 5 - 1.0, rtol=0, atol=1e-6)
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, col["mkt_vol_20d"]], 0.0, rtol=0, atol=1e-9)
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, col["mkt_mom_20d"]], 0.0, rtol=0, atol=1e-9)

    def test_missing_source_columns_use_neutral(self):
        # 合成数据无 ma_20/volume/TOT_SHARE -> breadth_ma20=0.5、turnover=0.0。
        subset = ["mkt_breadth_ma20", "mkt_turnover"]
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(path, mkt_factors=True, mkt_factor_list=subset))
        col = {name: ds.feature_cols_out.index(name) for name in subset}
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, col["mkt_breadth_ma20"]], 0.5, rtol=0, atol=1e-9)
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, col["mkt_turnover"]], 0.0, rtol=0, atol=1e-9)

    def test_bypasses_relative_normalization(self):
        subset = ["mkt_breadth_up", "mkt_dispersion"]
        with _parquet(_frame()) as path:
            cfg = _config(path, mkt_factors=True, mkt_factor_list=subset,
                           normalize="relative", feature_cols=["dmi", "open"])
            ds = ParquetDataset(cfg)
        self.assertEqual(ds.feature_cols_out, ["dmi", "open"] + subset)
        np.testing.assert_allclose(
            ds.groups["A"]["features"][:, -2], 1.0 / 3.0, rtol=0, atol=1e-6)
        np.testing.assert_allclose(ds.groups["A"]["features"][:, -1], 0.1, rtol=0, atol=1e-6)

    def test_combines_with_cs_rank_column_order(self):
        with _parquet(_frame()) as path:
            ds = ParquetDataset(_config(
                path, cs_rank=True, cs_rank_features=["dmi"],
                mkt_factors=True, mkt_factor_list=["mkt_breadth_up", "mkt_dispersion"]))
        self.assertEqual(
            ds.feature_cols_out, ["dmi", "cs_dmi", "mkt_breadth_up", "mkt_dispersion"])
        self.assertEqual(ds.num_features, 4)


class TestMktFactorCache(unittest.TestCase):
    @staticmethod
    def _kwargs() -> dict:
        return {
            "base_identity": {"parquet_path": "x", "size": 1, "mtime_ns": 2},
            "role": "training", "rolling_scope": None, "scaler_identity_hash": "h",
            "seq_len": 2, "horizon": 1, "max_windows_per_code": None, "bins_digest": "d",
        }

    def test_cache_key_sensitive_and_default_stable(self):
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), mkt_factors=True,
                              mkt_factor_list=["mkt_breadth_up"]),
            compute_cache_key(**self._kwargs()),
        )
        # 默认（不传）与显式关闭同 key
        self.assertEqual(compute_cache_key(**self._kwargs()),
                         compute_cache_key(**self._kwargs(), mkt_factors=False))
        # 启用时不同因子列表必须派生不同 key
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), mkt_factors=True,
                              mkt_factor_list=["mkt_breadth_up"]),
            compute_cache_key(**self._kwargs(), mkt_factors=True,
                              mkt_factor_list=["mkt_skew"]),
        )
        # cs_rank 与 mkt_factors 各自独立影响 key
        self.assertNotEqual(
            compute_cache_key(**self._kwargs(), mkt_factors=True,
                              mkt_factor_list=["mkt_breadth_up"]),
            compute_cache_key(**self._kwargs(), cs_rank=True, cs_rank_features=["dmi"],
                              mkt_factors=True, mkt_factor_list=["mkt_breadth_up"]),
        )

    def test_round_trip_through_cache(self):
        with _parquet(_frame()) as path:
            cache_dir = tempfile.mkdtemp(prefix="mktf_cache_")
            try:
                cfg = _config(path, mkt_factors=True,
                              mkt_factor_list=["mkt_breadth_up", "mkt_dispersion"],
                              cache_enabled=True, cache_dir=cache_dir)
                first = ParquetDataset(cfg)
                second = ParquetDataset(cfg)  # 二次构造命中缓存
                self.assertEqual(first.num_features, second.num_features)
                self.assertEqual(first.feature_cols_out, second.feature_cols_out)
                for code in first.groups:
                    np.testing.assert_array_equal(
                        first.groups[code]["features"], second.groups[code]["features"]
                    )
            finally:
                del first, second
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)

    def test_relative_cache_hit_accepts_appended_mkt_columns(self):
        with _parquet(_frame()) as path:
            cache_dir = tempfile.mkdtemp(prefix="mktf_rel_cache_")
            try:
                cfg = _config(path, mkt_factors=True,
                              mkt_factor_list=["mkt_breadth_up"],
                              normalize="relative", feature_cols=["dmi", "open"],
                              cache_enabled=True, cache_dir=cache_dir)
                first = ParquetDataset(cfg)
                second = ParquetDataset(cfg)  # 命中缓存，触发 _resolve_scaler_on_cache_hit
                self.assertEqual(second.feature_cols_out, ["dmi", "open", "mkt_breadth_up"])
                self.assertEqual(first.num_features, second.num_features)
                for code in first.groups:
                    np.testing.assert_array_equal(
                        first.groups[code]["features"], second.groups[code]["features"]
                    )
            finally:
                del first, second
                gc.collect()
                shutil.rmtree(cache_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
