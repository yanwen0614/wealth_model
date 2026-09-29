"""Parquet -> 训练数据集门面：T11 拆分后的兼容层（零逻辑改动）。

 canonical 实现已移至：
 - data.reader（parquet IO/is_trading/时间过滤+context/scaler 装配/建窗/CLI）
 - data.cs_mkt（截面 rank/市场因子）
 - data.cached_dataset（_RollingDatasetState/cache key/hit/save）
 本文件只留 ParquetDataConfig、重导出与 ParquetDataset 薄门面（<400 行）。
 F 列序恒为 [P→R→N→G→mask]+cs+mkt；warmup 可入窗、绝不作标签日。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import DataLoader, Dataset

from data.cached_dataset import (
    _RollingDatasetState,
    apply_cache_hit,
    resolve_scaler_on_cache_hit,
)
from data.cached_dataset import (
    cache_key as _cache_key_impl,
)
from data.cached_dataset import (
    rolling_source_identity as _rolling_source_identity_impl,
)
from data.cached_dataset import (
    save_cache as _save_cache_impl,
)
from data.cached_dataset import (
    scaler_identity as _scaler_identity_impl,
)
from data.cached_dataset import (
    transform_digest as _transform_digest_impl,
)
from data.cs_mkt import (
    CS_RANK_FILL,
)
from data.cs_mkt import (
    compute_cross_sectional_rank as _cs_rank_impl,
)
from data.cs_mkt import (
    compute_market_factors as _mkt_impl,
)
from data.cs_mkt import (
    resolve_cs_rank_features as _resolve_cs_impl,
)
from data.cs_mkt import (
    resolve_mkt_factor_list as _resolve_mkt_impl,
)
from data.labels import _cross_sectional_excess, _future_ret_open_open
from data.reader import load_and_prepare as _load_and_prepare_impl
from data.rolling_scaler import (  # canonical在data.rolling_scaler，兼容patch("data.dataset.RollingNormalizer")
    RollingNormalizationConfig,
    RollingNormalizer,
)
from data.scaler import (  # canonical在data.scaler，兼容from data.dataset import X
    PerCodeGroupedScaler,
    RelativeScaler,
)
from data.schema import (  # noqa: F401
    BASE_COLUMNS,
    DEFAULT_CS_RANK_FEATURES,
    DEFAULT_MKT_FACTOR_FEATURES,
    EXPORT_FACTORS,
    MKT_FACTOR_NEUTRAL,
    _default_feature_cols,
)

__all__ = [
    "CS_RANK_FILL",
    "ParquetDataConfig",
    "ParquetDataset",
    "PerCodeGroupedScaler",
    "RelativeScaler",
    "RollingNormalizationConfig",
    "RollingNormalizer",
    "_RollingDatasetState",
    "_future_ret_open_open",
]


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


class ParquetDataset(Dataset):
    """基于单文件 parquet 的滑动窗口数据集（门面：逻辑委托 reader/cs_mkt/cached_dataset）。

    每个样本：
      x: [num_features, seq_len]  float32  (当前默认输出为 51 raw + 18 G9 mask)
      y: int  (digitized future return)
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

        # 1. 读取 parquet（委托 data.reader，保证 IO/过滤/context/warmup 语义不变）
        self._load_and_prepare(scaler_stats)

    @staticmethod
    def _transform_digest(normalize: str) -> str:
        """薄包装：委托 data.cached_dataset.transform_digest（digest 逐位一致）。"""
        return _transform_digest_impl(normalize)

    @staticmethod
    def _resolve_cs_rank_features(feature_cols: list[str], requested: list[str] | None) -> list[str]:
        """薄包装：委托 data.cs_mkt.resolve_cs_rank_features。"""
        return _resolve_cs_impl(feature_cols, requested)

    @staticmethod
    def _compute_cross_sectional_rank(df: pd.DataFrame, cs_features: list[str]) -> None:
        """薄包装：委托 data.cs_mkt.compute_cross_sectional_rank。"""
        _cs_rank_impl(df, cs_features)

    @staticmethod
    def _resolve_mkt_factor_list(requested: list[str] | None) -> list[str]:
        """薄包装：委托 data.cs_mkt.resolve_mkt_factor_list。"""
        return _resolve_mkt_impl(requested)

    @staticmethod
    def _compute_market_factors(df: pd.DataFrame, mkt_features: list[str]) -> None:
        """薄包装：委托 data.cs_mkt.compute_market_factors。"""
        _mkt_impl(df, mkt_features)

    @staticmethod
    def _scaler_identity(cfg: ParquetDataConfig, pf: pq.ParquetFile, feature_cols: list[str]) -> dict:
        """薄包装：委托 data.cached_dataset.scaler_identity。"""
        return _scaler_identity_impl(cfg, pf, feature_cols)

    @staticmethod
    def _rolling_source_identity(expected_identity: dict) -> dict:
        """薄包装：委托 data.cached_dataset.rolling_source_identity。"""
        return _rolling_source_identity_impl(expected_identity)

    @staticmethod
    def _cache_key(cfg: ParquetDataConfig, bins: np.ndarray,
                   expected_identity: dict, feature_cols: list[str]) -> str:
        """薄包装：委托 data.cached_dataset.cache_key。"""
        return _cache_key_impl(cfg, bins, expected_identity, feature_cols)

    def _load_and_prepare(self, scaler_stats: dict | object | None):
        """薄委托：data.reader.load_and_prepare（零逻辑改动，self→dataset 改名）。"""
        _load_and_prepare_impl(self, scaler_stats)

    def _apply_cache_hit(self, data, scaler_stats: dict | object | None,
                         expected_identity: dict, feature_cols: list[str]) -> None:
        """薄包装：委托 data.cached_dataset.apply_cache_hit。"""
        apply_cache_hit(self, data, scaler_stats, expected_identity, feature_cols)

    def _resolve_scaler_on_cache_hit(self, scaler_stats: dict | object | None,
                                     expected_identity: dict, feature_cols: list[str]) -> None:
        """薄包装：委托 data.cached_dataset.resolve_scaler_on_cache_hit。"""
        resolve_scaler_on_cache_hit(self, scaler_stats, expected_identity, feature_cols)

    def _save_cache(self, cache_key: str) -> None:
        """薄包装：委托 data.cached_dataset.save_cache。"""
        _save_cache_impl(self, cache_key)

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
    # python -m data.dataset --max_codes 10（委托 reader.cli_main，零逻辑改动）
    from data.reader import cli_main

    cli_main()
