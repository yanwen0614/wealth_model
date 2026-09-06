"""open-open 标签口径单测（TDD RED -> GREEN）。

公式锚定: future_ret[t] = open[t+1+horizon] / open[t+1] - 1
有效条件: open[t+1] 与 open[t+1+horizon] 均非 NaN 且 open[t+1] > 0，否则 NaN
窗口边界: label_pos=s+seq_len-1 需 label_pos+1+horizon <= n-1，max_s = n-seq_len-horizon
"""
import os
import shutil
import tempfile
import unittest

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data.dataset import ParquetDataConfig, ParquetDataset, _future_ret_open_open


def _make_mini_df() -> pd.DataFrame:
    rows = []
    for code, dirty in (("000001", False), ("000002", True)):
        for t in range(80):
            open_v = 10.0 + t
            if dirty and t == 65:
                open_v = 0.0
            if dirty and t == 70:
                open_v = np.nan
            rows.append({
                "code": code,
                "kline_time": pd.Timestamp("2025-01-01") + pd.Timedelta(days=t),
                "open": open_v,
                "high": open_v + 1.0,
                "low": open_v - 1.0,
                "close": open_v + 0.5,
                "volume": 1000.0,
                "amount": 10000.0,
                "TOT_SHARE": 500.0,
                "is_trading": True,
            })
    return pd.DataFrame(rows)


class TestFutureRetOpenOpen(unittest.TestCase):
    def test_formula_exact(self):
        """UT1: 逐点手算 open[t+6]/open[t+1]-1 全数组对齐。"""
        open_arr = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0])
        fr = _future_ret_open_open(open_arr, 5)
        for t in range(3):
            expected = open_arr[t + 6] / open_arr[t + 1] - 1.0
            self.assertAlmostEqual(fr[t], expected, places=12)
        self.assertTrue(np.all(np.isnan(fr[3:])))

    def test_nan_endpoints(self):
        """UT2: open[t+1] 或 open[t+1+horizon] 为 NaN 时标签 NaN（停牌/缺数语义）。"""
        nan_denom = np.array([10.0, 11.0, np.nan, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0])
        fr = _future_ret_open_open(nan_denom, 5)
        self.assertTrue(np.isnan(fr[1]))
        nan_num = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, np.nan, 17.0, 18.0])
        fr2 = _future_ret_open_open(nan_num, 5)
        self.assertTrue(np.isnan(fr2[0]))
        self.assertAlmostEqual(fr2[1], 17.0 / 12.0 - 1.0, places=12)

    def test_nonpositive_base_protected(self):
        """UT3: open[t+1]<=0（0 与负值）-> NaN 不抛异常；open[t+6]<=0 正常计算。"""
        zero_base = np.array([10.0, 0.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0])
        fr = _future_ret_open_open(zero_base, 5)
        self.assertTrue(np.isnan(fr[0]))
        neg_base = np.array([10.0, -1.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0])
        self.assertTrue(np.isnan(_future_ret_open_open(neg_base, 5)[0]))
        neg_num = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, -20.0, 17.0, 18.0])
        fr3 = _future_ret_open_open(neg_num, 5)
        self.assertAlmostEqual(fr3[0], -20.0 / 11.0 - 1.0, places=12)

    def test_tail_truncation(self):
        """UT4a: 尾部 t 不满足 t+1+horizon<=n-1 时标签 NaN，其余非 NaN。"""
        open_arr = np.arange(1.0, 12.0)
        fr = _future_ret_open_open(open_arr, 5)
        self.assertTrue(np.all(np.isnan(fr[5:])))
        self.assertFalse(np.any(np.isnan(fr[:5])))

    def test_short_array_all_nan(self):
        """UT4b: n <= horizon+1 时无有效 t，返回全 NaN 且长度不变。"""
        for n in (0, 1, 5, 6, 7):
            fr = _future_ret_open_open(np.full(n, 10.0), 5)
            self.assertEqual(len(fr), n)
            if n <= 6:
                self.assertTrue(np.all(np.isnan(fr)))
            else:
                self.assertAlmostEqual(fr[0], 0.0, places=12)

    def test_horizon_parameterized(self):
        """UT5: horizon=5 默认与 horizon=2 结果一致性抽查。"""
        open_arr = np.arange(10.0, 21.0)
        fr5 = _future_ret_open_open(open_arr, 5)
        fr2 = _future_ret_open_open(open_arr, 2)
        self.assertAlmostEqual(fr5[0], open_arr[6] / open_arr[1] - 1.0, places=12)
        self.assertAlmostEqual(fr2[0], open_arr[3] / open_arr[1] - 1.0, places=12)
        self.assertAlmostEqual(fr2[1], open_arr[4] / open_arr[2] - 1.0, places=12)
        self.assertAlmostEqual(fr2[7], open_arr[10] / open_arr[8] - 1.0, places=12)
        self.assertTrue(np.all(np.isnan(fr2[8:])))


class TestDatasetOpenOpenIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        cls.parquet_path = os.path.join(cls.tmpdir, "mini.parquet")
        pq.write_table(pa.Table.from_pandas(_make_mini_df(), preserve_index=False), cls.parquet_path)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _load(self) -> ParquetDataset:
        cfg = ParquetDataConfig(
            parquet_path=self.parquet_path, seq_len=60, horizon=5,
            normalize="none", batch_size=8, num_workers=0,
        )
        return ParquetDataset(cfg)

    def test_window_count_max_s(self):
        """UT4c: n=80, seq=60, horizon=5 -> max_s=15（旧口径 16 收 1）；脏行过滤对应窗口。"""
        ds = self._load()
        count_a = sum(1 for c, _ in ds.index if c == "000001")
        count_b = sum(1 for c, _ in ds.index if c == "000002")
        self.assertEqual(count_a, 15)
        self.assertEqual(count_b, 13)
        starts_b = sorted(s for c, s in ds.index if c == "000002")
        self.assertNotIn(5, starts_b)
        self.assertNotIn(10, starts_b)
        self.assertIn(4, starts_b)
        self.assertIn(6, starts_b)
        self.assertIn(9, starts_b)
        self.assertIn(11, starts_b)

    def test_label_values(self):
        """UT4d: 逐点核对 groups 内 future_ret 与手算 open[t+6]/open[t+1]-1 一致。"""
        ds = self._load()
        g_a = ds.groups["000001"]
        self.assertAlmostEqual(float(g_a["future_ret"][59]), 75.0 / 70.0 - 1.0, places=6)
        self.assertAlmostEqual(float(g_a["future_ret"][73]), 89.0 / 84.0 - 1.0, places=6)
        self.assertTrue(np.all(np.isnan(g_a["future_ret"][74:])))
        g_b = ds.groups["000002"]
        self.assertAlmostEqual(float(g_b["future_ret"][59]), -1.0, places=10)
        self.assertTrue(np.isnan(g_b["future_ret"][64]))
        self.assertTrue(np.isnan(g_b["future_ret"][69]))
        self.assertTrue(np.all(np.isnan(g_b["future_ret"][74:])))

    def test_getitem_y_ret_clip(self):
        """UT4e: open[t+6]=0 使标签=-1，__getitem__ y_ret clip 到 -0.5。"""
        ds = self._load()
        idx = ds.index.index(("000002", 0))
        _, _, y_ret = ds[idx]
        self.assertAlmostEqual(float(y_ret), -0.5, places=5)
        idx_a = ds.index.index(("000001", 0))
        _, _, y_ret_a = ds[idx_a]
        self.assertAlmostEqual(float(y_ret_a), 75.0 / 70.0 - 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
