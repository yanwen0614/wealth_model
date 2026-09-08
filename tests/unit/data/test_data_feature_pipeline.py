"""Focused contracts for the approved parquet feature pipeline."""
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset
from data.scaler import PerCodeGroupedScaler
from data.schema import APPROVED_RAW_FEATURES


class TestFeaturePipeline(unittest.TestCase):
    @staticmethod
    def _frame(days: int = 8) -> pd.DataFrame:
        rows = []
        for day in range(days):
            row = {"code": "A", "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=day),
                   "is_trading": True, "close": 10.0 + day}
            row.update({col: 10.0 + day for col in APPROVED_RAW_FEATURES})
            row["margin_balance_ratio"] = 0.5
            rows.append(row)
        return pd.DataFrame(rows)

    def test_save_rejects_unbound_identity(self):
        frame = pd.DataFrame({"code": ["A", "A"], "kline_time": pd.date_range("2020-01-01", periods=2),
                              "close": [10.0, 11.0], "open": [10.0, 11.0]})
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        with tempfile.NamedTemporaryFile() as file, self.assertRaisesRegex(TypeError, "identity"):
            scaler.save(file.name)

    def test_training_refits_mismatch_but_validation_requires_scaler(self):
        with tempfile.NamedTemporaryFile(suffix=".parquet") as data_file, tempfile.NamedTemporaryFile() as cache_file:
            pq.write_table(pa.Table.from_pandas(self._frame()), data_file.name)
            stale = PerCodeGroupedScaler().fit(self._frame(), APPROVED_RAW_FEATURES)
            stale.set_identity({"stale": True})
            stale.save(cache_file.name)
            train = ParquetDataset(ParquetDataConfig(parquet_path=data_file.name, seq_len=2, horizon=1, scaler_path=cache_file.name))
            self.assertIsNotNone(train.scaler_stats)
            assert train.scaler_stats is not None
            self.assertNotEqual(train.scaler_stats.identity_hash, stale.identity_hash)
            with self.assertRaisesRegex(ValueError, "scaler"):
                ParquetDataset(ParquetDataConfig(parquet_path=data_file.name, seq_len=2, horizon=1, role="validation"))

    def test_unseen_code_uses_global_winsor_fallback(self):
        frame = pd.DataFrame({"code": ["A"] * 4, "kline_time": pd.date_range("2020-01-01", periods=4),
                              "close": [10.0] * 4, "volatility_5d": [1.0, 2.0, 3.0, 100.0]})
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["volatility_5d"])
        out = scaler.transform_code("UNSEEN", np.array([[1000.0]]), ["volatility_5d"], np.array([10.0]))
        self.assertLessEqual(out[0, 0], scaler.global_stats["volatility_5d"]["winsor_upper"])

    def test_identity_hash_is_canonical_and_cache_payload_is_v3(self):
        manifest = {"path": "/data/a.parquet", "features": ["open"], "version": "v3"}
        self.assertEqual(
            PerCodeGroupedScaler.identity_hash_for(manifest),
            PerCodeGroupedScaler.identity_hash_for(dict(reversed(list(manifest.items())))),
        )
        frame = pd.DataFrame({"code": ["A", "A"], "kline_time": pd.date_range("2020-01-01", periods=2),
                              "close": [10.0, 11.0], "open": [10.0, 11.0]})
        scaler = PerCodeGroupedScaler(add_mask=False).fit(frame, ["open"])
        scaler.set_identity(manifest)
        with tempfile.NamedTemporaryFile() as file:
            scaler.save(file.name)
            loaded = PerCodeGroupedScaler.load(file.name)
        self.assertEqual(loaded.identity_hash, scaler.identity_hash)

    def test_missing_is_neutral_and_g9_mask_tracks_original_observation(self):
        frame = pd.DataFrame({"code": ["A", "A", "A"], "kline_time": pd.date_range("2020-01-01", periods=3),
                              "close": [10.0, 10.0, 10.0], "open": [10.0, np.nan, 12.0],
                              "margin_balance_ratio": [np.nan, 2.0, 0.5]})
        scaler = PerCodeGroupedScaler().fit(frame, ["open", "margin_balance_ratio"])
        out = scaler.transform_code("A", frame[["open", "margin_balance_ratio"]].to_numpy(), ["open", "margin_balance_ratio"], frame.close.to_numpy())
        self.assertTrue(np.isfinite(out).all())
        self.assertEqual(out[1, 0], 0.0)
        self.assertEqual(out[0, 2], 0.0)
        self.assertEqual(out[1, 2], 1.0)

    def test_date_bounded_validation_uses_context_without_exposing_it(self):
        rows = []
        for code in ["A", "B"]:
            for day in range(8):
                rows.append({"code": code, "kline_time": pd.Timestamp("2020-01-01") + pd.Timedelta(days=day),
                             "is_trading": True, "close": 10.0 + day, "open": 10.0 + day,
                             "high": 11.0 + day, "low": 9.0 + day, "ma_5": 10.0 + day, "ma_10": 10.0 + day,
                             "ma_20": 10.0 + day, "ma_60": 10.0 + day, "ema_12": 10.0 + day, "ema_26": 10.0 + day,
                             "sar": 10.0 + day, "trend_duokong": 10.0 + day, "trend_shortline": 10.0 + day,
                             **{col: 0.1 for col in ["volatility_5d", "volatility_10d", "volatility_20d", "std_5", "std_10", "std_20", "atr", "volume_ratio_5d", "volume_ratio_10d", "amihud", "macd", "dmi", "adx", "boll", "kelch", "trend_duokong_dev", "gross_margin", "net_margin", "roe", "roa", "debt_to_equity", "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio", "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio"]}})
        with tempfile.NamedTemporaryFile(suffix=".parquet") as file:
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(rows)), file.name)
            train = ParquetDataset(ParquetDataConfig(parquet_path=file.name, seq_len=2, horizon=1, end_date="2020-01-04"))
            valid = ParquetDataset(ParquetDataConfig(parquet_path=file.name, seq_len=2, horizon=1, start_date="2020-01-05"), train.scaler_stats)
        self.assertTrue(all(times[0] >= np.datetime64("2020-01-05") for times in (g["kline_time"] for g in valid.groups.values())))
        self.assertTrue(np.isfinite(valid.groups["A"]["features"]).all())


if __name__ == "__main__":
    unittest.main()
