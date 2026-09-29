"""回测包门面：生产唯一入口 backtest.cnn_adapter + backtest-core.

生产路径一律走 ``backtest.cnn_adapter``（订单引擎，底层为外部
``backtest_core`` 包，本地 editable 依赖 ``../backtest-core``）；
费用/基准/topn 口径见 docs/per_code_normalization_spec.md 5.2，本文件只改导出、不动口径。

向后兼容说明：旧 ``backtest.engine`` 符号（run_backtest/run_backtest_target/
commission/nav_metrics/费率常量等）已不再经包根重导出；历史代码须显式
``from backtest.engine import ...``（冻结 OLD_LOGIC，需 CNN_ALLOW_LEGACY=1 opt-in，
见 backtest.legacy.guard_legacy_disabled），包根导入旧符号将直接 ImportError。
"""

import backtest_core as backtest_core

from backtest import cnn_adapter as cnn_adapter
from backtest import legacy as legacy
from backtest.cnn_adapter import CnnBacktestOutcome, run_cnn_backtest, write_cnn_result
from backtest.legacy import LegacyBacktestDisabledError, guard_legacy_disabled

__all__ = [
    "CnnBacktestOutcome",
    "LegacyBacktestDisabledError",
    "backtest_core",
    "cnn_adapter",
    "guard_legacy_disabled",
    "legacy",
    "run_cnn_backtest",
    "write_cnn_result",
]
