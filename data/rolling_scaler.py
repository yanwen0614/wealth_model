"""Standalone causal rolling normalization for one sorted code sequence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from data.schema import G9_RAW_FEATURES

ROLLING_MODE = "rolling"
ROLLING_VERSION = "v1_rolling_252"
ROLLING_TRANSFORM_VERSION = "rolling_transform_v1"
ROLLING_HELPER_COLUMNS = ("close",)

ROLLING_PRICE_FEATURES = (
    "open",
    "high",
    "low",
    "ma_5",
    "ma_10",
    "ma_20",
    "ma_60",
    "ema_12",
    "ema_26",
)
ROLLING_VOLATILITY_FEATURES = (
    "volatility_5d",
    "volatility_10d",
    "volatility_20d",
)
ROLLING_VOLUME_FEATURES = (
    "volume_ratio_5d",
    "volume_ratio_10d",
    "amihud",
)
ROLLING_WINSOR_FEATURES = ("macd",) + ROLLING_VOLATILITY_FEATURES + ROLLING_VOLUME_FEATURES
ROLLING_FEATURES = ROLLING_PRICE_FEATURES + ROLLING_WINSOR_FEATURES


@dataclass(frozen=True)
class RollingNormalizationConfig:
    """Identity-bearing rolling parameters; current t is always included."""

    window: int = 252
    min_periods: int = 120
    include_current_t: bool = True
    lower_percentile: float = 1.0
    upper_percentile: float = 99.0
    robust_clip: float = 5.0
    add_g9_masks: bool = True

    def __post_init__(self) -> None:
        if self.window < 1 or not 1 <= self.min_periods <= self.window:
            raise ValueError("rolling window/min_periods 配置无效")
        if not self.include_current_t:
            raise ValueError("rolling kernel 只支持 include_current_t=True")
        if not 0 <= self.lower_percentile < self.upper_percentile <= 100:
            raise ValueError("rolling percentile 配置无效")


@dataclass
class RollingAudit:
    total_rows: int = 0
    rolling_values: int = 0
    fallback_values: int = 0
    neutral_fallback_values: int = 0
    passthrough_values: int = 0
    missing_values: int = 0
    constant_iqr_values: int = 0


@dataclass(frozen=True)
class RollingTransformResult:
    values: np.ndarray
    fallback_mask: np.ndarray
    audit: RollingAudit


class RollingNormalizer:
    """Transform arrays without fitting, persistence, parquet I/O, or labels."""

    def __init__(self, config: RollingNormalizationConfig | None = None):
        self.config = config or RollingNormalizationConfig()

    @staticmethod
    def _canonical_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def transform_config_digest(self) -> str:
        payload = {
            "mode": ROLLING_MODE,
            "version": ROLLING_TRANSFORM_VERSION,
            "config": asdict(self.config),
            "price_strategy": "relative_then_rolling_median_iqr_clip",
            "winsor_strategy": "rolling_percentile_clip",
            "rolling_price_features": ROLLING_PRICE_FEATURES,
            "rolling_winsor_features": ROLLING_WINSOR_FEATURES,
            "g9_strategy": "finite_fill_zero_clip_0_1_plus_observed_mask",
            "other_strategy": "finite_or_zero_passthrough_without_frozen_transform",
        }
        return self._canonical_hash(payload)

    def output_feature_cols(self, feature_cols: list[str]) -> list[str]:
        self._validate_feature_cols(feature_cols)
        masks = [f"{column}_mask" for column in feature_cols if column in G9_RAW_FEATURES]
        return list(feature_cols) + (masks if self.config.add_g9_masks else [])

    def schema_manifest(self, feature_cols: list[str]) -> dict[str, Any]:
        return {
            "mode": ROLLING_MODE,
            "version": ROLLING_VERSION,
            "window": self.config.window,
            "min_periods": self.config.min_periods,
            "include_current_t": self.config.include_current_t,
            "raw_feature_cols": list(feature_cols),
            "output_feature_cols": self.output_feature_cols(feature_cols),
            "helper_cols": list(ROLLING_HELPER_COLUMNS),
            "transform_digest": self.transform_config_digest(),
        }

    def identity_manifest(
        self, source_manifest: dict[str, Any], feature_cols: list[str]
    ) -> dict[str, Any]:
        return {
            "preprocessing": self.schema_manifest(feature_cols),
            "source": json.loads(json.dumps(source_manifest, sort_keys=True)),
        }

    def identity(self, source_manifest: dict[str, Any], feature_cols: list[str]) -> str:
        return self._canonical_hash(self.identity_manifest(source_manifest, feature_cols))

    @staticmethod
    def _validate_feature_cols(feature_cols: list[str]) -> None:
        if "close" in feature_cols:
            raise ValueError("close 只能作为 rolling helper，不能进入 output feature columns")
        if len(feature_cols) != len(set(feature_cols)):
            raise ValueError("rolling feature_cols 不能重复")

    def _validate_inputs(
        self,
        features: np.ndarray,
        feature_cols: list[str],
        close: np.ndarray,
        frozen_fallback: np.ndarray | None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        self._validate_feature_cols(feature_cols)
        values = np.asarray(features, dtype=np.float64)
        helper = np.asarray(close, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(feature_cols):
            raise ValueError("features 必须是与 feature_cols 对齐的 [N,F] 数组")
        if helper.ndim != 1 or helper.shape[0] != values.shape[0]:
            raise ValueError("close helper 必须是长度 N 的一维数组")
        fallback = None if frozen_fallback is None else np.asarray(frozen_fallback, dtype=np.float64)
        valid_fallback_shapes = {
            values.shape,
            (values.shape[0], len(self.output_feature_cols(feature_cols))),
        }
        if fallback is not None and fallback.shape not in valid_fallback_shapes:
            raise ValueError("frozen_fallback 必须匹配 raw 或带 G9 masks 的 output 形状")
        if fallback is not None:
            fallback = fallback[:, : values.shape[1]]
        return values, helper, fallback

    @staticmethod
    def _relative(values: np.ndarray, close: np.ndarray) -> np.ndarray:
        previous_close = np.roll(close, 1)
        previous_close[0] = np.nan
        valid_denominator = np.isfinite(previous_close) & (previous_close != 0)
        return np.divide(
            values,
            previous_close,
            out=np.full(values.shape, np.nan, dtype=np.float64),
            where=valid_denominator,
        ) - 1.0

    def transform_code(
        self,
        features: np.ndarray,
        feature_cols: list[str],
        close: np.ndarray,
        frozen_fallback: np.ndarray | None = None,
    ) -> RollingTransformResult:
        """Transform one already sorted code sequence using only data through each t."""
        values, helper, fallback = self._validate_inputs(
            features, feature_cols, close, frozen_fallback
        )
        row_count = values.shape[0]
        output_columns: list[np.ndarray] = []
        masks: list[np.ndarray] = []
        output_count = len(self.output_feature_cols(feature_cols))
        fallback_mask = np.zeros((row_count, output_count), dtype=bool)
        audit = RollingAudit(total_rows=row_count)

        for column_index, column in enumerate(feature_cols):
            raw = values[:, column_index]
            audit.missing_values += int((~np.isfinite(raw)).sum())
            if column in ROLLING_FEATURES:
                prepared = self._relative(raw, helper) if (
                    column in ROLLING_PRICE_FEATURES or column == "macd"
                ) else raw.copy()
                transformed = self._rolling_column(
                    prepared,
                    column in ROLLING_PRICE_FEATURES,
                    None if fallback is None else fallback[:, column_index],
                    fallback_mask[:, column_index],
                    audit,
                )
                output_columns.append(transformed)
                continue

            audit.passthrough_values += row_count
            finite = np.isfinite(raw)
            if column in G9_RAW_FEATURES:
                output_columns.append(np.clip(np.where(finite, raw, 0.0), 0.0, 1.0))
                if self.config.add_g9_masks:
                    masks.append(finite.astype(np.float64))
            else:
                output_columns.append(np.where(finite, raw, 0.0))

        output = np.stack(output_columns + masks, axis=1)
        output = np.where(np.isfinite(output), output, 0.0).astype(np.float32)
        return RollingTransformResult(output, fallback_mask, audit)

    def _rolling_column(
        self,
        values: np.ndarray,
        robust: bool,
        fallback: np.ndarray | None,
        fallback_mask: np.ndarray,
        audit: RollingAudit,
    ) -> np.ndarray:
        output = np.zeros(values.shape, dtype=np.float64)
        for current in range(len(values)):
            start = max(0, current - self.config.window + 1)
            window = values[start : current + 1]
            valid = window[np.isfinite(window)]
            if valid.size < self.config.min_periods:
                fallback_mask[current] = True
                audit.fallback_values += 1
                if fallback is not None and np.isfinite(fallback[current]):
                    output[current] = fallback[current]
                else:
                    audit.neutral_fallback_values += 1
                continue
            if not np.isfinite(values[current]):
                continue
            if robust:
                median = float(np.median(valid))
                q25, q75 = np.percentile(valid, [25, 75])
                iqr = float(q75 - q25)
                if iqr <= np.finfo(np.float64).eps:
                    scale = 1.0
                    audit.constant_iqr_values += 1
                else:
                    scale = iqr / 1.349
                output[current] = np.clip(
                    (values[current] - median) / scale,
                    -self.config.robust_clip,
                    self.config.robust_clip,
                )
            else:
                lower, upper = np.percentile(
                    valid, [self.config.lower_percentile, self.config.upper_percentile]
                )
                output[current] = np.clip(values[current], lower, upper)
            audit.rolling_values += 1
        return output
