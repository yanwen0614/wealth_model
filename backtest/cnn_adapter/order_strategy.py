"""cnn 订单策略（B04）：T 日截面 top_n 等权现金单 + 目标外全量卖单。

与旧引擎 ``run_backtest`` 同语义：T 日截面按 exp_ret 取前 top_n，
买单等权现金预算（core 引擎按成交价+费用折算整手向下），已持有目标不动；
非目标持仓 shares 全量卖单（T+1 锁定/整单拒绝由 core 引擎裁决，策略不预判价格）。
禁影子账户：持仓/现金/锁定只读 AccountView，不保存任何状态。
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from backtest_core.contracts import OrderIntent, Side
from backtest_core.contracts.protocols import AccountView, MarketView
from backtest_core.contracts.validation import ensure_calendar_date, ensure_tz_aware

from backtest.cnn_adapter.common import signal_time_for
from backtest.cnn_adapter.predictions import CnnPredictionAdapter

__all__ = ["DEFAULT_TOP_N", "CnnOrderCounters", "CnnOrderStrategy"]

# 对齐旧引擎常用档（scripts rolling-topn 默认 topn=10）
DEFAULT_TOP_N = 10


@dataclass(frozen=True)
class CnnOrderCounters:
    """计数快照：键名稳定，供 B05 provenance 消费；均为实例生命周期累计值."""

    buy_order_count: int = 0
    sell_order_count: int = 0


class CnnOrderStrategy:
    """截面排序 → core 原子订单（B04；``OrderStrategy`` 协议实现）."""

    def __init__(self, prediction_adapter: CnnPredictionAdapter, *, top_n: int = DEFAULT_TOP_N) -> None:
        if not isinstance(prediction_adapter, CnnPredictionAdapter):
            raise ValueError(  # noqa: TRY004
                f"prediction_adapter must be a CnnPredictionAdapter, got {prediction_adapter!r}"
            )
        if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
            raise ValueError(f"top_n must be a positive int, got {top_n!r}")
        self._adapter = prediction_adapter
        self._top_n = top_n
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
        return {"buy_order_count": str(counters.buy_order_count),
                "sell_order_count": str(counters.sell_order_count)}

    def orders_for(self, *, trading_date: date, signal_time: datetime, account: AccountView,
                   market: MarketView) -> tuple:
        """T 日截面 → 原子订单（卖出在前、买入按名次序；无订单显式空元组）.

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
