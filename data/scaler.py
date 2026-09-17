"""归一化策略（不做 window）：ColumnRule Registry + relative/per_code 两策略。

列语义分组（data/schema.py FEATURE_GROUPS）驱动变换：
- P 价格量纲：x/close[t-1]-1；E0 `RelativeScaler` 无统计量，E1 `PerCodeGroupedScaler` 静态 per-code robust。
- R 无界比值：clip(asinh(x·scale), ±ASINH_CLIP)；amihud scale=AMIHUD_SCALE。
- N 已归一化（G9 rank/ts）：clip(0,1)。
- G G9 `*_raw`：按 G9_RAW_CLIP 固定区间 clip，保留负值/量纲。

通用契约：
- 缺失（NaN/inf）→ 填 0；feature_cols 含 G9 观测源列且 add_mask=True 时，末尾追加 1 个
  `g9_observed_mask = OR(原始值 finite)`；未知列直接 raise，不再静默透传。
- 持久化：pickle {per_code_stats, global_stats, feature_cols, feature_cols_out, mask_cols,
  add_mask, identity_manifest, identity_hash, schema_manifest, version}。
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from dataclasses import asdict, dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from data.schema import FEATURE_GROUPS, G9_MASK_COLUMNS, G9_OBSERVATION_SOURCE

EPS = 1e-8
SCALER_VERSION = "v4_per_code"
TRANSFORM_VERSION = "per_code_transform_v4"
IQR_TO_SIGMA = 1.349  # 正态下 IQR → σ 的换算系数（robust 标准化分母）
REQUIRED_STAT_KEYS = frozenset({"group", "transform", "median", "iqr"})


class PerCodeGroupedScaler:
    """E1 静态 per-code 策略：仅 P 组按股拟合 robust 统计量，其余组走 COLUMN_RULES 确定性变换。

    - P：fit 按股计算 x/close[t-1]-1 的 median/IQR；transform 做
      (v - median)/(IQR/1.349 + EPS) 后 clip P_CLIP，未见 code 回退 global_stats。
    - R/N/G：分别按 asinh/clip01/fixed_clip 规则变换，无统计量。
    - mask：feature_cols 含 G9 观测源列且 add_mask=True 时追加 1 个 g9_observed_mask。
    """

    def __init__(self, add_mask: bool = True):
        self.add_mask = add_mask
        self.per_code_stats: dict[str, dict[str, dict]] = {}  # code -> col -> {group, transform, median, iqr}
        self.global_stats: dict[str, dict] = {}
        self.feature_cols: list[str] = []
        self.feature_cols_out: list[str] = []
        self.mask_cols: list[str] = []
        self.fitted = False
        self.identity_manifest: dict | None = None
        self.identity_hash: str | None = None

    @staticmethod
    def identity_hash_for(manifest: dict) -> str:
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def transform_config_digest() -> str:
        payload = {
            "rules": {column: asdict(rule) for column, rule in COLUMN_RULES.items()},
            "version": TRANSFORM_VERSION,
            "mask_columns": list(G9_MASK_COLUMNS),
        }
        return PerCodeGroupedScaler.identity_hash_for(payload)

    def set_identity(self, manifest: dict) -> None:
        identity_manifest = cast(dict, json.loads(json.dumps(manifest, sort_keys=True)))
        self.identity_manifest = identity_manifest
        self.identity_hash = self.identity_hash_for(identity_manifest)

    @staticmethod
    def _mask_columns_for(feature_cols: list[str], add_mask: bool) -> list[str]:
        if add_mask and any(col in _G9_OBSERVATION_SOURCE_SET for col in feature_cols):
            return list(G9_MASK_COLUMNS)
        return []

    def validate_requested_schema(self, feature_cols: list[str], add_mask: bool = True) -> None:
        """校验请求的 feature 子集/输出 mask 与本 scaler 一致，并核对 P 组统计完整性。"""
        requested = list(feature_cols)
        mask_cols = self._mask_columns_for(requested, add_mask)
        schema_mismatch = (
            self.feature_cols != requested
            or self.add_mask != add_mask
            or self.feature_cols_out != requested + mask_cols
        )
        if schema_mismatch:
            raise ValueError("scaler feature schema 不匹配: feature_cols/add_mask/output columns")
        if self.mask_cols != mask_cols:
            raise ValueError("scaler mask schema 不匹配")
        if not self.fitted:
            raise ValueError("scaler 未拟合")
        for stats in [self.global_stats, *self.per_code_stats.values()]:
            for col in self.feature_cols:
                if not column_rule(col).robust:
                    continue
                if col not in stats or not REQUIRED_STAT_KEYS.issubset(stats[col]):
                    raise ValueError(f"scaler 统计缺失或不完整: {col}")

    def fit(self, df: pd.DataFrame, feature_cols: list[str] | None = None) -> PerCodeGroupedScaler:
        """拟合 P 组 per-code robust 统计量；未知列直接 raise。"""
        if feature_cols is None:
            exclude = {"code", "kline_time", "is_trading"}
            feature_cols = [c for c in df.columns if c not in exclude]
        self.feature_cols = list(feature_cols)
        for column in self.feature_cols:
            column_rule(column)
        self._fit_global_fallback(df)
        for code, group in df.groupby("code", sort=False):
            code = str(code)
            group = cast(Any, group).sort_values("kline_time")
            close = group["close"].to_numpy(dtype=np.float64) if "close" in group.columns else None
            code_stats: dict[str, dict] = {}
            for column in self.feature_cols:
                if column not in group.columns:
                    continue
                rule = column_rule(column)
                if rule.robust:
                    vals = group[column].to_numpy(dtype=np.float64)
                    vals_t = _relative_transform(vals, close) if rule.transform == "relative" else vals
                    median, iqr = self._robust_stats(vals_t)
                else:
                    median, iqr = 0.0, 1.0
                code_stats[column] = {"group": rule.group, "transform": rule.transform, "median": median, "iqr": iqr}
            self.per_code_stats[code] = code_stats
        self._set_mask_schema()
        self.fitted = True
        print(f"[PerCodeGroupedScaler] 拟合完成: {len(self.feature_cols)} -> {len(self.feature_cols_out)} "
              f"(per-code {len(self.per_code_stats)} 股, mask {len(self.mask_cols)})")
        return self

    @staticmethod
    def _robust_stats(values: np.ndarray) -> tuple[float, float]:
        valid = values[np.isfinite(values)]
        if len(valid) == 0:
            return 0.0, 1.0
        median = float(np.median(valid))
        q75, q25 = np.percentile(valid, [75, 25])
        iqr = float(q75 - q25)
        return median, iqr if iqr > EPS else 1.0

    def _fit_global_fallback(self, df: pd.DataFrame) -> None:
        """按全部训练行拟合 robust 组全局统计量，供未见 code 回退。"""
        values_by_col: dict[str, list[np.ndarray]] = {column: [] for column in self.feature_cols}
        for _, group in df.groupby("code", sort=False):
            group = cast(Any, group).sort_values("kline_time")
            close = group["close"].to_numpy(dtype=np.float64) if "close" in group.columns else None
            for column in self.feature_cols:
                rule = column_rule(column)
                if column not in group.columns or not rule.robust:
                    continue
                vals = group[column].to_numpy(dtype=np.float64)
                vals_t = _relative_transform(vals, close) if rule.transform == "relative" else vals
                values_by_col[column].append(vals_t)
        for column in self.feature_cols:
            rule = column_rule(column)
            chunks = values_by_col[column]
            values = np.concatenate(chunks) if chunks else np.array([], dtype=np.float64)
            median, iqr = self._robust_stats(values) if rule.robust else (0.0, 1.0)
            self.global_stats[column] = {"group": rule.group, "transform": rule.transform, "median": median, "iqr": iqr}

    def _set_mask_schema(self) -> None:
        self.mask_cols = self._mask_columns_for(self.feature_cols, self.add_mask)
        self.feature_cols_out = self.feature_cols + self.mask_cols

    def _stat_for(self, column: str, code_stats: dict[str, dict] | None, use_global: bool) -> dict:
        if not use_global and code_stats is not None and column in code_stats:
            return code_stats[column]
        return self.global_stats.get(column, {"median": 0.0, "iqr": 1.0})

    def transform_code(
        self, code: str, feat: np.ndarray, feature_cols: list[str], close: np.ndarray | None = None
    ) -> np.ndarray:
        """对单股 [N, F] 按 COLUMN_RULES 变换，返回 [N, F_out] float32；缺失→0，mask 追加末尾。"""
        if not self.fitted:
            raise RuntimeError("未拟合")
        values = np.asarray(feat, dtype=np.float64)
        code_stats = self.per_code_stats.get(code)
        use_global = code_stats is None
        out_cols: list[np.ndarray] = []
        observed: np.ndarray | None = None
        for index, column in enumerate(feature_cols):
            rule = column_rule(column)
            vals = values[:, index]
            missing = ~np.isfinite(vals)
            out_cols.append(self._apply_rule(column, vals, missing, rule, code_stats, use_global, close))
            if column in _G9_OBSERVATION_SOURCE_SET:
                row_observed = ~missing
                observed = row_observed if observed is None else (observed | row_observed)
        out = np.stack(out_cols, axis=1) if out_cols else np.zeros((len(values), 0), dtype=np.float64)
        if self.mask_cols:
            mask = np.zeros(len(values), dtype=bool) if observed is None else observed
            out = np.concatenate([out, mask.astype(np.float32).reshape(-1, 1)], axis=1)
        return out.astype(np.float32)

    def _apply_rule(
        self,
        column: str,
        vals: np.ndarray,
        missing: np.ndarray,
        rule: ColumnRule,
        code_stats: dict[str, dict] | None,
        use_global: bool,
        close: np.ndarray | None,
    ) -> np.ndarray:
        transform = rule.transform
        if transform == "relative":
            transformed = _relative_transform(vals, close)
            stat = self._stat_for(column, code_stats, use_global)
            transformed = (transformed - stat["median"]) / (stat["iqr"] / IQR_TO_SIGMA + EPS)
        elif transform == "asinh":
            transformed = np.arcsinh(vals * rule.scale)
        elif transform in ("clip01", "fixed_clip", "passthrough"):
            transformed = vals
        else:
            raise ValueError(f"未知 transform: {transform!r}")
        if rule.clip is not None:
            transformed = np.clip(transformed, rule.clip[0], rule.clip[1])
        transformed = np.where(missing, 0.0, transformed)
        return np.where(np.isfinite(transformed), transformed, 0.0)

    # ---------- 持久化 ----------
    def save(self, path: str):
        if not self.fitted:
            raise ValueError("不能保存未拟合 scaler")
        if not isinstance(self.identity_manifest, dict) or not isinstance(self.identity_hash, str):
            raise TypeError("不能保存缺少 identity 的 scaler")
        if self.identity_hash != self.identity_hash_for(self.identity_manifest):
            raise ValueError("不能保存 identity hash 不匹配的 scaler")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "per_code_stats": self.per_code_stats,
            "global_stats": self.global_stats,
            "feature_cols": self.feature_cols,
            "feature_cols_out": self.feature_cols_out,
            "mask_cols": self.mask_cols,
            "add_mask": self.add_mask,
            "identity_manifest": self.identity_manifest,
            "identity_hash": self.identity_hash,
            "schema_manifest": {
                "feature_cols": self.feature_cols,
                "feature_cols_out": self.feature_cols_out,
                "mask_cols": self.mask_cols,
                "add_mask": self.add_mask,
                "transform_version": TRANSFORM_VERSION,
                "transform_digest": self.transform_config_digest(),
            },
            "version": SCALER_VERSION,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        print(f"[PerCodeGroupedScaler] 已保存到 {path}, per-code {len(self.per_code_stats)} 股, {len(self.feature_cols)} -> {len(self.feature_cols_out)}")

    @classmethod
    def load(cls, path: str) -> PerCodeGroupedScaler:
        with open(path, "rb") as f:
            payload = pickle.load(f)
        required = {"per_code_stats", "global_stats", "feature_cols", "feature_cols_out", "mask_cols", "add_mask",
                    "identity_manifest", "identity_hash", "schema_manifest", "version"}
        if (
            not isinstance(payload, dict)
            or payload.get("version") != SCALER_VERSION
            or not required.issubset(payload)
            or not isinstance(payload["identity_manifest"], dict)
            or not isinstance(payload["identity_hash"], str)
        ):
            raise ValueError("不支持的 scaler payload；需要 v4_per_code")
        obj = cls(add_mask=payload.get("add_mask", True))
        obj.per_code_stats = payload["per_code_stats"]
        obj.global_stats = payload["global_stats"]
        obj.feature_cols = payload["feature_cols"]
        obj.feature_cols_out = payload["feature_cols_out"]
        obj.mask_cols = payload["mask_cols"]
        obj.identity_manifest = payload["identity_manifest"]
        obj.identity_hash = payload["identity_hash"]
        obj.fitted = True
        if obj.identity_hash != obj.identity_hash_for(obj.identity_manifest):
            raise ValueError("scaler identity hash 不匹配")
        schema = payload["schema_manifest"]
        if schema.get("transform_version") != TRANSFORM_VERSION or schema.get("transform_digest") != obj.transform_config_digest():
            raise ValueError("scaler transform 配置不兼容")
        obj.validate_requested_schema(obj.feature_cols, obj.add_mask)
        print(f"[PerCodeGroupedScaler] 从 {path} 加载, per-code {len(obj.per_code_stats)} 股")
        return obj


# ---------------------------------------------------------------------------
# relative 归一化（E0）—— ColumnRule Registry 与相对变换策略
# 目标 schema：52 raw（P/R/N/G）+ 1 shared mask = F_out 53
# ---------------------------------------------------------------------------
ASINH_CLIP = 5.0
P_CLIP = (-5.0, 5.0)
N_CLIP = (0.0, 1.0)
AMIHUD_SCALE = 1e12
RELATIVE_DENOMINATOR = "close"
RELATIVE_TRANSFORM_VERSION = "relative_transform_v1"
G9_RAW_CLIP = {
    "margin_net_buy_ratio_raw": (-1.0, 1.0),
    "margin_balance_chg_5d_raw": (-1.0, 5.0),
    "margin_buy_ratio_raw": (0.0, 1.5),
    "margin_balance_ratio_raw": (0.0, 1.0),
    "short_balance_ratio_raw": (0.0, 1.0),
    "short_sell_vol_ratio_raw": (0.0, 1.0),
}
_G9_OBSERVATION_SOURCE_SET = frozenset(G9_OBSERVATION_SOURCE)


@dataclass(frozen=True)
class ColumnRule:
    """单列变换规则（Registry 的值；禁止在 transform 内按列名硬编码）。"""

    group: str
    transform: str
    clip: tuple[float, float] | None
    robust: bool = False
    winsor: tuple[float, float] | None = None
    scale: float = 1.0
    relative_denominator: str | None = None


def _build_column_rules() -> dict[str, ColumnRule]:
    """由 data/schema.py 的 FEATURE_GROUPS 生成全量列规则；未知组名报错。"""
    rules: dict[str, ColumnRule] = {}
    for group, columns in FEATURE_GROUPS.items():
        for column in columns:
            if group == "P":
                rule = ColumnRule(group, "relative", P_CLIP, robust=True, relative_denominator=RELATIVE_DENOMINATOR)
            elif group == "R":
                scale = AMIHUD_SCALE if column == "amihud" else 1.0
                rule = ColumnRule(group, "asinh", (-ASINH_CLIP, ASINH_CLIP), scale=scale)
            elif group == "N":
                rule = ColumnRule(group, "clip01", N_CLIP)
            elif group == "G":
                if column not in G9_RAW_CLIP:
                    raise ValueError(f"G 组列缺少固定 clip 区间: {column!r}")
                rule = ColumnRule(group, "fixed_clip", G9_RAW_CLIP[column])
            else:
                raise ValueError(f"FEATURE_GROUPS 含未知分组: {group!r}")
            rules[column] = rule
    return rules


COLUMN_RULES: dict[str, ColumnRule] = _build_column_rules()


def column_rule(column: str) -> ColumnRule:
    """返回列的 ColumnRule，未知列报错而非静默透传。"""
    try:
        return COLUMN_RULES[column]
    except KeyError:
        raise ValueError(f"未知特征列: {column!r}，无 ColumnRule") from None


def _relative_transform(vals: np.ndarray, close: np.ndarray | None) -> np.ndarray:
    """P 组相对变换 val/close[t-1]-1；close 缺失或分母非有限/为 0 时该点置 NaN。"""
    if close is None:
        return vals
    prev_close = np.roll(close, 1)
    prev_close[0] = np.nan
    safe_prev = np.where(np.isfinite(prev_close) & (prev_close != 0.0), prev_close, np.nan)
    return vals / safe_prev - 1.0


class RelativeScaler:
    """E0 策略：P 组 x/close[t-1]-1（clip±5），R/N/G 按 COLUMN_RULES 变换，无 fit。

    mask：当 feature_cols 含至少 1 个 G9_OBSERVATION_SOURCE 列时，追加 1 个 shared
    g9_observed_mask（OR(相关列 finite)）到 feature_cols_out 末尾。
    """

    def __init__(self, feature_cols: list[str], add_mask: bool = True):
        self.feature_cols = list(feature_cols)
        self.add_mask = add_mask
        has_g9 = any(col in _G9_OBSERVATION_SOURCE_SET for col in self.feature_cols)
        self.mask_cols = list(G9_MASK_COLUMNS) if (add_mask and has_g9) else []
        self.feature_cols_out = self.feature_cols + self.mask_cols

    @staticmethod
    def transform_config_digest() -> str:
        payload = {
            "rules": {column: asdict(rule) for column, rule in COLUMN_RULES.items()},
            "version": RELATIVE_TRANSFORM_VERSION,
            "mask_columns": list(G9_MASK_COLUMNS),
        }
        return PerCodeGroupedScaler.identity_hash_for(payload)

    @staticmethod
    def _apply_rule(vals: np.ndarray, rule: ColumnRule, close: np.ndarray | None) -> np.ndarray:
        if rule.transform == "relative":
            return _relative_transform(vals, close)
        if rule.transform == "asinh":
            return np.arcsinh(vals * rule.scale)
        if rule.transform in ("clip01", "fixed_clip", "passthrough"):
            return vals
        raise ValueError(f"未知 transform: {rule.transform!r}")

    def transform_code(
        self, code: str, features: np.ndarray, feature_cols: list[str], close: np.ndarray | None = None
    ) -> np.ndarray:
        """返回 [N, F_out] float32；缺失/非有限填 0，shared mask 追加在末尾。"""
        values = np.asarray(features, dtype=np.float64)
        out_cols: list[np.ndarray] = []
        observed: np.ndarray | None = None
        for index, column in enumerate(feature_cols):
            rule = column_rule(column)
            vals = values[:, index]
            missing = ~np.isfinite(vals)
            vals_t = self._apply_rule(vals, rule, close)
            if rule.clip is not None:
                vals_t = np.clip(vals_t, rule.clip[0], rule.clip[1])
            vals_t = np.where(missing, 0.0, vals_t)
            vals_t = np.where(np.isfinite(vals_t), vals_t, 0.0)
            out_cols.append(vals_t)
            if column in _G9_OBSERVATION_SOURCE_SET:
                row_observed = ~missing
                observed = row_observed if observed is None else (observed | row_observed)
        out = np.stack(out_cols, axis=1) if out_cols else np.zeros((len(values), 0), dtype=np.float64)
        if self.mask_cols:
            mask = np.zeros(len(values), dtype=bool) if observed is None else observed
            out = np.concatenate([out, mask.astype(np.float32).reshape(-1, 1)], axis=1)
        return out.astype(np.float32)
