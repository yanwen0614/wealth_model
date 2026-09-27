"""cnn backtest adapter 包：预测缓存/指纹/信号时间共享工具（B02–B04 消费）。"""
from backtest.cnn_adapter.cache import (
    OHLC_PATH_KEYS,
    cache_fingerprint,
    load_prediction_cache,
    save_prediction_cache,
    validate_ohlc_path_arrays,
)
from backtest.cnn_adapter.common import SHANGHAI_TZ, SIGNAL_HOUR, npz_fingerprint, require_keys, signal_time_for
from backtest.cnn_adapter.market import AMOUNT_UNIT, VOLUME_UNIT, CnnMarketDataProvider, MarketDataCounters
from backtest.cnn_adapter.order_strategy import DEFAULT_TOP_N, CnnOrderCounters, CnnOrderStrategy
from backtest.cnn_adapter.predictions import (
    LABEL_FORMULA,
    PREDICTED_HORIZON,
    CnnPredictionAdapter,
    PredictionCounters,
)
from backtest.cnn_adapter.runner import ORDER_ENTRY, CnnBacktestOutcome, run_cnn_backtest, write_cnn_result

__all__ = [
    "AMOUNT_UNIT",
    "DEFAULT_TOP_N",
    "LABEL_FORMULA",
    "OHLC_PATH_KEYS",
    "ORDER_ENTRY",
    "PREDICTED_HORIZON",
    "SHANGHAI_TZ",
    "SIGNAL_HOUR",
    "VOLUME_UNIT",
    "CnnBacktestOutcome",
    "CnnMarketDataProvider",
    "CnnOrderCounters",
    "CnnOrderStrategy",
    "CnnPredictionAdapter",
    "MarketDataCounters",
    "PredictionCounters",
    "cache_fingerprint",
    "load_prediction_cache",
    "npz_fingerprint",
    "require_keys",
    "run_cnn_backtest",
    "save_prediction_cache",
    "signal_time_for",
    "validate_ohlc_path_arrays",
    "write_cnn_result",
]
