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
- 依据 BINS 离散化为多分类标签（与 main2.py EMDLoss 配套）
- 滑动窗口生成 [seq_len, num_features] 样本，默认输出 F=69（51 特征 + 18 G9 mask）
- 构建全局索引，支持 DataLoader 多进程

与旧 NPZ 链路对比：
- 旧：processed_data_train/*.npz，每样本 train_features [8,60], labels [5,8] -> sum amp -> digitize
- 新：parquet 直读，无需中间 npz，特征维度 ~50，标签为未来 5日累计收益

分组归一化（per-code 共识，精简后仅保留 per_code）：
- 69特征=51+18 mask（G9 两融 18 列各带 1 mask），G1/mcd robust(median/IQR)+clip±5、G3/G4 winsor 1/99、G9 rank透传+mask
- per-code 按股独立拟合 via PerCodeGroupedScaler，验证集复用训练集 scaler 防泄露
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

from data.labels import _future_ret_open_open
from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import SCALER_VERSION, PerCodeGroupedScaler
from data.schema import BASE_COLUMNS, EXPORT_FACTORS, _default_feature_cols  # noqa: F401


@dataclass
class ParquetDataConfig:
    parquet_path: str = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
    seq_len: int = 60
    horizon: int = 5  # 未来 N 日收益作为标签
    bins: list[float] = field(default_factory=lambda: (np.linspace(-25, 25, 51) / 100).tolist())
    batch_size: int = 256
    num_workers: int = 4
    # 特征列：None 时自动推导（排除 code/kline_time/is_trading，保留全部数值列）
    # 推荐显式传入以避免泄露：排除未来信息；默认排除 return_* 过去收益也可保留，按需配置
    feature_cols: list[str] | None = None
    # 过滤 is_trading（必须 True，避免合成行污染窗口）
    filter_is_trading: bool = True
    # 数据集职责决定缓存失配时是否允许拟合。
    role: str = "training"  # "training" | "validation" | "evaluation"
    # 时间切分
    start_date: str | None = None  # "2013-01-01"
    end_date: str | None = None
    split_date: str | None = None  # 用于外部 train/val 划分，本 Dataset 内部可基于 start/end 过滤
    # 归一化：per_code | none | rolling（rolling 必须显式 opt-in）
    normalize: str = "per_code"
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


class _RollingDatasetState:
    """Training/validation rolling identity; it never fits or calls frozen code."""

    PAYLOAD_VERSION = "v1_rolling_state"

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

    def validate(self, source_manifest: dict, feature_cols: list[str]) -> None:
        self.fallback_scaler.validate_requested_schema(feature_cols, self.fallback_scaler.add_mask)
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
        self.config = config
        self.bins = np.array(config.bins, dtype=np.float64)

        # 1. 读取 parquet
        self._load_and_prepare(scaler_stats)

    @staticmethod
    def _scaler_identity(cfg: ParquetDataConfig, pf: pq.ParquetFile, feature_cols: list[str]) -> dict:
        from data.scaler import SCALER_VERSION, PerCodeGroupedScaler

        path = os.path.realpath(cfg.parquet_path)
        stat = os.stat(path)
        metadata = pf.metadata
        schema = str(pf.schema_arrow)
        return {
            "parquet_path": path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "row_count": metadata.num_rows, "schema_fingerprint": hashlib.sha256(schema.encode()).hexdigest(),
            "fit_start_date": cfg.start_date, "fit_end_date": cfg.end_date,
            "feature_cols": list(feature_cols), "normalize": cfg.normalize,
            "per_code_add_mask": cfg.per_code_add_mask, "filter_is_trading": cfg.filter_is_trading,
            "max_codes": cfg.max_codes, "transform_digest": PerCodeGroupedScaler.transform_config_digest(),
            "scaler_version": SCALER_VERSION,
        }

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
        expected_identity = self._scaler_identity(cfg, pf, feature_cols)
        print(f"[ParquetDataset] 特征列数: {self.num_features}, 特征: {feature_cols[:8]}...")

        # 读取全表（11M 行，约 3.5G parquet，内存约 4-5G）
        # 使用 pyarrow 读取后转 pandas，按需过滤日期
        print(f"[ParquetDataset] 读取 parquet: {cfg.parquet_path}")
        # 仅读取需要的列以降低内存
        read_cols = ["code", "kline_time", "close", "open", "is_trading"] + feature_cols
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
            context_limit = 251 if cfg.normalize == "rolling" and cfg.role != "training" else 1
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
            normalizer = RollingNormalizer()
            source_identity = dict(expected_identity)
            source_identity.pop("fit_start_date", None)
            source_identity.pop("fit_end_date", None)
            source_identity.pop("transform_digest", None)
            source_identity.pop("scaler_version", None)
            source_identity.pop("max_codes", None)
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
                scaler_stats.validate(source_identity, feature_cols)
                self.scaler_stats = scaler_stats
            self.feature_cols_out = normalizer.output_feature_cols(feature_cols)
            self.num_features = len(self.feature_cols_out)
            if scaler_stats is None and cfg.scaler_path:
                self.scaler_stats.save(cfg.scaler_path)
        else:
            raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 per_code/none/rolling")

        print(f"[ParquetDataset] 输出特征列数: {self.num_features}, 输出特征: {self.feature_cols_out[:8]}...")

        # 3. 按 code 构建分组数据与索引
        self.groups: dict[str, dict] = {}
        self.index: list[tuple[str, int]] = []  # (code, window_start_pos)
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

            # NaN 填充 + 归一化（per_code 按 code 独立）
            if cfg.normalize == "per_code":
                # per-code：需传入 close 供 G1/macd relative
                if isinstance(self.scaler_stats, PerCodeGroupedScaler):
                    feat = self.scaler_stats.transform_code(code, feat, feature_cols, close)
                    # 同步更新 feature_cols_out 长度（首次循环后已一致）
                    if len(self.feature_cols_out) != feat.shape[1]:
                        # 首次 code 的 F_out 可能与全局不一致，动态修正（理论上一致）
                        pass
                    else:
                        feat = self._preprocess_features(feat, feature_cols)
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

            # Context was used above for prev_close but is never eligible for labels/windows.
            keep = ~group["_transform_context"].to_numpy()
            group = group.loc[keep].reset_index(drop=True)
            feat = feat[keep]
            close = close[keep]
            open_arr = open_arr[keep]

            n = len(group)
            if n < cfg.seq_len + cfg.horizon + 1:
                skipped_codes += 1
                continue

            future_ret = _future_ret_open_open(open_arr, cfg.horizon)

            max_s = n - cfg.seq_len - cfg.horizon
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

        # 标签分布统计
        self._print_label_stats()

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

    # 测试持久化与复用（仅 per_code）
    if scaler is not None:
        import tempfile

        tmp = tempfile.mktemp(suffix="_scaler.pkl")
        scaler.save(tmp)
        print(f"[Persistence] 保存成功: {tmp}")
        cfg_val = ParquetDataConfig(**{**cfg.__dict__, "role": "validation", "scaler_path": None})
        from data.scaler import PerCodeGroupedScaler

        loaded = PerCodeGroupedScaler.load(tmp)
        ds_val = ParquetDataset(cfg_val, scaler_stats=loaded)
        print(f"[Reuse] 验证集特征数: {ds_val.num_features}, 样本数: {len(ds_val)}，与训练集一致: {ds_val.num_features == ds.num_features}")
        os.remove(tmp)
    print("[Test] 全流程验证通过")
