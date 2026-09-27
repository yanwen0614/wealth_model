"""T01 RED: Dataset __getitem__ must return (x, y_cls, y_ret), y_ret clip +/-0.5."""
import unittest

import numpy as np
import torch

from data.dataset import ParquetDataConfig, ParquetDataset


def _mock_ds(seq_len=60, feat=45):
    cfg = ParquetDataConfig(seq_len=seq_len, horizon=5)
    ds = ParquetDataset.__new__(ParquetDataset)
    ds.config = cfg
    ds.bins = np.array(cfg.bins, dtype=np.float64)
    n = seq_len + 5
    feats = np.random.randn(n, feat).astype(np.float32)
    # 含尖刺 12.73 (1273%) 与正常值，验证 clip
    fret = np.full(n, 0.02, dtype=np.float32)
    fret[seq_len - 1] = 12.73
    disc = np.digitize(fret.astype(np.float64), ds.bins).astype(np.int64)
    code = "000001"
    ds.groups = {code: {"features": feats, "future_ret": fret,
                        "discrete": disc, "kline_time": np.arange(n), "n": n}}
    ds.index = [(code, 0)]
    ds.feature_cols = [f"f{i}" for i in range(feat)]
    ds.feature_cols_out = list(ds.feature_cols)
    ds.num_features = feat
    return ds


class TestDatasetTriple(unittest.TestCase):
    def test_getitem_returns_three(self):
        ds = _mock_ds()
        out = ds[0]
        self.assertEqual(len(out), 3, "must return (x, y_cls, y_ret)")
        x, y_cls, y_ret = out
        self.assertEqual(tuple(x.shape), (45, 60))
        self.assertEqual(y_cls.dtype, torch.long)
        self.assertEqual(y_ret.dtype, torch.float32)

    def test_y_ret_clipped(self):
        ds = _mock_ds()
        _, _, y_ret = ds[0]
        self.assertLessEqual(float(y_ret), 0.5)
        self.assertGreaterEqual(float(y_ret), -0.5)
        self.assertAlmostEqual(float(y_ret), 0.5, places=5)


if __name__ == "__main__":
    unittest.main()
