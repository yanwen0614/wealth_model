"""Parquet -> 训练 数据集：对接 quant 最新因子数据 train_data_v1_*.parquet

数据契约（见 quant/scripts/export_training_data.py）：
- OHLC/close = 后复权；amount=真实元；volume=真实股；TOT_SHARE=万股
- is_trading=False 为合成行：OHLC/因子=NaN、volume/amount=0，训练侧必须过滤 is_trading
- 48 因子 = EXPORT_FACTORS，含 gross_margin 5094/5194 结构性缺席等
- 训练/回测口径统一，产物可复现（指纹含 git hash + 数据快照）

本模块职责：
- 读取单文件 parquet（11M+ 行，5166 股，2013-2025）
- 按 code 分组、按 kline_time 排序、过滤 is_trading
- 计算未来 N 日收益率标签（open-open 口径 open[t+1+horizon]/open[t+1]-1，与回测实盘 T+1 open 买入口径对齐）
- label_mode 标签口径：absolute（默认, 原始未来收益）/ excess（按 kline_time 剔除当日截面均值，剥离市场 beta）
- 依据 BINS 离散化为多分类标签（与 main2.py EMDLoss 配套）
- 滑动窗口生成 [seq_len, num_features] 样本，默认输出 F=53（52 特征 + 1 shared G9 mask）
- 构建全局索引，支持 DataLoader 多进程

与旧 NPZ 链路对比：
- 旧：processed_data_train/*.npz，每样本 train_features [8,60], labels [5,8] -> sum amp -> digitize
- 新：parquet 直读，无需中间 npz，特征维度 52，标签为未来 5日累计收益

归一化模式（normalize）：
- relative：P 组 x/close[t-1]-1 + clip±5，R asinh、N clip01、G fixed_clip，无 fit、无持久 state
- per_code：P 组按股 fit robust(median/IQR)，其余确定性；训练集拟合，验证集复用防泄露
- rolling：scope e0..e5 因果滚动；fallback per-code 由训练集 fit 一次，验证/评估复用
"""
import hashlib
import json
import os
import pickle
from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import DataLoader, Dataset

from data.feature_cache import (
    FeatureCache,
    _WindowIndex,
    compute_bins_digest,
    compute_cache_key,
    resolve_cache_root,
)
from data.labels import _cross_sectional_excess, _future_ret_open_open
from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import SCALER_VERSION, PerCodeGroupedScaler, RelativeScaler
from data.schema import (  # noqa: F401
    BASE_COLUMNS,
    DEFAULT_CS_RANK_FEATURES,
    DEFAULT_MKT_FACTOR_FEATURES,
    EXPORT_FACTORS,
    MKT_FACTOR_NEUTRAL,
    _default_feature_cols,
)

# 截面 rank 缺失（原始值 NaN/inf 或当日无有效截面）时的中性填充：rank∈[0,1] 的中位数。
CS_RANK_FILL = 0.5


@dataclass
class ParquetDataConfig:
    # 默认指向当前 F60 schema（52 raw + 1 shared mask）的单文件 parquet；win32 实际路径由 train.py 按平台覆盖
    parquet_path: str = "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"
    seq_len: int = 60
    horizon: int = 10  # 未来 N 日收益作为标签
    bins: list[float] = field(default_factory=lambda: (np.linspace(-38, 38, 51) / 100).tolist())
    batch_size: int = 256
    num_workers: int = 4
    # 特征列：None 时自动推导（排除 code/kline_time/is_trading，保留全部数值列）
    # 推荐显式传入以避免泄露：排除未来信息；默认排除 return_* 过去收益也可保留，按需配置
    feature_cols: list[str] | None = None
    # 过滤 is_trading（必须 True，避免合成行污染窗口）
    filter_is_trading: bool = True
    # 标签口径：
    # - "absolute"（默认，现有行为）：y = future_ret = open[t+1+horizon]/open[t+1]-1
    # - "excess"：y = future_ret - 当日（kline_time）截面均值，剥离市场 beta；
    #   截面均值在 is_trading 过滤后按日统计，仅纳入有限标签。
    # 注意：excess 模式下 groups["future_ret"] 保存的即最终超额收益（__getitem__ y_ret 同源），
    # 原始绝对收益不再单独保留（可由 open 价格按同口径重算）。
    label_mode: str = "absolute"
    # 截面 rank 特征（可选，默认关，不影响现有行为）：
    # - cs_rank=True 时在按 code 分组之前、全市场（含 context warmup 行）按 kline_time 逐日计算
    #   百分位 rank，必须在 max_codes 截断前完成，否则 rank 只相对少数股票、语义错误；
    # - cs_rank_features=None 用 data/schema.DEFAULT_CS_RANK_FEATURES（16 个独立特征）；
    # - 输出列 `cs_<feature>` 追加在归一化输出末尾并旁路归一化（rank∈[0,1] 绝不能再做时序归一化）。
    cs_rank: bool = False
    cs_rank_features: list[str] | None = None
    # 全市场截面因子（可选，默认关，不影响现有行为）：
    # - mkt_factors=True 时在按 code 分组之前、全市场（含 context warmup 行）按 kline_time 逐日计算
    #   M 个全市场因子（每日全股票共享的时间序列），必须在 max_codes 截断前完成，保证全市场口径；
    # - mkt_factor_list=None 用 data/schema.DEFAULT_MKT_FACTOR_FEATURES（11 个）；
    # - 输出列（列名即 `mkt_*`，不再加前缀）追加在归一化输出（含 mask）与 cs 列之后并旁路归一化
    #   （因子已是标准化时间序列：占比∈[0,1]、动量/波动/偏度为 z-score 量级，绝不能再做时序归一化）。
    mkt_factors: bool = False
    mkt_factor_list: list[str] | None = None
    # 数据集职责决定缓存失配时是否允许拟合。
    role: str = "training"  # "training" | "validation" | "evaluation"
    # 时间切分
    start_date: str | None = None  # "2013-01-01"
    end_date: str | None = None
    split_date: str | None = None  # 用于外部 train/val 划分，本 Dataset 内部可基于 start/end 过滤
    # 归一化：relative | per_code | none | rolling（per_code 为冻结默认；rolling/relative 显式 opt-in）
    normalize: str = "relative"
    # rolling 子集范围：e0..e5（默认 e5 = 含 G9 raw 全量；仅 rolling 分支使用）
    rolling_scope: str = "e5"
    # 归一化统计文件（训练集拟合后保存，供验证集复用）
    scaler_path: str | None = None
    # NaN 填充策略（仅 none 分支使用，per_code 内置分级填充）
    fill_method: str = "median"  # "median" | "zero"
    # 小样本调试：仅取前 N 只股票
    max_codes: int | None = None
    # 采样：每股最大窗口数（用于快速验证）
    max_windows_per_code: int | None = None
    # per_code 专用：是否添加 G9 mask
    per_code_add_mask: bool = True
    # feature memmap 磁盘缓存（默认关，train.py 默认开；见 data/feature_cache.py）
    cache_enabled: bool = False
    cache_dir: str | None = None  # None -> 由 resolve_cache_root 决定（env/平台默认）
    rebuild_cache: bool = False  # True 时跳过命中、强制重建并写新 generation


class _RollingDatasetState:
    """Training/validation rolling identity; it never fits or calls frozen code."""

    PAYLOAD_VERSION = "v2_rolling_state"

    def __init__(
        self,
        normalizer: RollingNormalizer,
        source_manifest: dict,
        feature_cols: list[str],
        fallback_scaler: PerCodeGroupedScaler,
    ):
        if not isinstance(fallback_scaler, PerCodeGroupedScaler):
            raise TypeError("rolling state fallback 必须是 PerCodeGroupedScaler")
        fallback_scaler.validate_requested_schema(feature_cols, fallback_scaler.add_mask)
        self.normalizer = normalizer
        self.source_manifest = source_manifest
        self.feature_cols = list(feature_cols)
        self.fallback_scaler = fallback_scaler
        self.schema_manifest = {
            **normalizer.schema_manifest(feature_cols),
            "fallback": {
                "mode": "per_code",
                "version": SCALER_VERSION,
                "transform_digest": PerCodeGroupedScaler.transform_config_digest(),
                "feature_cols_out": list(fallback_scaler.feature_cols_out),
                "identity_hash": fallback_scaler.identity_hash,
            },
        }
        self.identity_manifest = {
            "preprocessing": self.schema_manifest,
            "source": json.loads(json.dumps(source_manifest, sort_keys=True)),
        }
        self.identity_hash = self._identity_hash(self.identity_manifest)

    @staticmethod
    def _identity_hash(manifest: dict) -> str:
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def validate(self, source_manifest: dict, feature_cols: list[str], scope: str | None = None) -> None:
        self.fallback_scaler.validate_requested_schema(feature_cols, self.fallback_scaler.add_mask)
        if scope is not None and self.normalizer.config.scope != scope:
            raise ValueError(
                f"rolling scope 不匹配：state={self.normalizer.config.scope!r} vs 请求={scope!r}"
            )
        requested_manifest = {
            "preprocessing": self.schema_manifest,
            "source": json.loads(json.dumps(source_manifest, sort_keys=True)),
        }
        requested = self._identity_hash(requested_manifest)
        if requested != self.identity_hash:
            raise ValueError("rolling preprocessing identity 不匹配")
        if self.feature_cols != list(feature_cols):
            raise ValueError("rolling feature schema 不匹配")

    def save(self, path: str) -> None:
        payload = {
            "version": self.PAYLOAD_VERSION,
            "mode": "rolling",
            "normalizer_config": self.normalizer.config.__dict__,
            "source_manifest": self.source_manifest,
            "feature_cols": self.feature_cols,
            "schema_manifest": self.schema_manifest,
            "identity_manifest": self.identity_manifest,
            "identity_hash": self.identity_hash,
            "fallback_scaler": self.fallback_scaler,
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as file:
            pickle.dump(payload, file)

    @classmethod
    def load(cls, path: str) -> "_RollingDatasetState":
        with open(path, "rb") as file:
            payload = pickle.load(file)
        required = {
            "version", "mode", "normalizer_config", "source_manifest", "feature_cols",
            "schema_manifest", "identity_manifest", "identity_hash", "fallback_scaler",
        }
        if not isinstance(payload, dict) or payload.get("version") != cls.PAYLOAD_VERSION:
            raise ValueError("不支持的 rolling state payload")
        if payload.get("mode") != "rolling" or not required.issubset(payload):
            raise ValueError("rolling state payload schema 不匹配")
        normalizer = RollingNormalizer(RollingNormalizationConfig(**payload["normalizer_config"]))
        fallback_scaler = payload["fallback_scaler"]
        if not isinstance(fallback_scaler, PerCodeGroupedScaler):
            raise TypeError("rolling state fallback payload 类型不匹配")
        state = cls(normalizer, payload["source_manifest"], payload["feature_cols"], fallback_scaler)
        if (
            state.schema_manifest != payload["schema_manifest"]
            or state.identity_manifest != payload["identity_manifest"]
            or state.identity_hash != payload["identity_hash"]
        ):
            raise ValueError("rolling state identity 不匹配")
        return state


class ParquetDataset(Dataset):
    """基于单文件 parquet 的滑动窗口数据集

    每个样本：
      x: [num_features, seq_len]  float32  (当前默认输出为 51 raw + 18 G9 mask)
      y: int  (digitized future return)

    索引构建：
      按 code 分组后，对每组计算 future_ret = open[t+1+horizon]/open[t+1] - 1
      （T+1 open 买入 -> T+1+horizon open 卖出，与回测实盘口径对齐）
      有效条件: open[t+1] 与 open[t+1+horizon] 均非 NaN 且 open[t+1] > 0
      有效窗口需满足: 窗口末端 t=s+seq_len-1 有 t+1+horizon <= n-1，
      且窗口末端对应的 future_ret 非 NaN
    """

    def __init__(self, config: ParquetDataConfig, scaler_stats: dict | object | None = None):
        if not config.filter_is_trading:
            raise ValueError("filter_is_trading 必须为 True，禁止将合成行用于训练/评估")
        if config.role not in {"training", "validation", "evaluation"}:
            raise ValueError(f"未知 dataset role: {config.role}")
        if config.label_mode not in {"absolute", "excess"}:
            raise ValueError(f"未知 label_mode: {config.label_mode}, 可选 absolute/excess")
        self.config = config
        self.bins = np.array(config.bins, dtype=np.float64)

        # 1. 读取 parquet
        self._load_and_prepare(scaler_stats)

    @staticmethod
    def _transform_digest(normalize: str) -> str:
        """按归一化模式取变换配置摘要：relative 无统计量，per_code/rolling 用 frozen 规则。"""
        if normalize == "relative":
            return RelativeScaler.transform_config_digest()
        return PerCodeGroupedScaler.transform_config_digest()

    @staticmethod
    def _resolve_cs_rank_features(feature_cols: list[str], requested: list[str] | None) -> list[str]:
        """解析 cs_rank 特征子集：缺省用 DEFAULT_CS_RANK_FEATURES，去重保序并校验属于 feature_cols。"""
        features = list(DEFAULT_CS_RANK_FEATURES if requested is None else requested)
        features = list(dict.fromkeys(features))
        unknown = [column for column in features if column not in feature_cols]
        if unknown:
            raise ValueError(f"cs_rank_features 不在 feature_cols 中: {unknown}")
        return features

    @staticmethod
    def _compute_cross_sectional_rank(df: pd.DataFrame, cs_features: list[str]) -> None:
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

    @staticmethod
    def _resolve_mkt_factor_list(requested: list[str] | None) -> list[str]:
        """解析市场因子子集：缺省用 DEFAULT_MKT_FACTOR_FEATURES，去重保序并校验为已知因子。"""
        factors = list(DEFAULT_MKT_FACTOR_FEATURES if requested is None else requested)
        factors = list(dict.fromkeys(factors))
        unknown = [column for column in factors if column not in MKT_FACTOR_NEUTRAL]
        if unknown:
            raise ValueError(f"mkt_factor_list 含未知市场因子: {unknown}")
        return factors

    @staticmethod
    def _compute_market_factors(df: pd.DataFrame, mkt_features: list[str]) -> None:
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

    @staticmethod
    def _scaler_identity(cfg: ParquetDataConfig, pf: pq.ParquetFile, feature_cols: list[str]) -> dict:
        path = os.path.realpath(cfg.parquet_path)
        stat = os.stat(path)
        metadata = pf.metadata
        schema = str(pf.schema_arrow)
        identity = {
            "parquet_path": path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "row_count": metadata.num_rows, "schema_fingerprint": hashlib.sha256(schema.encode()).hexdigest(),
            "fit_start_date": cfg.start_date, "fit_end_date": cfg.end_date,
            "feature_cols": list(feature_cols), "normalize": cfg.normalize,
            "per_code_add_mask": cfg.per_code_add_mask, "filter_is_trading": cfg.filter_is_trading,
            "max_codes": cfg.max_codes, "transform_digest": ParquetDataset._transform_digest(cfg.normalize),
            "scaler_version": SCALER_VERSION,
        }
        # rolling_scope 仅 rolling 有意义；写入后由 _rolling_source_identity 剔除，保持 per_code 字节不变。
        if cfg.normalize == "rolling":
            identity["rolling_scope"] = cfg.rolling_scope
        return identity

    @staticmethod
    def _rolling_source_identity(expected_identity: dict) -> dict:
        """rolling 的 source identity：剔除仅影响 frozen 拟合/调试/scope 的字段（与 _RollingDatasetState 一致）。"""
        source_identity = dict(expected_identity)
        for key in (
            "fit_start_date", "fit_end_date", "transform_digest", "scaler_version", "max_codes", "rolling_scope"
        ):
            source_identity.pop(key, None)
        return source_identity

    @staticmethod
    def _cache_key(
        cfg: ParquetDataConfig,
        bins: np.ndarray,
        expected_identity: dict,
        feature_cols: list[str],
    ) -> str:
        """由 data identity + role/scope/scaler identity/seq/horizon/max_windows/bins 派生缓存 key。

        key 必须对 train/val、per_code/rolling、E2/E3/E4 scope、seq_len/horizon/max_windows/bins
        任一变化敏感，避免跨配置串缓存。
        """
        if cfg.normalize == "per_code":
            scaler_identity_hash: str | None = PerCodeGroupedScaler.identity_hash_for(expected_identity)
            rolling_scope: str | None = None
        elif cfg.normalize == "rolling":
            normalizer = RollingNormalizer(RollingNormalizationConfig(scope=cfg.rolling_scope))
            source_identity = ParquetDataset._rolling_source_identity(expected_identity)
            scaler_identity_hash = normalizer.identity(source_identity, feature_cols)
            rolling_scope = cfg.rolling_scope
        elif cfg.normalize == "relative":
            # relative 无持久 state：identity 即 COLUMN_RULES/版本/mask 策略摘要。
            scaler_identity_hash = RelativeScaler.transform_config_digest()
            rolling_scope = None
        else:
            scaler_identity_hash = None
            rolling_scope = None
        return compute_cache_key(
            base_identity=expected_identity,
            role=cfg.role,
            rolling_scope=rolling_scope,
            scaler_identity_hash=scaler_identity_hash,
            seq_len=cfg.seq_len,
            horizon=cfg.horizon,
            max_windows_per_code=cfg.max_windows_per_code,
            bins_digest=compute_bins_digest([float(b) for b in bins]),
            label_mode=cfg.label_mode,
            cs_rank=cfg.cs_rank,
            cs_rank_features=ParquetDataset._resolve_cs_rank_features(feature_cols, cfg.cs_rank_features)
            if cfg.cs_rank else None,
            mkt_factors=cfg.mkt_factors,
            mkt_factor_list=ParquetDataset._resolve_mkt_factor_list(cfg.mkt_factor_list)
            if cfg.mkt_factors else None,
        )

    def _load_and_prepare(self, scaler_stats: dict | object | None):
        cfg = self.config
        pf = pq.ParquetFile(cfg.parquet_path)
        # 快速校验列
        all_cols = pf.schema.names
        if cfg.feature_cols is not None:
            feature_cols = list(cfg.feature_cols)
        else:
            feature_cols = _default_feature_cols(all_cols)

        # 验证特征列存在
        missing = [c for c in feature_cols if c not in all_cols]
        if missing:
            raise ValueError(f"特征列缺失于 parquet: {missing}, 可用列: {all_cols[:10]}...")

        self.feature_cols = feature_cols  # 输入 raw 特征列（默认 F=51）
        self.feature_cols_out = list(feature_cols)  # 输出特征列（per_code 可能追加 mask）
        self.num_features = len(feature_cols)
        # cs_rank 配置在两条路径（缓存命中/未命中）都可用：cs 列名确定性由 feature_cols + 请求派生。
        self.cs_rank_features = (
            self._resolve_cs_rank_features(feature_cols, cfg.cs_rank_features) if cfg.cs_rank else []
        )
        self.cs_rank_cols = [f"cs_{column}" for column in self.cs_rank_features]
        # 市场因子列名即 `mkt_*` 本身（不再加前缀），不依赖 feature_cols，直接校验已知因子。
        self.mkt_factor_features = (
            self._resolve_mkt_factor_list(cfg.mkt_factor_list) if cfg.mkt_factors else []
        )
        self.mkt_factor_cols = list(self.mkt_factor_features)
        expected_identity = self._scaler_identity(cfg, pf, feature_cols)
        print(f"[ParquetDataset] 特征列数: {self.num_features}, 特征: {feature_cols[:8]}...")

        cache_key = self._cache_key(cfg, self.bins, expected_identity, feature_cols)
        if cfg.cache_enabled and not cfg.rebuild_cache:
            cache_data = FeatureCache.load(resolve_cache_root(cfg.cache_dir), cache_key)
            if cache_data is not None:
                self._apply_cache_hit(cache_data, scaler_stats, expected_identity, feature_cols)
                return

        # 读取全表（11M 行，约 3.5G parquet，内存约 4-5G）
        # 使用 pyarrow 读取后转 pandas，按需过滤日期
        print(f"[ParquetDataset] 读取 parquet: {cfg.parquet_path}")
        # 仅读取需要的列以降低内存；市场因子需额外原始列（ma_20/volume/TOT_SHARE/high/low），
        # 仅当 parquet schema 存在时才读（mini 合成数据缺席则下游填中性值）。
        read_cols = ["code", "kline_time", "close", "open", "is_trading"] + feature_cols
        if cfg.mkt_factors:
            for extra in ("ma_20", "high", "low", "volume", "TOT_SHARE"):
                if extra in all_cols:
                    read_cols.append(extra)
        # 去重
        read_cols = list(dict.fromkeys(read_cols))
        table = pq.read_table(cfg.parquet_path, columns=read_cols)
        df = table.to_pandas()
        print(f"[ParquetDataset] 原始行数: {len(df):,}, 列数: {len(df.columns)}")

        # is_trading 已在构造时强制为 True。
        before = len(df)
        df = df[df["is_trading"] == True]
        print(f"[ParquetDataset] 过滤 is_trading False: {before:,} -> {len(df):,} (drop {before - len(df):,})")

        # 时间过滤；frozen 只保留一行 relative context，rolling validation 可保留 251 行。
        df["kline_time"] = pd.to_datetime(df["kline_time"])
        df["_transform_context"] = False
        if cfg.start_date:
            start = pd.to_datetime(cfg.start_date)
            eligible = df[df["kline_time"] >= start]
            # context 保留上限：rolling 非训练沿用 251（归一化统计预热），其余场景至少 seq_len-1
            # 行以让首个真实交易日凑满窗口；两者取大，保证 warmup 输入充足。
            if cfg.normalize == "rolling" and cfg.role != "training":
                context_limit = max(cfg.seq_len - 1, 251)
            else:
                context_limit = max(cfg.seq_len - 1, 1)
            context = (
                df[df["kline_time"] < start].sort_values("kline_time")
                .groupby("code", sort=False).tail(context_limit)
            )
            context = context[context["code"].isin(eligible["code"].unique())].copy()
            context["_transform_context"] = True
            df = pd.concat([context, eligible], ignore_index=True)
        if cfg.end_date:
            df = df[df["kline_time"] <= pd.to_datetime(cfg.end_date)]
        print(f"[ParquetDataset] 时间过滤后: {len(df):,} 行, 范围 {df['kline_time'].min()} -> {df['kline_time'].max()}")

        # 截面 rank：必须在按 code 分组/排序与 max_codes 截断之前，在全体股票（含 context 行）
        # 的逐日截面上计算；否则 rank 只相对被保留的少数股票，语义错误。
        if cfg.cs_rank:
            self._compute_cross_sectional_rank(df, self.cs_rank_features)

        # 市场因子：与 cs_rank 同处（时间过滤后、分组与 max_codes 截断前），全市场逐日计算后广播。
        if cfg.mkt_factors:
            self._compute_market_factors(df, self.mkt_factor_features)

        # 按 code 分组排序
        df = cast(Any, df).sort_values(["code", "kline_time"]).reset_index(drop=True)

        # 限制调试股票数
        codes = df["code"].unique()
        if cfg.max_codes is not None and len(codes) > cfg.max_codes:
            keep_codes = list(codes[: cfg.max_codes])
            df = df[df["code"].isin(keep_codes)]
            print(f"[ParquetDataset] 限制 max_codes={cfg.max_codes}, 保留 {len(keep_codes)} 只, 行数 {len(df):,}")

        # 2. 归一化统计
        # per_code 支持外部传入 scaler_stats / 文件持久化 / 验证集复用
        if cfg.normalize == "per_code":
            self.scaler_stats = None
            if scaler_stats is not None:
                if not isinstance(scaler_stats, PerCodeGroupedScaler):
                    raise ValueError("外部 scaler_stats 必须是有效的 PerCodeGroupedScaler v3 对象")
                if not scaler_stats.fitted:
                    raise ValueError("外部 scaler_stats 未拟合")
                if not scaler_stats.identity_manifest or not scaler_stats.identity_hash:
                    raise ValueError("外部 scaler_stats 缺少训练 identity")
                scaler_stats.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                self.scaler_stats = scaler_stats
                print("[ParquetDataset] 使用外部传入的 scaler_stats (per_code)")
                if hasattr(self.scaler_stats, "feature_cols_out"):
                    self.feature_cols_out = self.scaler_stats.feature_cols_out
                    self.num_features = len(self.feature_cols_out)
            elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
                try:
                    cached = PerCodeGroupedScaler.load(cfg.scaler_path)
                    cached.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                    if cached.identity_hash != PerCodeGroupedScaler.identity_hash_for(expected_identity):
                        raise ValueError("scaler cache identity 不匹配")
                    self.scaler_stats = cached
                    print(f"[ParquetDataset] 复用匹配的 {cfg.scaler_path} PerCodeGroupedScaler")
                except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                    print(f"[ParquetDataset] scaler cache 无效 ({e})，将在训练集重拟合")
                    self.scaler_stats = None
                if self.scaler_stats is not None:
                    self.feature_cols_out = self.scaler_stats.feature_cols_out
                    self.num_features = len(self.feature_cols_out)
            if self.scaler_stats is None:
                if cfg.role != "training":
                    raise ValueError(f"{cfg.role} 数据集必须提供兼容的已拟合训练 scaler")
                print(f"[ParquetDataset] 拟合 PerCodeGroupedScaler (add_mask={cfg.per_code_add_mask}) ...")
                scaler = PerCodeGroupedScaler(add_mask=cfg.per_code_add_mask)
                # 限制 feature_cols 剔除项：return_*/TOT_SHARE/volume/amount/close 已在上层 feature_cols 中剔除
                scaler.fit(df.loc[~df["_transform_context"]], feature_cols)
                scaler.set_identity(expected_identity)
                self.scaler_stats = scaler
                self.feature_cols_out = scaler.feature_cols_out
                self.num_features = len(self.feature_cols_out)
                print(f"[ParquetDataset] PerCodeGroupedScaler 拟合完成: {len(self.feature_cols)} -> {self.num_features} (per-code {len(scaler.per_code_stats)} 股)")
                if cfg.scaler_path:
                    scaler.save(cfg.scaler_path)
        elif cfg.normalize == "none":
            self.scaler_stats = None
            self.feature_cols_out = list(self.feature_cols)
            self.num_features = len(self.feature_cols_out)
        elif cfg.normalize == "rolling":
            normalizer = RollingNormalizer(RollingNormalizationConfig(scope=cfg.rolling_scope))
            source_identity = self._rolling_source_identity(expected_identity)
            if scaler_stats is None:
                if cfg.role != "training":
                    raise ValueError("validation rolling 数据集必须提供训练 rolling identity")
                fallback_scaler = PerCodeGroupedScaler(add_mask=cfg.per_code_add_mask)
                fallback_scaler.fit(df.loc[~df["_transform_context"]], feature_cols)
                fallback_identity = dict(expected_identity)
                fallback_identity["normalize"] = "rolling_fallback_per_code"
                fallback_scaler.set_identity(fallback_identity)
                self.scaler_stats = _RollingDatasetState(
                    normalizer, source_identity, feature_cols, fallback_scaler
                )
            else:
                if not isinstance(scaler_stats, _RollingDatasetState):
                    raise ValueError("外部 scaler_stats 必须是匹配的 rolling identity")
                scaler_stats.validate(source_identity, feature_cols, scope=cfg.rolling_scope)
                self.scaler_stats = scaler_stats
            self.feature_cols_out = normalizer.output_feature_cols(feature_cols)
            self.num_features = len(self.feature_cols_out)
            if scaler_stats is None and cfg.scaler_path:
                self.scaler_stats.save(cfg.scaler_path)
        elif cfg.normalize == "relative":
            # relative 无 fit / 无落盘 / 无持久 state：scaler_stats 仅是当期确定性变换器。
            scaler = RelativeScaler(feature_cols=feature_cols, add_mask=cfg.per_code_add_mask)
            if scaler_stats is not None:
                if not isinstance(scaler_stats, RelativeScaler):
                    raise ValueError("外部 scaler_stats 必须是 RelativeScaler（relative 无持久 state）")
                if list(scaler_stats.feature_cols_out) != list(scaler.feature_cols_out):
                    raise ValueError("relative scaler_stats feature schema 不匹配")
            self.scaler_stats = scaler
            self.feature_cols_out = scaler.feature_cols_out
            self.num_features = len(self.feature_cols_out)
        else:
            raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 relative/per_code/none/rolling")

        # 截面 rank 列追加在归一化输出（含 mask）之后并旁路归一化：列名与主循环拼接顺序严格一致。
        if self.cs_rank_cols:
            self.feature_cols_out = list(self.feature_cols_out) + list(self.cs_rank_cols)
            self.num_features = len(self.feature_cols_out)

        # 市场因子列追加在 cs 列之后并旁路归一化：最终列序 [归一化输出(含 mask)] + cs + mkt。
        if self.mkt_factor_cols:
            self.feature_cols_out = list(self.feature_cols_out) + list(self.mkt_factor_cols)
            self.num_features = len(self.feature_cols_out)

        print(f"[ParquetDataset] 输出特征列数: {self.num_features}, 输出特征: {self.feature_cols_out[:8]}...")

        # 3. 按 code 构建分组数据与索引
        self.groups: dict[str, dict] = {}
        self.index: list[tuple[str, int]] | _WindowIndex = []  # (code, window_start_pos)
        self.rolling_audit: dict[str, int | float] = {
            "total_rows": 0,
            "rolling_values": 0,
            "fallback_values": 0,
            "neutral_fallback_values": 0,
            "passthrough_values": 0,
            "missing_values": 0,
            "constant_iqr_values": 0,
            "fallback_ratio": 0.0,
        }

        # 统计
        total_windows = 0
        skipped_codes = 0
        grouped = df.groupby("code", sort=False)
        # per_code 分支：feat 变换移到循环内按 code 独立处理（_preprocess 已改为 per-code 内部用 close）
        for code, group in grouped:
            code = str(code)
            group = cast(Any, group).sort_values("kline_time")
            # 提取 features 矩阵 [N, num_features_in]
            feat = group[feature_cols].values.astype(np.float64)  # 先 float64 便于处理 NaN
            close = group["close"].values.astype(np.float64)
            open_arr = group["open"].values.astype(np.float64)
            # cs rank 提取为独立旁路矩阵：不进入 scaler/COLUMN_RULES，缺失填 neutral。
            cs_feat = None
            if self.cs_rank_cols:
                cs_feat = np.nan_to_num(
                    group[self.cs_rank_cols].values.astype(np.float64),
                    nan=CS_RANK_FILL, posinf=CS_RANK_FILL, neginf=CS_RANK_FILL,
                )
            # 市场因子提取为独立旁路矩阵：不进入 scaler，缺失按 MKT_FACTOR_NEUTRAL 逐列填充。
            mkt_feat = None
            if self.mkt_factor_cols:
                raw_mkt = group[self.mkt_factor_cols].values.astype(np.float64)
                fills = np.array([MKT_FACTOR_NEUTRAL[column] for column in self.mkt_factor_cols],
                                 dtype=np.float64)
                bad = ~np.isfinite(raw_mkt)
                raw_mkt[bad] = np.take(fills, np.broadcast_to(np.arange(len(fills)), bad.shape)[bad])
                mkt_feat = raw_mkt

            # NaN 填充 + 归一化（per_code / relative 按 code 独立）
            if cfg.normalize == "per_code":
                # per-code：需传入 close 供 P 组 relative
                if isinstance(self.scaler_stats, PerCodeGroupedScaler):
                    feat = self.scaler_stats.transform_code(code, feat, feature_cols, close)
            elif cfg.normalize == "relative":
                if not isinstance(self.scaler_stats, RelativeScaler):
                    raise ValueError("relative 数据集缺少有效 preprocessing")
                feat = self.scaler_stats.transform_code(code, feat, feature_cols, close)
            elif cfg.normalize == "rolling":
                if not isinstance(self.scaler_stats, _RollingDatasetState):
                    raise ValueError("rolling 数据集缺少有效 preprocessing identity")
                frozen_fallback = self.scaler_stats.fallback_scaler.transform_code(
                    code, feat, feature_cols, close
                )
                result = self.scaler_stats.normalizer.transform_code(
                    feat, feature_cols, close, frozen_fallback=frozen_fallback
                )
                feat = result.values
                for key, value in vars(result.audit).items():
                    self.rolling_audit[key] = int(self.rolling_audit[key]) + int(value)
            else:
                feat = self._preprocess_features(feat, feature_cols)

            # cs/mkt 输出列顺序 = 归一化输出（含 mask）后先 cs 后 mkt，与 feature_cols_out 一致。
            if cs_feat is not None:
                feat = np.concatenate([feat, cs_feat], axis=1)
            if mkt_feat is not None:
                feat = np.concatenate([feat, mkt_feat], axis=1)

            # context 保留为窗口 warmup 输入：group/feat/close/open_arr 保留全部行（context 在先），
            # 用 is_context 保证标签日恒为非 context 的真实交易日。
            is_context = group["_transform_context"].to_numpy()
            n = len(group)
            if n < cfg.seq_len + cfg.horizon + 1:
                skipped_codes += 1
                continue

            future_ret = _future_ret_open_open(open_arr, cfg.horizon)

            max_s = n - cfg.seq_len - cfg.horizon
            if max_s <= 0:
                skipped_codes += 1
                continue

            # 预先过滤 context 标签日与标签 NaN 的窗口
            valid_starts = []
            for s in range(max_s):
                label_pos = s + cfg.seq_len - 1
                if is_context[label_pos]:
                    continue
                if not np.isnan(future_ret[label_pos]):
                    # 可选：过滤特征窗口内全 NaN 过多的样本（已填充，此处可跳过）
                    valid_starts.append(s)

            # 限制每股最大窗口数（随机采样或截断）
            if cfg.max_windows_per_code is not None and len(valid_starts) > cfg.max_windows_per_code:
                # 均匀采样以保留时序覆盖
                idx = np.linspace(0, len(valid_starts) - 1, cfg.max_windows_per_code, dtype=int)
                valid_starts = [valid_starts[i] for i in idx]

            if not valid_starts:
                skipped_codes += 1
                continue

            # 存储该 code 的处理后数据
            # 为节省内存，将特征转为 float32
            feat = feat.astype(np.float32)
            future_ret = future_ret.astype(np.float32)
            # 离散化标签
            discrete = np.digitize(future_ret, self.bins).astype(np.int64)  # 0..len(bins)

            self.groups[code] = {
                "features": feat,  # [N, num_features_out]
                "future_ret": future_ret,
                "discrete": discrete,
                "kline_time": group["kline_time"].values,
                "n": n,
                "open": open_arr,
                "close": close,
            }
            for s in valid_starts:
                self.index.append((code, s))
            total_windows += len(valid_starts)

        print(f"[ParquetDataset] 分组完成: 保留 {len(self.groups)} 只股票, 跳过 {skipped_codes} 只 (长度不足/无有效标签)")
        print(f"[ParquetDataset] 总样本数 (窗口): {total_windows:,}")
        if cfg.normalize == "rolling":
            audited = int(self.rolling_audit["fallback_values"]) + int(
                self.rolling_audit["rolling_values"]
            )
            self.rolling_audit["fallback_ratio"] = (
                int(self.rolling_audit["fallback_values"]) / audited if audited else 0.0
            )
            print(
                "[ParquetDataset] rolling audit: "
                f"fallback_ratio={self.rolling_audit['fallback_ratio']:.6f}, "
                f"fallback={self.rolling_audit['fallback_values']}, "
                f"neutral={self.rolling_audit['neutral_fallback_values']}, "
                f"rolling={self.rolling_audit['rolling_values']}"
            )
        if total_windows == 0:
            raise ValueError("无有效样本，请检查数据过滤条件（is_trading/时间范围/特征列）")

        # 截面超额收益：在 groups 建成后、标签统计/缓存落盘前统一变换（不影响索引）
        if cfg.label_mode == "excess":
            self._apply_excess_labels()

        # 标签分布统计
        self._print_label_stats()

        if cfg.cache_enabled:
            self._save_cache(cache_key)

    def _apply_cache_hit(
        self,
        data,
        scaler_stats: dict | object | None,
        expected_identity: dict,
        feature_cols: list[str],
    ) -> None:
        """用磁盘缓存重建 groups/index，跳过 parquet 读取与归一化。"""
        self.feature_cols_out = list(data.feature_cols_out)
        self.num_features = int(data.num_features)
        default_audit: dict[str, int | float] = {
            "total_rows": 0, "rolling_values": 0, "fallback_values": 0,
            "neutral_fallback_values": 0, "passthrough_values": 0,
            "missing_values": 0, "constant_iqr_values": 0, "fallback_ratio": 0.0,
        }
        cached_audit = data.extra.get("rolling_audit") if isinstance(data.extra, dict) else None
        self.rolling_audit = {**default_audit, **cached_audit} if isinstance(cached_audit, dict) else default_audit
        self.groups = {}
        for position, code in enumerate(data.codes):
            offset = int(data.offsets[position])
            n = int(data.n_per_code[position])
            self.groups[code] = {
                "features": data.features.subview(offset, n),
                "future_ret": data.future_ret[offset: offset + n],
                "discrete": data.discrete[offset: offset + n],
                "kline_time": np.asarray(data.kline_time[offset: offset + n]).view("datetime64[ns]"),
                "n": n,
                "open": data.open[offset: offset + n],
                "close": data.close[offset: offset + n],
            }
        self.index = _WindowIndex(data.codes, data.window_code_ids, data.window_starts)
        # 命中路径不读 parquet，但仍执行既有的 validation scaler 校验红线（绝不重 fit）。
        self._resolve_scaler_on_cache_hit(scaler_stats, expected_identity, feature_cols)
        print(
            f"[ParquetDataset] 缓存命中: key={data.key}, 股票 {len(data.codes)} 只, "
            f"窗口 {len(self.index):,}, 特征 {self.num_features}, path={data.path}"
        )
        # 命中路径补标签分布统计，保持与 miss 路径日志一致。
        self._print_label_stats()

    def _resolve_scaler_on_cache_hit(
        self,
        scaler_stats: dict | object | None,
        expected_identity: dict,
        feature_cols: list[str],
    ) -> None:
        """缓存命中时不重 fit，只做与内存路径一致的 scaler identity/schema 校验。"""
        cfg = self.config
        if cfg.normalize == "per_code":
            self.scaler_stats = None
            if scaler_stats is not None:
                if not isinstance(scaler_stats, PerCodeGroupedScaler):
                    raise ValueError("外部 scaler_stats 必须是有效的 PerCodeGroupedScaler v3 对象")
                if not scaler_stats.fitted:
                    raise ValueError("外部 scaler_stats 未拟合")
                if not scaler_stats.identity_manifest or not scaler_stats.identity_hash:
                    raise ValueError("外部 scaler_stats 缺少训练 identity")
                scaler_stats.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                self.scaler_stats = scaler_stats
                print("[ParquetDataset] 使用外部传入的 scaler_stats (per_code)")
            elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
                try:
                    cached_scaler = PerCodeGroupedScaler.load(cfg.scaler_path)
                    cached_scaler.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                    if cached_scaler.identity_hash != PerCodeGroupedScaler.identity_hash_for(expected_identity):
                        raise ValueError("scaler cache identity 不匹配")
                    self.scaler_stats = cached_scaler
                    print(f"[ParquetDataset] 复用匹配的 {cfg.scaler_path} PerCodeGroupedScaler")
                except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                    print(f"[ParquetDataset] scaler cache 无效 ({e})")
                    self.scaler_stats = None
            if self.scaler_stats is None and cfg.role != "training":
                raise ValueError(f"{cfg.role} 数据集必须提供兼容的已拟合训练 scaler")
            if self.scaler_stats is None:
                # miss 路径会现场拟合；命中路径无法重拟合，必须显式失败而非静默退化。
                raise ValueError(
                    "per_code 训练集缓存命中但缺少可用 scaler：请提供 scaler_path（命中时复用已保存的 "
                    "训练 scaler），或设置 cache_enabled=False / rebuild_cache=True 重新拟合"
                )
        elif cfg.normalize == "none":
            self.scaler_stats = None
        elif cfg.normalize == "rolling":
            if scaler_stats is not None:
                if not isinstance(scaler_stats, _RollingDatasetState):
                    raise ValueError("外部 scaler_stats 必须是匹配的 rolling identity")
                scaler_stats.validate(
                    self._rolling_source_identity(expected_identity), feature_cols, scope=cfg.rolling_scope
                )
                self.scaler_stats = scaler_stats
            elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
                try:
                    state = _RollingDatasetState.load(cfg.scaler_path)
                    state.validate(
                        self._rolling_source_identity(expected_identity), feature_cols, scope=cfg.rolling_scope
                    )
                    self.scaler_stats = state
                except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                    print(f"[ParquetDataset] rolling state cache 无效 ({e})")
                    self.scaler_stats = None
            else:
                self.scaler_stats = None
            if self.scaler_stats is None and cfg.role != "training":
                raise ValueError("validation rolling 数据集必须提供训练 rolling identity")
        elif cfg.normalize == "relative":
            # relative 无状态：按 rules 重建当期变换器，绝不 fit。
            scaler = RelativeScaler(feature_cols=feature_cols, add_mask=cfg.per_code_add_mask)
            # 缓存 feature_cols_out 含旁路追加的 cs/mkt 列，scaler 重建结果不含，需补上再比对。
            expected_out = list(scaler.feature_cols_out) + list(self.cs_rank_cols) + list(self.mkt_factor_cols)
            if expected_out != list(self.feature_cols_out):
                raise ValueError("relative 缓存 feature_cols_out 与 rules 重建结果不匹配")
            if scaler_stats is not None:
                if not isinstance(scaler_stats, RelativeScaler):
                    raise ValueError("外部 scaler_stats 必须是 RelativeScaler（relative 无持久 state）")
                if list(scaler_stats.feature_cols_out) != list(scaler.feature_cols_out):
                    raise ValueError("外部 relative scaler_stats feature schema 不匹配")
            self.scaler_stats = scaler
        else:
            raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 relative/per_code/none/rolling")

    def _save_cache(self, cache_key: str) -> None:
        cfg = self.config
        extra: dict = {}
        if cfg.normalize == "rolling":
            # 命中路径依赖 extra 恢复 rolling_audit（E1–E4 需记录 fallback 比例）。
            extra["rolling_audit"] = dict(self.rolling_audit)
        try:
            root = resolve_cache_root(cfg.cache_dir)
            path = FeatureCache.save(
                root, cache_key, self.groups, self.index,
                feature_cols=self.feature_cols, feature_cols_out=self.feature_cols_out,
                key_components={
                    "role": cfg.role,
                    "normalize": cfg.normalize,
                    "rolling_scope": cfg.rolling_scope if cfg.normalize == "rolling" else None,
                    "label_mode": cfg.label_mode,
                    "cs_rank": cfg.cs_rank,
                    "cs_rank_features": list(self.cs_rank_features) if cfg.cs_rank else None,
                    "mkt_factors": cfg.mkt_factors,
                    "mkt_factor_list": list(self.mkt_factor_features) if cfg.mkt_factors else None,
                },
                extra=extra or None,
            )
            print(f"[ParquetDataset] 缓存写入: {path}")
        except (OSError, ValueError, RuntimeError, TypeError) as e:  # 缓存是优化项，写失败不应中断训练
            print(f"[ParquetDataset] 缓存写入失败（忽略）: {e!r}")

    def _preprocess_features(self, feat: np.ndarray, feature_cols: list[str]) -> np.ndarray:
        """NaN 填充 + 归一化（仅 per_code/none，per_code 主循环已处理，此处兜底）"""
        cfg = self.config
        if cfg.normalize == "none":
            for j, col in enumerate(feature_cols):
                col_vals = feat[:, j]
                nan_mask = np.isnan(col_vals)
                if np.any(nan_mask):
                    col_vals[nan_mask] = 0.0
                    feat[:, j] = col_vals
            return feat
        # per_code 分支在 _load_and_prepare 循环内已逐股 transform，此处仅 fallback 填0
        feat = np.where(np.isnan(feat), 0, feat)
        return feat

    def _apply_excess_labels(self) -> None:
        """将 absolute future_ret 就地转为截面超额收益并重算离散标签。

        截面均值按 kline_time 日期跨全部 code 统计（is_trading 已在上游过滤，合成行不参与）；
        NaN 标签不参与均值且输出仍为 NaN，故窗口 valid_starts/index 不变，仅 groups 内
        `future_ret`/`discrete` 被替换为超额口径。`start_date` 之前的 context warmup 行与
        标签日日期天然互斥，不会污染任何标签日的截面均值。
        """
        codes = list(self.groups)
        dates = np.concatenate([np.asarray(self.groups[code]["kline_time"]) for code in codes])
        rets = np.concatenate(
            [np.asarray(self.groups[code]["future_ret"], dtype=np.float64) for code in codes]
        )
        excess = _cross_sectional_excess(dates, rets)
        offset = 0
        for code in codes:
            n = int(self.groups[code]["n"])
            chunk = excess[offset: offset + n]
            offset += n
            self.groups[code]["future_ret"] = chunk.astype(np.float32)
            self.groups[code]["discrete"] = np.digitize(chunk, self.bins).astype(np.int64)
        print(f"[ParquetDataset] label_mode=excess：已按 kline_time 剔除截面均值（{len(codes)} 只）")

    def _print_label_stats(self):
        """打印标签分布"""
        # 采样最多 1M 窗口统计，避免过慢
        sample_n = min(len(self.index), 1000000)
        if sample_n == 0:
            return
        # 随机采样
        rng = np.random.default_rng(42)
        sample_idx = rng.choice(len(self.index), sample_n, replace=False)
        labels = []
        for idx in sample_idx:
            code, s = self.index[idx]
            g = self.groups[code]
            label_pos = s + self.config.seq_len - 1
            labels.append(int(g["discrete"][label_pos]))
        labels = np.array(labels)
        unique, counts = np.unique(labels, return_counts=True)
        print(f"[ParquetDataset] 标签分布 (采样 {sample_n} 个窗口, 共 {len(self.bins)+1} 类, bins={self.bins[:3]}...{self.bins[-3:]}):")
        for u, c in zip(unique, counts):
            print(f"  类 {u}: {c} ({c/sample_n*100:.2f}%)")
        # 打印 bins 边界对应的收益
        print(f"  BINS: {self.bins.tolist()[:5]} ... {self.bins.tolist()[-5:]} (共 {len(self.bins)} 边界, {len(self.bins)+1} 类)")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        code, s = self.index[idx]
        g = self.groups[code]
        feat = g["features"]  # [N, num_features_out]
        # 窗口 [s, s+seq_len)
        window = feat[s: s + self.config.seq_len]  # [seq_len, num_features]
        # 转为 [num_features, seq_len] 以适配 CNNTransformer 输入 [batch, featurenum, seq_len]
        window = window.T  # [num_features, seq_len]

        label_pos = s + self.config.seq_len - 1
        label = int(g["discrete"][label_pos])
        # 连续收益率标签：clip ±0.5 防尖刺（如 1273%），2x BINS 边缘
        y_ret = float(np.clip(float(g["future_ret"][label_pos]), -0.5, 0.5))

        x = torch.from_numpy(window.astype(np.float32))
        y = torch.tensor(label, dtype=torch.long)
        y_r = torch.tensor(y_ret, dtype=torch.float32)
        return x, y, y_r

    @classmethod
    def create_dataloaders(
        cls,
        config: ParquetDataConfig,
        train_start: str | None = None,
        train_end: str | None = None,
        val_start: str | None = None,
        val_end: str | None = None,
        scaler_path: str | None = None,
    ) -> tuple[DataLoader, DataLoader | None, dict | object]:
        """创建训练/验证 DataLoader，自动处理归一化统计共享

        约定：
          - 训练集拟合 scaler，并保存到 scaler_path（若提供）
          - 验证集复用训练集的 scaler_stats，避免泄露
        """
        # 训练集
        train_cfg = ParquetDataConfig(
            **{**config.__dict__, "start_date": train_start, "end_date": train_end, "scaler_path": scaler_path, "role": "training"}
        )
        print("=" * 60)
        print(f"[create_dataloaders] 创建训练集: {train_start} -> {train_end}")
        train_dataset = cls(train_cfg)
        train_loader = DataLoader(
            train_dataset,
            batch_size=config.batch_size,
            shuffle=True,
            num_workers=config.num_workers,
            pin_memory=True,
            persistent_workers=config.num_workers > 0,
        )
        print(f"[create_dataloaders] 训练集样本数: {len(train_dataset):,} 特征数: {train_dataset.num_features}")

        val_loader = None
        if val_start is not None or val_end is not None:
            val_cfg = ParquetDataConfig(
                **{
                    **config.__dict__,
                    "start_date": val_start,
                    "end_date": val_end,
                    "scaler_path": scaler_path,
                    "role": "validation",
                }
            )
            print("=" * 60)
            print(f"[create_dataloaders] 创建验证集: {val_start} -> {val_end}")
            # 复用训练集的 scaler（关键：避免验证集重新拟合泄露）
            val_dataset = cls(val_cfg, scaler_stats=train_dataset.scaler_stats)
            # 校验训练集与验证集输出特征数一致
            if val_dataset.num_features != train_dataset.num_features:
                print(f"[create_dataloaders] 警告：训练/验证特征数不一致 {train_dataset.num_features} vs {val_dataset.num_features}，以训练集为准")
            val_loader = DataLoader(
                val_dataset,
                batch_size=config.batch_size,
                shuffle=False,
                num_workers=config.num_workers,
                pin_memory=True,
                persistent_workers=config.num_workers > 0,
            )
            print(f"[create_dataloaders] 验证集样本数: {len(val_dataset):,} 特征数: {val_dataset.num_features}")

        return train_loader, val_loader, train_dataset.scaler_stats


if __name__ == "__main__":
    # python -m data.dataset --max_codes 10
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet")
    parser.add_argument("--max_codes", type=int, default=10)
    parser.add_argument(
        "--normalize", type=str, default="relative",
        choices=["relative", "per_code", "none", "rolling"], help="归一化方式",
    )
    parser.add_argument(
        "--rolling_scope", type=str, default="e5",
        choices=["e0", "e1", "e2", "e3", "e4", "e5"], help="rolling 子集范围",
    )
    parser.add_argument("--scaler_path", type=str, default=None, help="scaler 持久化路径")
    parser.add_argument(
        "--label_mode", type=str, default="absolute", choices=["absolute", "excess"],
        help="标签口径：absolute 原始未来收益；excess 截面超额收益",
    )
    parser.add_argument(
        "--cs_rank", action="store_true",
        help="启用逐日全市场截面 rank 特征（默认关；列 cs_<feature> 追加并旁路归一化）",
    )
    parser.add_argument(
        "--cs_rank_features", nargs="*", default=None,
        help="cs_rank 特征子集；缺省用 data/schema.DEFAULT_CS_RANK_FEATURES 的 16 个独立特征",
    )
    parser.add_argument(
        "--mkt_factors", action="store_true",
        help="启用全市场截面因子（默认关；列 mkt_* 追加在 cs 列之后并旁路归一化）",
    )
    parser.add_argument(
        "--mkt_factor_list", nargs="*", default=None,
        help="市场因子子集；缺省用 data/schema.DEFAULT_MKT_FACTOR_FEATURES 的 11 个因子",
    )
    parser.add_argument(
        "--feature_cols", nargs="*", default=None,
        help="显式特征列子集；缺省按 schema 推导（旧 parquet 缺列时可显式传入可用子集）",
    )
    args = parser.parse_args()

    print(f"[Test] normalize={args.normalize}, max_codes={args.max_codes}")
    cfg = ParquetDataConfig(
        parquet_path=args.parquet,
        seq_len=60,
        horizon=10,
        batch_size=64,
        num_workers=0,
        max_codes=args.max_codes,
        normalize=args.normalize,
        rolling_scope=args.rolling_scope,
        scaler_path=args.scaler_path,
        label_mode=args.label_mode,
        feature_cols=args.feature_cols,
        cs_rank=args.cs_rank,
        cs_rank_features=args.cs_rank_features,
        mkt_factors=args.mkt_factors,
        mkt_factor_list=args.mkt_factor_list,
    )
    ds = ParquetDataset(cfg)
    print(f"Dataset len: {len(ds)}")
    x, y, y_ret = ds[0]
    print(f"x shape: {x.shape}, y_cls: {y}, y_ret: {y_ret}")
    print(f"features_in: {len(ds.feature_cols)}, features_out: {ds.num_features} (out cols: {ds.feature_cols_out[:5]}... + mask {ds.feature_cols_out[-6:] if len(ds.feature_cols_out)>len(ds.feature_cols) else []})")
    print(f"seq_len: {cfg.seq_len}, num_classes: {len(cfg.bins)+1}")
    scaler = ds.scaler_stats
    if scaler is not None and hasattr(scaler, "per_code_stats"):
        per_code_stats = cast(Any, scaler).per_code_stats
        print(f"[PerCode Stats] per-code {len(per_code_stats)} 股, mask {getattr(scaler, 'mask_cols', [])}")
        print(f"x stats: mean={x.float().mean().item():.3f} std={x.float().std().item():.3f} min={x.min().item():.3f} max={x.max().item():.3f}")
        print(f"x has_nan: {torch.isnan(x).any().item()}, has_inf: {torch.isinf(x).any().item()}")

    loader = DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)
    for bx, by, br in loader:
        print(f"batch x: {bx.shape}, y_cls: {by.shape}, y_ret: {br.shape}, y values: {by}, rets: {br}")
        print(f"batch x mean: {bx.mean().item():.4f}, std: {bx.std().item():.4f}, min: {bx.min().item():.3f}, max: {bx.max().item():.3f}")
        break

    # 测试持久化与复用（仅 per_code；rolling/relative 有独立无状态语义）
    if isinstance(scaler, PerCodeGroupedScaler) and args.normalize == "per_code":
        import tempfile

        tmp = tempfile.mktemp(suffix="_scaler.pkl")
        scaler.save(tmp)
        print(f"[Persistence] 保存成功: {tmp}")
        cfg_val = ParquetDataConfig(**{**cfg.__dict__, "role": "validation", "scaler_path": None})
        loaded = PerCodeGroupedScaler.load(tmp)
        ds_val = ParquetDataset(cfg_val, scaler_stats=loaded)
        print(f"[Reuse] 验证集特征数: {ds_val.num_features}, 样本数: {len(ds_val)}，与训练集一致: {ds_val.num_features == ds.num_features}")
        os.remove(tmp)
    print("[Test] 全流程验证通过")
