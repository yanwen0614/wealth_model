"""data 包门面：只做重导出，无逻辑（T19）。

canonical 位置：
- hash/digest → data.identity（canonical_hash/canonical_bytes，T06 单事实源）
- 逐元素变换 → data.transform_kernel（apply_column_rule/append_shared_mask，T07）
- parquet IO/装配 → data.reader（load_and_prepare/build_groups，T11）
- 截面 rank/市场因子 → data.cs_mkt（T11）
- 缓存键/命中/落盘 → data.cached_dataset（含 _RollingDatasetState，T11）
- 数据集门面 → data.dataset（ParquetDataset/ParquetDataConfig；旧 from data.dataset import X 仍可用）
- scaler/schema/labels 保持直引（from data.scaler / data.schema / data.labels import …），不在此转导。
"""

from data.cached_dataset import (
    _RollingDatasetState,
    apply_cache_hit,
    cache_key,
    resolve_scaler_on_cache_hit,
    rolling_source_identity,
    save_cache,
    scaler_identity,
    transform_digest,
)
from data.cs_mkt import (
    CS_RANK_FILL,
    compute_cross_sectional_rank,
    compute_market_factors,
    resolve_cs_rank_features,
    resolve_mkt_factor_list,
)
from data.dataset import ParquetDataConfig, ParquetDataset
from data.identity import canonical_bytes, canonical_hash
from data.reader import build_groups, load_and_prepare
from data.transform_kernel import append_shared_mask, apply_column_rule, relative_transform

__all__ = [
    "CS_RANK_FILL",
    "ParquetDataConfig",
    "ParquetDataset",
    "_RollingDatasetState",
    "append_shared_mask",
    "apply_cache_hit",
    "apply_column_rule",
    "build_groups",
    "cache_key",
    "canonical_bytes",
    "canonical_hash",
    "compute_cross_sectional_rank",
    "compute_market_factors",
    "load_and_prepare",
    "relative_transform",
    "resolve_cs_rank_features",
    "resolve_mkt_factor_list",
    "resolve_scaler_on_cache_hit",
    "rolling_source_identity",
    "save_cache",
    "scaler_identity",
    "transform_digest",
]
