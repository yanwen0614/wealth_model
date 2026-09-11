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

__all__ = [
    "AMOUNT_UNIT",
    "OHLC_PATH_KEYS",
    "SHANGHAI_TZ",
    "SIGNAL_HOUR",
    "VOLUME_UNIT",
    "CnnMarketDataProvider",
    "MarketDataCounters",
    "cache_fingerprint",
    "load_prediction_cache",
    "npz_fingerprint",
    "require_keys",
    "save_prediction_cache",
    "signal_time_for",
    "validate_ohlc_path_arrays",
]
