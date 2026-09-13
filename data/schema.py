"""训练 parquet 的列 schema、特征分组与默认特征选择。"""

import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

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

# 分组注册表：组名 -> 有序特征列名（顺序即输出列序契约）。
FEATURE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "P": (
        "open", "high", "low", "close", "ma_5", "ma_10", "ma_20", "ma_60",
        "ema_12", "ema_26", "sar", "trend_duokong", "trend_shortline", "macd",
        "std_5", "std_10", "std_20", "atr",
    ),
    "R": (
        "dmi", "adx", "boll", "kelch", "trend_duokong_dev",
        "volatility_5d", "volatility_10d", "volatility_20d",
        "volume_ratio_5d", "volume_ratio_10d",
        "gross_margin", "net_margin", "roe", "roa", "debt_to_equity", "amihud",
    ),
    "N": (
        "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio",
        "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
        "margin_balance_ratio_ts", "margin_buy_ratio_ts", "margin_net_buy_ratio_ts",
        "margin_balance_chg_5d_ts", "short_balance_ratio_ts", "short_sell_vol_ratio_ts",
    ),
    "G": (
        "margin_balance_ratio_raw", "margin_buy_ratio_raw", "margin_net_buy_ratio_raw",
        "margin_balance_chg_5d_raw", "short_balance_ratio_raw", "short_sell_vol_ratio_raw",
    ),
}

# 52 列 = P(18) + R(16) + N(12) + G(6)，顺序即 feature 输出顺序。
APPROVED_RAW_FEATURES: tuple[str, ...] = tuple(
    column for columns in FEATURE_GROUPS.values() for column in columns
)

G9_RAW_FEATURES = (
    "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio",
    "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
    "margin_balance_ratio_raw", "margin_buy_ratio_raw", "margin_net_buy_ratio_raw",
    "margin_balance_chg_5d_raw", "short_balance_ratio_raw", "short_sell_vol_ratio_raw",
    "margin_balance_ratio_ts", "margin_buy_ratio_ts", "margin_net_buy_ratio_ts",
    "margin_balance_chg_5d_ts", "short_balance_ratio_ts", "short_sell_vol_ratio_ts",
)
G9_OBSERVATION_SOURCE = G9_RAW_FEATURES
G9_MASK_COLUMNS = ("g9_observed_mask",)

NORMALIZE_MODES = frozenset({"relative", "per_code", "rolling", "none"})

PROHIBITED_COLUMNS = {
    "code", "kline_time", "is_trading", "return_1d", "return_5d", "return_10d", "return_20d",
    "TOT_SHARE", "volume", "amount", "pe", "pb", "pcf", "ps",
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


_COLUMN_TO_GROUP: Mapping[str, str] = {
    column: group for group, columns in FEATURE_GROUPS.items() for column in columns
}


def column_group(column: str) -> str:
    """返回列所属组名（"P"/"R"/"N"/"G"），未知列报错而非静默透传。"""
    try:
        return _COLUMN_TO_GROUP[column]
    except KeyError:
        raise ValueError(f"未知特征列: {column!r}，无法确定其分组") from None


def default_feature_cols(normalize: str) -> list[str]:
    """返回指定归一化模式下的默认特征列（与 FEATURE_GROUPS 顺序一致）。"""
    if normalize not in NORMALIZE_MODES:
        raise ValueError(f"未知归一化模式: {normalize!r}，可选 {sorted(NORMALIZE_MODES)}")
    return list(APPROVED_RAW_FEATURES)


def g9_observed_mask(frame: "pd.DataFrame") -> "np.ndarray":
    """对 G9_OBSERVATION_SOURCE 各列取 finite 后逐行 OR，返回 float32 [N] ∈ {0,1}。"""
    missing = [column for column in G9_OBSERVATION_SOURCE if column not in frame.columns]
    if missing:
        raise ValueError(f"G9 观测列缺失: {missing}")
    observed = np.zeros(len(frame), dtype=bool)
    for column in G9_OBSERVATION_SOURCE:
        observed |= np.isfinite(np.asarray(frame[column], dtype=np.float64))
    return observed.astype(np.float32)
