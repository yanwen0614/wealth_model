"""goal 联合订单策略（C04 joint）：稀疏 episode 联合排序 → 等权现金单 + 滞后带。

joint 所指（以 ``backtest/account_engine_joint.py`` 实证为准）：

- 非多模型加权：joint 指同期候选池一次联合排序 + 稀疏调仓。``models/joint_portfolio``
  每 episode 在信号日对全候选池（``candidate_limit=300``）产出联合 logits，经
  softmax 得目标权重再经 ``project_policy_scores`` 按分降序截断 TopN；
  ``future_ret_5d`` 置零作 schema 垫片（禁作纸面收益曲线）。
- ``account_engine_joint`` 以 ``--freq 1`` 直接调用 V6：预测日期本身已稀疏
  （``make_rebalance_dates`` stride≈40/horizon≈41），不再二次抽稀；尾段统一
  ``final_liquidation`` 清算。策略侧不复刻清算（由 Runner/引擎承担）。

与 daily 的差异对照：

| 维度 | daily（``daily_policy``） | joint（本模块） |
|---|---|---|
| 信号密度 | 稠密日频截面（HGB 可实现收益 ``score_trade``） | 稀疏 episode（联合 logits/投影分） |
| 调仓节拍 | 引擎按 freq 抽稀（如每 20 信号日） | 日期本身稀疏，引擎 freq=1 直跑 |
| 默认 TopN/滞后 | 20/20（个人版，前 40 才卖） | 100/50（分散版，前 150 才卖） |
| 候选池 | 全市场截面 | episode 候选池（上限 300，投影截断） |
| actuals | ``future_ret_5d`` 诊断可用 | 置零垫片，策略禁读（只消费预测分） |
| 护栏/预算 | 信号日 amount 护栏＋等权 ``现金/目标数`` | 同口径（参数名/计数键对齐 daily） |
| 清算 | 目标外全卖（引擎 T+1 裁决） | 同左；尾段统一清算由 Runner 承担 |

判定依据：STRATEGY §3 分散版备注（Top100/滞后 50/v2 引擎）定默认值；
``account_engine_joint`` 默认 ``topn=100`` 对齐，``sell-buffer=200``（200% 规则
退出前 300）为实验变体，默认不取（docstring 锁定 50）。
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
    "JointOrderCounters",
    "JointOrderStrategy",
]

# STRATEGY §3 分散版口径：Top100 + 滞后带 50（跌出前 150 才卖）。
DEFAULT_TOP_N = 100
DEFAULT_SELL_BUFFER = 50
# 与 daily 同口径：执行日成交额 < 1 亿剔除（真实元）。
DEFAULT_MIN_AMOUNT_YUAN = 1e8

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JointOrderCounters:
    """计数快照：键名与 daily 对齐，供 C05 provenance 消费."""

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


class JointOrderStrategy:
    """稀疏 episode 联合排序 → core 原子订单（C04 joint；``OrderStrategy`` 协议实现）."""

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
        """谱系日期直通：稀疏 episode 日序列，策略/Runner 共用 fail-fast 边界."""
        return tuple(self._adapter.available_dates)

    @property
    def counters(self) -> JointOrderCounters:
        """计数快照（键名与 daily 对齐）。"""
        return JointOrderCounters(
            buy_order_count=self._buy_order_count,
            sell_order_count=self._sell_order_count,
            filtered_low_liquidity_count=self._filtered_low_liquidity_count,
            empty_cross_section_count=self._empty_cross_section_count,
        )

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        """信号时点：episode 信号日 15:00 Asia/Shanghai（与 C01 同口径）."""
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
        """episode 信号日 → 原子订单（卖出在前、买入按联合名次序；无订单显式空元组）.

        联合排序：同期候选池按投影分降序（并列按代码升序），与 daily 同为
        ``(-value, code)`` 确定序；差异在输入口径（联合 logits 投影 vs 日频
        HGB），不在排序算子。``market`` 为协议形状参数，不直接消费。
        """
        del market
        ensure_calendar_date(trading_date, "trading_date")
        ensure_tz_aware(signal_time, "signal_time")
        if signal_time.date() != trading_date:
            raise ValueError(f"signal_time {signal_time!r} 与 trading_date {trading_date!r} 不一致")
        if trading_date not in set(self._adapter.available_dates):
            raise ValueError(f"trading_date {trading_date!r} 不在 episode 覆盖内，拒绝误传日期（fail-fast）")
        ranked = self._ranked_codes(trading_date)
        if not ranked:
            self._empty_cross_section_count += 1
            self._warn_once("empty_cross_section", f"空 episode：{trading_date.isoformat()} 无可用投影分，返回空订单")
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
        """episode 联合排名：投影分降序，并列按代码升序（与投影侧同序）."""
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
        """信号日成交额（真实元）；无行情/非法值返回 None（不断流）."""
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
