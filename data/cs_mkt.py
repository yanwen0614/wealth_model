"""截面 rank / 全市场因子：自 data.dataset 纯移动（T11 零逻辑改动）。

 canonical 位置：本模块为截面特征的唯一事实源；data.dataset 仅保留
 ParquetDataset._resolve/_compute_* 薄包装以兼容旧导入路径。
 约束：cs/mkt 列旁路归一化、缺失填充与列序契约均与移动前逐位一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.schema import (
    DEFAULT_CS_RANK_FEATURES,
    DEFAULT_MKT_FACTOR_FEATURES,
    MKT_FACTOR_NEUTRAL,
)

# 截面 rank 缺失（原始值 NaN/inf 或当日无有效截面）时的中性填充：rank∈[0,1] 的中位数。
CS_RANK_FILL = 0.5


def resolve_cs_rank_features(feature_cols: list[str], requested: list[str] | None) -> list[str]:
    """解析 cs_rank 特征子集：缺省用 DEFAULT_CS_RANK_FEATURES，去重保序并校验属于 feature_cols。"""
    features = list(DEFAULT_CS_RANK_FEATURES if requested is None else requested)
    features = list(dict.fromkeys(features))
    unknown = [column for column in features if column not in feature_cols]
    if unknown:
        raise ValueError(f"cs_rank_features 不在 feature_cols 中: {unknown}")
    return features


def compute_cross_sectional_rank(df: pd.DataFrame, cs_features: list[str]) -> None:
    """就地新增 `cs_<feature>`：按 kline_time 逐日全市场百分位 rank(pct=True)。

    必须在 sort_values(["code","kline_time"]) 分组与 max_codes 截断之前调用，保证截面
    覆盖全部股票（含 `_transform_context=True` 的真实历史 warmup 行）。原始 NaN/inf 不
    参与 rank，输出 NaN 由下游统一填中性值。
    """
    for column in cs_features:
        values = pd.to_numeric(df[column], errors="coerce")
        values = values.where(np.isfinite(values))
        df[f"cs_{column}"] = values.groupby(df["kline_time"].to_numpy()).rank(pct=True)
    print(f"[ParquetDataset] 截面 rank: {len(cs_features)} 列 (全市场逐日 pct), 例: cs_{cs_features[0]}")


def resolve_mkt_factor_list(requested: list[str] | None) -> list[str]:
    """解析市场因子子集：缺省用 DEFAULT_MKT_FACTOR_FEATURES，去重保序并校验为已知因子。"""
    factors = list(DEFAULT_MKT_FACTOR_FEATURES if requested is None else requested)
    factors = list(dict.fromkeys(factors))
    unknown = [column for column in factors if column not in MKT_FACTOR_NEUTRAL]
    if unknown:
        raise ValueError(f"mkt_factor_list 含未知市场因子: {unknown}")
    return factors


def compute_market_factors(df: pd.DataFrame, mkt_features: list[str]) -> None:
    """就地新增 `mkt_*` 列：按 kline_time 逐日用全体股票计算后广播到当日所有股票。

    每个因子精确定义（`ret = close/open-1`，仅 open>0 且有限的行参与截面统计）：
    - `mkt_breadth_up`：当日上涨占比 = mean(ret > 0) ∈ [0,1]
    - `mkt_breadth_ma20`：站上 MA20 占比 = mean(close > ma_20) ∈ [0,1]（ma_20 缺席则当日无值）
    - `mkt_dispersion`：截面收益标准差 = std(ret)（当日有效值 <2 则无值）
    - `mkt_mom_5d/10d/20d`：等权市场过去 N 日累计收益 = prod(1+mkt_ret)-1，
      其中 `mkt_ret[d] = mean(ret)` 为当日截面平均，要求过去 N 日（含当日）均有值
    - `mkt_vol_20d`：市场已实现波动 = std(mkt_ret[d-19..d])（20 日滚动，要求满 20 日）
    - `mkt_turnover`：平均换手 = mean(volume/(TOT_SHARE*1e4))（volume/TOT_SHARE 缺席则无值）
    - `mkt_limit_up`：涨停占比 ≈ mean(ret >= 0.095)（10% 涨停近似，取 0.095 容差）
    - `mkt_limit_down`：跌停占比 ≈ mean(ret <= -0.095)
    - `mkt_skew`：截面收益偏度 = skew(ret)（当日有效值 <3 则无值）

    缺失处理：历史窗口不足的早期日期（如 mom_20/vol_20 前 19 天）与所需原始列
    缺席（如 mini 合成数据无 volume/TOT_SHARE/ma_20）时输出 NaN，由下游按
    `MKT_FACTOR_NEUTRAL`（占比类 0.5，其余 0.0）填充。必须在 max_codes 截断前调用。
    """
    dates = pd.to_datetime(df["kline_time"])
    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=np.float64)
    open_arr = pd.to_numeric(df["open"], errors="coerce").to_numpy(dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.where(np.isfinite(close) & np.isfinite(open_arr) & (open_arr > 0),
                       close / open_arr - 1.0, np.nan)
    ret = np.where(np.isfinite(ret), ret, np.nan)
    frame = pd.DataFrame({"kline_time": dates, "ret": ret})
    if "ma_20" in df.columns:
        ma20 = pd.to_numeric(df["ma_20"], errors="coerce").to_numpy(dtype=np.float64)
        frame["above_ma20"] = np.where(np.isfinite(close) & np.isfinite(ma20), close > ma20, np.nan)
    if "volume" in df.columns and "TOT_SHARE" in df.columns:
        vol = pd.to_numeric(df["volume"], errors="coerce").to_numpy(dtype=np.float64)
        shr = pd.to_numeric(df["TOT_SHARE"], errors="coerce").to_numpy(dtype=np.float64)
        with np.errstate(divide="ignore", invalid="ignore"):
            turnover = np.where(np.isfinite(vol) & np.isfinite(shr) & (shr > 0),
                                vol / (shr * 1e4), np.nan)
        frame["turnover"] = np.where(np.isfinite(turnover), turnover, np.nan)

    grouped = frame.groupby("kline_time", sort=True)
    breadth_up = grouped["ret"].apply(lambda s: float(np.mean(s.to_numpy() > 0)) if s.count() else np.nan)
    dispersion = grouped["ret"].std(ddof=1)
    skew = grouped["ret"].apply(lambda s: float(s.skew()) if s.count() >= 3 else np.nan)
    limit_up = grouped["ret"].apply(lambda s: float(np.mean(s.to_numpy() >= 0.095)) if s.count() else np.nan)
    limit_down = grouped["ret"].apply(lambda s: float(np.mean(s.to_numpy() <= -0.095)) if s.count() else np.nan)
    if "above_ma20" in frame.columns:
        breadth_ma20 = grouped["above_ma20"].mean()
    else:
        breadth_ma20 = pd.Series(np.nan, index=breadth_up.index)
    if "turnover" in frame.columns:
        turnover_d = grouped["turnover"].mean()
    else:
        turnover_d = pd.Series(np.nan, index=breadth_up.index)

    mkt_ret = grouped["ret"].mean().sort_index()
    mom_5d = (1.0 + mkt_ret).rolling(5, min_periods=5).apply(np.prod, raw=True) - 1.0
    mom_10d = (1.0 + mkt_ret).rolling(10, min_periods=10).apply(np.prod, raw=True) - 1.0
    mom_20d = (1.0 + mkt_ret).rolling(20, min_periods=20).apply(np.prod, raw=True) - 1.0
    vol_20d = mkt_ret.rolling(20, min_periods=20).std(ddof=1)

    daily = pd.DataFrame({
        "mkt_breadth_up": breadth_up, "mkt_breadth_ma20": breadth_ma20,
        "mkt_dispersion": dispersion, "mkt_mom_5d": mom_5d, "mkt_mom_10d": mom_10d,
        "mkt_mom_20d": mom_20d, "mkt_vol_20d": vol_20d, "mkt_turnover": turnover_d,
        "mkt_limit_up": limit_up, "mkt_limit_down": limit_down, "mkt_skew": skew,
    })
    keys = dates.dt.tz_localize(None) if getattr(dates.dt, "tz", None) is not None else dates
    daily.index = pd.to_datetime(daily.index).tz_localize(None)
    for column in mkt_features:
        df[column] = keys.map(daily[column]).to_numpy(dtype=np.float64)
    print(f"[ParquetDataset] 市场因子: {len(mkt_features)} 列 (全市场逐日广播), 例: {mkt_features[0]}")
