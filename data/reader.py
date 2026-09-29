"""parquet 读取 / 过滤 / 时间切分与主装配：自 data.dataset 纯移动（T11 零逻辑改动）。

 canonical 位置：parquet IO、is_trading 过滤、start/end 时间过滤与 context warmup、
 scaler 装配与分组建窗均以本模块 `load_and_prepare(dataset, scaler_stats)` 为准；
 data.dataset.ParquetDataset._load_and_prepare 仅做薄委托。
 单向依赖：可 import data.cs_mkt / data.cached_dataset / scaler / schema / labels，
 禁止 import data.dataset（dataset 侧单向导入本模块，防循环）。
 warmup 语义：context 可入窗不可作标签日（valid_starts 过滤 is_context[label_pos]）。
"""
from __future__ import annotations

import os
import pickle
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from data.cached_dataset import (
    apply_cache_hit,
    rolling_source_identity,
    save_cache,
    scaler_identity,
)
from data.cached_dataset import (
    cache_key as _cache_key_for,
)
from data.cs_mkt import (
    CS_RANK_FILL,
    compute_cross_sectional_rank,
    compute_market_factors,
    resolve_cs_rank_features,
    resolve_mkt_factor_list,
)
from data.feature_cache import FeatureCache, resolve_cache_root
from data.labels import _future_ret_open_open
from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import PerCodeGroupedScaler, RelativeScaler
from data.schema import MKT_FACTOR_NEUTRAL, _default_feature_cols


def resolve_feature_cols(pf: pq.ParquetFile, cfg: Any) -> tuple[list[str], list[str]]:
    """解析输入 raw 特征列并校验 parquet schema（原 _load_and_prepare 首段逐行移动）。"""
    all_cols = pf.schema.names
    if cfg.feature_cols is not None:
        feature_cols = list(cfg.feature_cols)
    else:
        feature_cols = _default_feature_cols(all_cols)
    missing = [c for c in feature_cols if c not in all_cols]
    if missing:
        raise ValueError(f"特征列缺失于 parquet: {missing}, 可用列: {all_cols[:10]}...")
    return feature_cols, all_cols


def read_parquet_table(cfg: Any, feature_cols: list[str], all_cols: list[str]) -> pd.DataFrame:
    """仅读必需列（含 mkt 额外列）并转 pandas（原 _load_and_prepare 读取段逐行移动）。"""
    print(f"[ParquetDataset] 读取 parquet: {cfg.parquet_path}")
    read_cols = ["code", "kline_time", "close", "open", "is_trading"] + feature_cols
    if cfg.mkt_factors:
        for extra in ("ma_20", "high", "low", "volume", "TOT_SHARE"):
            if extra in all_cols:
                read_cols.append(extra)
    read_cols = list(dict.fromkeys(read_cols))
    table = pq.read_table(cfg.parquet_path, columns=read_cols)
    df = table.to_pandas()
    print(f"[ParquetDataset] 原始行数: {len(df):,}, 列数: {len(df.columns)}")
    return df


def filter_is_trading(df: pd.DataFrame) -> pd.DataFrame:
    """过滤 is_trading=False 合成行（原 _load_and_prepare 过滤段逐行移动）。"""
    before = len(df)
    df = df[df["is_trading"] == True]
    print(f"[ParquetDataset] 过滤 is_trading False: {before:,} -> {len(df):,} (drop {before - len(df):,})")
    return df


def apply_time_filter_with_context(df: pd.DataFrame, cfg: Any) -> pd.DataFrame:
    """时间过滤并保留 context warmup 行（原 _load_and_prepare 时间段逐行移动）。

    context 上限：rolling 且 role!=training 为 max(seq_len-1,251)，否则 max(seq_len-1,1)；
    `_transform_context=True` 行可入窗、绝不作标签日（下游 valid_starts 过滤）。
    """
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    df["_transform_context"] = False
    if cfg.start_date:
        start = pd.to_datetime(cfg.start_date)
        eligible = df[df["kline_time"] >= start]
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
    return df


def ensure_scaler(dataset: Any, df: pd.DataFrame, cfg: Any, expected_identity: dict,
                  feature_cols: list[str], scaler_stats: dict | object | None) -> None:
    """装配归一化统计（原 _load_and_prepare 归一化分支逐行移动，含 fit/复用/防泄露红线）。"""
    from data.cached_dataset import _RollingDatasetState

    if cfg.normalize == "per_code":
        dataset.scaler_stats = None
        if scaler_stats is not None:
            if not isinstance(scaler_stats, PerCodeGroupedScaler):
                raise ValueError("外部 scaler_stats 必须是有效的 PerCodeGroupedScaler v3 对象")
            if not scaler_stats.fitted:
                raise ValueError("外部 scaler_stats 未拟合")
            if not scaler_stats.identity_manifest or not scaler_stats.identity_hash:
                raise ValueError("外部 scaler_stats 缺少训练 identity")
            scaler_stats.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
            dataset.scaler_stats = scaler_stats
            print("[ParquetDataset] 使用外部传入的 scaler_stats (per_code)")
            if hasattr(dataset.scaler_stats, "feature_cols_out"):
                dataset.feature_cols_out = dataset.scaler_stats.feature_cols_out
                dataset.num_features = len(dataset.feature_cols_out)
        elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
            try:
                cached = PerCodeGroupedScaler.load(cfg.scaler_path)
                cached.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                if cached.identity_hash != PerCodeGroupedScaler.identity_hash_for(expected_identity):
                    raise ValueError("scaler cache identity 不匹配")
                dataset.scaler_stats = cached
                print(f"[ParquetDataset] 复用匹配的 {cfg.scaler_path} PerCodeGroupedScaler")
            except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                print(f"[ParquetDataset] scaler cache 无效 ({e})，将在训练集重拟合")
                dataset.scaler_stats = None
            if dataset.scaler_stats is not None:
                dataset.feature_cols_out = dataset.scaler_stats.feature_cols_out
                dataset.num_features = len(dataset.feature_cols_out)
        if dataset.scaler_stats is None:
            if cfg.role != "training":
                raise ValueError(f"{cfg.role} 数据集必须提供兼容的已拟合训练 scaler")
            print(f"[ParquetDataset] 拟合 PerCodeGroupedScaler (add_mask={cfg.per_code_add_mask}) ...")
            scaler = PerCodeGroupedScaler(add_mask=cfg.per_code_add_mask)
            # 限制 feature_cols 剔除项：return_*/TOT_SHARE/volume/amount/close 已在上层 feature_cols 中剔除
            scaler.fit(df.loc[~df["_transform_context"]], feature_cols)
            scaler.set_identity(expected_identity)
            dataset.scaler_stats = scaler
            dataset.feature_cols_out = scaler.feature_cols_out
            dataset.num_features = len(dataset.feature_cols_out)
            print(f"[ParquetDataset] PerCodeGroupedScaler 拟合完成: {len(dataset.feature_cols)} -> {dataset.num_features} (per-code {len(scaler.per_code_stats)} 股)")
            if cfg.scaler_path:
                scaler.save(cfg.scaler_path)
    elif cfg.normalize == "none":
        dataset.scaler_stats = None
        dataset.feature_cols_out = list(dataset.feature_cols)
        dataset.num_features = len(dataset.feature_cols_out)
    elif cfg.normalize == "rolling":
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope=cfg.rolling_scope))
        source_identity = rolling_source_identity(expected_identity)
        if scaler_stats is None:
            if cfg.role != "training":
                raise ValueError("validation rolling 数据集必须提供训练 rolling identity")
            fallback_scaler = PerCodeGroupedScaler(add_mask=cfg.per_code_add_mask)
            fallback_scaler.fit(df.loc[~df["_transform_context"]], feature_cols)
            fallback_identity = dict(expected_identity)
            fallback_identity["normalize"] = "rolling_fallback_per_code"
            fallback_scaler.set_identity(fallback_identity)
            dataset.scaler_stats = _RollingDatasetState(
                normalizer, source_identity, feature_cols, fallback_scaler
            )
        else:
            if not isinstance(scaler_stats, _RollingDatasetState):
                raise ValueError("外部 scaler_stats 必须是匹配的 rolling identity")
            scaler_stats.validate(source_identity, feature_cols, scope=cfg.rolling_scope)
            dataset.scaler_stats = scaler_stats
        dataset.feature_cols_out = normalizer.output_feature_cols(feature_cols)
        dataset.num_features = len(dataset.feature_cols_out)
        if scaler_stats is None and cfg.scaler_path:
            dataset.scaler_stats.save(cfg.scaler_path)
    elif cfg.normalize == "relative":
        # relative 无 fit / 无落盘 / 无持久 state：scaler_stats 仅是当期确定性变换器。
        scaler = RelativeScaler(feature_cols=feature_cols, add_mask=cfg.per_code_add_mask)
        if scaler_stats is not None:
            if not isinstance(scaler_stats, RelativeScaler):
                raise ValueError("外部 scaler_stats 必须是 RelativeScaler（relative 无持久 state）")
            if list(scaler_stats.feature_cols_out) != list(scaler.feature_cols_out):
                raise ValueError("relative scaler_stats feature schema 不匹配")
        dataset.scaler_stats = scaler
        dataset.feature_cols_out = scaler.feature_cols_out
        dataset.num_features = len(dataset.feature_cols_out)
    else:
        raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 relative/per_code/none/rolling")


def load_and_prepare(dataset: Any, scaler_stats: dict | object | None) -> None:
    """主装配（原 ParquetDataset._load_and_prepare 逐行移动，仅 self→dataset 改名）。

    顺序恒定：特征解析→identity→cache 命中短路→读表→is_trading→时间/context→
    cs_rank/mkt（截断前全市场）→排序→max_codes→scaler 装配→旁路拼接→建窗（见 build_groups）。
    F 列序恒为 [P→R→N→G→mask]+cs+mkt；warmup 不作标签日。
    """
    cfg = dataset.config
    pf = pq.ParquetFile(cfg.parquet_path)
    feature_cols, _all_cols = resolve_feature_cols(pf, cfg)

    dataset.feature_cols = feature_cols  # 输入 raw 特征列（默认 F=51）
    dataset.feature_cols_out = list(feature_cols)  # 输出特征列（per_code 可能追加 mask）
    dataset.num_features = len(feature_cols)
    # cs_rank 配置在两条路径（缓存命中/未命中）都可用：cs 列名确定性由 feature_cols + 请求派生。
    dataset.cs_rank_features = (
        resolve_cs_rank_features(feature_cols, cfg.cs_rank_features) if cfg.cs_rank else []
    )
    dataset.cs_rank_cols = [f"cs_{column}" for column in dataset.cs_rank_features]
    # 市场因子列名即 `mkt_*` 本身（不再加前缀），不依赖 feature_cols，直接校验已知因子。
    dataset.mkt_factor_features = (
        resolve_mkt_factor_list(cfg.mkt_factor_list) if cfg.mkt_factors else []
    )
    dataset.mkt_factor_cols = list(dataset.mkt_factor_features)
    expected_identity = scaler_identity(cfg, pf, feature_cols)
    print(f"[ParquetDataset] 特征列数: {dataset.num_features}, 特征: {feature_cols[:8]}...")

    bins = dataset.bins
    key = _cache_key_for(cfg, bins, expected_identity, feature_cols)
    if cfg.cache_enabled and not cfg.rebuild_cache:
        cache_data = FeatureCache.load(resolve_cache_root(cfg.cache_dir), key)
        if cache_data is not None:
            apply_cache_hit(dataset, cache_data, scaler_stats, expected_identity, feature_cols)
            return

    df = read_parquet_table(cfg, feature_cols, _all_cols)
    # is_trading 已在构造时强制为 True。
    df = filter_is_trading(df)
    df = apply_time_filter_with_context(df, cfg)

    # 截面 rank：必须在按 code 分组/排序与 max_codes 截断之前，在全体股票（含 context 行）
    # 的逐日截面上计算；否则 rank 只相对被保留的少数股票，语义错误。
    if cfg.cs_rank:
        compute_cross_sectional_rank(df, dataset.cs_rank_features)

    # 市场因子：与 cs_rank 同处（时间过滤后、分组与 max_codes 截断前），全市场逐日计算后广播。
    if cfg.mkt_factors:
        compute_market_factors(df, dataset.mkt_factor_features)

    # 按 code 分组排序
    df = cast(Any, df).sort_values(["code", "kline_time"]).reset_index(drop=True)

    # 限制调试股票数
    codes = df["code"].unique()
    if cfg.max_codes is not None and len(codes) > cfg.max_codes:
        keep_codes = list(codes[: cfg.max_codes])
        df = df[df["code"].isin(keep_codes)]
        print(f"[ParquetDataset] 限制 max_codes={cfg.max_codes}, 保留 {len(keep_codes)} 只, 行数 {len(df):,}")

    ensure_scaler(dataset, df, cfg, expected_identity, feature_cols, scaler_stats)

    # 截面 rank 列追加在归一化输出（含 mask）之后并旁路归一化：列名与主循环拼接顺序严格一致。
    if dataset.cs_rank_cols:
        dataset.feature_cols_out = list(dataset.feature_cols_out) + list(dataset.cs_rank_cols)
        dataset.num_features = len(dataset.feature_cols_out)

    # 市场因子列追加在 cs 列之后并旁路归一化：最终列序 [归一化输出(含 mask)] + cs + mkt。
    if dataset.mkt_factor_cols:
        dataset.feature_cols_out = list(dataset.feature_cols_out) + list(dataset.mkt_factor_cols)
        dataset.num_features = len(dataset.feature_cols_out)

    print(f"[ParquetDataset] 输出特征列数: {dataset.num_features}, 输出特征: {dataset.feature_cols_out[:8]}...")
    build_groups(dataset, df, cfg, feature_cols)
    # 标签分布统计与缓存落盘（原 _load_and_prepare 尾段逐行移动）。
    if cfg.label_mode == "excess":
        dataset._apply_excess_labels()
    dataset._print_label_stats()
    if cfg.cache_enabled:
        save_cache(dataset, key)


def build_groups(dataset: Any, df: pd.DataFrame, cfg: Any, feature_cols: list[str]) -> None:
    """按 code 建分组特征与滑动窗口索引（原 _load_and_prepare 分组段逐行移动）。

    context 保留为窗口 warmup 输入：group/feat/close/open 保留全部行（context 在先），
    用 is_context 保证标签日恒为非 context 的真实交易日。
    """
    from data.cached_dataset import _RollingDatasetState

    dataset.groups: dict[str, dict] = {}
    dataset.index: list[tuple[str, int]] = []  # (code, window_start_pos)
    dataset.rolling_audit: dict[str, int | float] = {
        "total_rows": 0,
        "rolling_values": 0,
        "fallback_values": 0,
        "neutral_fallback_values": 0,
        "passthrough_values": 0,
        "missing_values": 0,
        "constant_iqr_values": 0,
        "fallback_ratio": 0.0,
    }

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
        if dataset.cs_rank_cols:
            cs_feat = np.nan_to_num(
                group[dataset.cs_rank_cols].values.astype(np.float64),
                nan=CS_RANK_FILL, posinf=CS_RANK_FILL, neginf=CS_RANK_FILL,
            )
        # 市场因子提取为独立旁路矩阵：不进入 scaler，缺失按 MKT_FACTOR_NEUTRAL 逐列填充。
        mkt_feat = None
        if dataset.mkt_factor_cols:
            raw_mkt = group[dataset.mkt_factor_cols].values.astype(np.float64)
            fills = np.array([MKT_FACTOR_NEUTRAL[column] for column in dataset.mkt_factor_cols],
                             dtype=np.float64)
            bad = ~np.isfinite(raw_mkt)
            raw_mkt[bad] = np.take(fills, np.broadcast_to(np.arange(len(fills)), bad.shape)[bad])
            mkt_feat = raw_mkt

        # NaN 填充 + 归一化（per_code / relative 按 code 独立）
        if cfg.normalize == "per_code":
            # per-code：需传入 close 供 P 组 relative
            if isinstance(dataset.scaler_stats, PerCodeGroupedScaler):
                feat = dataset.scaler_stats.transform_code(code, feat, feature_cols, close)
        elif cfg.normalize == "relative":
            if not isinstance(dataset.scaler_stats, RelativeScaler):
                raise ValueError("relative 数据集缺少有效 preprocessing")
            feat = dataset.scaler_stats.transform_code(code, feat, feature_cols, close)
        elif cfg.normalize == "rolling":
            if not isinstance(dataset.scaler_stats, _RollingDatasetState):
                raise ValueError("rolling 数据集缺少有效 preprocessing identity")
            frozen_fallback = dataset.scaler_stats.fallback_scaler.transform_code(
                code, feat, feature_cols, close
            )
            result = dataset.scaler_stats.normalizer.transform_code(
                feat, feature_cols, close, frozen_fallback=frozen_fallback
            )
            feat = result.values
            for key, value in vars(result.audit).items():
                dataset.rolling_audit[key] = int(dataset.rolling_audit[key]) + int(value)
        else:
            feat = dataset._preprocess_features(feat, feature_cols)

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
        discrete = np.digitize(future_ret, dataset.bins).astype(np.int64)  # 0..len(bins)

        dataset.groups[code] = {
            "features": feat,  # [N, num_features_out]
            "future_ret": future_ret,
            "discrete": discrete,
            "kline_time": group["kline_time"].values,
            "n": n,
            "open": open_arr,
            "close": close,
        }
        for s in valid_starts:
            dataset.index.append((code, s))
        total_windows += len(valid_starts)

    print(f"[ParquetDataset] 分组完成: 保留 {len(dataset.groups)} 只股票, 跳过 {skipped_codes} 只 (长度不足/无有效标签)")
    print(f"[ParquetDataset] 总样本数 (窗口): {total_windows:,}")
    if cfg.normalize == "rolling":
        audited = int(dataset.rolling_audit["fallback_values"]) + int(
            dataset.rolling_audit["rolling_values"]
        )
        dataset.rolling_audit["fallback_ratio"] = (
            int(dataset.rolling_audit["fallback_values"]) / audited if audited else 0.0
        )
        print(
            "[ParquetDataset] rolling audit: "
            f"fallback_ratio={dataset.rolling_audit['fallback_ratio']:.6f}, "
            f"fallback={dataset.rolling_audit['fallback_values']}, "
            f"neutral={dataset.rolling_audit['neutral_fallback_values']}, "
            f"rolling={dataset.rolling_audit['rolling_values']}"
        )
    if total_windows == 0:
        raise ValueError("无有效样本，请检查数据过滤条件（is_trading/时间范围/特征列）")


def cli_main(argv: list[str] | None = None) -> None:
    """`python -m data.dataset` 调试入口（原 dataset.__main__ 逐行移动，零逻辑改动）。"""
    import argparse
    from typing import cast as _cast

    import torch
    from torch.utils.data import DataLoader

    from data.scaler import PerCodeGroupedScaler as _PerCodeGroupedScaler

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
    args = parser.parse_args(argv)

    # 延迟导入门面，避免循环（reader 为被导入方，dataset 门面单向导入本模块）。
    from data.dataset import ParquetDataConfig, ParquetDataset

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
        per_code_stats = _cast(Any, scaler).per_code_stats
        print(f"[PerCode Stats] per-code {len(per_code_stats)} 股, mask {getattr(scaler, 'mask_cols', [])}")
        print(f"x stats: mean={x.float().mean().item():.3f} std={x.float().std().item():.3f} min={x.min().item():.3f} max={x.max().item():.3f}")
        print(f"x has_nan: {torch.isnan(x).any().item()}, has_inf: {torch.isinf(x).any().item()}")

    loader = DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)
    for bx, by, br in loader:
        print(f"batch x: {bx.shape}, y_cls: {by.shape}, y_ret: {br.shape}, y values: {by}, rets: {br}")
        print(f"batch x mean: {bx.mean().item():.4f}, std: {bx.std().item():.4f}, min: {bx.min().item():.3f}, max: {bx.max().item():.3f}")
        break

    # 测试持久化与复用（仅 per_code；rolling/relative 有独立无状态语义）
    if isinstance(scaler, _PerCodeGroupedScaler) and args.normalize == "per_code":
        import tempfile

        tmp = tempfile.mktemp(suffix="_scaler.pkl")
        scaler.save(tmp)
        print(f"[Persistence] 保存成功: {tmp}")
        cfg_val = ParquetDataConfig(**{**cfg.__dict__, "role": "validation", "scaler_path": None})
        loaded = _PerCodeGroupedScaler.load(tmp)
        ds_val = ParquetDataset(cfg_val, scaler_stats=loaded)
        print(f"[Reuse] 验证集特征数: {ds_val.num_features}, 样本数: {len(ds_val)}，与训练集一致: {ds_val.num_features == ds.num_features}")
        os.remove(tmp)
    print("[Test] 全流程验证通过")


if __name__ == "__main__":
    cli_main()
