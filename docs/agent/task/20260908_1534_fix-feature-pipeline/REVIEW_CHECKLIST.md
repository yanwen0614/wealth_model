# 审查清单 — fix-feature-pipeline

> 生成时间：2026-09-08 15:34

## 需求理解

需求：完成 feature processing 修复的完整实现计划，但本次仅生成规划文档。目标为：

1. 仅当 scaler identity hash 匹配时复用；至少绑定 parquet 指纹、训练日期范围、原始特征名及顺序、归一化/mask 配置和 scaler version；训练不匹配时重拟合。
2. 缺失信号的最终输出为中性零。
3. 用批准的显式特征 allowlist 取代 parquet denylist，并移除或修复无效 `use_factor_only`。
4. 校验加载的 scaler schema 与输出兼容性。
5. 验证首日 relative 计算保留上一个收盘价，但 context 行不得创建验证样本。
6. 未见 code 的 fallback 统计采用同一 transform/winsor 语义。
7. 补充相关单元测试；不修改无关脏文件；后续每次源文件 edit 小于 100 行。

显式假设：

- 批准的原始特征是规范中 G1(12)+G3(7)+G4(3)+G5(6)+G8(5)+G9(6) 的固定顺序，共 39；G9 增加六个 mask 后为 F=45。
- `use_factor_only` 删除而非保留兼容别名，因为其 48 因子结果与批准 F=45 契约冲突；显式 `feature_cols` 是唯一实验性覆盖入口。
- parquet 指纹使用 resolved path、size、mtime_ns 与 parquet metadata schema/row-count digest，不对 3.5G 文件全量内容哈希。
- identity 的日期范围指 scaler 的训练 fit 区间。验证/评估不以自身日期范围比对，而是必须得到并校验训练 identity；验证仍只复用训练 scaler。
- 旧 `v2_per_code` pickle 不迁移，视为不兼容；训练会重拟合，正式评估会报错，避免不透明兼容路径。
- 验证 context 仅包括同 code、过滤 `is_trading=False` 后、严格早于 `val_start` 的最后一行；它不参与 fit、标签、窗口、索引或样本计数。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|---|---|---|---|
| data | `data/schema.py` | modify | 39 列有序 allowlist，删除 `use_factor_only` 分支。 |
| data | `data/scaler.py` | modify | v3 identity/schema payload、严格 load、共享 global/per-code 变换统计。 |
| data | `data/dataset.py` | modify | 训练缓存 refit policy、外部 reuse 校验、验证 context 行剔除。 |
| scripts | `scripts/eval_bins_mapping.py` | modify | 评估时提供并验证训练 identity。 |
| docs | `docs/per_code_normalization_spec.md` | modify | 持久化、fallback 与验证 context 的事实源更新。 |
| tests | `tests/unit/data/test_data_schema_labels.py` | modify | allowlist 与 F=45 契约。 |
| tests | `tests/unit/data/test_data_feature_pipeline.py` | create | identity、payload、missing、fallback、context、cache 回归测试。 |

未改动：models、training、criterion、inference、`train.py`、`config/defaults.py`、现有无关脏文件。

## 重复检测

| 搜索关键词 | 是否存在 | 位置 |
|---|---|---|
| `ParquetDataset` | 是 | `data/dataset.py` |
| `PerCodeGroupedScaler` | 是 | `data/scaler.py` |
| `_default_feature_cols` / `use_factor_only` | 是 | `data/schema.py`, `data/dataset.py` |
| `global_stats` fallback | 是，但语义不完整 | `data/scaler.py` |
| `scaler_path` 复用 | 是 | `data/dataset.py`, `train.py`, `scripts/multi_seed_train.py`, `scripts/eval_bins_mapping.py` |
| F=45 / G9 mask | 是 | `docs/per_code_normalization_spec.md`, `data/scaler.py` |
| scaler identity hash / schema manifest | 否 | 本次新增 |
| EMD loss | 是，未受影响 | `criterion/emd_loss.py` |
| model registration / `ModelConfig` | 是，未受影响 | `models/cnn_transformer/` |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|---|---|---|
| 1 | 规范一致性 | allowlist、G1 relative robust、G3/G4 winsor、G8 pass-through、G9 fill0+mask 与 spec 完全一致 | HIGH |
| 2 | 模块边界 | 数据处理仅在 `data/`；训练只协调 dataloaders；评估只提供 identity，不在模型/训练层复制 scaler 逻辑 | HIGH |
| 3 | Cache identity | canonical JSON、SHA-256、全部必需字段、不同 feature order/period/snapshot/config/version 均不复用 | HIGH |
| 4 | Schema compatibility | payload 版本、input/output/mask 顺序、统计字段、F=45 和 transform configuration 均验证；无 pickle fallback | HIGH |
| 5 | Leakage | 仅训练集 `fit`；validation/evaluation 不因 cache 不匹配而拟合；context 不进入 samples | HIGH |
| 6 | Missing values | transform 后 NaN/inf 均为 0；G9 mask 基于原始 observed 状态 | HIGH |
| 7 | Unseen code | 全局 relative/winsor/robust 的 fitting 与 transform 路径匹配 per-code 语义 | HIGH |
| 8 | Error handling | identity/schema mismatch 抛含字段差异的 `ValueError`；不静默降级 | MEDIUM |
| 9 | Performance | 指纹仅读 stat/parquet metadata；不引入 parquet 全量二次读取或 O(N^2) context 查找 | MEDIUM |
| 10 | Style and scope | source/test edits each under 100 lines；不改现有无关 dirty files；无未使用 import | MEDIUM |
| 11 | Tests | synthetic parquet 覆盖 hash、schema、missing、unseen code、context、F=45/[B,45,60]；data unittest 与 ruff | HIGH |
