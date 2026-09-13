"""Standalone causal rolling normalization for one sorted code sequence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from data.scaler import IQR_TO_SIGMA, ColumnRule, column_rule
from data.schema import FEATURE_GROUPS, G9_MASK_COLUMNS, G9_OBSERVATION_SOURCE

ROLLING_MODE = "rolling"
ROLLING_VERSION = "v2_rolling_scope_e0_e5"
ROLLING_TRANSFORM_VERSION = "rolling_transform_v2"
ROLLING_HELPER_COLUMNS = ("close",)
EPS = 1e-8

# scope 预设由 FEATURE_GROUPS 派生，避免重复列清单；顺序即输出列序契约。
ROLLING_PRICE_FEATURES = tuple(FEATURE_GROUPS["P"])
ROLLING_VOLATILITY_FEATURES = ("volatility_5d", "volatility_10d", "volatility_20d")
ROLLING_VOLUME_FEATURES = ("volume_ratio_5d", "volume_ratio_10d", "amihud")
ROLLING_WINSOR_FEATURES = ROLLING_VOLATILITY_FEATURES + ROLLING_VOLUME_FEATURES
ROLLING_FEATURES = ROLLING_PRICE_FEATURES + ROLLING_WINSOR_FEATURES
ROLLING_SCOPE_FEATURES: dict[str, tuple[str, ...]] = {
    "e0": (),
    "e1": ROLLING_PRICE_FEATURES,
    "e2": ROLLING_PRICE_FEATURES,
    "e3": ROLLING_PRICE_FEATURES + ROLLING_VOLATILITY_FEATURES,
    "e4": ROLLING_FEATURES,
    "e5": ROLLING_FEATURES + tuple(FEATURE_GROUPS["G"]),
}
ROLLING_SCOPES = tuple(ROLLING_SCOPE_FEATURES)
_G9_OBSERVATION_SOURCE_SET = frozenset(G9_OBSERVATION_SOURCE)


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
    scope: str = "e5"

    def __post_init__(self) -> None:
        if self.window < 1 or not 1 <= self.min_periods <= self.window:
            raise ValueError("rolling window/min_periods 配置无效")
        if not self.include_current_t:
            raise ValueError("rolling kernel 只支持 include_current_t=True")
        if not 0 <= self.lower_percentile < self.upper_percentile <= 100:
            raise ValueError("rolling percentile 配置无效")
        if self.scope not in ROLLING_SCOPE_FEATURES:
            raise ValueError(f"rolling scope 非法: {self.scope!r}，仅支持 {ROLLING_SCOPES}")


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

    def scope_features(self) -> tuple[str, ...]:
        return ROLLING_SCOPE_FEATURES[self.config.scope]

    def transform_config_digest(self) -> str:
        # scope 名与其解析出的列子集共同进入 digest：e1/e2 列集相同但语义不同
        # （静态 vs 动态），故 scope 名必须参与哈希使异 scope digest 互异；
        # config 明细剔除 scope 后参与哈希，避免默认值漂移。
        config_dict = asdict(self.config)
        config_dict.pop("scope", None)
        scope_features = self.scope_features()
        scope_subset = set(scope_features)
        payload = {
            "mode": ROLLING_MODE,
            "version": ROLLING_TRANSFORM_VERSION,
            "scope": self.config.scope,
            "config": config_dict,
            "price_strategy": "relative_then_rolling_median_iqr_clip",
            "winsor_strategy": "rolling_percentile_clip",
            "scope_features": list(scope_features),
            "rolling_price_features": [c for c in ROLLING_PRICE_FEATURES if c in scope_subset],
            "rolling_winsor_features": [c for c in ROLLING_WINSOR_FEATURES if c in scope_subset],
            "other_strategy": "column_rules_asinh_clip01_fixed_clip_fill_zero",
            "mask_columns": list(G9_MASK_COLUMNS),
            "mask_strategy": "shared_or_gn_observation_source_finite",
        }
        return self._canonical_hash(payload)

    def _mask_columns_for(self, feature_cols: list[str]) -> list[str]:
        if self.config.add_g9_masks and any(c in _G9_OBSERVATION_SOURCE_SET for c in feature_cols):
            return list(G9_MASK_COLUMNS)
        return []

    def output_feature_cols(self, feature_cols: list[str]) -> list[str]:
        self._validate_feature_cols(feature_cols)
        return list(feature_cols) + self._mask_columns_for(feature_cols)

    def schema_manifest(self, feature_cols: list[str]) -> dict[str, Any]:
        return {
            "mode": ROLLING_MODE,
            "version": ROLLING_VERSION,
            "window": self.config.window,
            "min_periods": self.config.min_periods,
            "include_current_t": self.config.include_current_t,
            "scope": self.config.scope,
            "rolling_scope_features": list(self.scope_features()),
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

    @staticmethod
    def _apply_column_rule(
        values: np.ndarray, missing: np.ndarray, rule: ColumnRule, close: np.ndarray | None
    ) -> np.ndarray:
        """非 scope 列按 COLUMN_RULES 变换（P relative / R asinh / N clip01 / G fixed_clip）。"""
        if rule.transform == "relative":
            if close is None:
                raise ValueError("非 scope 的 P 组列需要 close 上下文")
            transformed = RollingNormalizer._relative(values, close)
            transformed = np.where(np.isfinite(transformed), transformed, 0.0)
            transformed = np.where(missing, 0.0, transformed)
            if rule.clip is not None:
                transformed = np.clip(transformed, rule.clip[0], rule.clip[1])
            return transformed
        if rule.transform == "asinh":
            transformed = np.arcsinh(values * rule.scale)
        elif rule.transform in ("clip01", "fixed_clip", "passthrough"):
            transformed = values
        else:
            raise ValueError(f"未知 transform: {rule.transform!r}")
        if rule.clip is not None:
            transformed = np.clip(transformed, rule.clip[0], rule.clip[1])
        transformed = np.where(missing, 0.0, transformed)
        return np.where(np.isfinite(transformed), transformed, 0.0)

    def _transform_scoped_column(
        self,
        column: str,
        raw: np.ndarray,
        helper: np.ndarray,
        fallback_col: np.ndarray | None,
        fallback_mask_col: np.ndarray,
        audit: RollingAudit,
    ) -> np.ndarray:
        """入 scope 列：P 走 relative→rolling robust；VOL/VOLUME/G 走 rolling winsor。"""
        rule = column_rule(column)
        robust = rule.robust and rule.transform == "relative"
        prepared = self._relative(raw, helper) if robust else raw.copy()
        return self._rolling_column(prepared, robust, fallback_col, fallback_mask_col, audit)

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
        output_count = len(self.output_feature_cols(feature_cols))
        fallback_mask = np.zeros((row_count, output_count), dtype=bool)
        audit = RollingAudit(total_rows=row_count)
        rolling_cols = set(self.scope_features())
        observed = np.zeros(row_count, dtype=bool)
        has_g9_source = any(c in _G9_OBSERVATION_SOURCE_SET for c in feature_cols)

        for column_index, column in enumerate(feature_cols):
            raw = values[:, column_index]
            finite = np.isfinite(raw)
            audit.missing_values += int((~finite).sum())
            if column in _G9_OBSERVATION_SOURCE_SET:
                observed |= finite
            if column in rolling_cols:
                transformed = self._transform_scoped_column(
                    column,
                    raw,
                    helper,
                    None if fallback is None else fallback[:, column_index],
                    fallback_mask[:, column_index],
                    audit,
                )
            else:
                audit.passthrough_values += row_count
                transformed = self._apply_column_rule(raw, ~finite, column_rule(column), helper)
            output_columns.append(transformed)

        output = np.stack(output_columns, axis=1)
        if self.config.add_g9_masks and has_g9_source:
            shared_mask = observed.astype(np.float32).reshape(-1, 1)
            output = np.concatenate([output, shared_mask], axis=1)
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
        # 向量化：pandas.rolling 复现逐行窗口语义（NaN/inf 均按缺失处理）。
        # pandas 分位数与 numpy 存在 ULP 级实现差异（见等价测试），
        # 因此输出以 rtol=0/atol=1e-12 判定等价，fallback_mask/audit 计数逐位一致。
        output = np.zeros(values.shape, dtype=np.float64)
        row_count = len(values)
        if row_count == 0:
            return output

        config = self.config
        finite_current = np.isfinite(values)
        series = pd.Series(np.where(finite_current, values, np.nan))
        rolling = series.rolling(window=config.window, min_periods=config.min_periods)
        counts = rolling.count().to_numpy()
        counts = np.where(np.isnan(counts), 0.0, counts)
        fallback_rows = counts < config.min_periods
        rolling_rows = (~fallback_rows) & finite_current

        if fallback_rows.any():
            fallback_mask[fallback_rows] = True
            audit.fallback_values += int(fallback_rows.sum())
            if fallback is None:
                audit.neutral_fallback_values += int(fallback_rows.sum())
            else:
                fallback_finite = np.isfinite(fallback)
                supplied = fallback_rows & fallback_finite
                output[supplied] = fallback[supplied]
                neutral = fallback_rows & ~fallback_finite
                audit.neutral_fallback_values += int(neutral.sum())

        if not rolling_rows.any():
            return output

        epsilon = np.finfo(np.float64).eps
        with np.errstate(invalid="ignore", divide="ignore"):
            if robust:
                median = rolling.median().to_numpy()
                q25 = rolling.quantile(0.25).to_numpy()
                q75 = rolling.quantile(0.75).to_numpy()
                iqr = q75 - q25
                constant = rolling_rows & (iqr <= epsilon)
                audit.constant_iqr_values += int(constant.sum())
                scale = np.where(iqr <= epsilon, 1.0, iqr / IQR_TO_SIGMA)
                transformed = np.clip(
                    (values - median) / scale, -config.robust_clip, config.robust_clip
                )
            else:
                lower = rolling.quantile(config.lower_percentile / 100.0).to_numpy()
                upper = rolling.quantile(config.upper_percentile / 100.0).to_numpy()
                transformed = np.clip(values, lower, upper)
        output[rolling_rows] = transformed[rolling_rows]
        audit.rolling_values += int(rolling_rows.sum())
        return output
