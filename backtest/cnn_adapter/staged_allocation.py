"""纯预算登记；账户现金与持仓快照必须由 core 提供。"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Literal


class AllocationError(ValueError):
    """预算或执行反馈不符合状态契约。"""


class Policy(StrEnum):
    """仅保留预算标签，不连接买卖信号。"""

    B1 = "B1"
    S1 = "S1"
    S2 = "S2"
    C70 = "C70"


class EpisodeStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    CLOSED = "closed"


@dataclass(frozen=True)
class ExecutionFeedback:
    """单笔成交及成交后 core 权威账户快照。"""

    episode_id: str
    order_id: str | None
    fill_id: str | None
    event: Literal["fill", "cancel", "reject", "failed"]
    side: Literal["buy", "sell"]
    amount: float
    fees: float
    cash_debit: float
    shares_delta: int
    available_cash: float | None = None
    core_snapshot_id: str | None = None
    core_snapshot_sequence: int | None = None
    positions: Mapping[str, int] | None = None
    unlisted_entitlement_codes: frozenset[str] | None = None
    active_order_codes: frozenset[str] | None = None


@dataclass(frozen=True)
class CoreAccountSnapshot:
    """通过反馈校验后的非 Optional core 快照。"""

    snapshot_id: str
    sequence: int
    available_cash: float
    positions: Mapping[str, int]
    unlisted_entitlement_codes: frozenset[str]
    active_order_codes: frozenset[str]


@dataclass(frozen=True)
class Episode:
    episode_id: str
    code: str
    policy: Policy
    commitment: float
    investment_cap: float
    cumulative_cash_debit: float = 0.0
    exit_pending: bool = False
    exit_date: date | None = None
    status: EpisodeStatus = EpisodeStatus.ACTIVE


@dataclass(frozen=True)
class RegistrySnapshot:
    active_slots: int
    available_cash: float
    active_codes: frozenset[str]
    active_commitments: float
    core_snapshot_id: str | None
    last_fill_id: str | None
    last_order_id: str | None
    core_snapshot_sequence: int | None


def budget_per_episode(initial_cash: float) -> float:
    if (isinstance(initial_cash, bool) or not isinstance(initial_cash, (int, float))
            or not isfinite(initial_cash) or initial_cash <= 0):
        raise AllocationError("初始现金必须为有限正数")
    return float(initial_cash) / 5


class AllocationRegistry:
    """五槽承诺表；不推算现金、股数或成交费用。"""

    def __init__(self, *, initial_cash: float, calendar_days: list[date]):
        self.tranche_budget = budget_per_episode(initial_cash)
        if not calendar_days or calendar_days != sorted(set(calendar_days)):
            raise AllocationError("calendar 必须显式且严格递增")
        self.calendar_days = tuple(calendar_days)
        self.current_day = calendar_days[0]
        self._available_cash = float(initial_cash)
        self._episodes: dict[str, Episode] = {}
        self._seen_fills: dict[str, ExecutionFeedback] = {}
        self._seen_snapshots: dict[str, tuple[object, ...]] = {}
        self._positions: Mapping[str, int] = MappingProxyType({})
        self._entitlements: frozenset[str] = frozenset()
        self._active_orders: frozenset[str] = frozenset()
        self._core_snapshot_id: str | None = None
        self._last_fill_id: str | None = None
        self._last_order_id: str | None = None
        self._snapshot_sequence: int | None = None

    @property
    def available_cash(self) -> float:
        return self._available_cash

    @property
    def free_cash(self) -> float:
        return self._available_cash - self.active_commitments

    @property
    def active_commitments(self) -> float:
        return sum(item.commitment for item in self._episodes.values())

    @property
    def episodes(self) -> Mapping[str, Episode]:
        return MappingProxyType(dict(self._episodes))

    @property
    def active_codes(self) -> frozenset[str]:
        return frozenset(
            {code for code, shares in self._positions.items() if shares > 0}
            | self._entitlements | self._active_orders
        )

    @property
    def positions(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._positions))

    @property
    def fill_ledger(self) -> Mapping[str, ExecutionFeedback]:
        return MappingProxyType(dict(self._seen_fills))

    @property
    def held_instruments(self) -> frozenset[str]:
        return self.active_codes

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            len(self._episodes), self._available_cash, self.active_codes,
            self.active_commitments, self._core_snapshot_id, self._last_fill_id,
            self._last_order_id, self._snapshot_sequence,
        )

    def open_episode(self, episode_id: str, code: str, policy: Policy = Policy.B1) -> Episode:
        if not episode_id or episode_id in self._episodes:
            raise AllocationError("episode_id 必须唯一且非空")
        if any(e.code == code and e.status is not EpisodeStatus.CLOSED
               for e in self._episodes.values()):
            raise AllocationError("同代码旧 episode 尚未由 core 快照清除")
        if not code or code in self.active_codes:
            raise AllocationError("代码已有持仓、权益或活动订单")
        if len(self._episodes) >= 5:
            raise AllocationError("五个预算槽已占满")
        if self.free_cash < self.tranche_budget:
            raise AllocationError("free_cash 不足一个完整 C/5")
        if any(e.exit_pending for e in self._episodes.values()):
            raise AllocationError("存在未由 core 快照解除的 exit pending")
        selected_policy = Policy(policy)
        cap = self.tranche_budget * (0.7 if selected_policy is Policy.C70 else 1.0)
        episode = Episode(episode_id, code, selected_policy, self.tranche_budget, cap)
        self._episodes[episode_id] = episode
        return episode

    def mark_exit_pending(self, episode_id: str, requested_day: date) -> None:
        if requested_day not in self.calendar_days:
            raise AllocationError("退出日期不在显式 calendar 中")
        episode = self._episodes[episode_id]
        self._episodes[episode_id] = replace(
            episode, exit_pending=True, exit_date=requested_day
        )

    def advance(self, day: date) -> None:
        if day not in self.calendar_days or day < self.current_day:
            raise AllocationError("advance 日期必须来自 calendar 且不得倒退")
        self.current_day = day

    def cancel_episode(self, episode_id: str) -> None:
        # 取消只记录流程状态，预算承诺和 slot 保留至周期结束。
        episode = self._episodes[episode_id]
        self._episodes[episode_id] = replace(episode, status=EpisodeStatus.CANCELLED)

    def _validate_feedback(self, feedback: ExecutionFeedback) -> None:
        if (not isinstance(feedback.episode_id, str) or not feedback.episode_id
                or not isinstance(feedback.order_id, str) or not feedback.order_id):
            raise AllocationError("episode_id/order_id 缺失，生产桥接不完整")
        if feedback.event not in ("fill", "cancel", "reject", "failed"):
            raise AllocationError("未知 feedback event")
        if feedback.side not in ("buy", "sell"):
            raise AllocationError("未知成交方向")
        if not isinstance(feedback.shares_delta, int) or isinstance(feedback.shares_delta, bool):
            raise AllocationError("shares_delta 必须为整数")
        if feedback.shares_delta < 0:
            raise AllocationError("shares_delta 不得为负")

        for label, value in (
            ("amount", feedback.amount), ("fees", feedback.fees),
            ("cash_debit", feedback.cash_debit),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
                raise AllocationError(f"{label} 必须为有限非负数")
        if feedback.available_cash is not None and (
            isinstance(feedback.available_cash, bool)
            or not isinstance(feedback.available_cash, (int, float))
            or not isfinite(feedback.available_cash)
            or feedback.available_cash < 0
        ):
            raise AllocationError("available_cash 必须为有限非负数")
        if feedback.event != "fill":
            return
        if not isinstance(feedback.fill_id, str) or not feedback.fill_id:
            raise AllocationError("fill_id 缺失")
        if (isinstance(feedback.available_cash, bool)
                or not isinstance(feedback.available_cash, (int, float))
                or not isfinite(feedback.available_cash)):
            raise AllocationError("available_cash 必须为有限非负数")
        if feedback.available_cash < 0:
            raise AllocationError("available_cash 不得为负")
        if not isinstance(feedback.core_snapshot_id, str) or not feedback.core_snapshot_id:
            raise AllocationError("成交后 core_snapshot_id 缺失")
        sequence = feedback.core_snapshot_sequence
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise AllocationError("core_snapshot_sequence 必须为非负整数")
        if feedback.positions is None or feedback.unlisted_entitlement_codes is None:
            raise AllocationError("fill 必须携带 core positions 与权益快照")
        if feedback.active_order_codes is None:
            raise AllocationError("fill 必须携带活动订单代码快照")
        if not isinstance(feedback.positions, Mapping):
            raise AllocationError("positions 必须为 mapping")
        for code, shares in feedback.positions.items():
            if (not isinstance(code, str) or not code or not isinstance(shares, int)
                    or isinstance(shares, bool) or shares < 0):
                raise AllocationError("positions 必须是代码到非负整数股数的快照")
        if not isinstance(feedback.unlisted_entitlement_codes, (set, frozenset)):
            raise AllocationError("权益代码快照必须为 set")
        if not isinstance(feedback.active_order_codes, (set, frozenset)):
            raise AllocationError("活动订单代码快照必须为 set")
        if any(not isinstance(code, str) or not code
               for code in feedback.unlisted_entitlement_codes | feedback.active_order_codes):
            raise AllocationError("权益/活动订单代码不得为空")
        if feedback.side == "buy" and feedback.cash_debit != feedback.amount + feedback.fees:
            raise AllocationError("buy cash_debit 必须等于成交额加真实费用")

    def apply_feedback(self, feedback: ExecutionFeedback) -> bool:
        self._validate_feedback(feedback)
        if feedback.event != "fill":
            return False
        if feedback.episode_id not in self._episodes:
            raise AllocationError("feedback episode 不存在")
        fill_id = feedback.fill_id
        order_id = feedback.order_id
        snapshot_id = feedback.core_snapshot_id
        sequence = feedback.core_snapshot_sequence
        available_cash = feedback.available_cash
        positions = feedback.positions
        entitlements = feedback.unlisted_entitlement_codes
        active_orders = feedback.active_order_codes
        assert fill_id is not None
        assert order_id is not None
        assert snapshot_id is not None
        assert sequence is not None
        assert available_cash is not None
        assert positions is not None
        assert entitlements is not None
        assert active_orders is not None
        snapshot = CoreAccountSnapshot(
            snapshot_id, sequence, available_cash, positions,
            frozenset(entitlements), frozenset(active_orders),
        )
        feedback = replace(
            feedback,
            positions=MappingProxyType(dict(snapshot.positions)),
            unlisted_entitlement_codes=snapshot.unlisted_entitlement_codes,
            active_order_codes=snapshot.active_order_codes,
        )
        if fill_id in self._seen_fills:
            previous = self._seen_fills[fill_id]
            if previous != feedback:
                raise AllocationError("fill_id 已用于不同成交内容")
            return False
        episode = self._episodes[feedback.episode_id]
        if episode.status is EpisodeStatus.CLOSED:
            raise AllocationError("CLOSED episode 收到新 fill，必须对账")
        if episode.status is EpisodeStatus.CANCELLED and feedback.side == "buy":
            raise AllocationError("CANCELLED episode 禁止新买入")
        if feedback.side == "sell":
            held = self._positions.get(episode.code, 0)
            if feedback.shares_delta <= 0 or feedback.shares_delta > held:
                raise AllocationError("卖出 fill 与当前 core 持仓不一致")
        if feedback.side == "buy":
            total = episode.cumulative_cash_debit + feedback.cash_debit
            if total > episode.investment_cap:
                label = "C70" if episode.policy is Policy.C70 else "episode"
                raise AllocationError(f"{label} 累计现金借记超过投资上限")
            if feedback.cash_debit > episode.commitment:
                raise AllocationError("真实现金借记超过 episode 未投入承诺")
        payload = self._snapshot_payload(snapshot)
        if snapshot.snapshot_id in self._seen_snapshots:
            previous = self._seen_snapshots[snapshot.snapshot_id]
            if previous != payload:
                raise AllocationError("core_snapshot_id 重用且内容不一致")
            raise AllocationError("core_snapshot_id 必须唯一")
        if (self._snapshot_sequence is not None
                and snapshot.sequence <= self._snapshot_sequence):
            raise AllocationError("core snapshot sequence 陈旧或未递进")
        self._seen_fills[fill_id] = feedback
        self._seen_snapshots[snapshot.snapshot_id] = payload
        episode = replace(
            episode,
            commitment=episode.commitment - feedback.cash_debit
            if feedback.side == "buy" else episode.commitment,
            cumulative_cash_debit=episode.cumulative_cash_debit
            + (feedback.cash_debit if feedback.side == "buy" else 0.0),
        )
        self._episodes[episode.episode_id] = episode
        self._available_cash = float(snapshot.available_cash)
        self._core_snapshot_id = snapshot.snapshot_id
        self._last_fill_id = fill_id
        self._last_order_id = order_id
        self._snapshot_sequence = snapshot.sequence
        self._positions = MappingProxyType(dict(snapshot.positions))
        self._entitlements = snapshot.unlisted_entitlement_codes
        self._active_orders = snapshot.active_order_codes
        self._sync_exit_state()
        return True

    @staticmethod
    def _snapshot_payload(snapshot: CoreAccountSnapshot) -> tuple[object, ...]:
        return (
            snapshot.sequence,
            snapshot.available_cash,
            tuple(sorted(snapshot.positions.items())),
            tuple(sorted(snapshot.unlisted_entitlement_codes)),
            tuple(sorted(snapshot.active_order_codes)),
        )

    def _sync_exit_state(self) -> None:
        active = self.active_codes
        for episode_id, episode in tuple(self._episodes.items()):
            should_close = episode.exit_pending or episode.status is EpisodeStatus.CANCELLED
            if should_close and episode.code not in active:
                self._episodes[episode_id] = replace(
                    episode, exit_pending=False, exit_date=None,
                    status=EpisodeStatus.CLOSED,
                )


StagedAllocationRegistry = AllocationRegistry
