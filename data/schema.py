"""训练 parquet 的列 schema 与默认特征选择。"""

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


def _default_feature_cols(all_columns: list[str], use_factor_only: bool = False) -> list[str]:
    """自动推导默认原始特征列，默认链路经 mask 后输出 F=45。"""
    if use_factor_only:
        return [c for c in EXPORT_FACTORS if c in all_columns]
    exclude = {
        "code", "kline_time", "is_trading",
        "return_1d", "return_5d", "return_10d", "return_20d",
        "TOT_SHARE", "volume", "amount", "close",
        "pe", "pb", "pcf", "ps",
        "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
    }
    return [c for c in all_columns if c not in exclude]
