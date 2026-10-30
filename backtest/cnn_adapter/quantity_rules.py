"""显式来源支持的历史股票申报数量规则。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backtest_core.contracts import Side

_PLACEHOLDERS = frozenset({"", "unknown", "none", "null", "n/a", "na", "tbd", "placeholder"})


class QuantityRuleError(ValueError):
    """数量规则缺失、无效或申报数量不合规。"""


@dataclass(frozen=True)
class QuantityRule:
    minimum: int
    step: int
    maximum: int
    source_id: str
    effective_from: date
    effective_through: date

    def __post_init__(self) -> None:
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0
               for v in (self.minimum, self.step, self.maximum)):
            raise QuantityRuleError("minimum、step、maximum 必须为正整数")
        if (not isinstance(self.source_id, str) or self.minimum > self.maximum
                or not self.source_id.strip()):
            raise QuantityRuleError("数量范围或规则来源无效")
        if self.source_id.strip().casefold() in _PLACEHOLDERS:
            raise QuantityRuleError("规则来源不能使用占位值")
        if type(self.effective_from) is not date or type(self.effective_through) is not date:
            raise QuantityRuleError("规则生效区间必须显式提供日期")
        if self.effective_from > self.effective_through:
            raise QuantityRuleError("规则生效区间倒置")

    def validate(self, side: Side, shares: int, trading_date: date,
                 *, available_shares: int | None = None) -> None:
        if not isinstance(side, Side):
            raise QuantityRuleError("交易方向必须为 Side")
        if type(trading_date) is not date:
            raise QuantityRuleError("交易日期必须为 date")
        if not self.effective_from <= trading_date <= self.effective_through:
            raise QuantityRuleError("交易日期不在规则生效区间内")
        if isinstance(shares, bool) or not isinstance(shares, int) or shares <= 0:
            raise QuantityRuleError("申报数量必须为正整数")
        if shares > self.maximum:
            raise QuantityRuleError("申报数量超过单笔上限；策略不自动拆单")
        if side is Side.SELL and shares == available_shares:
            return
        if side is Side.SELL and shares < self.minimum:
            raise QuantityRuleError("不足最小申报量的卖出必须一次性卖出全部可用余额")
        if shares < self.minimum or (shares - self.minimum) % self.step:
            raise QuantityRuleError("申报数量不满足最小量或申报步长")


class MappingQuantityRuleResolver:
    """按显式日期区间和代码映射解析规则；未匹配时拒绝猜测。"""

    def __init__(self, rules: dict[str, tuple[date, date, QuantityRule]]):
        if not rules or any(not isinstance(code, str) or not code for code in rules):
            raise QuantityRuleError("规则映射必须包含非空代码前缀")
        for start, end, rule in rules.values():
            if (not isinstance(rule, QuantityRule) or type(start) is not date
                    or type(end) is not date or start > end
                    or start != rule.effective_from or end != rule.effective_through):
                raise QuantityRuleError("解析器区间必须与来源规则生效区间一致")
        self._rules = dict(rules)

    def __call__(self, trading_date: date, code: str) -> QuantityRule:
        if type(trading_date) is not date or not isinstance(code, str) or not code:
            raise QuantityRuleError("规则查询必须提供有效日期和代码")
        matches = [rule for prefix, (start, end, rule) in self._rules.items()
                   if code.startswith(prefix) and start <= trading_date <= end]
        if len(matches) != 1:
            raise QuantityRuleError("代码或日期未唯一匹配数量规则")
        return matches[0]
