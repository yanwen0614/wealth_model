"""goal 日频订单策略（C04 daily）：T 日截面 Top-N 等权现金单 + 滞后带持有。

语义判定（STRATEGY §3 + ``backtest/account_engine.py`` + ``account_engine_v6.py`` 实证）：

- 以 STRATEGY §3 个人版为准：每 20 信号日调仓由引擎节拍承担，策略只做单截面
  ``-score``（即 C03 ``score_trade``）降序取 Top-N（默认 20）；持仓排名跌出前
  ``top_n + sell_buffer``（默认 40）才卖，其余持有不动；目标外持仓 shares 全卖。
- 以 ``account_engine.py`` buffered-sell（``allow=topn+B`` 先卖后买、等权
  ``cash/n_new`` 整手）为对齐依据；v6 的 S1 强制退出/S2 二次重分配/min-edge/
  涨停跳过由 core 引擎裁决，策略侧不复刻（避免与引擎口径漂移）。
- 流动性护栏用信号日成交额作可执行代理：执行日（T+1）成交额在信号时点属前视，
  策略禁前视，故取 ``trading_date`` 当日 ``amount``（真实元，C02 口径）与
  ``min_amount_yuan``（默认 1 亿）比较；明确低于阈值剔除买入并计数，无行情/
  缺量不断流（留给引擎缺量裁决）。引擎侧仍保留执行日 min_amount/涨停/无价裁决。
- 预算分母取目标总数（``可用现金/目标数``，任务口径；已持有目标不动不补仓）；
  与 v6 ``cash/n_new``（按空位数均分）的差异由引擎整手折算吸收，docstring 锁定。
- 禁影子账户：只读 ``AccountView``，不保存持仓/现金/锁定；日期经
  ``available_dates`` fail-fast。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from backtest_core.contracts import OrderIntent, Side
from backtest_core.contracts.protocols import AccountView, MarketView
from backtest_core.contracts.validation import ensure_calendar_date, ensure_tz_aware

from goal_adapter.common import signal_time_for

__all__ = [
    "DEFAULT_MIN_AMOUNT_YUAN",
    "DEFAULT_SELL_BUFFER",
    "DEFAULT_TOP_N",
    "DailyOrderCounters",
    "DailyOrderStrategy",
]

# STRATEGY §3 个人版口径：Top20 + 滞后带 20（跌出前 40 才卖）。
DEFAULT_TOP_N = 20
DEFAULT_SELL_BUFFER = 20
# STRATEGY §3 流动性护栏：执行日成交额 < 1 亿剔除（真实元，C02 amount_basis=yuan）。
DEFAULT_MIN_AMOUNT_YUAN = 1e8

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyOrderCounters:
    """计数快照：键名稳定，供 C05 provenance 消费；均为实例生命周期累计值."""

    buy_order_count: int = 0
    sell_order_count: int = 0
    filtered_low_liquidity_count: int = 0
    empty_cross_section_count: int = 0


def _checked_top_n(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"top_n must be a positive int, got {value!r}")
    return value


def _checked_buffer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"sell_buffer must be a non-negative int, got {value!r}")
    return value


def _checked_min_amount(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"min_amount_yuan must be finite, got {value!r}")
    numeric = float(value)
    if numeric < 0.0:
        raise ValueError(f"min_amount_yuan must be >= 0, got {value!r}")
    return numeric


class DailyOrderStrategy:
    """T 日截面 → core 原子订单（C04 daily；``OrderStrategy`` 协议实现）."""

    def __init__(
        self,
        prediction_adapter,
        market_provider=None,
        *,
        top_n: int = DEFAULT_TOP_N,
        sell_buffer: int = DEFAULT_SELL_BUFFER,
        min_amount_yuan: float = DEFAULT_MIN_AMOUNT_YUAN,
    ) -> None:
        if not hasattr(prediction_adapter, "available_dates") or not callable(
            getattr(prediction_adapter, "predictions_for_date", None)
        ):
            raise ValueError(f"prediction_adapter 缺少 available_dates/predictions_for_date：{prediction_adapter!r}")
        if market_provider is not None and not callable(getattr(market_provider, "get_bar", None)):
            raise ValueError(f"market_provider 缺少 get_bar：{market_provider!r}")
        self._adapter = prediction_adapter
        self._market = market_provider
        self._top_n = _checked_top_n(top_n)
        self._sell_buffer = _checked_buffer(sell_buffer)
        self._min_amount = _checked_min_amount(min_amount_yuan)
        self._buy_order_count = 0
        self._sell_order_count = 0
        self._filtered_low_liquidity_count = 0
        self._empty_cross_section_count = 0
        self._warned: set[str] = set()

    @property
    def top_n(self) -> int:
        return self._top_n

    @property
    def sell_buffer(self) -> int:
        return self._sell_buffer

    @property
    def min_amount_yuan(self) -> float:
        return self._min_amount

    @property
    def available_dates(self) -> tuple:
        """C03 谱系日期直通：策略/Runner 共用同一 fail-fast 边界."""
        return tuple(self._adapter.available_dates)

    @property
    def counters(self) -> DailyOrderCounters:
        """计数快照（键名稳定）。"""
        return DailyOrderCounters(
            buy_order_count=self._buy_order_count,
            sell_order_count=self._sell_order_count,
            filtered_low_liquidity_count=self._filtered_low_liquidity_count,
            empty_cross_section_count=self._empty_cross_section_count,
        )

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        """信号时点：T 日 15:00 Asia/Shanghai（与 C01/C03 同口径）."""
        return signal_time_for(trading_date)

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）."""
        counters = self.counters
        return {
            "buy_order_count": str(counters.buy_order_count),
            "sell_order_count": str(counters.sell_order_count),
            "filtered_low_liquidity_count": str(counters.filtered_low_liquidity_count),
            "empty_cross_section_count": str(counters.empty_cross_section_count),
        }

    def orders_for(
        self,
        *,
        trading_date: date,
        signal_time: datetime,
        account: AccountView,
        market: MarketView,
    ) -> tuple:
        """T 日截面 → 原子订单（卖出在前、买入按名次序；无订单显式空元组）.

        ``market`` 为协议形状参数：护栏金额走注入的 ``market_provider``（信号日
        行情），不直接消费 ``MarketView``，避免与账户视图估值口径漂移。
        """
        del market
        ensure_calendar_date(trading_date, "trading_date")
        ensure_tz_aware(signal_time, "signal_time")
        if signal_time.date() != trading_date:
            raise ValueError(f"signal_time {signal_time!r} 与 trading_date {trading_date!r} 不一致")
        if trading_date not in set(self._adapter.available_dates):
            raise ValueError(f"trading_date {trading_date!r} 不在预测覆盖内，拒绝误传日期（fail-fast）")
        ranked = self._ranked_codes(trading_date)
        if not ranked:
            self._empty_cross_section_count += 1
            self._warn_once("empty_cross_section", f"空截面：{trading_date.isoformat()} 无可用预测，返回空订单")
            return ()
        targets = ranked[: self._top_n]
        allow_set = set(ranked[: self._top_n + self._sell_buffer])
        liquid_targets = self._guard_liquidity(targets, trading_date)
        sells = self._sell_orders(account, allow_set)
        buys = self._buy_orders(account, liquid_targets)
        self._sell_order_count += len(sells)
        self._buy_order_count += len(buys)
        return (*sells, *buys)

    def _ranked_codes(self, trading_date: date) -> tuple[str, ...]:
        """按 score_trade 降序取全截面排名；并列按代码升序（stable 确定）."""
        preds = self._adapter.predictions_for_date(trading_date)
        return tuple(
            pred.instrument_id
            for pred in sorted(preds, key=lambda p: (-p.value, p.instrument_id))
        )

    def _guard_liquidity(self, targets: Sequence[str], trading_date: date) -> tuple[str, ...]:
        """流动性护栏：信号日 amount 明确 < 阈值剔除买入并计数；无行情/缺量不断流."""
        if self._market is None or self._min_amount <= 0.0:
            return tuple(targets)
        kept: list[str] = []
        for code in targets:
            amount = self._amount_for(code, trading_date)
            if amount is not None and amount < self._min_amount:
                self._filtered_low_liquidity_count += 1
                self._warn_once("low_liquidity", f"低流动性已剔除买入并计入 filtered_low_liquidity_count：{code!r}")
                continue
            kept.append(code)
        return tuple(kept)

    def _amount_for(self, code: str, trading_date: date) -> float | None:
        """信号日成交额（真实元）；无行情/非法值返回 None（不断流，留给引擎裁决）."""
        assert self._market is not None
        try:
            bar = self._market.get_bar(code, trading_date)
        except (OSError, ValueError, TypeError, AttributeError):
            return None
        if bar is None:
            return None
        amount = getattr(bar, "amount", None)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            return None
        if amount <= 0.0:
            return None
        return float(amount)

    def _sell_orders(self, account: AccountView, allow_set: set[str]) -> list[OrderIntent]:
        """允许集外持仓 shares 全卖（锁仓部分留给 core 引擎裁决 locked 事件）."""
        orders: list[OrderIntent] = []
        for code in sorted(account.positions):
            if code in allow_set:
                continue
            held = int(account.positions[code].shares)
            if held > 0:
                orders.append(OrderIntent(instrument_id=code, side=Side.SELL, shares=held))
        return orders

    def _buy_orders(self, account: AccountView, targets: Sequence[str]) -> list[OrderIntent]:
        """等权现金单：``cash_amount = 可用现金 / 目标数``；已持有目标不动."""
        if not targets:
            return []
        usable = float(account.available_cash)
        if usable <= 0.0 or not math.isfinite(usable):
            return []
        budget = usable / len(targets)
        return [
            OrderIntent(instrument_id=code, side=Side.BUY, cash_amount=budget)
            for code in targets
            if code not in account.positions
        ]

    def _warn_once(self, key: str, message: str) -> None:
        """同类事件只告警一次（后续仅计数，避免长回测刷屏）。"""
        if key in self._warned:
            return
        self._warned.add(key)
        logger.warning(message)
