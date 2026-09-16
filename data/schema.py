"""训练 parquet 的列 schema 与默认特征选择。"""

import warnings

EXPORT_FACTORS = [
    "return_1d", "return_5d", "return_10d", "return_20d",
    "volatility_5d", "volatility_10d", "volatility_20d",
    "amihud", "volume_ratio_5d", "volume_ratio_10d",
    "ma_5", "ma_10", "ma_20", "ma_60",
    "ema_12", "ema_26", "macd", "dmi", "adx", "sar",
    "boll", "atr", "kelch", "std_5", "std_10", "std_20",
    "trend_duokong", "trend_shortline", "trend_duokong_dev",
    "pe", "pb", "pcf", "ps",
    "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
    "gross_margin", "net_margin", "roe", "roa", "debt_to_equity",
    "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio",
    "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
]

BASE_COLUMNS = [
    "code", "kline_time", "open", "high", "low", "close", "volume", "amount",
    "TOT_SHARE", "is_trading",
]

APPROVED_RAW_FEATURES = [
    "open", "high", "low", "ma_5", "ma_10", "ma_20", "ma_60", "ema_12", "ema_26", "sar",
    "trend_duokong", "trend_shortline",
    "volatility_5d", "volatility_10d", "volatility_20d", "std_5", "std_10", "std_20", "atr",
    "volume_ratio_5d", "volume_ratio_10d", "amihud",
    "macd", "dmi", "adx", "boll", "kelch", "trend_duokong_dev",
    "gross_margin", "net_margin", "roe", "roa", "debt_to_equity",
    "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio", "margin_balance_chg_5d",
    "short_balance_ratio", "short_sell_vol_ratio",
    "margin_balance_ratio_raw", "margin_buy_ratio_raw", "margin_net_buy_ratio_raw",
    "margin_balance_chg_5d_raw", "short_balance_ratio_raw", "short_sell_vol_ratio_raw",
    "margin_balance_ratio_ts", "margin_buy_ratio_ts", "margin_net_buy_ratio_ts",
    "margin_balance_chg_5d_ts", "short_balance_ratio_ts", "short_sell_vol_ratio_ts",
]

G9_RAW_FEATURES = (
    "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio",
    "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
    "margin_balance_ratio_raw", "margin_buy_ratio_raw", "margin_net_buy_ratio_raw",
    "margin_balance_chg_5d_raw", "short_balance_ratio_raw", "short_sell_vol_ratio_raw",
    "margin_balance_ratio_ts", "margin_buy_ratio_ts", "margin_net_buy_ratio_ts",
    "margin_balance_chg_5d_ts", "short_balance_ratio_ts", "short_sell_vol_ratio_ts",
)
G9_MASK_COLUMNS = tuple(f"{column}_mask" for column in G9_RAW_FEATURES)

PROHIBITED_COLUMNS = {
    "code", "kline_time", "is_trading", "return_1d", "return_5d", "return_10d", "return_20d",
    "TOT_SHARE", "volume", "amount", "close", "pe", "pb", "pcf", "ps",
    "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
}

PREDICTION_CACHE_KEYS = ("exp_ret", "true_ret", "dates", "codes")


def validate_prediction_cache_keys(keys, source: str = "预测缓存") -> None:
    """校验回测/绘图共用的逐样本预测缓存 schema。"""
    missing = [key for key in PREDICTION_CACHE_KEYS if key not in keys]
    if missing:
        raise ValueError(
            f"{source} 缺少必需键 {missing}；旧缓存缺少 codes，请用新版 eval_bins_mapping.py 重建"
        )


def validate_prediction_cache_arrays(arrays: dict, source: str = "预测缓存") -> None:
    """校验预测缓存四个字段存在且逐样本长度一致。"""
    validate_prediction_cache_keys(arrays.keys(), source)
    lengths = {key: len(arrays[key]) for key in PREDICTION_CACHE_KEYS}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{source} 字段长度不一致: {lengths}")


def _default_feature_cols(all_columns: list[str]) -> list[str]:
    """Return the approved ordered raw feature list, rejecting schema drift."""
    missing = [col for col in APPROVED_RAW_FEATURES if col not in all_columns]
    if missing:
        raise ValueError(f"批准特征列缺失于 parquet: {missing}")
    unknown = sorted(set(all_columns) - set(APPROVED_RAW_FEATURES) - PROHIBITED_COLUMNS)
    if unknown:
        warnings.warn(
            f"未知 parquet 列将被排除: {unknown}; 请更新 whitelist/blacklist 后再纳入训练。",
            UserWarning,
            stacklevel=2,
        )
    return list(APPROVED_RAW_FEATURES)
