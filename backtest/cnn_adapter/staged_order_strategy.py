"""按固定预算 tranche 生成收盘限价意图；账户执行状态仅来自 core。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import floor, isfinite
from types import MappingProxyType

from backtest_core.contracts import CostConfig, MarketBar, OrderIntent, Side
from backtest_core.contracts.protocols import AccountView, MarketView
from backtest_core.contracts.validation import ensure_calendar_date, ensure_tz_aware
from backtest_core.policies import AShareCostModel

from backtest.cnn_adapter.common import signal_time_for
from backtest.cnn_adapter.quantity_rules import QuantityRule, QuantityRuleError
from backtest.cnn_adapter.staged_allocation import (
    AllocationError,
    AllocationRegistry,
    Episode,
    EpisodeStatus,
    Policy,
    TrancheStatus,
)

BUY_RANK_MAX = 5
EXIT_RANK_MIN = 11
_LIMIT_BUFFER = 0.045
_SOURCE_ID_PLACEHOLDERS = frozenset({
    "unknown", "none", "null", "n/a", "na", "undefined", "placeholder", "tbd",
    "not available", "<unknown>",
})


class RankingError(ValueError):
    """排名来源、日期或完整性不满足收盘决策契约。"""


@dataclass(frozen=True)
class RankingSnapshot:
    trading_date: date
    source_id: str
    ranks: Mapping[str, int]
    complete: bool
    buy_eligible: Mapping[str, bool]

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise RankingError("排名 source_id 缺失或为空白")
        if self.source_id.strip().casefold() in _SOURCE_ID_PLACEHOLDERS:
            raise RankingError("排名 source_id 不能使用来源占位值")
        if not isinstance(self.complete, bool):
            raise RankingError("排名完整性必须显式声明")
        checked: dict[str, int] = {}
        for code, rank in self.ranks.items():
            if (not isinstance(code, str) or not code or isinstance(rank, bool)
                    or not isinstance(rank, int) or rank <= 0):
                raise RankingError("排名必须是代码到正整数名次的映射")
            checked[code] = rank
        if set(checked.values()) != set(range(1, len(checked) + 1)):
            raise RankingError("rank 必须唯一、连续，保持正式排序的代码升序并列规则")
        eligibility = dict(self.buy_eligible)
        if set(eligibility) != set(checked) or any(type(value) is not bool for value in eligibility.values()):
            raise RankingError("buy_eligible 必须覆盖完整排名且为 bool")
        object.__setattr__(self, "ranks", MappingProxyType(checked))
        object.__setattr__(self, "buy_eligible", MappingProxyType(eligibility))

    @classmethod
    def from_scores(cls, trading_date: date, source_id: str, rows: Sequence[Mapping[str, object]],
                    *, complete: bool) -> RankingSnapshot:
        ready: list[tuple[str, float, bool]] = []
        seen: set[str] = set()
        for row in rows:
            code, status, score = row.get("instrument_id"), row.get("status"), row.get("exp_ret")
            if not isinstance(code, str) or not code or code in seen:
                raise RankingError("预测代码缺失或重复")
            seen.add(code)
            if status != "ready":
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score):
                continue
            eligible = row.get("buy_eligible")
            if type(eligible) is not bool:
                raise RankingError(f"{code} 缺少可核 buy_eligible")
            ready.append((code, float(score), eligible))
        ready.sort(key=lambda item: (-item[1], item[0]))
        ranks = {code: index for index, (code, _, _) in enumerate(ready, 1)}
        return cls(trading_date, source_id, ranks, complete,
                   {code: eligible for code, _, eligible in ready})


@dataclass(frozen=True)
class PositionUsage:
    positive_position_codes: frozenset[str] = frozenset()
    locked_codes: frozenset[str] = frozenset()
    entitlement_codes: frozenset[str] = frozenset()
    active_order_codes: frozenset[str] = frozenset()
    occupied_codes: frozenset[str] = frozenset()


class MappingRankingSource:
    def __init__(self, snapshots: Mapping[date, RankingSnapshot]):
        self._snapshots = MappingProxyType(dict(snapshots))

    def for_date(self, trading_date: date) -> RankingSnapshot:
        try:
            snapshot = self._snapshots[trading_date]
        except KeyError as exc:
            raise RankingError(f"缺少 {trading_date} 排名，拒绝猜测资格") from exc
        if snapshot.trading_date != trading_date or not snapshot.complete:
            raise RankingError("排名日期不符或榜单不完整")
        return snapshot


class StagedOrderStrategy:
    def __init__(self, registry: AllocationRegistry, ranking_source: MappingRankingSource,
                 *, policy: Policy, execution_calendar: Sequence[date],
                 worst_case_cost_config: CostConfig,
                 cost_config_resolver: Callable[[date, str], CostConfig] | None = None,
                 quantity_rule_resolver: Callable[[date, str], QuantityRule] | None = None,
                 tick_size: float, lot_size: int = 100,
                 buffer_start_date: date | None = None):
        days = tuple(execution_calendar)
        if not days or days != tuple(sorted(set(days))) or any(day not in registry.calendar_days for day in days):
            raise ValueError("execution_calendar 必须严格递增且属于 registry calendar")
        if buffer_start_date is not None and buffer_start_date not in days:
            raise ValueError("buffer_start_date 必须属于 execution_calendar")
        if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
            raise ValueError("lot_size 必须为正整数")
        for name, value in (("tick_size", tick_size),):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须为有限正数")
        if not isinstance(worst_case_cost_config, CostConfig):
            raise TypeError("worst_case_cost_config 必须为 CostConfig")
        if cost_config_resolver is not None and not callable(cost_config_resolver):
            raise ValueError("cost_config_resolver 必须可调用")
        if quantity_rule_resolver is not None and not callable(quantity_rule_resolver):
            raise ValueError("quantity_rule_resolver 必须可调用")
        self._registry = registry
        self._ranking_source = ranking_source
        self._policy = Policy(policy)
        self._calendar = days
        self._cost = worst_case_cost_config
        self._cost_resolver = cost_config_resolver
        self._quantity_rule_resolver = quantity_rule_resolver
        self._lot_size = lot_size
        self._limit_buffer = _LIMIT_BUFFER
        self._tick = float(tick_size)
        self._buffer_start = buffer_start_date
        self._history: dict[str, dict[date, int | None]] = {}
        self._rejections: list[str] = []
        self._position_usage = PositionUsage()

    @staticmethod
    def signal_time_for(trading_date: date) -> datetime:
        return signal_time_for(trading_date)

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def rejection_log(self) -> tuple[str, ...]:
        return tuple(self._rejections)

    @property
    def position_usage(self) -> PositionUsage:
        return self._position_usage

    # -- 收盘决策主入口 -------------------------------------------------

    def orders_for(self, *, trading_date: date, signal_time: datetime,
                   account: AccountView, market: MarketView) -> tuple[OrderIntent, ...]:
        ensure_calendar_date(trading_date, "trading_date")
        ensure_tz_aware(signal_time, "signal_time")
        if signal_time.date() != trading_date:
            raise ValueError(f"signal_time {signal_time!r} 与 trading_date {trading_date!r} 不一致")
        if trading_date not in set(self._calendar):
            return ()
        core_snapshot = self._registry.core_snapshot
        if core_snapshot is None or core_snapshot.trading_date != trading_date:
            raise AllocationError("收盘决策需要同日最新 core AccountState 快照")
        self._validate_account_view(account, core_snapshot)
        positive = frozenset(code for code, position in account.positions.items()
                             if position.shares > 0)
        locked = frozenset(code for code, shares in core_snapshot.locked.items() if shares > 0)
        entitlements = core_snapshot.unlisted_entitlement_codes
        active_orders = core_snapshot.active_order_codes
        self._position_usage = PositionUsage(
            positive, locked, entitlements, active_orders,
            positive | locked | entitlements | active_orders,
        )
        self._registry.advance(trading_date)
        in_buffer = self._buffer_start is not None and trading_date >= self._buffer_start
        if in_buffer:
            orders: list[OrderIntent] = []
            for episode in sorted(
                (item for item in self._registry.episodes.values()
                 if item.status is not EpisodeStatus.CLOSED),
                key=lambda item: item.episode_id,
            ):
                self._registry.mark_exit_pending(episode.episode_id, trading_date)
                self._registry.cancel_future_tranches(
                    episode.episode_id, trading_date, "buffer_maintenance",
                )
                orders.extend(self._exit_sell_orders(episode, trading_date, account, market))
            self._registry.finalize_close(trading_date)
            return tuple(orders)
        snapshot = self._ranking_source.for_date(trading_date)
        for code in sorted(snapshot.ranks):
            self._history.setdefault(code, {})[trading_date] = snapshot.ranks[code]
        orders: list[OrderIntent] = []
        for episode in sorted(
            (item for item in self._registry.episodes.values()
             if item.status is not EpisodeStatus.CLOSED),
            key=lambda item: item.episode_id,
        ):
            orders.extend(
                self._episode_orders(episode, trading_date, snapshot, account, market)
            )
        if self._buy_window_open(trading_date):
            orders.extend(
                self._new_episode_orders(trading_date, snapshot, account, market)
            )
        self._registry.finalize_close(trading_date)
        return tuple(orders)

    def _validate_account_view(self, account: AccountView, snapshot) -> None:
        if (isinstance(account.available_cash, bool)
                or not isinstance(account.available_cash, (int, float))
                or not isfinite(account.available_cash)
                or abs(float(account.available_cash) - snapshot.available_cash) > 1e-8):
            raise AllocationError("AccountView available_cash 与最新 core snapshot 不一致")
        positions: dict[str, int] = {}
        for code, position in account.positions.items():
            if not isinstance(code, str) or not code:
                raise AllocationError("AccountView positions 包含无效 instrument_id")
            shares = self._view_shares(position.shares, f"positions[{code}]")
            if shares > 0:
                positions[code] = shares
        locked: dict[str, int] = {}
        for code, value in account.locked.items():
            if not isinstance(code, str) or not code:
                raise AllocationError("AccountView locked 包含无效 instrument_id")
            shares = self._view_shares(value, f"locked[{code}]")
            if shares > 0:
                locked[code] = shares
        expected_positions = {code: shares for code, shares in snapshot.positions.items() if shares > 0}
        expected_locked = {code: shares for code, shares in snapshot.locked.items() if shares > 0}
        if positions != expected_positions or locked != expected_locked:
            raise AllocationError("AccountView positions/locked 与最新 core snapshot 不一致")

    @staticmethod
    def _view_shares(value: object, label: str) -> int:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not isfinite(value) or value < 0 or not float(value).is_integer()):
            raise AllocationError(f"{label} 必须为有限非负整数股")
        return int(value)

    def _episode_orders(self, episode: Episode, trading_date: date, snapshot: RankingSnapshot,
                        account: AccountView, market: MarketView,
                        ) -> list[OrderIntent]:
        ranks = snapshot.ranks
        rank = ranks.get(episode.code)
        eligible_now = snapshot.buy_eligible.get(episode.code, False)
        if rank is not None and rank >= EXIT_RANK_MIN:
            self._registry.mark_exit_pending(episode.episode_id, trading_date)
            self._registry.cancel_future_tranches(
                episode.episode_id, trading_date, "exit_rank_gt_10",
            )
            return self._exit_sell_orders(episode, trading_date, account, market)
        if self._enters_buffer_next_day(trading_date):
            self._registry.mark_exit_pending(episode.episode_id, trading_date)
            self._registry.cancel_future_tranches(
                episode.episode_id, trading_date, "buffer_start_or_final_signal_day",
            )
            return self._exit_sell_orders(episode, trading_date, account, market)
        if episode.exit_pending:
            return self._exit_sell_orders(episode, trading_date, account, market)
        if not self._buy_window_open(trading_date):
            self._registry.cancel_future_tranches(
                episode.episode_id, trading_date, "buffer_execution_boundary",
            )
            return []
        orders: list[OrderIntent] = []
        for key, tranche in sorted(self._registry.tranches.items()):
            episode_id, tranche_id = key
            if episode_id != episode.episode_id or tranche.decision_date != trading_date:
                continue
            if tranche.status is not TrancheStatus.PLANNED:
                continue
            tranche_eligible = (
                rank is not None and eligible_now and rank <= BUY_RANK_MAX
                and self._tranche_history_ok(episode, tranche_id, trading_date)
            )
            self._registry.decide_tranche(
                episode.episode_id, tranche_id, eligible=tranche_eligible,
                reason=None if tranche_eligible else "rank_or_continuity_ineligible",
            )
            if tranche_eligible:
                intent = self._buy_intent(episode, tranche_id, trading_date, tranche.budget, market)
                if intent is not None:
                    orders.append(intent)
        return orders

    def _tranche_history_ok(self, episode: Episode, tranche_id: str, trading_date: date) -> bool:
        if episode.policy is not Policy.S2 or episode.plan_start_date is None:
            return True
        start = episode.plan_start_date
        if tranche_id == "t6":
            start = self._offset_trading_day(episode.plan_start_date, 4)
            if start is None:
                return False
        history = self._history.get(episode.code, {})
        for day in (item for item in self._calendar if start <= item <= trading_date):
            rank = history.get(day)
            if rank is None or rank > BUY_RANK_MAX:
                return False
        return True

    def _offset_trading_day(self, anchor: date, offset: int) -> date | None:
        try:
            index = self._calendar.index(anchor) + offset
        except ValueError:
            return None
        return self._calendar[index] if index < len(self._calendar) else None

    def _buy_window_open(self, trading_date: date) -> bool:
        try:
            next_day = self._calendar[self._calendar.index(trading_date) + 1]
        except (ValueError, IndexError):
            return False
        return self._buffer_start is None or next_day < self._buffer_start

    def _enters_buffer_next_day(self, trading_date: date) -> bool:
        try:
            next_day = self._calendar[self._calendar.index(trading_date) + 1]
        except (ValueError, IndexError):
            return False
        return self._buffer_start is not None and next_day == self._buffer_start

    def _new_episode_orders(self, trading_date: date, snapshot: RankingSnapshot,
                            account: AccountView, market: MarketView) -> list[OrderIntent]:
        occupied = set(self._position_usage.occupied_codes)
        occupied.update(
            episode.code for episode in self._registry.episodes.values()
            if episode.status is not EpisodeStatus.CLOSED
        )
        occupied.update(code for code, pos in account.positions.items() if pos.shares > 0)
        occupied.update(code for code, shares in account.locked.items() if shares > 0)
        orders: list[OrderIntent] = []
        for code, rank in sorted(snapshot.ranks.items(), key=lambda item: item[1]):
            if rank > BUY_RANK_MAX or not snapshot.buy_eligible.get(code, False) or code in occupied:
                continue
            if len(occupied) >= 10:
                break
            if (self._registry.snapshot().active_slots >= 5
                    or self._registry.free_cash < self._registry.tranche_budget):
                break
            bar = self._bar(market, code, trading_date)
            if bar is None or bar.close is None or not isfinite(bar.close) or bar.close <= 0:
                self._rejections.append(f"{trading_date}:{code}:raw_close_unknown")
                continue
            episode_id = f"{self._policy.value}:{code}:{trading_date.isoformat()}"
            try:
                episode = self._registry.open_episode(episode_id, code, self._policy)
            except AllocationError:
                occupied.add(code)
                continue
            tranches = self._plan_tranches(trading_date, episode.commitment)
            self._registry.initialize_plan(
                episode_id, f"plan:{episode_id}", trading_date,
                tranches[-1][1], {name: (day, amount) for name, day, amount in tranches},
            )
            self._registry.decide_tranche(episode_id, "t0", eligible=True)
            intent = self._buy_intent(episode, "t0", trading_date, tranches[0][2], market)
            if intent is not None:
                orders.append(intent)
            occupied.add(code)
        return orders

    def _plan_tranches(self, start: date, commitment: float) -> list[tuple[str, date, float]]:
        if self._policy is Policy.B1:
            return [("t0", start, commitment)]
        if self._policy is Policy.C70:
            return [("t0", start, commitment * 0.7)]
        third = commitment / 3
        planned = [("t0", start, third)]
        for offset, tranche_id in ((3, "t3"), (6, "t6")):
            day = self._offset_trading_day(start, offset)
            if day is not None:
                amount = commitment - third * 2 if tranche_id == "t6" else third
                planned.append((tranche_id, day, amount))
        return planned

    def _buy_intent(self, episode: Episode, tranche_id: str, trading_date: date,
                    budget: float, market: MarketView) -> OrderIntent | None:
        bar = self._bar(market, episode.code, trading_date)
        if bar is None or bar.close is None or not isfinite(bar.close) or bar.close <= 0:
            self._registry.fail_tranche(episode.episode_id, tranche_id, "close_or_limit_unknown")
            return None
        limit = self._floor_tick(bar.close * (1 + self._limit_buffer))
        shares = self._affordable_shares(budget, limit, episode.code, trading_date)
        if shares <= 0:
            self._registry.fail_tranche(episode.episode_id, tranche_id, "zero_lot")
            return None
        try:
            rule = self._quantity_rule(episode.code, trading_date)
            if rule is not None:
                rule.validate(Side.BUY, shares, trading_date)
        except (QuantityRuleError, ValueError) as exc:
            self._registry.fail_tranche(episode.episode_id, tranche_id, "quantity_rule: " + str(exc))
            self._rejections.append(f"{trading_date}:{episode.code}:buy_quantity_rule")
            return None
        order_id = f"{episode.episode_id}:{tranche_id}:{trading_date.isoformat()}"
        self._registry.schedule_tranche(episode.episode_id, tranche_id, order_id, shares, limit)
        return OrderIntent(
            instrument_id=episode.code, side=Side.BUY, shares=shares,
            episode_id=episode.episode_id, order_id=order_id, limit_price=limit,
        )

    def _affordable_shares(self, budget: float, limit: float, code: str,
                           signal_date: date) -> int:
        execution_date = self._offset_trading_day(signal_date, 1)
        if execution_date is None:
            return 0
        config = (self._cost_resolver(execution_date, code)
                  if self._cost_resolver is not None else self._cost)
        if not isinstance(config, CostConfig):
            raise AllocationError("worst-case cost config resolver 必须返回 CostConfig")
        cost_model = AShareCostModel(config)
        shares = int(floor(budget / limit / self._lot_size)) * self._lot_size
        while shares > 0:
            amount = shares * limit
            commission, stamp_tax, transfer_fee = cost_model.calculate(Side.BUY, amount)
            if amount + commission + stamp_tax + transfer_fee <= budget:
                return shares
            shares -= self._lot_size
        return 0

    def _floor_tick(self, price: float) -> float:
        return round(floor(price / self._tick + 1e-10) * self._tick, 10)

    def _ceil_tick(self, price: float) -> float:
        return round(-floor(-price / self._tick + 1e-10) * self._tick, 10)

    def _exit_sell_orders(self, episode: Episode, trading_date: date,
                          account: AccountView, market: MarketView) -> list[OrderIntent]:
        position = account.positions.get(episode.code)
        if position is None:
            return []
        shares = int(position.shares) - int(account.locked.get(episode.code, 0))
        if shares <= 0:
            return []
        try:
            rule = self._quantity_rule(episode.code, trading_date)
            if rule is not None:
                rule.validate(Side.SELL, shares, trading_date, available_shares=shares)
        except (QuantityRuleError, ValueError):
            self._rejections.append(f"{trading_date}:{episode.code}:sell_quantity_rule")
            return []
        bar = self._bar(market, episode.code, trading_date)
        if bar is None or bar.close is None or not isfinite(bar.close) or bar.close <= 0:
            self._rejections.append(f"{trading_date}:{episode.code}:sell_raw_close_unknown")
            return []
        limit = self._ceil_tick(bar.close * (1 - self._limit_buffer))
        order_id = f"{episode.episode_id}:exit:{trading_date.isoformat()}"
        return [OrderIntent(
            instrument_id=episode.code, side=Side.SELL, shares=shares,
            episode_id=episode.episode_id, order_id=order_id, limit_price=limit,
        )]

    def _quantity_rule(self, code: str, trading_date: date) -> QuantityRule | None:
        if self._quantity_rule_resolver is None:
            return None
        rule = self._quantity_rule_resolver(trading_date, code)
        if not isinstance(rule, QuantityRule):
            raise QuantityRuleError("数量规则 resolver 必须返回 QuantityRule")
        return rule

    def _bar(self, market: MarketView, code: str, trading_date: date) -> MarketBar | None:
        bars = market.get_bars(code, trading_date, trading_date)
        series = tuple(bars.get(code, ()))
        if not series:
            return None
        bar = series[-1]
        if (bar.instrument_id != code or bar.trading_date != trading_date or not bar.is_trading
                or not bar.market_state_known or not bar.st_state_known
                or not bar.reference_known or not bar.limit_state_known):
            return None
        return bar
