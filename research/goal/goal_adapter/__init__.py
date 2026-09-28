"""goal backtest adapter：backtest-core 适配层（goal 原生实现）.

导入约定：本包为仓库根目录包，无 packaging（不建 pyproject）；
以仓库根为 cwd 或 `PYTHONPATH=.` 导入。
"""

from goal_adapter.common import (
    BSE_PCT,
    MAIN_BOARD_PCT,
    SHANGHAI_TZ,
    SIGNAL_HOUR,
    ST_PCT,
    STAR_CHINEXT_PCT,
    default_limit_pct,
    fingerprint_mapping,
    limit_price,
    require_keys,
    signal_time_for,
)
from goal_adapter.daily_policy import (
    DEFAULT_MIN_AMOUNT_YUAN as DAILY_DEFAULT_MIN_AMOUNT_YUAN,
)
from goal_adapter.daily_policy import (
    DEFAULT_SELL_BUFFER as DAILY_DEFAULT_SELL_BUFFER,
)
from goal_adapter.daily_policy import (
    DEFAULT_TOP_N as DAILY_DEFAULT_TOP_N,
)
from goal_adapter.daily_policy import (
    DailyOrderCounters,
    DailyOrderStrategy,
)
from goal_adapter.joint_policy import (
    DEFAULT_MIN_AMOUNT_YUAN as JOINT_DEFAULT_MIN_AMOUNT_YUAN,
)
from goal_adapter.joint_policy import (
    DEFAULT_SELL_BUFFER as JOINT_DEFAULT_SELL_BUFFER,
)
from goal_adapter.joint_policy import (
    DEFAULT_TOP_N as JOINT_DEFAULT_TOP_N,
)
from goal_adapter.joint_policy import (
    JointOrderCounters,
    JointOrderStrategy,
)
from goal_adapter.market import (
    AMOUNT_UNIT,
    VOLUME_UNIT,
    GoalMarketDataProvider,
    MarketDataCounters,
)
from goal_adapter.predictions import (
    ACTUALS_LABEL_FORMULA,
    PREDICTED_HORIZON,
    SCORE_COL_RAW,
    SCORE_LABEL_FORMULA,
    SCORE_TRADE_FORMULA,
    SCORE_TRADE_SIGN,
    GoalPredictionAdapter,
    PredictionCounters,
)

__all__ = [
    "ACTUALS_LABEL_FORMULA",
    "AMOUNT_UNIT",
    "BSE_PCT",
    "DAILY_DEFAULT_MIN_AMOUNT_YUAN",
    "DAILY_DEFAULT_SELL_BUFFER",
    "DAILY_DEFAULT_TOP_N",
    "JOINT_DEFAULT_MIN_AMOUNT_YUAN",
    "JOINT_DEFAULT_SELL_BUFFER",
    "JOINT_DEFAULT_TOP_N",
    "MAIN_BOARD_PCT",
    "PREDICTED_HORIZON",
    "SCORE_COL_RAW",
    "SCORE_LABEL_FORMULA",
    "SCORE_TRADE_FORMULA",
    "SCORE_TRADE_SIGN",
    "SHANGHAI_TZ",
    "SIGNAL_HOUR",
    "STAR_CHINEXT_PCT",
    "ST_PCT",
    "VOLUME_UNIT",
    "DailyOrderCounters",
    "DailyOrderStrategy",
    "GoalMarketDataProvider",
    "GoalPredictionAdapter",
    "JointOrderCounters",
    "JointOrderStrategy",
    "MarketDataCounters",
    "PredictionCounters",
    "default_limit_pct",
    "fingerprint_mapping",
    "limit_price",
    "require_keys",
    "signal_time_for",
]
