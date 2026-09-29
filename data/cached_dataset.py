"""缓存键 / 命中重建 / 落盘：自 data.dataset 纯移动（T11 零逻辑改动）。

 canonical 位置：_RollingDatasetState 与 scaler/cache identity 均以本模块为准；
 data.dataset 仅做 `from data.cached_dataset import _RollingDatasetState` 重导出
 与 ParquetDataset._* 薄包装。warmup/标签/列序语义与移动前逐位一致。
 单向依赖：本模块可 import data.cs_mkt（resolvers），禁止 import data.dataset/reader。
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle

import numpy as np
import pyarrow.parquet as pq

from data.cs_mkt import resolve_cs_rank_features, resolve_mkt_factor_list
from data.feature_cache import (
    FeatureCache,
    _WindowIndex,
    compute_bins_digest,
    compute_cache_key,
    resolve_cache_root,
)
from data.identity import canonical_hash
from data.rolling_scaler import RollingNormalizationConfig, RollingNormalizer
from data.scaler import SCALER_VERSION, PerCodeGroupedScaler, RelativeScaler

__all__ = [
    "_RollingDatasetState",
    "apply_cache_hit",
    "cache_key",
    "resolve_scaler_on_cache_hit",
    "rolling_source_identity",
    "save_cache",
    "scaler_identity",
    "transform_digest",
]


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
        """旧入口保留：委托 data.identity.canonical_hash（digest 逐位一致）。"""
        return canonical_hash(manifest)

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
    def load(cls, path: str) -> _RollingDatasetState:
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


def transform_digest(normalize: str) -> str:
    """按归一化模式取变换配置摘要：relative 无统计量，per_code/rolling 用 frozen 规则。"""
    if normalize == "relative":
        return RelativeScaler.transform_config_digest()
    return PerCodeGroupedScaler.transform_config_digest()


def scaler_identity(cfg, pf: pq.ParquetFile, feature_cols: list[str]) -> dict:
    """scaler identity：绑定 resolved parquet 路径/size/mtime/row/schema 与拟合配置。"""
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
        "max_codes": cfg.max_codes, "transform_digest": transform_digest(cfg.normalize),
        "scaler_version": SCALER_VERSION,
    }
    # rolling_scope 仅 rolling 有意义；写入后由 rolling_source_identity 剔除，保持 per_code 字节不变。
    if cfg.normalize == "rolling":
        identity["rolling_scope"] = cfg.rolling_scope
    return identity


def rolling_source_identity(expected_identity: dict) -> dict:
    """rolling 的 source identity：剔除仅影响 frozen 拟合/调试/scope 的字段（与 _RollingDatasetState 一致）。"""
    source_identity = dict(expected_identity)
    for key in (
        "fit_start_date", "fit_end_date", "transform_digest", "scaler_version", "max_codes", "rolling_scope"
    ):
        source_identity.pop(key, None)
    return source_identity


def cache_key(cfg, bins: np.ndarray, expected_identity: dict, feature_cols: list[str]) -> str:
    """由 data identity + role/scope/scaler identity/seq/horizon/max_windows/bins 派生缓存 key。

    key 必须对 train/val、per_code/rolling、E2/E3/E4 scope、seq_len/horizon/max_windows/bins
    任一变化敏感，避免跨配置串缓存。
    """
    if cfg.normalize == "per_code":
        scaler_identity_hash: str | None = PerCodeGroupedScaler.identity_hash_for(expected_identity)
        rolling_scope: str | None = None
    elif cfg.normalize == "rolling":
        normalizer = RollingNormalizer(RollingNormalizationConfig(scope=cfg.rolling_scope))
        source_identity = rolling_source_identity(expected_identity)
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
        cs_rank_features=resolve_cs_rank_features(feature_cols, cfg.cs_rank_features)
        if cfg.cs_rank else None,
        mkt_factors=cfg.mkt_factors,
        mkt_factor_list=resolve_mkt_factor_list(cfg.mkt_factor_list)
        if cfg.mkt_factors else None,
    )


def apply_cache_hit(dataset, data, scaler_stats: dict | object | None,
                    expected_identity: dict, feature_cols: list[str]) -> None:
    """用磁盘缓存重建 groups/index，跳过 parquet 读取与归一化。"""
    dataset.feature_cols_out = list(data.feature_cols_out)
    dataset.num_features = int(data.num_features)
    default_audit: dict[str, int | float] = {
        "total_rows": 0, "rolling_values": 0, "fallback_values": 0,
        "neutral_fallback_values": 0, "passthrough_values": 0,
        "missing_values": 0, "constant_iqr_values": 0, "fallback_ratio": 0.0,
    }
    cached_audit = data.extra.get("rolling_audit") if isinstance(data.extra, dict) else None
    dataset.rolling_audit = {**default_audit, **cached_audit} if isinstance(cached_audit, dict) else default_audit
    dataset.groups = {}
    for position, code in enumerate(data.codes):
        offset = int(data.offsets[position])
        n = int(data.n_per_code[position])
        dataset.groups[code] = {
            "features": data.features.subview(offset, n),
            "future_ret": data.future_ret[offset: offset + n],
            "discrete": data.discrete[offset: offset + n],
            "kline_time": np.asarray(data.kline_time[offset: offset + n]).view("datetime64[ns]"),
            "n": n,
            "open": data.open[offset: offset + n],
            "close": data.close[offset: offset + n],
        }
    dataset.index = _WindowIndex(data.codes, data.window_code_ids, data.window_starts)
    # 命中路径不读 parquet，但仍执行既有的 validation scaler 校验红线（绝不重 fit）。
    resolve_scaler_on_cache_hit(dataset, scaler_stats, expected_identity, feature_cols)
    print(
        f"[ParquetDataset] 缓存命中: key={data.key}, 股票 {len(data.codes)} 只, "
        f"窗口 {len(dataset.index):,}, 特征 {dataset.num_features}, path={data.path}"
    )
    # 命中路径补标签分布统计，保持与 miss 路径日志一致。
    dataset._print_label_stats()


def resolve_scaler_on_cache_hit(dataset, scaler_stats: dict | object | None,
                                expected_identity: dict, feature_cols: list[str]) -> None:
    """缓存命中时不重 fit，只做与内存路径一致的 scaler identity/schema 校验。"""
    cfg = dataset.config
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
        elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
            try:
                cached_scaler = PerCodeGroupedScaler.load(cfg.scaler_path)
                cached_scaler.validate_requested_schema(feature_cols, cfg.per_code_add_mask)
                if cached_scaler.identity_hash != PerCodeGroupedScaler.identity_hash_for(expected_identity):
                    raise ValueError("scaler cache identity 不匹配")
                dataset.scaler_stats = cached_scaler
                print(f"[ParquetDataset] 复用匹配的 {cfg.scaler_path} PerCodeGroupedScaler")
            except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                print(f"[ParquetDataset] scaler cache 无效 ({e})")
                dataset.scaler_stats = None
        if dataset.scaler_stats is None and cfg.role != "training":
            raise ValueError(f"{cfg.role} 数据集必须提供兼容的已拟合训练 scaler")
        if dataset.scaler_stats is None:
            # miss 路径会现场拟合；命中路径无法重拟合，必须显式失败而非静默退化。
            raise ValueError(
                "per_code 训练集缓存命中但缺少可用 scaler：请提供 scaler_path（命中时复用已保存的 "
                "训练 scaler），或设置 cache_enabled=False / rebuild_cache=True 重新拟合"
            )
    elif cfg.normalize == "none":
        dataset.scaler_stats = None
    elif cfg.normalize == "rolling":
        if scaler_stats is not None:
            if not isinstance(scaler_stats, _RollingDatasetState):
                raise ValueError("外部 scaler_stats 必须是匹配的 rolling identity")
            scaler_stats.validate(
                rolling_source_identity(expected_identity), feature_cols, scope=cfg.rolling_scope
            )
            dataset.scaler_stats = scaler_stats
        elif cfg.role == "training" and cfg.scaler_path and os.path.exists(cfg.scaler_path):
            try:
                state = _RollingDatasetState.load(cfg.scaler_path)
                state.validate(
                    rolling_source_identity(expected_identity), feature_cols, scope=cfg.rolling_scope
                )
                dataset.scaler_stats = state
            except (EOFError, OSError, pickle.UnpicklingError, ValueError) as e:
                print(f"[ParquetDataset] rolling state cache 无效 ({e})")
                dataset.scaler_stats = None
        else:
            dataset.scaler_stats = None
        if dataset.scaler_stats is None and cfg.role != "training":
            raise ValueError("validation rolling 数据集必须提供训练 rolling identity")
    elif cfg.normalize == "relative":
        # relative 无状态：按 rules 重建当期变换器，绝不 fit。
        scaler = RelativeScaler(feature_cols=feature_cols, add_mask=cfg.per_code_add_mask)
        # 缓存 feature_cols_out 含旁路追加的 cs/mkt 列，scaler 重建结果不含，需补上再比对。
        expected_out = list(scaler.feature_cols_out) + list(dataset.cs_rank_cols) + list(dataset.mkt_factor_cols)
        if expected_out != list(dataset.feature_cols_out):
            raise ValueError("relative 缓存 feature_cols_out 与 rules 重建结果不匹配")
        if scaler_stats is not None:
            if not isinstance(scaler_stats, RelativeScaler):
                raise ValueError("外部 scaler_stats 必须是 RelativeScaler（relative 无持久 state）")
            if list(scaler_stats.feature_cols_out) != list(scaler.feature_cols_out):
                raise ValueError("外部 relative scaler_stats feature schema 不匹配")
        dataset.scaler_stats = scaler
    else:
        raise ValueError(f"未知 normalize: {cfg.normalize}, 可选 relative/per_code/none/rolling")


def save_cache(dataset, cache_key_value: str) -> None:
    """落盘归一化后特征与小数组（优化项，写失败不中断训练）。"""
    cfg = dataset.config
    extra: dict = {}
    if cfg.normalize == "rolling":
        # 命中路径依赖 extra 恢复 rolling_audit（E1–E4 需记录 fallback 比例）。
        extra["rolling_audit"] = dict(dataset.rolling_audit)
    try:
        root = resolve_cache_root(cfg.cache_dir)
        path = FeatureCache.save(
            root, cache_key_value, dataset.groups, dataset.index,
            feature_cols=dataset.feature_cols, feature_cols_out=dataset.feature_cols_out,
            key_components={
                "role": cfg.role,
                "normalize": cfg.normalize,
                "rolling_scope": cfg.rolling_scope if cfg.normalize == "rolling" else None,
                "label_mode": cfg.label_mode,
                "cs_rank": cfg.cs_rank,
                "cs_rank_features": list(dataset.cs_rank_features) if cfg.cs_rank else None,
                "mkt_factors": cfg.mkt_factors,
                "mkt_factor_list": list(dataset.mkt_factor_features) if cfg.mkt_factors else None,
            },
            extra=extra or None,
        )
        print(f"[ParquetDataset] 缓存写入: {path}")
    except (OSError, ValueError, RuntimeError, TypeError) as e:  # 缓存是优化项，写失败不应中断训练
        print(f"[ParquetDataset] 缓存写入失败（忽略）: {e!r}")
