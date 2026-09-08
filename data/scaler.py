"""Per-Code 分组归一化 Scaler（不做 window，只 per-code 分组）

总基调（用户 2026-09-03 确认）：
- G1 价格水平 12列：feature/prev_close -1（prev_close 为同一 code 的上一日 close），无非线性，per-code robust (median/IQR) + clip ±5
- G2 收益率 4列：不入训，跳过
- G3 波动率 7列：仅 clip + per-code（无 log1p），per-code winsor 1/99 截断（不做 robust）
- G4 量能 3列：volume_ratio_5/10, amihud 仅 clip + per-code；volume/amount 剔除
- G5 技术 6列：macd 同样 feature/prev_close -1 + clip + per-code，其余 5(dmi/adx/boll/kelch/trend_dev) 已比值 跳过
- G6 估值 4列：仅 asinh + per-code robust
- G7 成长 4列：仅 clip + per-code
- G8 质量 5列：跳过
- G9 两融 6列：完全不做 per-code，已 rank [0,1]，仅 填0 + 单 mask + clip[0,1] 兜底

实现：
- 按 code 独立计算统计量（median/IQR/winsor 界），存 per_code_stats: {code: {col: stats}}
- 验证集复用：重叠 code 用训练集的 per-code 统计量；未见 code 回退到全局 median/IQR（从训练集全局拟合）
- 持久化：pickle {per_code_stats, global_stats, feature_cols, version}
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from typing import Any, cast

import numpy as np
import pandas as pd

EPS = 1e-8
SCALER_VERSION = "v3_per_code"
TRANSFORM_VERSION = "per_code_transform_v3"
REQUIRED_STAT_KEYS = {"group", "median", "iqr", "winsor_lower", "winsor_upper", "transform"}

# ---- 分组（与 grouped_scaler 保持一致，但按用户最新剔除） ----
# 有效特征 47 + 1 mask =48（已剔除 G2 4 + TOT 1 + volume/amount 2，close恒0剔除后 G1 12）
GROUP_DEFS_PER_CODE = {
    "G1_Price": ["open", "high", "low", "ma_5", "ma_10", "ma_20", "ma_60", "ema_12", "ema_26", "sar", "trend_duokong", "trend_shortline"],
    "G3_Vol": ["volatility_5d", "volatility_10d", "volatility_20d", "std_5", "std_10", "std_20", "atr"],
    "G4_Volume": ["volume_ratio_5d", "volume_ratio_10d", "amihud"],
    "G5_Tech": ["macd", "dmi", "adx", "boll", "kelch", "trend_duokong_dev"],
    "G6_Valuation": ["pe", "pb", "pcf", "ps"],
    "G7_Growth": ["revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq"],
    "G8_Quality": ["gross_margin", "net_margin", "roe", "roa", "debt_to_equity"],
    "G9_Margin": ["margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio", "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
                   "margin_balance_ratio_raw", "margin_buy_ratio_raw", "margin_net_buy_ratio_raw",
                   "margin_balance_chg_5d_raw", "short_balance_ratio_raw", "short_sell_vol_ratio_raw",
                   "margin_balance_ratio_ts", "margin_buy_ratio_ts", "margin_net_buy_ratio_ts",
                   "margin_balance_chg_5d_ts", "short_balance_ratio_ts", "short_sell_vol_ratio_ts"],
}

COL_TO_GROUP_PER_CODE = {c: g for g, cols in GROUP_DEFS_PER_CODE.items() for c in cols}

# 各组是否需要 per-code 处理及变换
PER_CODE_CONFIG = {
    "G1_Price": {"transform": "relative", "robust": True, "clip": (-5, 5)},  # feature/prev_close -1 + robust
    "G3_Vol": {"transform": None, "robust": False, "clip": None, "winsor": (1, 99)},  # 仅 clip (winsor)
    "G4_Volume": {"transform": None, "robust": False, "clip": None, "winsor": (1, 99)},
    "G5_Tech": {"transform": "relative_macd_only", "robust": False, "clip": None, "winsor": (1, 99)},  # 仅 macd relative + clip，其余跳过
    "G6_Valuation": {"transform": "asinh", "robust": True, "clip": (-5, 5)},
    "G7_Growth": {"transform": None, "robust": False, "clip": None, "winsor": (1, 99)},
    "G8_Quality": {"transform": None, "robust": False, "clip": None},  # 跳过
    "G9_Margin": {"transform": None, "robust": False, "clip": (0, 1)},  # 已 rank，不做 per-code
}


def _asinh(x: np.ndarray) -> np.ndarray:
    return np.arcsinh(x)


class PerCodeGroupedScaler:
    """Per-Code 分组归一化

    fit(df) 会对每个 code 的每列计算 per-code 统计量（median/IQR/winsor）
    transform(code, feat_array, feature_cols, close_series) 对单股的 [N,F] 做变换
    """

    def __init__(self, add_mask: bool = True):
        self.add_mask = add_mask
        self.per_code_stats: dict[str, dict[str, dict]] = {}  # code -> col -> {median, iqr, winsor_lower, winsor_upper, transform}
        self.global_stats: dict[str, dict] = {}  # 回退用
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
        payload = {"groups": GROUP_DEFS_PER_CODE, "config": PER_CODE_CONFIG, "version": TRANSFORM_VERSION}
        return PerCodeGroupedScaler.identity_hash_for(payload)

    def set_identity(self, manifest: dict) -> None:
        identity_manifest = cast(dict, json.loads(json.dumps(manifest, sort_keys=True)))
        self.identity_manifest = identity_manifest
        self.identity_hash = self.identity_hash_for(identity_manifest)

    def validate_requested_schema(self, feature_cols: list[str], add_mask: bool = True) -> None:
        expected_out = list(feature_cols) + ([f"{c}_mask" for c in feature_cols if COL_TO_GROUP_PER_CODE.get(c) == "G9_Margin"] if add_mask else [])
        if self.feature_cols != list(feature_cols) or self.add_mask != add_mask or self.feature_cols_out != expected_out:
            raise ValueError("scaler feature schema 不匹配: feature_cols/add_mask/output columns")
        if self.mask_cols != expected_out[len(feature_cols):]:
            raise ValueError("scaler mask schema 不匹配")
        if not self.fitted:
            raise ValueError("scaler 未拟合")
        for stats in [self.global_stats, *self.per_code_stats.values()]:
            for col in self.feature_cols:
                if col not in stats or not REQUIRED_STAT_KEYS.issubset(stats[col]):
                    raise ValueError(f"scaler 统计缺失或不完整: {col}")

    def fit(self, df: pd.DataFrame, feature_cols: list[str] | None = None) -> PerCodeGroupedScaler:
        if feature_cols is None:
            exclude = {"code", "kline_time", "is_trading"}
            feature_cols = [c for c in df.columns if c not in exclude]
        self.feature_cols = list(feature_cols)

        # 全局回退统计（用于未见 code）
        self._fit_global_fallback(df)

        # per-code
        for code, group in df.groupby("code", sort=False):
            code = str(code)
            group = cast(Any, group).sort_values("kline_time")
            close = group["close"].values.astype(np.float64) if "close" in group.columns else None
            # need close for G1 relative; close itself is available as column
            # for each col, compute per-code stats on transformed valid values
            code_stats: dict[str, dict] = {}
            for col in self.feature_cols:
                if col not in group.columns:
                    continue
                grp = COL_TO_GROUP_PER_CODE.get(col, None)
                # G2 已剔除，不应出现；若出现则跳过
                if grp is None:
                    # 未在分组中的列（如 close 恒0 或未来新增）跳过统计，按原值
                    code_stats[col] = {"group": "UNKNOWN", "median": 0.0, "iqr": 1.0, "winsor_lower": None, "winsor_upper": None, "transform": None}
                    continue

                cfg = PER_CODE_CONFIG.get(grp, {})
                transform = cfg.get("transform")
                # 取原始列值
                vals = group[col].values.astype(np.float64)

                # G1 / G5 macd 需要 relative 变换后再算统计
                if transform == "relative":
                    # feature / prev_close -1
                    vals_t = self._relative_transform(vals, close)
                elif transform == "relative_macd_only":
                    if col == "macd":
                        vals_t = self._relative_transform(vals, close)
                    else:
                        # 其余跳过：统计量不用于归一化，但仍存占位
                        vals_t = vals
                elif transform == "asinh":
                    # 先 asinh
                    # 缺失先不填，valid 上算
                    valid = vals[np.isfinite(vals)]
                    if len(valid) == 0:
                        code_stats[col] = {"group": grp, "median": 0.0, "iqr": 1.0, "winsor_lower": None, "winsor_upper": None, "transform": "asinh"}
                        continue
                    valid_t = _asinh(valid)
                    # 按配置 winsor? G6 asinh后是否 winsor? 用户说仅 asinh，不 clip winsor，但 per-code 仍需 median/IQR
                    # 这里对 asinh后算 median/IQR，不做 winsor
                    median = float(np.median(valid_t))
                    q75, q25 = np.percentile(valid_t, [75, 25])
                    iqr = float(q75 - q25) if (q75 - q25) > EPS else 1.0
                    code_stats[col] = {"group": grp, "median": median, "iqr": iqr, "winsor_lower": None, "winsor_upper": None, "transform": "asinh"}
                    continue
                elif transform is None:
                    vals_t = vals
                else:
                    vals_t = vals

                # 对于需要 winsor 的组，计算 winsor 界
                winsor = cfg.get("winsor")
                valid = vals_t[np.isfinite(vals_t)]
                if len(valid) == 0:
                    code_stats[col] = {"group": grp, "median": 0.0, "iqr": 1.0, "winsor_lower": None, "winsor_upper": None, "transform": transform}
                    continue

                winsor_lower, winsor_upper = None, None
                if winsor is not None:
                    lo_p, hi_p = winsor
                    winsor_lower = float(np.percentile(valid, lo_p))
                    winsor_upper = float(np.percentile(valid, hi_p))
                    if winsor_upper - winsor_lower < EPS:
                        winsor_upper = winsor_lower + 1.0

                # 对于 robust 组，计算 median/IQR（在 winsor 截断后）
                if cfg.get("robust"):
                    # winsor 截断后再算
                    valid_clip = np.clip(valid, winsor_lower, winsor_upper) if winsor_lower is not None else valid
                    median = float(np.median(valid_clip))
                    q75, q25 = np.percentile(valid_clip, [75, 25])
                    iqr = float(q75 - q25) if (q75 - q25) > EPS else 1.0
                else:
                    # 仅 clip 组，无 robust，用 0/1 占位
                    median, iqr = 0.0, 1.0

                code_stats[col] = {
                    "group": grp,
                    "median": median,
                    "iqr": iqr,
                    "winsor_lower": winsor_lower,
                    "winsor_upper": winsor_upper,
                    "transform": transform,
                }
            self.per_code_stats[code] = code_stats

        # mask 列
        if self.add_mask:
            self.mask_cols = [f"{c}_mask" for c in self.feature_cols if COL_TO_GROUP_PER_CODE.get(c) == "G9_Margin"]
        else:
            self.mask_cols = []
        self.feature_cols_out = self.feature_cols + self.mask_cols
        self.fitted = True
        print(f"[PerCodeGroupedScaler] 拟合完成: {len(self.feature_cols)} -> {len(self.feature_cols_out)} (per-code {len(self.per_code_stats)} 股, mask {len(self.mask_cols)})")
        return self

    def _fit_global_fallback(self, df: pd.DataFrame):
        """Fit fallback stats through the same pre-stat transform as per-code data."""
        values_by_col = {col: [] for col in self.feature_cols}
        for _, group in df.groupby("code", sort=False):
            group = cast(Any, group).sort_values("kline_time")
            close = group["close"].to_numpy(dtype=np.float64)
            for col in self.feature_cols:
                vals = group[col].to_numpy(dtype=np.float64)
                group_name = COL_TO_GROUP_PER_CODE.get(col)
                transform = PER_CODE_CONFIG.get(group_name, {}).get("transform") if group_name else None
                if transform == "relative" or (transform == "relative_macd_only" and col == "macd"):
                    vals = self._relative_transform(vals, close)
                elif transform == "asinh":
                    vals = _asinh(vals)
                values_by_col[col].append(vals[np.isfinite(vals)])
        for col, chunks in values_by_col.items():
            valid = np.concatenate(chunks) if chunks else np.array([], dtype=np.float64)
            grp = COL_TO_GROUP_PER_CODE.get(col)
            cfg = PER_CODE_CONFIG.get(grp, {}) if grp else {}
            lower = upper = None
            if len(valid) and cfg.get("winsor"):
                lower, upper = (float(v) for v in np.percentile(valid, cfg["winsor"]))
            clipped = np.clip(valid, lower, upper) if lower is not None else valid
            median = float(np.median(clipped)) if len(clipped) and cfg.get("robust") else 0.0
            iqr = float(np.diff(np.percentile(clipped, [25, 75]))[0]) if len(clipped) and cfg.get("robust") else 1.0
            self.global_stats[col] = {"group": grp, "median": median, "iqr": iqr if iqr > EPS else 1.0,
                                      "winsor_lower": lower, "winsor_upper": upper, "transform": cfg.get("transform")}

    def _relative_transform(self, vals: np.ndarray, close: np.ndarray | None) -> np.ndarray:
        if close is None:
            return vals
        # feature / prev_close -1
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        # 避免除零
        safe_prev = np.where((prev_close == 0) | np.isnan(prev_close), np.nan, prev_close)
        return vals / safe_prev - 1.0

    def transform_code(self, code: str, feat: np.ndarray, feature_cols: list[str], close: np.ndarray | None = None) -> np.ndarray:
        """对单股的 [N, F] 做 per-code 变换，返回 [N, F_out]"""
        if not self.fitted:
            raise RuntimeError("未拟合")
        code_stats = self.per_code_stats.get(code, None)
        # 若 code 未见，用 global_stats
        use_global = code_stats is None
        out_cols = []
        masks = []
        for j, col in enumerate(feature_cols):
            vals = feat[:, j].astype(np.float64)
            missing = ~np.isfinite(vals)
            grp = COL_TO_GROUP_PER_CODE.get(col, None)
            if grp == "G8_Quality" or grp is None:
                # 跳过：已归一化不处理，缺失填0后原值透传（clip 兜底可选）
                # 按用户要求 G8 跳过：填0后不做任何变换
                vals_filled = np.where(missing, 0.0, vals)
                # 仅 clip 到极端保护？跳过则不 clip
                out_cols.append(vals_filled)
                # G8 无 mask
                continue
            if grp == "G9_Margin":
                # 已 rank，不做 per-code，填0 + clip[0,1]
                observed = (~missing).astype(np.float32)
                vals_filled = np.where(missing, 0.0, vals)
                vals_filled = np.clip(vals_filled, 0, 1)
                out_cols.append(vals_filled)
                if self.add_mask:
                    masks.append(observed)
                continue

            cfg = PER_CODE_CONFIG.get(grp, {})
            transform = cfg.get("transform")
            # 获取 per-code 统计量
            stat = None
            if not use_global and code_stats is not None and col in code_stats:
                stat = code_stats[col]
            else:
                # 回退全局
                gstat = self.global_stats.get(col, {"median": 0.0, "iqr": 1.0})
                # 构造 stat 占位
                stat = gstat

            # 1. relative / asinh
            if transform == "relative":
                vals = self._relative_transform(vals, close)
            elif transform == "relative_macd_only":
                if col == "macd":
                    vals = self._relative_transform(vals, close)
                else:
                    # 其余跳过：已比值不处理
                    vals_filled = np.where(np.isnan(vals), 0.0, vals)
                    out_cols.append(vals_filled)
                    continue
            elif transform == "asinh":
                # 缺失填0后再 asinh? 先 asinh 有效值，缺失填0的 asinh(0)=0
                # 这里先 fill NaN 0，再 asinh
                vals = _asinh(vals)
                # 然后 robust
                median = stat["median"]
                iqr = stat["iqr"]
                vals = (vals - median) / (iqr / 1.349 + EPS) if cfg.get("robust") else vals
                if cfg.get("clip"):
                    lo, hi = cfg["clip"]
                    vals = np.clip(vals, lo, hi)
                vals[missing] = 0.0
                vals[~np.isfinite(vals)] = 0.0
                out_cols.append(vals)
                continue

            # 2. 对于 robust 组，做 (x - median)/ (IQR/1.349)
            # 对于仅 clip 组，做 winsor clip
            if cfg.get("robust"):
                # 缺失填0后，winsor? G1 无 winsor，仅 robust
                vals_filled = vals.copy()
                # 若有 winsor 界，先 clip
                if stat.get("winsor_lower") is not None:
                    vals_filled = np.clip(vals_filled, stat["winsor_lower"], stat["winsor_upper"])
                median = stat["median"]
                iqr = stat["iqr"]
                vals_filled = (vals_filled - median) / (iqr / 1.349 + EPS)
                if cfg.get("clip"):
                    lo, hi = cfg["clip"]
                    vals_filled = np.clip(vals_filled, lo, hi)
                vals_filled[missing] = 0.0
                out_cols.append(vals_filled)
            else:
                # 仅 clip 组（G3/G4/G7）：winsor clip
                vals_filled = vals.copy()
                wl, wh = stat.get("winsor_lower"), stat.get("winsor_upper")
                if wl is not None and wh is not None:
                    vals_filled = np.clip(vals_filled, wl, wh)
                vals_filled[missing] = 0.0
                # G3/G4/G7 无 robust，不做 median/IQR，仅 clip
                out_cols.append(vals_filled)

        out = np.stack(out_cols, axis=1)
        if masks:
            mask_arr = np.stack(masks, axis=1)
            out = np.concatenate([out, mask_arr], axis=1)
        # 防御
        out = np.where(np.isnan(out), 0.0, out)
        out = np.where(np.isinf(out), 0.0, out)
        return out.astype(np.float32)

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
            raise ValueError("不支持的 scaler payload；需要 v3_per_code")
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
        for stats in [obj.global_stats, *obj.per_code_stats.values()]:
            for col in obj.feature_cols:
                if col not in stats or not REQUIRED_STAT_KEYS.issubset(stats[col]):
                    raise ValueError(f"scaler 统计缺失或不完整: {col}")
        print(f"[PerCodeGroupedScaler] 从 {path} 加载, per-code {len(obj.per_code_stats)} 股")
        return obj
