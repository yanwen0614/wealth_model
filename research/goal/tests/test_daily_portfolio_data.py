import unittest
from typing import cast
from unittest.mock import patch

import numpy as np
import pandas as pd

from models.daily_portfolio_data import (
    DailyRecord,
    assemble_daily_record,
    make_daily_signal_dates,
)


class DailyPortfolioDataTests(unittest.TestCase):
    @staticmethod
    def _frame(periods=70):
        dates = pd.bdate_range("2024-01-02", periods=periods)
        rows = []
        for code_index, code in enumerate(("B", "A", "C")):
            for index, date in enumerate(dates):
                row = {
                    "code": code,
                    "kline_time": date,
                    "close": 10.0 + code_index + index,
                    "open": 10.5 + code_index + index,
                    "amount": float((3 - code_index) * 1000 + index),
                    "is_trading": True,
                }
                row.update({f"feature_{column}": float(code_index * 100 + index + column) for column in range(45)})
                rows.append(row)
        return pd.DataFrame(rows), dates

    @classmethod
    def _frame_with_volume(cls, periods=70):
        frame, dates = cls._frame(periods)
        frame["volume"] = frame["amount"] * 10
        return frame, dates

    def test_signal_dates_respect_warmup_horizon_split_and_stride(self):
        _, dates = self._frame(20)

        got = make_daily_signal_dates(
            dates,
            warmup=3,
            split_start=dates[5],
            split_end=dates[15],
            horizon=2,
            stride=2,
        )

        self.assertEqual(list(got), [dates[5], dates[7], dates[9], dates[11], dates[13]])

    def test_record_uses_signal_features_and_deterministic_amount_code_order(self):
        frame, dates = self._frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        signal_date = dates[60]

        record = assemble_daily_record(
            frame, signal_date, feature_columns, candidate_limit=2, horizon=5, split_end=dates[-1]
        )

        self.assertEqual(record.features.shape, (1000, 49))
        self.assertEqual(record.codes[:3], ("B", "A", ""))
        self.assertEqual(record.buy_date, dates[61])
        self.assertEqual(record.sell_date, dates[65])
        self.assertEqual(tuple(record.feature_columns[-4:]), ("mean_5", "mean_20", "vol_20", "ret_20"))
        self.assertEqual(
            set(record.reward_sidecar.columns),
            {"buy_open", "sell_open", "buy_amount", "reward_valid", "code"},
        )
        self.assertFalse(record.reward_valid[2])
        self.assertTrue(np.array_equal(record.features[2], np.zeros(49, dtype=np.float32)))

    def test_future_rows_cannot_change_signal_features_or_candidate_order(self):
        frame, dates = self._frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        before = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)
        changed = frame.copy()
        changed.loc[changed["kline_time"] > dates[60], feature_columns + ["amount"]] = 999999.0
        after = assemble_daily_record(changed, dates[60], feature_columns, candidate_limit=2, horizon=5)

        self.assertEqual(after.codes, before.codes)
        self.assertTrue(np.array_equal(after.features, before.features))

    def test_split_crossing_and_invalid_trade_are_masked_in_sidecar(self):
        frame, dates = self._frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        frame.loc[(frame["code"] == "B") & (frame["kline_time"] == dates[61]), "open"] = np.nan

        record = assemble_daily_record(
            frame, dates[60], feature_columns, candidate_limit=2, horizon=5, split_end=dates[63]
        )

        self.assertFalse(record.reward_valid[0])
        self.assertFalse(record.reward_valid[1])
        self.assertTrue(np.isfinite(record.reward_sidecar[["buy_open", "sell_open", "buy_amount"]].to_numpy()).all())

    def test_execution_sidecar_uses_buy_date_and_buy_date_predecessor(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]
        signal_date = dates[60]
        buy_date = dates[61]
        sell_date = dates[65]
        frame.loc[(frame["code"] == "B") & (frame["kline_time"] == sell_date), "close"] = 999999.0

        record = assemble_daily_record(frame, signal_date, feature_columns, candidate_limit=2, horizon=5)

        self.assertIsNotNone(record.execution_sidecar)
        sidecar = cast(pd.DataFrame, record.execution_sidecar)
        self.assertEqual(
            list(sidecar.columns),
            ["code", "open", "close", "volume", "amount", "is_trading", "prev_close"],
        )
        self.assertEqual(sidecar.loc[0, "code"], "B")
        self.assertEqual(sidecar.loc[0, "open"], frame.loc[(frame["code"] == "B") & (frame["kline_time"] == buy_date), "open"].iloc[0])
        self.assertEqual(sidecar.loc[0, "close"], frame.loc[(frame["code"] == "B") & (frame["kline_time"] == buy_date), "close"].iloc[0])
        self.assertEqual(sidecar.loc[0, "volume"], frame.loc[(frame["code"] == "B") & (frame["kline_time"] == buy_date), "volume"].iloc[0])
        self.assertEqual(sidecar.loc[0, "prev_close"], frame.loc[(frame["code"] == "B") & (frame["kline_time"] == signal_date), "close"].iloc[0])

    def test_explicit_false_disables_execution_sidecar_without_changing_model_inputs(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]
        default = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)

        disabled = assemble_daily_record(
            frame, dates[60], feature_columns, candidate_limit=2, horizon=5,
            include_execution_sidecar=False,
        )

        self.assertIsNone(disabled.execution_sidecar)
        self.assertEqual(disabled.codes, default.codes)
        np.testing.assert_array_equal(disabled.features, default.features)
        pd.testing.assert_frame_equal(disabled.reward_sidecar, default.reward_sidecar)

    def test_explicit_true_requires_volume_for_execution_sidecar(self):
        frame, dates = self._frame()
        feature_columns = [f"feature_{column}" for column in range(45)]

        record = assemble_daily_record(
            frame, dates[60], feature_columns, candidate_limit=2, horizon=5,
            include_execution_sidecar=True,
        )

        self.assertIsNone(record.execution_sidecar)

    def test_explicit_true_enables_execution_sidecar_when_volume_is_present(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]

        record = assemble_daily_record(
            frame, dates[60], feature_columns, candidate_limit=2, horizon=5,
            include_execution_sidecar=True,
        )

        self.assertIsNotNone(record.execution_sidecar)

    def test_execution_sidecar_includes_non_candidate_buy_date_market_rows(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]

        record = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)

        self.assertEqual(record.codes[:3], ("B", "A", ""))
        sidecar = cast(pd.DataFrame, record.execution_sidecar)
        self.assertEqual(sidecar["code"].tolist(), ["B", "A", "C"])
        self.assertEqual(
            sidecar.loc[sidecar["code"] == "C", "open"].iloc[0],
            frame.loc[(frame["code"] == "C") & (frame["kline_time"] == record.buy_date), "open"].iloc[0],
        )

    def test_execution_sidecar_does_not_require_padding_for_universe_rows(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]

        record = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)

        self.assertEqual(cast(pd.DataFrame, record.execution_sidecar)["code"].tolist(), ["B", "A", "C"])
        self.assertFalse((cast(pd.DataFrame, record.execution_sidecar)["code"] == "").any())

    def test_execution_sidecar_handles_duplicate_buy_rows_and_missing_previous_close(self):
        frame, dates = self._frame_with_volume()
        feature_columns = [f"feature_{column}" for column in range(45)]
        buy_date = dates[61]
        duplicate = frame.loc[(frame["code"] == "B") & (frame["kline_time"] == buy_date)].copy()
        duplicate.loc[:, "open"] = 999.0
        new_code = duplicate.copy()
        new_code.loc[:, "code"] = "D"
        new_code.loc[:, "kline_time"] = buy_date
        new_code.loc[:, "open"] = 12.0
        new_code.loc[:, "close"] = 12.0
        frame = pd.concat([frame, duplicate, new_code], ignore_index=True)

        record = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)

        sidecar = cast(pd.DataFrame, record.execution_sidecar)
        self.assertEqual(sidecar["code"].tolist(), ["B", "A", "C", "D"])
        self.assertEqual(sidecar.loc[sidecar["code"] == "B", "open"].iloc[0], 10.5 + 61)
        self.assertTrue(pd.isna(sidecar.loc[sidecar["code"] == "D", "prev_close"].iloc[0]))

    def test_execution_sidecar_does_not_scan_each_market_code(self):
        frame, dates = self._frame_with_volume()
        extra_codes = [f"X{index:03d}" for index in range(497)]
        extra = pd.concat(
            [frame.loc[frame["code"] == "C"].assign(code=code) for code in extra_codes],
            ignore_index=True,
        )
        frame = pd.concat([frame, extra], ignore_index=True)
        feature_columns = [f"feature_{column}" for column in range(45)]

        from pandas.core.indexing import _LocIndexer

        original_getitem = _LocIndexer.__getitem__
        loc_calls = []

        def counted_getitem(indexer, key):
            loc_calls.append(key)
            return original_getitem(indexer, key)

        with patch.object(_LocIndexer, "__getitem__", new=counted_getitem):
            record = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=1, horizon=5)

        self.assertEqual(len(cast(pd.DataFrame, record.execution_sidecar)), 500)
        self.assertLess(len(loc_calls), 30)

    def test_candidate_groups_preserve_500_candidate_output_without_repeated_filters(self):
        dates = pd.bdate_range("2024-01-02", periods=70)
        rows = []
        for code_index in range(500):
            code = f"C{code_index:03d}"
            for date_index, date in enumerate(dates):
                row = {
                    "code": code,
                    "kline_time": date,
                    "close": 20.0 + code_index + date_index,
                    "open": 20.5 + code_index + date_index,
                    "amount": float(100000 - code_index),
                    "is_trading": True,
                }
                row.update(
                    {
                        f"feature_{column}": float(code_index * 1000 + date_index + column)
                        for column in range(45)
                    }
                )
                rows.append(row)
        frame = pd.DataFrame(rows)
        feature_columns = [f"feature_{column}" for column in range(45)]
        from pandas.core.indexing import _LocIndexer

        original_getitem = _LocIndexer.__getitem__
        frame_loc_calls = []

        def counted_getitem(indexer, key):
            if indexer.obj is frame:
                frame_loc_calls.append(key)
            return original_getitem(indexer, key)

        with patch.object(_LocIndexer, "__getitem__", new=counted_getitem):
            record = assemble_daily_record(
                frame, dates[60], feature_columns, candidate_limit=500, horizon=5
            )

        self.assertEqual(record.codes[:500], tuple(f"C{index:03d}" for index in range(500)))
        self.assertEqual(record.codes[500:], ("",) * 500)
        self.assertTrue(np.array_equal(record.features[:500, 0], np.arange(500, dtype=np.float32) * 1000 + 60))
        self.assertTrue(record.reward_valid[:500].all())
        self.assertFalse(record.reward_valid[500:].any())
        self.assertLess(len(frame_loc_calls), 10)

    def test_execution_sidecar_is_optional_for_legacy_frames_and_construction(self):
        frame, dates = self._frame()
        feature_columns = [f"feature_{column}" for column in range(45)]
        record = assemble_daily_record(frame, dates[60], feature_columns, candidate_limit=2, horizon=5)

        legacy = DailyRecord(
            record.signal_date,
            record.buy_date,
            record.sell_date,
            record.codes,
            record.features,
            record.feature_columns,
            record.reward_sidecar,
        )
        self.assertIsNone(record.execution_sidecar)
        self.assertIsNone(legacy.execution_sidecar)


if __name__ == "__main__":
    unittest.main()
