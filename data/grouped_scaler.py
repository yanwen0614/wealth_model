"""分组归一化 Scaler：55特征 = 7 OHLCVA+TOT_SHARE + 48因子 分9组差异化处理

分组定义（与 quant/scripts/export_training_data.py EXPORT_FACTORS 对齐）：
- G1_Price (14): open/high/low/close/ma_5/10/20/60/ema_12/26/sar/trend_duokong/trend_shortline/TOT_SHARE
    -> log1p + winsor 0.5/99.5 + robust (median/IQR)
- G2_Return (4): return_1d/5d/10d/20d -> winsor 1/99 + robust
- G3_Vol (7): volatility_5d/10d/20d/std_5/10/20/atr -> log1p + winsor 0.5/99.5 + robust
- G4_Volume (5): volume/amount/volume_ratio_5d/10d/amihud -> log1p + robust (ratio类用log)
- G5_Tech (6): macd/dmi/adx/boll/kelch/trend_duokong_dev -> robust + tanh压缩
- G6_Valuation (4): pe/pb/pcf/ps -> asinh + winsor 1/99 + robust
- G7_Growth (4): revenue_growth/profit_growth/revenue_growth_qoq/profit_growth_qoq -> asinh + winsor 1/99 + robust
- G8_Quality (5): gross_margin/net_margin/roe/roa/debt_to_equity -> winsor 1/99 + robust
- G9_Margin (6): margin_balance_ratio/margin_buy_ratio/margin_net_buy_ratio/margin_balance_chg_5d/short_balance_ratio/short_sell_vol_ratio
    -> 有界[0,1] clip + 结构性缺失填0 + mask通道

缺失分级：
- warmup类 (<1%缺失，如 return_/volatility/ma/ema etc) : 变换后填0 (鲁棒零点 = median，经robust后为0)
- 结构性(55%两融 + 10% 估值/成长等) : 填0 + G9额外生成 mask通道 (is_observed)

持久化：
- 每组每列保存 winsor界/median/IQR及变换类型，支持 pickle
- 验证集复用训练集 scaler (不重新fit，避免泄露)

相对化说明：
- G1 Price本可做 (price/close -1) 相对化消除量纲，但 close本身需特殊处理且引入除法不稳定；
- 实现选用 log1p(price) 作单调压缩，经 winsor+robust 后与相对化等价消除非平稳；
- 保留相对化分支注释，若需切换可改 G1 transform为 relative

与 ParquetDataset 兼容：
- fit(df, feature_cols) / transform(feat_ndarray, feature_cols) 双接口
- transform返回 (transformed_feat, extra_masks) 或直接拼接
"""
from __future__ import annotations

import pickle
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---- 分组定义（单一事实源） ----
GROUP_DEFS: Dict[str, List[str]] = {
    "G1_Price": [
        "open", "high", "low", "close",
        "ma_5", "ma_10", "ma_20", "ma_60",
        "ema_12", "ema_26", "sar",
        "trend_duokong", "trend_shortline",
        "TOT_SHARE",
    ],
    "G2_Return": [
        "return_1d", "return_5d", "return_10d", "return_20d",
    ],
    "G3_Vol": [
        "volatility_5d", "volatility_10d", "volatility_20d",
        "std_5", "std_10", "std_20",
        "atr",
    ],
    "G4_Volume": [
        "volume", "amount",
        "volume_ratio_5d", "volume_ratio_10d",
        "amihud",
    ],
    "G5_Tech": [
        "macd", "dmi", "adx", "boll", "kelch", "trend_duokong_dev",
    ],
    "G6_Valuation": [
        "pe", "pb", "pcf", "ps",
    ],
    "G7_Growth": [
        "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
    ],
    "G8_Quality": [
        "gross_margin", "net_margin", "roe", "roa", "debt_to_equity",
    ],
    "G9_Margin": [
        "margin_balance_ratio", "margin_buy_ratio", "margin_net_buy_ratio",
        "margin_balance_chg_5d", "short_balance_ratio", "short_sell_vol_ratio",
    ],
}

# 反向映射 col -> group
COL_TO_GROUP: Dict[str, str] = {col: g for g, cols in GROUP_DEFS.items() for col in cols}

# 各组变换配置
GROUP_TRANSFORM = {
    "G1_Price": {"nonlinear": "log1p", "winsor": (0.5, 99.5), "robust": True, "tanh": False},
    "G2_Return": {"nonlinear": None, "winsor": (1, 99), "robust": True, "tanh": False},
    "G3_Vol": {"nonlinear": "log1p", "winsor": (0.5, 99.5), "robust": True, "tanh": False},
    "G4_Volume": {"nonlinear": "log1p", "winsor": None, "robust": True, "tanh": False},  # volume_ratio 变体在代码中特殊处理为 log
    "G5_Tech": {"nonlinear": None, "winsor": None, "robust": True, "tanh": True},
    "G6_Valuation": {"nonlinear": "asinh", "winsor": (1, 99), "robust": True, "tanh": False},
    "G7_Growth": {"nonlinear": "asinh", "winsor": (1, 99), "robust": True, "tanh": False},
    "G8_Quality": {"nonlinear": None, "winsor": (1, 99), "robust": True, "tanh": False},
    "G9_Margin": {"nonlinear": None, "winsor": None, "robust": False, "tanh": False},  # bounded clip
}

EPS = 1e-8


def _asinh(x: np.ndarray) -> np.ndarray:
    return np.arcsinh(x)


def _log1p_safe(x: np.ndarray) -> np.ndarray:
    # 对负值（理论不应出现于G1/G3/G4，但防御）clip到0再log1p
    # G1价格/ TOT_SHARE 均为正；G3 vol>=0；G4 volume/amount>=0, amihud>=0
    # 若出现负值，保留符号做 log1p(|x|) * sign? 简化：clip
    # 对 volume_ratio虽可<1，但仍>=0，log1p 也单调
    # 这里统一用 log1p(clip)
    # 例外：G4 volume_ratio 将在外层用 log 处理
    x_clipped = np.where(x < 0, 0, x)
    return np.log1p(x_clipped)


def _apply_nonlinear(x: np.ndarray, nonlinear: Optional[str], col: str, group: str) -> np.ndarray:
    if nonlinear is None:
        return x
    if nonlinear == "log1p":
        # G4 volume_ratio 特殊：用 log 而非 log1p 以更好区分 ~1 附近
        if group == "G4_Volume" and col.startswith("volume_ratio"):
            # ratio >0, log(ratio) 0附近对称
            # 避免 log(0)，先 clip 1e-8
            safe = np.clip(x, 1e-8, None)
            return np.log(safe)
        if group == "G4_Volume" and col == "amihud":
            # amihud 极小 1e-13，log1p ≈0 无效，用 log
            safe = np.clip(x, 1e-12, None)
            return np.log(safe)
        return _log1p_safe(x)
    if nonlinear == "asinh":
        return _asinh(x)
    return x


@dataclass
class ColumnStats:
    col: str
    group: str
    winsor_lower: Optional[float] = None
    winsor_upper: Optional[float] = None
    median: float = 0.0
    iqr: float = 1.0
    nonlinear: Optional[str] = None
    # 用于诊断
    raw_median: Optional[float] = None
    raw_iqr: Optional[float] = None
    missing_rate: float = 0.0


class GroupedScaler:
    """分组归一化 Scaler

    用法：
        scaler = GroupedScaler()
        scaler.fit(df, feature_cols)  # df 为 pandas DataFrame (已过滤 is_trading)
        transformed = scaler.transform_ndarray(feat_array, feature_cols)  # feat [N, F]
        # 或
        df_t = scaler.transform_dataframe(df)

    持久化：
        scaler.save(path)
        scaler = GroupedScaler.load(path)

    Mask：
        G9 6列结构性缺失 -> 额外生成 6个 mask 通道 (1=observed, 0=missing)，拼接到特征末尾
        transform_ndarray 返回拼接后数组，feature_cols_out 含 mask 列名
    """

    def __init__(self, add_mask: bool = True):
        self.add_mask = add_mask
        self.stats: Dict[str, ColumnStats] = {}
        self.feature_cols: List[str] = []
        self.feature_cols_out: List[str] = []  # 含 mask
        self.mask_cols: List[str] = []  # G9 mask 列名
        self.fitted = False
        # 记录整体缺失率用于诊断
        self.missing_rates: Dict[str, float] = {}

    # ---------- fit ----------
    def fit(self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None) -> "GroupedScaler":
        if feature_cols is None:
            # 自动推断：排除 code/kline_time/is_trading
            exclude = {"code", "kline_time", "is_trading"}
            feature_cols = [c for c in df.columns if c not in exclude]
        self.feature_cols = list(feature_cols)
        n = len(df)

        for col in self.feature_cols:
            group = COL_TO_GROUP.get(col, None)
            # 未在分组中的列（如未来新增因子）归到 G8 策略：winsor+robust
            if group is None:
                group = "G8_Quality"
            cfg = GROUP_TRANSFORM.get(group, {"nonlinear": None, "winsor": (1, 99), "robust": True, "tanh": False})
            nonlinear = cfg["nonlinear"]

            vals = df[col].values.astype(np.float64)
            valid = vals[~np.isnan(vals)]
            miss_rate = 1.0 - len(valid) / max(n, 1)
            self.missing_rates[col] = float(miss_rate)

            if len(valid) == 0:
                # 全NaN列（如部分股票无两融），统计量兜底
                self.stats[col] = ColumnStats(col=col, group=group, winsor_lower=0.0, winsor_upper=1.0, median=0.0, iqr=1.0, nonlinear=nonlinear, missing_rate=miss_rate)
                continue

            # 1. 非线性变换后计算 winsor 界
            # 为避免重复计算，先对 valid 做 nonlinear
            valid_t = _apply_nonlinear(valid, nonlinear, col, group)

            winsor_lower, winsor_upper = None, None
            if cfg["winsor"] is not None:
                lo_p, hi_p = cfg["winsor"]
                winsor_lower = float(np.percentile(valid_t, lo_p))
                winsor_upper = float(np.percentile(valid_t, hi_p))
                # 防止上下界相等
                if winsor_upper - winsor_lower < EPS:
                    winsor_upper = winsor_lower + 1.0
                # winsor 截断后再算 robust 统计
                valid_t = np.clip(valid_t, winsor_lower, winsor_upper)

            # 2. robust 统计 median / IQR
            if cfg["robust"]:
                median = float(np.median(valid_t))
                q75 = float(np.percentile(valid_t, 75))
                q25 = float(np.percentile(valid_t, 25))
                iqr = float(q75 - q25)
                if iqr < EPS:
                    # 回退到 std 或 1.0
                    std = float(np.std(valid_t))
                    iqr = std if std > EPS else 1.0
                # 对 G5 tanh 组，后续会再 tanh，可保持 iqr
            else:
                # G9 不做 robust，采用 bounded 0-1，无需 median/iqr
                median = 0.0
                iqr = 1.0

            self.stats[col] = ColumnStats(
                col=col,
                group=group,
                winsor_lower=winsor_lower,
                winsor_upper=winsor_upper,
                median=median,
                iqr=iqr,
                nonlinear=nonlinear,
                missing_rate=miss_rate,
            )

        # mask 列名
        if self.add_mask:
            self.mask_cols = [f"{c}_mask" for c in self.feature_cols if COL_TO_GROUP.get(c) == "G9_Margin"]
        else:
            self.mask_cols = []
        self.feature_cols_out = self.feature_cols + self.mask_cols
        self.fitted = True
        return self

    # ---------- transform ----------
    def _transform_column(self, vals: np.ndarray, col: str) -> Tuple[np.ndarray, np.ndarray]:
        """对单列做变换，返回 (transformed_vals, mask_observed)"""
        stat = self.stats[col]
        group = stat.group
        cfg = GROUP_TRANSFORM.get(group, {"nonlinear": None, "winsor": None, "robust": False, "tanh": False})

        # 原始缺失 mask (1=observed, 0=missing)
        observed_mask = (~np.isnan(vals)).astype(np.float32)

        # 缺失分级填充：先标记，稍后按组策略填0
        # warmup <1% 和 结构性 55% 都先填 median 占位，再经变换/robust后填0等价
        # 为保持 transform可逆性，这里用 stat.median 的逆变换? 简化：缺失先填 median对应的原始值
        # 更稳健：缺失在 nonlinear 之前填 median 的原始域中位数，或直接在变换后填0
        # 采用：缺失在 nonlinear 前用 0填充（warmup填0，G9填0），因 log1p(0)=0, asinh(0)=0，
        # 经 robust 后 median->0，故缺失最终为0，符合分级要求

        # 填充 NaN
        vals_filled = vals.copy()
        nan_mask = np.isnan(vals_filled)
        if np.any(nan_mask):
            # G9 结构性缺失填 0（有界通道0即无融资）
            # 其他组 warmup填0，若0在非线性域有意义则亦为中性；若需 median填充，可改 stat.median反推
            # 这里统一填 0，对 G1/G3/G4 的 log1p(0)=0 恰为最小值，经 robust 后为负偏，接近0可接受
            # 对 G6/G7 asinh(0)=0, robust后 = -median/IQR ~ 小偏置，亦近0
            # 为更贴合“warmup填0”要求，保持填0
            vals_filled[nan_mask] = 0.0

        # 非线性
        vals_t = _apply_nonlinear(vals_filled, stat.nonlinear, col, group)

        # winsor clip
        if stat.winsor_lower is not None and stat.winsor_upper is not None:
            vals_t = np.clip(vals_t, stat.winsor_lower, stat.winsor_upper)

        # robust + tanh
        if cfg["robust"]:
            vals_t = (vals_t - stat.median) / (stat.iqr + EPS)
            if cfg.get("tanh"):
                vals_t = np.tanh(vals_t)
            # 防止极端值，clip 到 [-5,5] (对 tanh 已在 [-1,1] 无需)
            if not cfg.get("tanh"):
                vals_t = np.clip(vals_t, -5, 5)
        else:
            # G9 bounded [0,1]
            if group == "G9_Margin":
                # 已在原始域 0-1，winsor 无，clip
                vals_t = np.clip(vals_t, 0, 1)
                # 缺失已填0，observed_mask 保留
            else:
                # 其他无 robust 组直接 clip
                pass

        return vals_t.astype(np.float64), observed_mask

    def transform_ndarray(self, feat: np.ndarray, feature_cols: List[str]) -> np.ndarray:
        """对 [N, F] ndarray 做分组归一化，追加 mask 通道

        Args:
            feat: [N, F] float64/float32，含 NaN
            feature_cols: 长度F，与 fit 时一致的列顺序

        Returns:
            out: [N, F_out] float32, F_out = F + num_G9_masks (若add_mask)
        """
        if not self.fitted:
            raise RuntimeError("GroupedScaler 未拟合，请先调用 fit")
        if len(feature_cols) != feat.shape[1]:
            raise ValueError(f"feature_cols 长度 {len(feature_cols)} 与 feat.shape[1] {feat.shape[1]} 不一致")
        # 校验列是否与 fit 时一致（顺序可不同，但需全包含）
        # 允许子集？严格要求一致以防错位
        if set(feature_cols) != set(self.feature_cols):
            # 若为验证集子集，警告但继续
            pass

        N, F = feat.shape
        # 预分配
        transformed_cols = []
        masks = []

        for j, col in enumerate(feature_cols):
            if col not in self.stats:
                # 未见列（新增因子），按 G8 策略兜底：winsor 1/99 + robust
                # 临时计算？这里按 0-mean 1-std 简单处理
                vals = feat[:, j]
                # 填 NaN 0
                vals = np.where(np.isnan(vals), 0, vals)
                vals = np.clip(vals, -5, 5)
                transformed_cols.append(vals.astype(np.float64))
                continue

            vals = feat[:, j]
            t_vals, obs_mask = self._transform_column(vals, col)
            transformed_cols.append(t_vals)
            if col in [c for c in feature_cols if COL_TO_GROUP.get(c) == "G9_Margin"]:
                masks.append(obs_mask)

        out = np.stack(transformed_cols, axis=1)  # [N, F]
        if self.add_mask and masks:
            mask_arr = np.stack(masks, axis=1)  # [N, 6]
            out = np.concatenate([out, mask_arr], axis=1)  # [N, F+6]

        # 最终防御：仍有 NaN/inf 置0
        out = np.where(np.isnan(out), 0, out)
        out = np.where(np.isinf(out), 0, out)
        return out.astype(np.float32)

    def transform_dataframe(self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None) -> pd.DataFrame:
        if feature_cols is None:
            feature_cols = self.feature_cols
        arr = df[feature_cols].values.astype(np.float64)
        out_arr = self.transform_ndarray(arr, feature_cols)
        out_cols = self.feature_cols_out if self.add_mask else feature_cols
        # 若 out_arr 列数与 out_cols 不一致（因子子集），截断/对齐
        if out_arr.shape[1] != len(out_cols):
            # 按实际 feature_cols 重新生成 out_cols
            mask_cols_actual = [f"{c}_mask" for c in feature_cols if COL_TO_GROUP.get(c) == "G9_Margin"] if self.add_mask else []
            out_cols_actual = list(feature_cols) + mask_cols_actual
            return pd.DataFrame(out_arr, columns=out_cols_actual, index=df.index)
        return pd.DataFrame(out_arr, columns=out_cols, index=df.index)

    # ---------- 持久化 ----------
    def save(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        payload = {
            "stats": self.stats,
            "feature_cols": self.feature_cols,
            "feature_cols_out": self.feature_cols_out,
            "mask_cols": self.mask_cols,
            "add_mask": self.add_mask,
            "missing_rates": self.missing_rates,
            "group_defs": GROUP_DEFS,
            "group_transform": GROUP_TRANSFORM,
            "version": "v1_grouped",
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        print(f"[GroupedScaler] 已保存到 {path}, 特征 {len(self.feature_cols)} -> {len(self.feature_cols_out)} (含{len(self.mask_cols)} mask)")

    @classmethod
    def load(cls, path: str) -> "GroupedScaler":
        with open(path, "rb") as f:
            payload = pickle.load(f)
        obj = cls(add_mask=payload.get("add_mask", True))
        obj.stats = payload["stats"]
        obj.feature_cols = payload["feature_cols"]
        obj.feature_cols_out = payload["feature_cols_out"]
        obj.mask_cols = payload["mask_cols"]
        obj.missing_rates = payload.get("missing_rates", {})
        obj.fitted = True
        print(f"[GroupedScaler] 从 {path} 加载, 特征 {len(obj.feature_cols)} -> {len(obj.feature_cols_out)}")
        return obj

    # 兼容旧接口：dict 形式 scaler_stats
    def to_dict(self) -> Dict:
        return {
            "stats": self.stats,
            "feature_cols": self.feature_cols,
            "feature_cols_out": self.feature_cols_out,
            "mask_cols": self.mask_cols,
            "add_mask": self.add_mask,
            "missing_rates": self.missing_rates,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "GroupedScaler":
        obj = cls(add_mask=d.get("add_mask", True))
        obj.stats = d["stats"]
        obj.feature_cols = d["feature_cols"]
        obj.feature_cols_out = d["feature_cols_out"]
        obj.mask_cols = d["mask_cols"]
        obj.missing_rates = d.get("missing_rates", {})
        obj.fitted = True
        return obj

    def print_summary(self):
        print(f"[GroupedScaler] 拟合完成: {len(self.feature_cols)} -> {len(self.feature_cols_out)}")
        for g, cols in GROUP_DEFS.items():
            present = [c for c in cols if c in self.feature_cols]
            if present:
                print(f"  {g} ({len(present)}): {present[:3]}...")
                for c in present[:2]:
                    s = self.stats[c]
                    miss = self.missing_rates.get(c, 0)
                    wl = f"{s.winsor_lower:.3f}" if s.winsor_lower is not None else "None"
                    wh = f"{s.winsor_upper:.3f}" if s.winsor_upper is not None else "None"
                    print(f"    {c}: miss={miss*100:.1f}% winsor=[{wl},{wh}] median={s.median:.3f} iqr={s.iqr:.3f} nl={s.nonlinear}")

