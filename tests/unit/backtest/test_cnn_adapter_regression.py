"""B05 新旧初步回归（PLAN D5）：旧 rolling-topn 引擎 vs 新订单路径。

对照对象：同一合成小样本（4 只确定性趋势股，12 交易日，零 DB / 零触网）。
旧：``backtest.engine.run_backtest``（rolling topn，open-open，horizon=5，
cost_rate=0.0015 双边一次性）；新：``run_cnn_backtest``（同 top_n/horizon 含义，
core 佣金/滑点模型 + T+1 锁定 + 尾日 force 清算）。
对比：净值方向/净值序列相关性、成交笔数/持仓批次数、成本量级。
判据：同向 + 净值相关>0.5 + 笔数同量级（|新-旧|≤max(2,旧)，沿 A07 规则）+
成本比值 [0.25, 4]。结论无数量级异常即可，不要求 parity。

实测结论（2026-09-11，确定性合成数据，仅口径健康检查）：
- 净值序列相关 ≈ 0.90；终值方向一致（同涨，旧 1.032 / 新 1.054）；
- 持仓批次数 12（旧）vs 成交 4（新：2 建仓 + 2 尾日强平），差值 8 ≤ 12，同量级；
- 成本 0.00185（旧）vs 0.00294（新，归一到初始本金）约 1.6x，同数量级。

已知口径差异（记录备查，非缺陷）：
- 成本模型：旧 cost_rate=0.0015 双边一次性扣减；新 core 佣金万 2 最低 5 /
  卖出印花税万 5 / σ 缩放滑点 v1（本样本约 1.6x）；
- T+1 锁定与拒单可观测性：旧引擎信号日即定仓、无锁定状态机；新订单路径真实
  T+1 锁定（当日买入不可卖）+ 现金不足整单拒绝逐单回报（OrderResult）；
- 尾日处理：旧引擎尾部不足 horizon 的信号日直接不建仓；新路径尾日 force 清算
  产出 forced_exit 事件（本样本新路径 2 笔强平即来源于此）；
- 涨跌停拦截：旧 rolling 仅买入做涨停跳过（卖出未做跌停检查）；新路径
  limit_up=skip / limit_down=lock（本样本无触发，差异记录备查）；
- 整手折算：旧为 float 股数等权；新 core 按成交价+费用折算 cash_amount 整手向下。
- 日收益相关未纳入判据：旧 rolling 按退出日一次性实现收益（前 horizon 日净值
  为平线），新路径逐日 mark-to-market，日收益序列结构性错位；只比净值序列相关。
"""

import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd
from backtest_core.contracts import EventStatus

from backtest.cnn_adapter.cache import load_prediction_cache, save_prediction_cache
from backtest.cnn_adapter.runner import run_cnn_backtest
from backtest.engine import run_backtest

_CODES = ("000001.SZ", "000002.SZ", "600000.SH", "600001.SH")
_DRIFTS = (0.008, 0.003, -0.003, -0.008)
_SCORES = (0.05, 0.02, -0.02, -0.05)
_TRADING_DAYS = 12
_TOP_N = 2
_HORIZON = 5
_COST_RATE = 0.0015
_INITIAL_CAPITAL = 1_000_000.0


def _trading_days(n: int) -> list[date]:
    """连续工作日（跳过周末），与合成行情交易日语义一致。"""
    days: list[date] = []
    current = date(2025, 3, 3)
    while len(days) < n:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _build_sample(tmpdir: str) -> tuple[dict, str]:
    """同一确定性价格路径 → (pred_cache, parquet_path) + 旧引擎 ohlc 路径表另行产出。

    为什么用稳定排序截面：新旧两路径选股名单逐日一致（A/B 恒居前二），回归对比
    只暴露执行/成本/持有语义差异，不混入选股分歧；换手场景留给契约测试覆盖。
    """
    days = _trading_days(_TRADING_DAYS)
    prev = {code: 10.0 + i for i, code in enumerate(_CODES)}
    rows: list[dict] = []
    closes: dict[str, list[tuple[date, float, float]]] = {code: [] for code in _CODES}
    exp_ret, true_ret, day_cells, code_cells = [], [], [], []
    for day_index, day in enumerate(days):
        for code_index, code in enumerate(_CODES):
            price = prev[code] * (1.0 + _DRIFTS[code_index] + 0.001 * np.sin(day_index + code_index))
            open_price = prev[code]
            rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": open_price,
                         "high": max(open_price, price) * 1.005, "low": min(open_price, price) * 0.995,
                         "close": price, "volume": 2_000_000.0, "amount": 2_000_000.0 * price,
                         "is_trading": True})
            closes[code].append((day, open_price, price))
            prev[code] = price
            exp_ret.append(_SCORES[code_index])
            true_ret.append(0.001)
            day_cells.append(day.isoformat())
            code_cells.append(code)
    parquet_path = os.path.join(tmpdir, "regression.parquet")
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)
    cache_path = os.path.join(tmpdir, "regression_preds.npz")
    save_prediction_cache(cache_path, np.asarray(exp_ret), np.asarray(true_ret),
                          np.asarray(day_cells, dtype="datetime64[D]"), np.asarray(code_cells))
    return load_prediction_cache(cache_path), parquet_path


def _build_ohlc() -> dict:
    """旧引擎 ohlc 路径表：t_close=当日 close，open_t1=次日 open，open_t6=6 日后 open（无则 NaN）。"""
    days = _trading_days(_TRADING_DAYS)
    prev = {code: 10.0 + i for i, code in enumerate(_CODES)}
    opens: dict[str, list[float]] = {code: [] for code in _CODES}
    closes: dict[str, list[float]] = {code: [] for code in _CODES}
    for day_index in range(_TRADING_DAYS):
        for code_index, code in enumerate(_CODES):
            price = prev[code] * (1.0 + _DRIFTS[code_index] + 0.001 * np.sin(day_index + code_index))
            opens[code].append(prev[code])
            closes[code].append(price)
            prev[code] = price
    table: dict[str, list] = {"codes": [], "dates": [], "t_close": [], "open_t1": [], "open_t6": []}
    for day_index, day in enumerate(days):
        for code in _CODES:
            table["codes"].append(code)
            table["dates"].append(np.datetime64(day))
            table["t_close"].append(closes[code][day_index])
            table["open_t1"].append(opens[code][day_index + 1] if day_index + 1 < _TRADING_DAYS else np.nan)
            table["open_t6"].append(opens[code][day_index + 6] if day_index + 6 < _TRADING_DAYS else np.nan)
    return {"codes": np.asarray(table["codes"]), "dates": np.asarray(table["dates"]),
            "t_close": np.asarray(table["t_close"], dtype=np.float64),
            "open_t1": np.asarray(table["open_t1"], dtype=np.float64),
            "open_t6": np.asarray(table["open_t6"], dtype=np.float64)}


class TestPartialRegression(unittest.TestCase):
    """新旧初步回归：方向/净值相关 + 笔数 + 成本量级；无数量级异常即通过。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="b05r_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direction_correlation_trades_and_cost_magnitude(self) -> None:
        pred_cache, parquet_path = _build_sample(self.tmp)
        days = _trading_days(_TRADING_DAYS)
        exp_ret = np.asarray([score for _ in days for score in _SCORES], dtype=np.float64)
        codes = np.asarray([code for _ in days for code in _CODES])
        dates = np.asarray([day.isoformat() for day in days for _ in _CODES], dtype="datetime64[D]")
        old = run_backtest(exp_ret, codes, dates, _build_ohlc(), topn=_TOP_N,
                           cost_rate=_COST_RATE, horizon=_HORIZON)
        new = run_cnn_backtest(pred_cache=pred_cache, parquet_path=parquet_path, top_n=_TOP_N,
                               initial_capital=_INITIAL_CAPITAL, model_name="cnn_transformer",
                               checkpoint="logs/run_demo/best_model.pth", bins_version="BINS52_v1",
                               eval_script_version="eval_bins_mapping@v1")
        new_nav = np.array([snapshot.nav for snapshot in new.result.account_snapshots])
        self.assertEqual(len(new_nav), _TRADING_DAYS)
        self.assertEqual(len(old.nav), _TRADING_DAYS)
        nav_corr = float(np.corrcoef(old.nav, new_nav)[0, 1])
        old_return = float(old.nav[-1]) - 1.0
        new_return = float(new_nav[-1]) / _INITIAL_CAPITAL - 1.0
        # 方向一致（同涨/同跌）且净值序列正相关
        self.assertEqual(old_return < 0.0, new_return < 0.0)
        self.assertGreater(nav_corr, 0.5)
        filled = [event for event in new.result.trades
                  if event.status in (EventStatus.FILLED, EventStatus.FORCED_EXIT)]
        old_cost = float(sum(h["weight"] * (h["ret_gross"] - h["ret_net"]) for h in old.holdings))
        new_cost = float(sum(event.commission + event.stamp_tax + event.transfer_fee
                             + event.slippage_cost for event in filled)) / _INITIAL_CAPITAL
        self.assertGreater(len(old.holdings), 0)
        self.assertGreater(len(filled), 0)
        # 笔数同量级：旧按信号日逐批建仓（eligible×topn），新持有至尾日强平；偏差容限沿 A07 规则
        self.assertLessEqual(abs(len(filled) - len(old.holdings)), max(2, len(old.holdings)))
        # 成本同数量级：费率口径不同（见模块 docstring），比值限定 [0.25, 4] 与本金 2% 上限
        self.assertGreater(old_cost, 0.0)
        self.assertGreater(new_cost, 0.0)
        self.assertGreater(new_cost / old_cost, 0.25)
        self.assertLess(new_cost / old_cost, 4.0)
        self.assertLess(old_cost, 0.02)
        self.assertLess(new_cost, 0.02)
        # 合成趋势样本不含涨跌停/停牌：新路径不得出现该类拦截（口径差异仅记录，不掩盖误判）
        blocked = [event for event in new.result.trades
                   if event.reason is not None and event.reason.value in ("limit_up", "limit_down", "suspended")]
        self.assertEqual(blocked, [])


if __name__ == "__main__":
    unittest.main()
