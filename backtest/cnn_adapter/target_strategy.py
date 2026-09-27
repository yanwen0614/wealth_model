"""cnn 目标持仓策略（B04-target）：T 日截面买入带等权现金单 + 滞后带卖单。

对标旧引擎 ``run_backtest_target`` 同语义：T 日全截面按 exp_ret 降序排名
（并列按代码升序）；持有仓位 rank > target_size + sell_buffer 则卖出；
``exit_on_nonpositive`` 时持仓 exp_ret <= exit_threshold 也卖出（忽略 rank
buffer，缺预测不卖）；买入带 rank <= target_size 内 exp_ret < 门槛
（仅当 ``strong_buy_threshold > 0``，0.0 = 关闭）跳过留现金、不补位；
买入按预算等权现金单，已持有目标不动。

口径声明：
- core 整手/涨跌停锁定由 core 引擎裁决，策略不预判价格（本文件不读任何
  价格，只按截面名单发单，避免与账户视图估值口径漂移）。
- 与 engine 版 limit_up 跳过口径差：engine 版买入前按 open/prev_close 预判
  涨停跳过；本策略不预判，涨停锁定留给 core 引擎 locked 事件裁决——执行口径以 core 为准。
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

__all__ = ["CnnTargetOrderCounters", "CnnTargetOrderStrategy"]


@dataclass(frozen=True)
class CnnTargetOrderCounters:
    """计数快照：键名稳定，供 B05 provenance 消费；均为实例生命周期累计值."""

    buy_order_count: int = 0
    sell_order_count: int = 0
    skipped_strong_buy_count: int = 0


def _ranked_predictions(adapter: CnnPredictionAdapter, trading_date: date) -> tuple:
    """全截面按 exp_ret 降序、并列按代码升序（与旧 CnnOrderStrategy 同序，保证确定性）."""
    return tuple(sorted(adapter.predictions_for_date(trading_date),
                        key=lambda pred: (-pred.value, pred.instrument_id)))


class CnnTargetOrderStrategy:
    """滞后带目标持仓 → core 原子订单（B04-target；``OrderStrategy`` 协议实现）."""

    def __init__(self, prediction_adapter: CnnPredictionAdapter, *, target_size: int = 100,
                 sell_buffer: int = 500, exit_on_nonpositive: bool = False,
                 exit_threshold: float = 0.0, strong_buy_threshold: float = 0.0) -> None:
        if not isinstance(prediction_adapter, CnnPredictionAdapter):
            raise ValueError(  # noqa: TRY004
                f"prediction_adapter must be a CnnPredictionAdapter, got {prediction_adapter!r}"
            )
        if isinstance(target_size, bool) or not isinstance(target_size, int) or target_size < 1:
            raise ValueError(f"target_size must be a positive int, got {target_size!r}")
        if isinstance(sell_buffer, bool) or not isinstance(sell_buffer, int) or sell_buffer < 0:
            raise ValueError(f"sell_buffer must be a non-negative int, got {sell_buffer!r}")
        if not isinstance(exit_on_nonpositive, bool):
            raise TypeError(f"exit_on_nonpositive must be a bool, got {exit_on_nonpositive!r}")
        exit_threshold = self._checked_threshold(exit_threshold, "exit_threshold")
        strong_buy_threshold = self._checked_threshold(strong_buy_threshold, "strong_buy_threshold")
        if strong_buy_threshold < 0.0:
            raise ValueError(f"strong_buy_threshold must be >= 0, got {strong_buy_threshold!r}")
        self._adapter = prediction_adapter
        self._target_size = target_size
        self._sell_buffer = sell_buffer
        self._exit_on_nonpositive = exit_on_nonpositive
        self._exit_threshold = exit_threshold
        self._strong_buy_threshold = strong_buy_threshold
        self._buy_order_count = 0
        self._sell_order_count = 0
        self._skipped_strong_buy_count = 0

    @staticmethod
    def _checked_threshold(value: object, name: str) -> float:
        """阈值校验：数值（拒 bool/str），NaN 显式失败（inf 保留，语义为全过/全不过）."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number, got {value!r}")
        result = float(value)
        if math.isnan(result):
            raise ValueError(f"{name} must not be NaN, got {value!r}")
        return result

    @property
    def target_size(self) -> int:
        return self._target_size

    @property
    def sell_buffer(self) -> int:
        return self._sell_buffer

    @property
    def exit_on_nonpositive(self) -> bool:
        return self._exit_on_nonpositive

    @property
    def exit_threshold(self) -> float:
        return self._exit_threshold

    @property
    def strong_buy_threshold(self) -> float:
        return self._strong_buy_threshold

    @property
    def available_dates(self) -> tuple:
        """B03 谱系日期直通：策略/Runner 共用同一 fail-fast 边界."""
        return self._adapter.available_dates

    @property
    def counters(self) -> CnnTargetOrderCounters:
        """计数快照（含 strong_buy 跳过数，供回测 skipped 口径对账）."""
        return CnnTargetOrderCounters(buy_order_count=self._buy_order_count,
                                      sell_order_count=self._sell_order_count,
                                      skipped_strong_buy_count=self._skipped_strong_buy_count)

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        """信号时点：T 日 15:00 Asia/Shanghai（与 B03 同口径）."""
        return signal_time_for(trading_date)

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）."""
        counters = self.counters
        return {"buy_order_count": str(counters.buy_order_count),
                "sell_order_count": str(counters.sell_order_count),
                "skipped_strong_buy_count": str(counters.skipped_strong_buy_count)}

    def orders_for(self, *, trading_date: date, signal_time: datetime, account: AccountView,
                   market: MarketView) -> tuple:
        """T 日截面 → 原子订单（卖出在前按代码序、买入按名次序；无订单显式空元组）.

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
        ranked = _ranked_predictions(self._adapter, trading_date)
        order_list = [pred.instrument_id for pred in ranked]
        rank_map = {code: pos + 1 for pos, code in enumerate(order_list)}
        exp_map = {pred.instrument_id: pred.value for pred in ranked}
        buy_band = order_list[:self._target_size]
        sells = self._sell_orders(account, rank_map, exp_map)
        buys, skipped = self._buy_orders(account, buy_band, exp_map)
        self._sell_order_count += len(sells)
        self._buy_order_count += len(buys)
        self._skipped_strong_buy_count += skipped
        return (*sells, *buys)

    def _sell_orders(self, account: AccountView, rank_map: dict, exp_map: dict) -> list[OrderIntent]:
        """滞后带卖单：exit 开启看阈值（缺预测不卖），否则看 rank（缺预测 rank 记 0 → 持有）."""
        to_sell: list[str] = []
        for code in account.positions:
            if self._exit_on_nonpositive:
                value = exp_map.get(code)
                if value is not None and value <= self._exit_threshold:
                    to_sell.append(code)
            elif rank_map.get(code, 0) > self._target_size + self._sell_buffer:
                to_sell.append(code)
        orders: list[OrderIntent] = []
        for code in sorted(to_sell):
            held = int(account.positions[code].shares)
            if held > 0:
                orders.append(OrderIntent(instrument_id=code, side=Side.SELL, shares=held))
        return orders

    def _buy_orders(self, account: AccountView, buy_band: Sequence[str],
                    exp_map: dict) -> tuple[list[OrderIntent], int]:
        """买入带等权现金单：已持有不动；门槛开启（>0）时带内低于门槛跳过留现金、不补位."""
        candidates: list[str] = []
        skipped = 0
        for code in buy_band:
            if code in account.positions:
                continue
            if self._strong_buy_threshold > 0.0 and exp_map[code] < self._strong_buy_threshold:
                skipped += 1
                continue
            candidates.append(code)
        if not candidates:
            return [], skipped
        usable = float(account.available_cash)
        if usable <= 0.0 or not math.isfinite(usable):
            return [], skipped
        # 预算按实际买入家数等分（跳过/已持有不占槽，core 引擎按成交价+费用折算整手）。
        budget = usable / len(candidates)
        orders = [OrderIntent(instrument_id=code, side=Side.BUY, cash_amount=budget)
                  for code in candidates]
        return orders, skipped
