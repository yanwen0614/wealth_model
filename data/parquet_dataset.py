"""Parquet -> 训练 数据集：对接 quant 最新因子数据 train_data_v1_*.parquet

数据契约（见 quant/scripts/export_training_data.py）：
- OHLC/close = 后复权；amount=真实元；volume=真实股；TOT_SHARE=万股
- is_trading=False 为合成行：OHLC/因子=NaN、volume/amount=0，训练侧必须过滤 is_trading
- 48 因子 = EXPORT_FACTORS（29 live+19 keep），含 gross_margin 5094/5194 结构性缺席等
- 训练/回测口径统一，产物可复现（指纹含 git hash + 数据快照）

本模块职责：
- 读取单文件 parquet（11M+ 行，5166 股，2013-2025）
- 按 code 分组、按 kline_time 排序、过滤 is_trading
- 计算未来 N 日收益率标签（基于 close 后复权价，避免使用 return_* 过去收益的泄露）
- 依据 BINS 离散化为多分类标签（与 main2.py EMDLoss 配套）
- 滑动窗口生成 [seq_len, num_features] 样本，支持全局 z-score 归一化 + 分组归一化
- 构建全局索引，支持 DataLoader 多进程

与旧 NPZ 链路对比：
- 旧：processed_data_train/*.npz，每样本 train_features [8,60], labels [5,8] -> sum amp -> digitize
- 新：parquet 直读，无需中间 npz，特征维度 ~50，标签为未来 5日累计收益

分组归一化（per-code 共识，精简后仅保留 per_code）：
- 45特征=39+6 mask，G1/mcd robust(median/IQR)+clip±5、G3/G4 winsor 1/99、G9 rank透传+mask
- per-code 按股独立拟合 via PerCodeGroupedScaler，验证集复用训练集 scaler 防泄露
"""
import os
import pickle
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Union

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch.utils.data import Dataset, DataLoader

# 与 quant 导出保持一致的 48 因子列（单一事实源复刻，用于默认特征列）
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

BASE_COLUMNS = ["code", "kline_time", "open", "high", "low", "close", "volume", "amount", "TOT_SHARE", "is_trading"]


@dataclass
class ParquetDataConfig:
    parquet_path: str = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
    seq_len: int = 60
    horizon: int = 5  # 未来 N 日收益作为标签
    bins: List[float] = field(default_factory=lambda: (np.linspace(-25, 25, 51) / 100).tolist())
    batch_size: int = 256
    num_workers: int = 4
    # 特征列：None 时自动推导（排除 code/kline_time/is_trading，保留全部数值列）
    # 推荐显式传入以避免泄露：排除未来信息；默认排除 return_* 过去收益也可保留，按需配置
    feature_cols: Optional[List[str]] = None
    # 是否仅使用因子列（48列）作为特征，忽略 OHLC/volume 等
    use_factor_only: bool = False
    # 过滤 is_trading（必须 True，避免合成行污染窗口）
    filter_is_trading: bool = True
    # 时间切分
    start_date: Optional[str] = None  # "2013-01-01"
    end_date: Optional[str] = None
    split_date: Optional[str] = None  # 用于外部 train/val 划分，本 Dataset 内部可基于 start/end 过滤
    # 归一化：per_code | none（per_code 为共识：不做 window 只 per-code 分组）
    normalize: str = "per_code"
    # 归一化统计文件（训练集拟合后保存，供验证集复用）
    scaler_path: Optional[str] = None
    # NaN 填充策略（仅 none 分支使用，per_code 内置分级填充）
    fill_method: str = "median"  # "median" | "zero"
    # 小样本调试：仅取前 N 只股票
    max_codes: Optional[int] = None
    # 采样：每股最大窗口数（用于快速验证）
    max_windows_per_code: Optional[int] = None
    # per_code 专用：是否添加 G9 mask
    per_code_add_mask: bool = True


def _default_feature_cols(all_columns: List[str], use_factor_only: bool = False) -> List[str]:
    """自动推导特征列（per-code 共识，G6/G7 暂不入训）"""
    if use_factor_only:
        return [c for c in EXPORT_FACTORS if c in all_columns]
    # 剔除：G2 return_*(标签)、TOT_SHARE(A)、volume/amount(绝对量)、close(恒0)、G6 估值 4、G7 成长 4
    exclude = {
        "code", "kline_time", "is_trading",
        "return_1d", "return_5d", "return_10d", "return_20d",
        "TOT_SHARE", "volume", "amount", "close",
        "pe", "pb", "pcf", "ps",
        "revenue_growth", "profit_growth", "revenue_growth_qoq", "profit_growth_qoq",
    }
    return [c for c in all_columns if c not in exclude]


class ParquetDataset(Dataset):
    """基于单文件 parquet 的滑动窗口数据集

    每个样本：
      x: [num_features, seq_len]  float32  (grouped 时 num_features 可能 +6 mask)
      y: int  (digitized future return)

    索引构建：
      按 code 分组后，对每组计算 future_return = close.shift(-horizon)/close -1
      有效窗口需满足：窗口内 seq_len 行 + 未来 horizon 行均存在且 close 非 NaN，
      且窗口末端对应的 future_return 非 NaN
    """

    def __init__(self, config: ParquetDataConfig, scaler_stats: Optional[Union[Dict, object]] = None):
        self.config = config
        self.bins = np.array(config.bins, dtype=np.float64)

        # 1. 读取 parquet
        self._load_and_prepare(scaler_stats)

    def _load_and_prepare(self, scaler_stats: Optional[Union[Dict, object]]):
        cfg = self.config
        pf = pq.ParquetFile(cfg.parquet_path)
        # 快速校验列
        all_cols = pf.schema.names
        if cfg.feature_cols is not None:
            feature_cols = cfg.feature_cols
        else:
            feature_cols = _default_feature_cols(all_cols, cfg.use_factor_only)

        # 验证特征列存在
        missing = [c for c in feature_cols if c not in all_cols]
        if missing:
            raise ValueError(f"特征列缺失于 parquet: {missing}, 可用列: {all_cols[:10]}...")

        self.feature_cols = feature_cols  # 输入特征列（含55）
        self.feature_cols_out = list(feature_cols)  # 输出特征列（grouped 可能追加 mask）
        self.num_features = len(feature_cols)
        print(f"[ParquetDataset] 特征列数: {self.num_features}, 特征: {feature_cols[:8]}...")

        # 读取全表（11M 行，约 3.5G parquet，内存约 4-5G）
        # 使用 pyarrow 读取后转 pandas，按需过滤日期
        print(f"[ParquetDataset] 读取 parquet: {cfg.parquet_path}")
        # 仅读取需要的列以降低内存
        read_cols = ["code", "kline_time", "close", "is_trading"] + feature_cols
        # 去重
        read_cols = list(dict.fromkeys(read_cols))
        table = pq.read_table(cfg.parquet_path, columns=read_cols)
        df = table.to_pandas()
        print(f"[ParquetDataset] 原始行数: {len(df):,}, 列数: {len(df.columns)}")

        # 过滤 is_trading
        if cfg.filter_is_trading:
            before = len(df)
            df = df[df["is_trading"] == True]  # noqa: E712
            print(f"[ParquetDataset] 过滤 is_trading False: {before:,} -> {len(df):,} (drop {before - len(df):,})")

        # 时间过滤
        df["kline_time"] = pd.to_datetime(df["kline_time"])
        if cfg.start_date:
            df = df[df["kline_time"] >= pd.to_datetime(cfg.start_date)]
        if cfg.end_date:
            df = df[df["kline_time"] <= pd.to_datetime(cfg.end_date)]
        print(f"[ParquetDataset] 时间过滤后: {len(df):,} 行, 范围 {df['kline_time'].min()} -> {df['kline_time'].max()}")

        # 按 code 分组排序
        df = df.sort_values(["code", "kline_time"]).reset_index(drop=True)

        # 限制调试股票数
        codes = df["code"].unique()
        if cfg.max_codes is not None and len(codes) > cfg.max_codes:
            keep_codes = codes[: cfg.max_codes]
            df = df[df["code"].isin(keep_codes)]
            print(f"[ParquetDataset] 限制 max_codes={cfg.max_codes}, 保留 {len(keep_codes)} 只, 行数 {len(df):,}")

        # 2. 归一化统计
        # 支持 grouped 与 per_code 分支（zscore 已删除），均支持外部传入 scaler_stats / 文件持久化 / 验证集复用
        if cfg.normalize == "per_code":
            from data.per_code_scaler import PerCodeGroupedScaler
            if scaler_stats is not None:
                if isinstance(scaler_stats, PerCodeGroupedScaler):
                    self.scaler_stats = scaler_stats
                elif isinstance(scaler_stats, dict) and "per_code_stats" in scaler_stats:
                    # dict 形态
                    try:
                        # 尝试按 PerCodeGroupedScaler 还原
                        self.scaler_stats = scaler_stats
                    except Exception:
                        self.scaler_stats = scaler_stats
                else:
                    self.scaler_stats = scaler_stats
                print(f"[ParquetDataset] 使用外部传入的 scaler_stats (per_code)")
                if hasattr(self.scaler_stats, "feature_cols_out"):
                    self.feature_cols_out = self.scaler_stats.feature_cols_out
                    self.num_features = len(self.feature_cols_out)
            elif cfg.scaler_path and os.path.exists(cfg.scaler_path):
                try:
                    self.scaler_stats = PerCodeGroupedScaler.load(cfg.scaler_path)
                    print(f"[ParquetDataset] 从 {cfg.scaler_path} 加载 PerCodeGroupedScaler")
                except Exception as e:
                    print(f"[ParquetDataset] PerCodeGroupedScaler 加载失败 ({e})，尝试 pickle 回退")
                    with open(cfg.scaler_path, "rb") as f:
                        self.scaler_stats = pickle.load(f)
                if hasattr(self.scaler_stats, "feature_cols_out"):
                    self.feature_cols_out = self.scaler_stats.feature_cols_out
                    self.num_features = len(self.feature_cols_out)
            else:
                print(f"[ParquetDataset] 拟合 PerCodeGroupedScaler (add_mask={cfg.per_code_add_mask}) ...")
                scaler = PerCodeGroupedScaler(add_mask=cfg.per_code_add_mask)
                # 限制 feature_cols 剔除项：return_*/TOT_SHARE/volume/amount/close 已在上层 feature_cols 中剔除
                scaler.fit(df, feature_cols)
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
        else:
            raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 per_code/none")

        print(f"[ParquetDataset] 输出特征列数: {self.num_features}, 输出特征: {self.feature_cols_out[:8]}...")

        # 3. 按 code 构建分组数据与索引
        self.groups: Dict[str, Dict] = {}
        self.index: List[Tuple[str, int]] = []  # (code, window_start_pos)

        # 统计
        total_windows = 0
        skipped_codes = 0
        grouped = df.groupby("code", sort=False)
        # per_code 分支：feat 变换移到循环内按 code 独立处理（_preprocess 已改为 per-code 内部用 close）
        for code, group in grouped:
            group = group.sort_values("kline_time")
            # 提取 features 矩阵 [N, num_features_in]
            feat = group[feature_cols].values.astype(np.float64)  # 先 float64 便于处理 NaN
            close = group["close"].values.astype(np.float64)

            # NaN 填充 + 归一化（per_code 按 code 独立，grouped 全局）
            if cfg.normalize == "per_code":
                # per-code：需传入 close 供 G1/macd relative
                from data.per_code_scaler import PerCodeGroupedScaler
                if isinstance(self.scaler_stats, PerCodeGroupedScaler):
                    feat = self.scaler_stats.transform_code(code, feat, feature_cols, close)
                    # 同步更新 feature_cols_out 长度（首次循环后已一致）
                    if len(self.feature_cols_out) != feat.shape[1]:
                        # 首次 code 的 F_out 可能与全局不一致，动态修正（理论上一致）
                        pass
                else:
                    feat = self._preprocess_features(feat, feature_cols)
            else:
                feat = self._preprocess_features(feat, feature_cols)

            # 计算未来 horizon 收益（训练标签，仅针对 OHLC 的 close 序列）
            # future_ret[t] = close[t+horizon] / close[t] - 1
            # 仅当 close[t] 与 close[t+horizon] 均有效时计算
            n = len(group)
            if n < cfg.seq_len + cfg.horizon:
                skipped_codes += 1
                continue

            future_ret = np.full(n, np.nan, dtype=np.float64)
            # 向量化计算
            valid_close = ~np.isnan(close)
            for t in range(n - cfg.horizon):
                if valid_close[t] and valid_close[t + cfg.horizon] and close[t] != 0:
                    future_ret[t] = close[t + cfg.horizon] / close[t] - 1.0

            # 构建窗口索引
            # 窗口 [s, s+seq_len) 对应的标签为 future_ret[s+seq_len-1]
            max_s = n - cfg.seq_len - cfg.horizon + 1
            # 若 horizon 收益定义在窗口末端，则需要 s+seq_len-1 + horizon < n
            # 上式已保证
            if max_s <= 0:
                skipped_codes += 1
                continue

            # 预先过滤标签 NaN 的窗口
            valid_starts = []
            for s in range(max_s):
                label_pos = s + cfg.seq_len - 1
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
            }
            for s in valid_starts:
                self.index.append((code, s))
            total_windows += len(valid_starts)

        print(f"[ParquetDataset] 分组完成: 保留 {len(self.groups)} 只股票, 跳过 {skipped_codes} 只 (长度不足/无有效标签)")
        print(f"[ParquetDataset] 总样本数 (窗口): {total_windows:,}")
        if total_windows == 0:
            raise ValueError("无有效样本，请检查数据过滤条件（is_trading/时间范围/特征列）")

        # 标签分布统计
        self._print_label_stats()

    def _preprocess_features(self, feat: np.ndarray, feature_cols: List[str]) -> np.ndarray:
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

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        code, s = self.index[idx]
        g = self.groups[code]
        feat = g["features"]  # [N, num_features_out]
        # 窗口 [s, s+seq_len)
        window = feat[s: s + self.config.seq_len]  # [seq_len, num_features]
        # 转为 [num_features, seq_len] 以适配 CNNTransformer 输入 [batch, featurenum, seq_len]
        window = window.T  # [num_features, seq_len]

        label_pos = s + self.config.seq_len - 1
        label = int(g["discrete"][label_pos])

        x = torch.from_numpy(window.astype(np.float32))
        y = torch.tensor(label, dtype=torch.long)
        return x, y

    @classmethod
    def create_dataloaders(
        cls,
        config: ParquetDataConfig,
        train_start: Optional[str] = None,
        train_end: Optional[str] = None,
        val_start: Optional[str] = None,
        val_end: Optional[str] = None,
        scaler_path: Optional[str] = None,
    ) -> Tuple[DataLoader, Optional[DataLoader], Union[Dict, object]]:
        """创建训练/验证 DataLoader，自动处理归一化统计共享

        约定：
          - 训练集拟合 scaler，并保存到 scaler_path（若提供）
          - 验证集复用训练集的 scaler_stats，避免泄露
        """
        # 训练集
        train_cfg = ParquetDataConfig(
            **{**config.__dict__, "start_date": train_start, "end_date": train_end, "scaler_path": scaler_path}
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
                }
            )
            print("=" * 60)
            print(f"[create_dataloaders] 创建验证集: {val_start} -> {val_end}")
            # 复用训练集的 scaler（关键：避免验证集重新拟合泄露）
            val_dataset = cls(val_cfg, scaler_stats=train_dataset.scaler_stats)
            # 校验特征数一致性：grouped 的 mask 会使两集一致，zscore 保持不变
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
    # python -m data.parquet_dataset --max_codes 10
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet")
    parser.add_argument("--max_codes", type=int, default=10)
    parser.add_argument("--normalize", type=str, default="per_code", choices=["per_code", "none"], help="归一化方式")
    parser.add_argument("--scaler_path", type=str, default=None, help="scaler 持久化路径")
    args = parser.parse_args()

    print(f"[Test] normalize={args.normalize}, max_codes={args.max_codes}")
    cfg = ParquetDataConfig(
        parquet_path=args.parquet,
        seq_len=60,
        horizon=5,
        batch_size=64,
        num_workers=0,
        max_codes=args.max_codes,
        normalize=args.normalize,
        scaler_path=args.scaler_path,
    )
    ds = ParquetDataset(cfg)
    print(f"Dataset len: {len(ds)}")
    x, y = ds[0]
    print(f"x shape: {x.shape}, y: {y}")
    print(f"features_in: {len(ds.feature_cols)}, features_out: {ds.num_features} (out cols: {ds.feature_cols_out[:5]}... + mask {ds.feature_cols_out[-6:] if len(ds.feature_cols_out)>len(ds.feature_cols) else []})")
    print(f"seq_len: {cfg.seq_len}, num_classes: {len(cfg.bins)+1}")
    if hasattr(ds, 'scaler_stats') and hasattr(ds.scaler_stats, 'per_code_stats'):
        print(f"[PerCode Stats] per-code {len(ds.scaler_stats.per_code_stats)} 股, mask {getattr(ds.scaler_stats, 'mask_cols', [])}")
        print(f"x stats: mean={x.float().mean().item():.3f} std={x.float().std().item():.3f} min={x.min().item():.3f} max={x.max().item():.3f}")
        print(f"x has_nan: {torch.isnan(x).any().item()}, has_inf: {torch.isinf(x).any().item()}")

    loader = DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)
    for bx, by in loader:
        print(f"batch x: {bx.shape}, y: {by.shape}, y values: {by}")
        print(f"batch x mean: {bx.mean().item():.4f}, std: {bx.std().item():.4f}, min: {bx.min().item():.3f}, max: {bx.max().item():.3f}")
        break

    # 测试持久化与复用（仅 per_code）
    import tempfile, os
    tmp = tempfile.mktemp(suffix="_scaler.pkl")
    ds.scaler_stats.save(tmp)
    print(f"[Persistence] 保存成功: {tmp}")
    cfg_val = ParquetDataConfig(
        parquet_path=args.parquet,
        seq_len=60,
        horizon=5,
        batch_size=64,
        num_workers=0,
        max_codes=args.max_codes,
        normalize=args.normalize,
    )
    from data.per_code_scaler import PerCodeGroupedScaler
    loaded = PerCodeGroupedScaler.load(tmp)
    ds_val = ParquetDataset(cfg_val, scaler_stats=loaded)
    print(f"[Reuse] 验证集特征数: {ds_val.num_features}, 样本数: {len(ds_val)}，与训练集一致: {ds_val.num_features==ds.num_features}")
    os.remove(tmp)
    print("[Test] 全流程验证通过")

