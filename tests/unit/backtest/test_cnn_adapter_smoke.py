"""B05 真实样本 smoke（规格 §14.3 / 验收 7）：真实 train parquet 2 只 × 约 60 交易日。

数据：``data/test/train_data/*.parquet``（pyarrow 只读 9 列，**cnn 无 DB，无触库问题**）。
链路：真实 parquet → CnnMarketDataProvider → run_cnn_backtest（确定性合成 preds npz，
seeded RNG 经 save/load 构造）→ CnnBacktestOutcome。
断言：单位量级（真实股/真实元，与 parquet 直读逐值核对）、signal tz、逐日快照、
manifest 必含键（config_hash/data_fingerprint/order_entry/provenance）；另锁定
``run_id`` 缺省格式 ``{model_name}@{checkpoint}#top{top_n}``（B03 LOW-① + B04 收口）。
文件缺失时显式 skip（消息明确，不静默 pass）；零触网。
"""

import glob
import os
import shutil
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts import EventStatus, OrderStatus

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.common import SHANGHAI_TZ
from backtest.cnn_adapter.market import CnnMarketDataProvider
from backtest.cnn_adapter.order_strategy import DEFAULT_TOP_N
from backtest.cnn_adapter.runner import ORDER_ENTRY, CnnBacktestOutcome, run_cnn_backtest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PARQUET_GLOB = str(_REPO_ROOT / "data" / "test" / "train_data" / "*.parquet")
_CODES = ("000001.SZ", "600000.SH")
_WINDOW = 60
_MIN_COMMON_DAYS = 40
_INITIAL_CAPITAL = 1_000_000.0
_TOP_N = 2
_MODEL = "cnn_transformer"
_CHECKPOINT = "logs/run_demo/best_model.pth"


def _load_frames(parquet_path: str, codes: tuple[str, ...], window: int,
                 min_common_days: int) -> tuple[dict[str, pd.DataFrame], tuple[date, ...]]:
    """真实 parquet 按码读 9 列 → 共同交易日尾部窗口；缺文件/缺码/天数不足显式 SkipTest。"""
    if not os.path.isfile(parquet_path):
        raise unittest.SkipTest(f"真实 train parquet 缺失，smoke 显式跳过（不静默 pass）: {parquet_path}")
    loaded: dict[str, pd.DataFrame] = {}
    for code in codes:
        frame = pq.read_table(parquet_path, columns=["code", "kline_time", "open", "high", "low",
                                                     "close", "volume", "amount", "is_trading"],
                              filters=[("code", "=", code)]).to_pandas()
        frame["kline_time"] = pd.to_datetime(frame["kline_time"])
        loaded[code] = frame.sort_values("kline_time", kind="stable").reset_index(drop=True)
    common = sorted(set(loaded[codes[0]]["kline_time"].dt.date) & set(loaded[codes[1]]["kline_time"].dt.date))
    if len(common) < min_common_days:
        raise unittest.SkipTest(f"真实样本共同交易日不足 {min_common_days}（实际 {len(common)}），显式跳过")
    window_days = common[-window:]
    selected = {}
    for code, frame in loaded.items():
        filtered = frame[frame["kline_time"].dt.date.isin(window_days)]
        assert isinstance(filtered, pd.DataFrame)
        if len(filtered) != len(window_days):
            raise unittest.SkipTest(f"{code} 在窗口内缺失交易日（{len(filtered)}/{len(window_days)}），显式跳过")
        selected[code] = filtered.reset_index(drop=True)
    return selected, tuple(window_days)


def _synth_pred_cache(dates: tuple[date, ...], codes: tuple[str, ...], path: str,
                      seed: int = 7) -> dict:
    """确定性合成 preds npz：seeded RNG（同 seed 跨进程同字节），经 save/load 往返构造。"""
    rng = np.random.default_rng(seed)
    exp_ret, true_ret, days, out_codes = [], [], [], []
    for day in dates:
        for code in codes:
            exp_ret.append(float(rng.uniform(-0.05, 0.05)))
            true_ret.append(float(rng.uniform(-0.03, 0.03)))
            days.append(day.isoformat())
            out_codes.append(code)
    save_prediction_cache(path, np.asarray(exp_ret), np.asarray(true_ret),
                          np.asarray(days, dtype="datetime64[D]"), np.asarray(out_codes))
    return load_prediction_cache(path)


class TestRealSampleSmoke(unittest.TestCase):
    """真实 parquet 样本端到端 smoke：缺文件显式 skip；存在则验证单位/tz/快照/血缘。"""

    frames: dict[str, pd.DataFrame]
    dates: tuple[date, ...]
    parquet_path: str
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        hits = sorted(glob.glob(_PARQUET_GLOB))
        if not hits:
            raise unittest.SkipTest(f"真实 train parquet 缺失，smoke 显式跳过（不静默 pass）: {_PARQUET_GLOB}")
        cls.parquet_path = hits[0]
        cls.frames, cls.dates = _load_frames(cls.parquet_path, _CODES, _WINDOW, _MIN_COMMON_DAYS)
        cls.tmp = tempfile.mkdtemp(prefix="b05s_")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.pred_cache = _synth_pred_cache(cls.dates, _CODES, os.path.join(cls.tmp, "smoke_preds.npz"))

    def _provider(self) -> CnnMarketDataProvider:
        return CnnMarketDataProvider(self.parquet_path)

    def _run(self, **overrides) -> CnnBacktestOutcome:
        kwargs = {"pred_cache": self.pred_cache, "parquet_path": self.parquet_path,
                  "model_name": _MODEL, "checkpoint": _CHECKPOINT,
                  "bins_version": "BINS52_v1", "eval_script_version": "eval_bins_mapping@v1",
                  "top_n": _TOP_N, "initial_capital": _INITIAL_CAPITAL}
        kwargs.update(overrides)
        return run_cnn_backtest(**kwargs)

    def test_real_bar_units_match_parquet_raw(self) -> None:
        """单位量级：provider 输出与 parquet 直读逐值相等（真实股/真实元，不做二次缩放）。"""
        provider = self._provider()
        self.assertEqual(provider.amount_basis, "yuan")
        positions = (0, len(self.dates) // 2, len(self.dates) - 1)
        for code in _CODES:
            frame = self.frames[code]
            for position in positions:
                with self.subTest(code=code, position=position):
                    day = self.dates[position]
                    bar = provider.get_bar(code, day)
                    assert bar is not None
                    self.assertTrue(bar.is_trading)
                    raw = frame.loc[frame["kline_time"].dt.date == day].iloc[0]
                    assert bar.volume is not None and bar.amount is not None
                    self.assertEqual(bar.volume, float(raw["volume"]))
                    self.assertEqual(bar.amount, float(raw["amount"]))
                    # 量级 sanity：amount/volume 为 raw 现价口径（000001.SZ~11 元/600000.SH~9 元），
                    # 与后复权 OHLC（数百~上千）不在同一量纲，故只约束 raw 现价带，不与 high/low 比
                    vwap = bar.amount / bar.volume
                    self.assertGreater(vwap, 1.0)
                    self.assertLess(vwap, 200.0)

    def test_full_chain_snapshots_manifest_and_provenance(self) -> None:
        """全链路不抛 + 逐日快照/tz/manifest 必含键断言。"""
        outcome = self._run()
        result = outcome.result
        self.assertEqual([snapshot.date for snapshot in result.account_snapshots], list(self.dates))
        self.assertGreater(len(result.account_snapshots), 0)
        for snapshot in result.account_snapshots:
            market_value = sum(position.market_value for position in snapshot.positions.values()
                               if position.market_value is not None)
            self.assertAlmostEqual(snapshot.nav, snapshot.cash + market_value, places=6)
        self.assertTrue(result.order_results)
        self.assertTrue(any(item.status is OrderStatus.FILLED for item in result.order_results))
        fills = [event for event in result.trades if event.status is EventStatus.FILLED]
        self.assertTrue(fills)
        for event in fills:
            self.assertEqual(event.signal_time.tzinfo, SHANGHAI_TZ)
            self.assertEqual(event.signal_time.time(), time(15, 0))
            self.assertGreater(event.execution_time, event.signal_time)
            self.assertIsInstance(event.shares, int)
        self.assertEqual(dict(result.signal_metrics), {})
        self.assertEqual(dict(result.paper_metrics), {})
        self.assertIn("total_return", result.account_metrics)
        for key in ("config_hash", "data_fingerprint", "order_entry", "run_id", "top_n"):
            self.assertIn(key, outcome.provenance, key)
        for attr in ("config_hash", "data_fingerprint", "run_id"):
            self.assertTrue(getattr(outcome.manifest, attr), attr)
        self.assertEqual(outcome.provenance["order_entry"], ORDER_ENTRY)
        self.assertEqual(outcome.provenance["order_entry"], "atomic_orders_cash_budget")
        self.assertEqual(outcome.provenance["top_n"], str(_TOP_N))
        self.assertEqual(len(outcome.provenance["config_hash"]), 40)
        self.assertEqual(len(outcome.provenance["data_fingerprint"]), 40)
        self.assertEqual(outcome.manifest.config_hash, outcome.provenance["config_hash"])
        self.assertEqual(outcome.manifest.data_fingerprint, outcome.provenance["data_fingerprint"])
        self.assertIn("run_id", outcome.provenance)

    def test_run_id_default_format_locked(self) -> None:
        """run_id 对齐收口：缺省格式 ``{model}@{checkpoint}#top{n}`` 锁定；显式透传；空值拒绝。"""
        outcome = self._run()
        expected = f"{_MODEL}@{_CHECKPOINT}#top{_TOP_N}"
        self.assertEqual(outcome.provenance["run_id"], expected)
        self.assertEqual(outcome.manifest.run_id, expected)
        self.assertEqual(outcome.result.run_id, expected)
        custom = self._run(run_id="smoke-custom-01")
        self.assertEqual(custom.provenance["run_id"], "smoke-custom-01")
        self.assertEqual(custom.manifest.run_id, "smoke-custom-01")
        with self.assertRaises(ValueError):
            self._run(run_id="  ")
        self.assertEqual(DEFAULT_TOP_N, 10)

    def test_missing_sample_raises_explicit_skip(self) -> None:
        """缺文件必须显式 SkipTest（消息明确），不得静默 pass 或触网兜底。"""
        with mock.patch("glob.glob", return_value=[]):
            hits = sorted(glob.glob(_PARQUET_GLOB))
            self.assertEqual(hits, [])
            with self.assertRaises(unittest.SkipTest) as caught:
                _load_frames("no/such/file.parquet", _CODES, _WINDOW, _MIN_COMMON_DAYS)
        self.assertIn("缺失", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
