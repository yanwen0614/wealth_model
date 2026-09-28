"""C05 真实样本 smoke（规格 §14.3 / 验收 7）：真实 pred + 真实行情小样本只读。

数据：``artifacts/baseline/pred_test.parquet``（真实码，421 日）+
``data/train_data.parquet``（pyarrow 按码过滤只读 9 列，**goal 无 DB**）。
链路：真实双源 → GoalMarketDataProvider + GoalPredictionAdapter →
DailyOrderStrategy / JointOrderStrategy → core 订单引擎。

runner 组装说明（任务二选一）：C04 只有策略无 runner，本文件用 core
``run_account_backtest_from_orders`` 直接组装（仿 B04 runner 模式的最小内联组装）。
不新建 ``goal_adapter/runner.py`` 的理由：独立 runner 涉及配置/血缘/落盘语义，
属阶段 3 入口切换范畴；smoke 只需验证全链路可跑通，内联组装零生产代码变更。
断言：单位量级（与 parquet 直读逐值核对）、signal tz、逐日快照非空、
manifest 必含键（config_hash/data_fingerprint/order_entry/provenance 谱系）。
文件缺失时显式 skip（消息明确，不静默 pass）；零触网。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts import EventStatus, OrderStatus
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.engine import run_account_backtest_from_orders

from goal_adapter.common import SHANGHAI_TZ, fingerprint_mapping
from goal_adapter.market import GoalMarketDataProvider

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PRED_PATH = str(_REPO_ROOT / "artifacts" / "baseline" / "pred_test.parquet")
_MKT_PATH = str(_REPO_ROOT / "data" / "train_data.parquet")
_CODES = ("000001.SZ", "600000.SH")
_WINDOW = 30
_INITIAL_CAPITAL = 1_000_000.0
_TOP_N = 2
_ORDER_ENTRY = "atomic_orders_cash_budget"
_READ_COLS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "is_trading"]


def _load_frames(pred_path: str, mkt_path: str, codes: tuple[str, ...],
                 window: int) -> tuple[dict[str, pd.DataFrame], tuple[date, ...]]:
    """真实双源按码读小样本 → 共同交易日尾部窗口；缺文件/缺码/天数不足显式 SkipTest。"""
    if not os.path.isfile(pred_path):
        raise unittest.SkipTest(f"真实 pred 缺失，smoke 显式跳过（不静默 pass）: {pred_path}")
    if not os.path.isfile(mkt_path):
        raise unittest.SkipTest(f"真实行情缺失，smoke 显式跳过（不静默 pass）: {mkt_path}")
    pred_days = sorted(pd.to_datetime(
        pq.read_table(pred_path, columns=["kline_time"]).to_pandas()["kline_time"]).dt.date.unique())
    window_days = tuple(pred_days[-window:])
    selected: dict[str, pd.DataFrame] = {}
    for code in codes:
        frame = pq.read_table(mkt_path, columns=_READ_COLS, filters=[("code", "=", code)]).to_pandas()
        frame["kline_time"] = pd.to_datetime(frame["kline_time"])
        filtered = frame[frame["kline_time"].dt.date.isin(window_days)]
        assert isinstance(filtered, pd.DataFrame)
        if len(filtered) != len(window_days):
            raise unittest.SkipTest(f"{code} 在窗口内缺失交易日（{len(filtered)}/{len(window_days)}），显式跳过")
        selected[code] = filtered.reset_index(drop=True)
    return selected, window_days


def _assemble_and_run(pred_path: str, mkt_path: str, dates: tuple[date, ...], strategy_factory,
                      top_n: int, sell_buffer: int) -> tuple:
    """最小内联组装（见模块 docstring）：provider + pred adapter + 策略 → 订单引擎 + 血缘。"""
    import numpy as np

    from goal_adapter.predictions import GoalPredictionAdapter

    provider = GoalMarketDataProvider(mkt_path)
    adapter = GoalPredictionAdapter(
        pred_path, model_name="smoke-hgb", model_artifact="artifacts/baseline/model_hgb.pkl",
        feature_version="smoke-feat", script_version="smoke-c05")
    strategy = strategy_factory(adapter, provider, top_n=top_n, sell_buffer=sell_buffer)
    result = run_account_backtest_from_orders(
        dates=list(dates), strategy=strategy, market=provider,
        execution_config=ExecutionConfig(), portfolio_config=PortfolioConfig(),
        cost_config=CostConfig(), run_id=f"smoke-top{top_n}", model_id="smoke-hgb",
        initial_capital=_INITIAL_CAPITAL)
    arrays = {}
    for code in _CODES:
        frame = pq.read_table(mkt_path, columns=["code", "kline_time", "close"],
                              filters=[("code", "=", code)]).to_pandas()
        frame["kline_time"] = pd.to_datetime(frame["kline_time"])
        closes = frame[frame["kline_time"].dt.date.isin(dates)]["close"].to_numpy(dtype="float64")
        arrays[f"mkt:{code}"] = np.ascontiguousarray(closes)
    data_fingerprint = fingerprint_mapping(arrays)
    config_text = f"top_n={top_n}|sell_buffer={sell_buffer}|capital={_INITIAL_CAPITAL}|entry={_ORDER_ENTRY}"
    config_hash = hashlib.sha1(config_text.encode("utf-8")).hexdigest()
    provenance = dict(adapter.provenance)
    provenance.update({"order_entry": _ORDER_ENTRY, "top_n": str(top_n),
                       "sell_buffer": str(sell_buffer), "config_hash": config_hash,
                       "data_fingerprint": data_fingerprint,
                       "market_counters": str(provider.counters),
                       "strategy_counters": str(strategy.counters)})
    manifest = {"config_hash": config_hash, "data_fingerprint": data_fingerprint,
                "order_entry": _ORDER_ENTRY, "run_id": f"smoke-top{top_n}",
                "created_at": datetime.now(SHANGHAI_TZ).isoformat(), "provenance": provenance}
    return result, provenance, manifest


class TestRealSampleSmoke(unittest.TestCase):
    """真实双源小样本端到端 smoke：缺文件显式 skip；存在则验证单位/tz/快照/血缘。"""

    frames: dict[str, pd.DataFrame]
    dates: tuple[date, ...]
    tmp: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.frames, cls.dates = _load_frames(_PRED_PATH, _MKT_PATH, _CODES, _WINDOW)
        cls.tmp = tempfile.mkdtemp(prefix="c05s_")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)

    def test_real_bar_units_match_parquet_raw(self) -> None:
        """单位量级：provider 输出与 parquet 直读逐值相等（真实股/真实元，不做二次缩放）。"""
        provider = GoalMarketDataProvider(_MKT_PATH)
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
                    vwap = bar.amount / bar.volume  # 真实元/真实股 = raw 现价口径
                    self.assertGreater(vwap, 1.0)
                    self.assertLess(vwap, 200.0)

    def test_daily_full_chain_snapshots_manifest_and_provenance(self) -> None:
        """daily 全链路不抛 + 逐日快照/tz/manifest 必含键断言。"""
        from goal_adapter.daily_policy import DailyOrderStrategy

        result, provenance, manifest = _assemble_and_run(
            _PRED_PATH, _MKT_PATH, self.dates, DailyOrderStrategy, _TOP_N, 2)
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
        self.assertIn("total_return", result.account_metrics)
        for key in ("config_hash", "data_fingerprint", "order_entry", "run_id", "provenance", "created_at"):
            self.assertIn(key, manifest, key)
        for key in ("model_name", "horizon", "score_mapping", "actuals_label_formula",
                    "order_entry", "config_hash", "data_fingerprint"):
            self.assertIn(key, provenance, key)
        self.assertEqual(provenance["order_entry"], _ORDER_ENTRY)
        self.assertEqual(len(provenance["config_hash"]), 40)
        self.assertEqual(len(provenance["data_fingerprint"]), 40)
        self.assertEqual(manifest["config_hash"], provenance["config_hash"])
        self.assertEqual(manifest["data_fingerprint"], provenance["data_fingerprint"])

    def test_joint_full_chain(self) -> None:
        """joint 全链路：稀疏 episode 策略在稠密样本上同样可跑通（top_n 小参数）。"""
        from goal_adapter.joint_policy import JointOrderStrategy

        result, provenance, manifest = _assemble_and_run(
            _PRED_PATH, _MKT_PATH, self.dates, JointOrderStrategy, _TOP_N, 1)
        self.assertEqual(len(result.account_snapshots), len(self.dates))
        self.assertTrue(result.order_results)
        self.assertEqual(provenance["order_entry"], _ORDER_ENTRY)
        self.assertIn("config_hash", manifest)

    def test_missing_sample_raises_explicit_skip(self) -> None:
        """缺文件必须显式 SkipTest（消息明确），不得静默 pass 或触网兜底。"""
        with mock.patch("os.path.isfile", return_value=False), self.assertRaises(unittest.SkipTest) as caught:
            _load_frames("no/such/pred.parquet", "no/such/mkt.parquet", _CODES, _WINDOW)
        self.assertIn("缺失", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
