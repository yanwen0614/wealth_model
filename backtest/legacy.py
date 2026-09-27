"""N01 旧逻辑隔离中枢：OLD_LOGIC 标记 + 显式禁跑守卫 + 历史结果 legacy 标记。

为什么做：阶段 3 直接切换要求旧引擎默认不可达（沿 quant Q01 模式）；
历史结果只加标记不删除，报告层可据此拒绝新旧口径静默混合。
"""

import os

__all__ = [
    "LEGACY_ENGINE_NAME",
    "LEGACY_SCHEMA_VERSION",
    "LegacyBacktestDisabledError",
    "guard_legacy_disabled",
    "mark_legacy_result",
]

# 旧引擎身份：写入历史结果的 engine/口径字段，新结果禁止使用该值
LEGACY_ENGINE_NAME = "legacy_backtest_engine"
LEGACY_SCHEMA_VERSION = "legacy_schema_v0"
# 显式 opt-in 通道：默认关闭，旧逻辑回归出口一律走守卫拒绝
_LEGACY_OPT_IN_ENV = "CNN_ALLOW_LEGACY"


class LegacyBacktestDisabledError(RuntimeError):
    """旧回测逻辑已被入口切换禁用后仍被调用时抛出。"""


def guard_legacy_disabled(caller: str) -> None:
    """旧逻辑入口守卫：无显式 opt-in 时一律拒绝，防回归出口静默执行旧逻辑。"""
    if os.environ.get(_LEGACY_OPT_IN_ENV) == "1":
        return
    raise LegacyBacktestDisabledError(
        f"legacy backtest logic is disabled (caller={caller}); "
        f"set {_LEGACY_OPT_IN_ENV}=1 to opt in explicitly"
    )


def mark_legacy_result(result: dict) -> dict:
    """历史结果加 legacy 标记：不删除旧数据，只追加可区分字段。"""
    if not isinstance(result, dict):
        raise ValueError(f"result must be a dict, got {result!r}")  # noqa: TRY004
    marked = dict(result)
    marked["legacy"] = True
    marked.setdefault("engine", LEGACY_ENGINE_NAME)
    marked.setdefault("legacy_schema_version", LEGACY_SCHEMA_VERSION)
    return marked
