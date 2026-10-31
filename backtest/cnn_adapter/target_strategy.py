"""cnn 目标持仓策略（B04-target）：T 日截面买入带等权现金单 + 滞后带卖单。

对标旧引擎 ``run_backtest_target`` 同语义：T 日全截面按 exp_ret 降序排名
（并列按代码升序）；持有仓位 rank > target_size + sell_buffer 则卖出；
``exit_on_nonpositive`` 时持仓 exp_ret <= exit_threshold 也卖出（忽略 rank
buffer，缺预测不卖）；买入带 rank <= target_size 内 exp_ret < 门槛
（仅当 ``strong_buy_threshold > 0``，0.0 = 关闭）跳过；
``min_edge > 0`` 时买入带尾部（默认后 30%，``min_edge_tail_ratio`` 可调）内
exp_ret < ``min_edge`` 同样跳过（0.0 = 关闭；goal v6 同语义的 cnn 侧等价参数）；
买入按预算等权现金单，已持有目标不动。

预算口径（与旧引擎不同，勿混用）：
- 本策略：``可用现金 / 当日实际成交家数``，另有 ``_MAX_HOLDINGS = 10`` 独立
  持仓上限；``target_size`` 仅表示买入带名次带宽（默认 100），不是预算分母。
  因此被门槛跳过的槽位，其份额会分摊给当日实际成交的标的。
- 旧引擎 ``run_backtest_target``：``nav / target_size`` 每槽固定预算，无持仓
  上限概念；被跳过的槽位留作现金、不补位。
- 后果：``strong_buy_threshold``/``min_edge`` 开启时，两者的现金比**不可直接
  比较**（同等阈值下本策略现金比显著更低）。历史强买门槛结论出自旧引擎。
- ``strong_buy``/``min_edge`` 属策略层过滤，跳过数记在本策略 counters，
  不进入 core ``skipped_counts``（后者只含 core 裁决的 limit_up/locked 等原因）。

两档止损（可选，默认关闭）：``stop_half``（如 0.03）触发持仓浮亏
``price / cost - 1 <= -stop_half`` 时卖出一半可卖股数；
``stop_full``（如 0.06）触发全仓卖出。浮亏按 AccountView 持仓快照计算：
``cost`` 为引擎维护的每股均价（core account 口径），``price`` 为最新市价；
缺价（price 为 None）或 cost <= 0 时不触发；T+1 锁定股数（locked）不可卖，
只卖可卖部分。
止损卖单与 rank/exit 卖单按代码取并集（股数取最大者），卖出在前按代码序。

口径声明：
- 涨跌停/整手/锁定最终由 core 引擎裁决：rank/exit 卖单沿旧语义发全量
  持有股数（引擎裁决 locked），止损卖单按可卖股数发单（同样接受引擎裁决）。
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

_MAX_HOLDINGS = 10


@dataclass(frozen=True)
class CnnTargetOrderCounters:
    """计数快照：键名稳定，供 B05 provenance 消费；均为实例生命周期累计值."""

    buy_order_count: int = 0
    sell_order_count: int = 0
    skipped_strong_buy_count: int = 0
    skipped_min_edge_count: int = 0
    stop_half_order_count: int = 0
    stop_full_order_count: int = 0


def _ranked_predictions(adapter: CnnPredictionAdapter, trading_date: date) -> tuple:
    """全截面按 exp_ret 降序、并列按代码升序（与旧 CnnOrderStrategy 同序，保证确定性）."""
    return tuple(sorted(adapter.predictions_for_date(trading_date),
                        key=lambda pred: (-pred.value, pred.instrument_id)))


class CnnTargetOrderStrategy:
    """滞后带目标持仓 → core 原子订单（B04-target；``OrderStrategy`` 协议实现）."""

    def __init__(self, prediction_adapter: CnnPredictionAdapter, *, target_size: int = 100,
                 sell_buffer: int = 500, exit_on_nonpositive: bool = False,
                 exit_threshold: float = 0.0, strong_buy_threshold: float = 0.0,
                 min_edge: float = 0.0, min_edge_tail_ratio: float = 0.3,
                 stop_half: float | None = None, stop_full: float | None = None) -> None:
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
        min_edge = self._checked_threshold(min_edge, "min_edge")
        if min_edge < 0.0:
            raise ValueError(f"min_edge must be >= 0, got {min_edge!r}")
        if (isinstance(min_edge_tail_ratio, bool)
                or not isinstance(min_edge_tail_ratio, (int, float))
                or not math.isfinite(float(min_edge_tail_ratio))
                or not 0.0 < float(min_edge_tail_ratio) <= 1.0):
            raise ValueError(
                f"min_edge_tail_ratio must be in (0, 1], got {min_edge_tail_ratio!r}")
        self._stop_half = self._checked_stop(stop_half, "stop_half")
        self._stop_full = self._checked_stop(stop_full, "stop_full")
        if self._stop_half is not None and self._stop_full is not None \
                and self._stop_full < self._stop_half:
            raise ValueError(
                f"stop_full ({self._stop_full!r}) must be >= stop_half ({self._stop_half!r})")
        self._adapter = prediction_adapter
        self._target_size = target_size
        self._sell_buffer = sell_buffer
        self._exit_on_nonpositive = exit_on_nonpositive
        self._exit_threshold = exit_threshold
        self._strong_buy_threshold = strong_buy_threshold
        self._min_edge = min_edge
        self._min_edge_tail_ratio = float(min_edge_tail_ratio)
        self._buy_order_count = 0
        self._sell_order_count = 0
        self._skipped_strong_buy_count = 0
        self._skipped_min_edge_count = 0
        self._stop_half_order_count = 0
        self._stop_full_order_count = 0

    @staticmethod
    def _checked_threshold(value: object, name: str) -> float:
        """阈值校验：数值（拒 bool/str），NaN 显式失败（inf 保留，语义为全过/全不过）."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number, got {value!r}")
        result = float(value)
        if math.isnan(result):
            raise ValueError(f"{name} must not be NaN, got {value!r}")
        return result

    @staticmethod
    def _checked_stop(value: object, name: str) -> float | None:
        """止损阈值校验：None/0.0 = 关闭；开启时须在 (0, 1) 内（亏损比例）。"""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a number or None, got {value!r}")
        result = float(value)
        if result == 0.0:
            return None
        if not math.isfinite(result) or not 0.0 < result < 1.0:
            raise ValueError(f"{name} must be in (0, 1) or 0.0/None (disabled), got {value!r}")
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
    def min_edge(self) -> float:
        return self._min_edge

    @property
    def min_edge_tail_ratio(self) -> float:
        return self._min_edge_tail_ratio

    @property
    def stop_half(self) -> float | None:
        return self._stop_half

    @property
    def stop_full(self) -> float | None:
        return self._stop_full

    @property
    def available_dates(self) -> tuple:
        """B03 谱系日期直通：策略/Runner 共用同一 fail-fast 边界."""
        return self._adapter.available_dates

    @property
    def counters(self) -> CnnTargetOrderCounters:
        """计数快照（含 strong_buy/min_edge 跳过数，供回测 skipped 口径对账）."""
        return CnnTargetOrderCounters(buy_order_count=self._buy_order_count,
                                      sell_order_count=self._sell_order_count,
                                      skipped_strong_buy_count=self._skipped_strong_buy_count,
                                      skipped_min_edge_count=self._skipped_min_edge_count,
                                      stop_half_order_count=self._stop_half_order_count,
                                      stop_full_order_count=self._stop_full_order_count)

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        """信号时点：T 日 15:00 Asia/Shanghai（与 B03 同口径）."""
        return signal_time_for(trading_date)

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）."""
        counters = self.counters
        return {"buy_order_count": str(counters.buy_order_count),
                "sell_order_count": str(counters.sell_order_count),
                "skipped_strong_buy_count": str(counters.skipped_strong_buy_count),
                "skipped_min_edge_count": str(counters.skipped_min_edge_count),
                "stop_half_order_count": str(counters.stop_half_order_count),
                "stop_full_order_count": str(counters.stop_full_order_count)}

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
        buys, skipped_strong_buy, skipped_min_edge = self._buy_orders(account, buy_band, exp_map)
        self._sell_order_count += len(sells)
        self._buy_order_count += len(buys)
        self._skipped_strong_buy_count += skipped_strong_buy
        self._skipped_min_edge_count += skipped_min_edge
        return (*sells, *buys)

    def _sell_orders(self, account: AccountView, rank_map: dict, exp_map: dict) -> list[OrderIntent]:
        """滞后带卖单：exit 开启看阈值（缺预测不卖），否则看 rank（缺预测 rank 记 0 → 持有）.

        止损卖单（可选）：浮亏达 ``stop_half`` 卖一半可卖股数，达 ``stop_full``
        卖全部可卖股数；与 rank/exit 卖单按代码取并集（股数取最大者）。
        """
        full_sell: set[str] = set()
        for code in account.positions:
            if self._exit_on_nonpositive:
                value = exp_map.get(code)
                if value is not None and value <= self._exit_threshold:
                    full_sell.add(code)
            elif rank_map.get(code, 0) > self._target_size + self._sell_buffer:
                full_sell.add(code)
        locked = account.locked if isinstance(account.locked, dict) else {}
        stop_shares: dict[str, int] = {}
        if self._stop_half is not None or self._stop_full is not None:
            for code in account.positions:
                desired = self._stop_shares_for(account, code, locked)
                if desired is not None and desired > 0:
                    stop_shares[code] = desired
        orders: list[OrderIntent] = []
        for code in sorted(set(full_sell) | set(stop_shares)):
            held = int(account.positions[code].shares)
            if held <= 0:
                continue
            if code in stop_shares and code not in full_sell:
                # 纯止损单：全量计 stop_full，半量计 stop_half；rank/exit 主导时不重复计
                shares = stop_shares[code]
                if shares >= held:
                    self._stop_full_order_count += 1
                else:
                    self._stop_half_order_count += 1
            else:
                shares = held
            if shares > 0:
                orders.append(OrderIntent(instrument_id=code, side=Side.SELL, shares=shares))
        return orders

    def _stop_shares_for(self, account: AccountView, code: str, locked: dict) -> int | None:
        """单持仓止损股数：无止损配置/缺价/cost 非正/锁定无可卖时返回 None."""
        if self._stop_half is None and self._stop_full is None:
            return None
        pos = account.positions[code]
        held = int(pos.shares)
        if held <= 0:
            return None
        price = pos.price
        try:
            cost = float(pos.cost)
        except (TypeError, ValueError):
            return None
        if price is None or not cost > 0.0 or not float(price) > 0.0:
            return None
        floating = float(price) / cost - 1.0
        if not math.isfinite(floating):
            return None
        sellable = held - int(locked.get(code, 0) or 0)
        if sellable <= 0:
            return None
        if self._stop_full is not None and floating <= -self._stop_full:
            return sellable
        if self._stop_half is not None and floating <= -self._stop_half:
            half = sellable // 2
            return half if half > 0 else None
        return None

    def _buy_orders(self, account: AccountView, buy_band: Sequence[str],
                    exp_map: dict) -> tuple[list[OrderIntent], int, int]:
        """买入带等权现金单：已持有不动；两道买入门槛（均跳过）.

        全带门槛 ``strong_buy_threshold``（>0 开启）；尾部门槛 ``min_edge``（>0 开启，
        仅作用于买入带后 ``min_edge_tail_ratio`` 部分，按带内名次划分）。

        预算按当日实际成交家数等分（``可用现金 / len(candidates)``）：被门槛跳过
        或已持有的槽位不保留份额，其现金会流向实际成交者。这与旧引擎每槽固定
        ``nav / target_size``、跳过留现金的口径不同，详见模块 docstring。
        """
        candidates: list[str] = []
        skipped_strong_buy = 0
        skipped_min_edge = 0
        tail_size = math.ceil(len(buy_band) * self._min_edge_tail_ratio)
        tail_start = len(buy_band) - tail_size
        for pos, code in enumerate(buy_band):
            if code in account.positions:
                continue
            if self._strong_buy_threshold > 0.0 and exp_map[code] < self._strong_buy_threshold:
                skipped_strong_buy += 1
                continue
            if (self._min_edge > 0.0 and pos >= tail_start
                    and exp_map[code] < self._min_edge):
                skipped_min_edge += 1
                continue
            candidates.append(code)
        # 所有当前仓位（包括当日可能被拒绝的卖单）先占用名额，不能预支卖出成交。
        held_count = sum(int(position.shares) > 0 for position in account.positions.values())
        slots = max(_MAX_HOLDINGS - held_count, 0)
        candidates = candidates[:slots]
        if not candidates:
            return [], skipped_strong_buy, skipped_min_edge
        usable = float(account.available_cash)
        if usable <= 0.0 or not math.isfinite(usable):
            return [], skipped_strong_buy, skipped_min_edge
        # 预算按实际买入家数等分（跳过/已持有不占槽，core 引擎按成交价+费用折算整手）。
        budget = usable / len(candidates)
        orders = [OrderIntent(instrument_id=code, side=Side.BUY, cash_amount=budget)
                  for code in candidates]
        return orders, skipped_strong_buy, skipped_min_edge
