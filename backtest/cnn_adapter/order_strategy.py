"""cnn 订单策略（B04）：T 日截面 top_n 等权现金单 + 目标外全量卖单。

与旧引擎 ``run_backtest`` 同语义：T 日截面按 exp_ret 取前 top_n，
买单等权现金预算（core 引擎按成交价+费用折算整手向下），已持有目标不动；
非目标持仓 shares 全量卖单（T+1 锁定/整单拒绝由 core 引擎裁决，策略不预判价格）。
禁影子账户：持仓/现金/锁定只读 AccountView，不保存任何状态。

新增 RollingIcGate（2026-10-24）：基于滚动历史 IC 决定是否交易（无前瞻），
信号弱时跳过当天（全现金），避免在低 IC 日开仓亏损。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
from backtest_core.contracts import OrderIntent, Side
from backtest_core.contracts.protocols import AccountView, MarketView
from backtest_core.contracts.validation import ensure_calendar_date, ensure_tz_aware

from backtest.cnn_adapter.common import signal_time_for
from backtest.cnn_adapter.predictions import CnnPredictionAdapter

__all__ = ["DEFAULT_TOP_N", "CnnOrderCounters", "CnnOrderStrategy", "RollingIcGate"]

# 默认 IC 门参数（从 2026 诊断优化得到）
_DEFAULT_IC_WINDOW = 10
_DEFAULT_MIN_IC = 0.02
_MIN_STOCKS_FOR_IC = 20


class RollingIcGate:
    """IC 门：基于滚动历史 IC 决定是否交易（无前瞻，真实环境可用）。

    在每天开仓前调用，只有过去 N 天的平均 IC ≥ 门限时才交易。
    否则跳过当天（全现金），避免低 IC 日开仓亏损。
    使用原始预测缓存数据（不透传 PredictionAdapter 避免计数污染）。

    Args:
        exp_arr: exp_ret numpy 数组
        true_arr: true_ret numpy 数组
        dates_arr: 逐样本日期
        codes_arr: 逐样本代码
        window: 滚动窗口天数（默认 10）
        min_ic: 最小 IC 门限（默认 0.02）
    """

    def __init__(
        self,
        exp_arr: np.ndarray,
        true_arr: np.ndarray,
        dates_arr: np.ndarray,
        codes_arr: np.ndarray,
        *,
        window: int = _DEFAULT_IC_WINDOW,
        min_ic: float = _DEFAULT_MIN_IC,
    ) -> None:
        if len({len(exp_arr), len(true_arr), len(dates_arr), len(codes_arr)}) != 1:
            raise ValueError("所有输入数组长度必须一致")
        self._exp = np.asarray(exp_arr, dtype=np.float64)
        self._true = np.asarray(true_arr, dtype=np.float64)
        # 统一日期格式
        if hasattr(dates_arr[0], "strftime"):
            self._dates = np.array([int(d.strftime("%Y%m%d")) for d in dates_arr], dtype=np.int32)
        else:
            self._dates = np.asarray(dates_arr, dtype=np.int32)
        if hasattr(codes_arr[0], "decode"):
            self._codes = np.array([c.decode("utf-8") for c in codes_arr])
        else:
            self._codes = np.asarray(codes_arr)
        self._index: dict[int, list[int]] = {}
        for pos, day in enumerate(self._dates):
            self._index.setdefault(int(day), []).append(pos)
        self._window = window
        self._min_ic = min_ic
        self._ic_cache: dict[int, float] = {}

    def _compute_day_ic(self, day: int) -> float | None:
        if day in self._ic_cache:
            return self._ic_cache[day]
        rows = self._index.get(day)
        if not rows or len(rows) < _MIN_STOCKS_FOR_IC:
            return None
        exp_vals, true_vals = self._exp[rows], self._true[rows]
        finite = np.isfinite(exp_vals) & np.isfinite(true_vals)
        if finite.sum() < _MIN_STOCKS_FOR_IC:
            return None
        from scipy.stats import spearmanr
        ic = float(spearmanr(exp_vals[finite], true_vals[finite])[0])
        self._ic_cache[day] = ic
        return ic

    def should_trade(self, trading_date: date) -> bool:
        """True=正常交易, False=跳过（全现金）。数据不足时默认交易。"""
        today_int = int(trading_date.strftime("%Y%m%d"))
        past_days = sorted(d for d in self._index if d < today_int)
        ics = [self._compute_day_ic(d) for d in past_days[-self._window:] if d in self._index]
        ics = [ic for ic in ics if ic is not None]
        if len(ics) < 3:
            return True
        return float(np.mean(ics)) >= self._min_ic


# 对齐旧引擎常用档（scripts rolling-topn 默认 topn=10）
DEFAULT_TOP_N = 10


@dataclass(frozen=True)
class CnnOrderCounters:
    """计数快照：键名稳定，供 B05 provenance 消费；均为实例生命周期累计值."""

    buy_order_count: int = 0
    sell_order_count: int = 0


class CnnOrderStrategy:
    """截面排序 → core 原子订单（B04；``OrderStrategy`` 协议实现）.

    可选 ``ic_gate``：启用滚动 IC 门，信号弱时跳过当天（全现金）。
    """

    def __init__(self, prediction_adapter: CnnPredictionAdapter, *, top_n: int = DEFAULT_TOP_N,
                 ic_gate: RollingIcGate | None = None) -> None:
        if not isinstance(prediction_adapter, CnnPredictionAdapter):
            raise ValueError(  # noqa: TRY004
                f"prediction_adapter must be a CnnPredictionAdapter, got {prediction_adapter!r}"
            )
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
            raise ValueError(f"top_n must be a positive int, got {top_n!r}")
        self._adapter = prediction_adapter
        self._top_n = top_n
        self._ic_gate = ic_gate
        self._skip_count = 0  # IC 门跳过的交易天数
        self._buy_order_count = 0
        self._sell_order_count = 0

    @property
    def top_n(self) -> int:
        return self._top_n

    @property
    def available_dates(self) -> tuple:
        """B03 谱系日期直通：策略/Runner 共用同一 fail-fast 边界."""
        return self._adapter.available_dates

    @property
    def counters(self) -> CnnOrderCounters:
        """计数快照."""
        return CnnOrderCounters(buy_order_count=self._buy_order_count,
                                sell_order_count=self._sell_order_count)

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        """信号时点：T 日 15:00 Asia/Shanghai（与 B03 同口径）."""
        return signal_time_for(trading_date)

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）."""
        counters = self.counters
        d: dict[str, str] = {"buy_order_count": str(counters.buy_order_count),
                             "sell_order_count": str(counters.sell_order_count)}
        if self._ic_gate is not None:
            d["ic_gate_skip_count"] = str(self._skip_count)
        return d

    def orders_for(self, *, trading_date: date, signal_time: datetime, account: AccountView,
                   market: MarketView) -> tuple:
        """T 日截面 → 原子订单（卖出在前、买入按名次序；无订单显式空元组）.

        如果启用 ``ic_gate`` 且门未通过，当天不交易（全现金）。
        ``market`` 为协议形状参数：本策略不预判价格（卖出缺价 locked 由引擎裁决），
        只按截面名单发单，避免与账户视图估值口径漂移.
        """
        del market
        ensure_calendar_date(trading_date, "trading_date")
        ensure_tz_aware(signal_time, "signal_time")
        if signal_time.date() != trading_date:
            raise ValueError(f"signal_time {signal_time!r} 与 trading_date {trading_date!r} 不一致")
        if trading_date not in set(self._adapter.available_dates):
            raise ValueError(f"trading_date {trading_date!r} 不在预测缓存覆盖内，拒绝误传日期（fail-fast）")
        # IC 门：信号弱时跳过当天
        if self._ic_gate is not None and not self._ic_gate.should_trade(trading_date):
            self._skip_count += 1
            return ()
        targets = self._rank_targets(trading_date)
        target_set = set(targets)
        sells = self._sell_orders(account, target_set)
        buys = self._buy_orders(account, targets)
        self._sell_order_count += len(sells)
        self._buy_order_count += len(buys)
        return (*sells, *buys)

    def _rank_targets(self, trading_date: date) -> tuple[str, ...]:
        """按 exp_ret 降序取前 top_n；分数并列按代码升序（stable 确定）."""
        ranked = sorted(self._adapter.predictions_for_date(trading_date),
                        key=lambda pred: (-pred.value, pred.instrument_id))
        return tuple(pred.instrument_id for pred in ranked[:self._top_n])

    def _sell_orders(self, account: AccountView, target_set: set[str]) -> list[OrderIntent]:
        """非目标持仓 shares 全量卖单（锁仓部分留给 core 裁决 locked 事件）."""
        orders: list[OrderIntent] = []
        for code in sorted(account.positions):
            if code in target_set:
                continue
            held = int(account.positions[code].shares)
            if held > 0:
                orders.append(OrderIntent(instrument_id=code, side=Side.SELL, shares=held))
        return orders

    def _buy_orders(self, account: AccountView, targets: Sequence[str]) -> list[OrderIntent]:
        """等权现金单：``cash_amount = 可用现金 / 目标持仓数``；已持有目标不动."""
        if not targets:
            return []
        usable = float(account.available_cash)
        if usable <= 0.0 or not math.isfinite(usable):
            return []
        budget = usable / len(targets)
        return [OrderIntent(instrument_id=code, side=Side.BUY, cash_amount=budget)
                for code in targets if code not in account.positions]
