"""按实际成交日解析沪深 A 股费用；佣金是调用者提供的券商假设。"""

from datetime import date, datetime

from backtest_core.contracts.config import CostConfig
from backtest_core.contracts.enums import Side
from backtest_core.policies.cost import AShareCostModel


def resolve_historical_costs(*, execution_date: date, market: str,
                             commission: CostConfig) -> CostConfig:
    """替换历史印花税和过户费，保留佣金及其余执行配置。"""
    if isinstance(execution_date, datetime) or not isinstance(execution_date, date):
        raise ValueError(f"execution_date must be a date, got {execution_date!r}")  # noqa: TRY004
    if execution_date < date(2021, 1, 1):
        raise ValueError(f"execution_date before supported history: {execution_date!r}")
    if market not in ("SSE_A", "SZSE_A"):
        raise ValueError(f"market must be SSE_A or SZSE_A, got {market!r}")
    if not isinstance(commission, CostConfig):
        raise ValueError(f"commission must be CostConfig, got {commission!r}")  # noqa: TRY004
    values = commission.model_dump()
    values.update({
        "stamp_tax_rate": 0.0005 if execution_date >= date(2023, 8, 28) else 0.001,
        "transfer_fee_rate": 0.00001 if execution_date >= date(2022, 4, 29) else 0.00002,
    })
    return CostConfig(**values)


def calculate_historical_costs(*, execution_date: date, market: str, side: Side,
                               amount: float, commission: CostConfig) -> tuple[float, float, float]:
    """通过 core 的 AShareCostModel 计算费用，不在 adapter 复制公式。"""
    resolved = resolve_historical_costs(execution_date=execution_date, market=market,
                                        commission=commission)
    return AShareCostModel(resolved).calculate(side, amount)
