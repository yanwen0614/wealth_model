# rolling-normalization-redesign 实施计划（DESIGN_SPEC v1.0）

> 生成时间：2026-09-13 23:31
> Task Dir: `docs/agent/task/20260913_2331_rolling-normalization-redesign/`
> 依据：`grouped_scaler_DESIGN_SPEC.md` v1.0 / `grouped_scaler_MODULE_DESIGN.md` / `grouped_scaler_INTERVIEW_LOG.md`（Q1–Q7）
> 分支：`feature/rolling-normalization-cnn`

## Goal

把归一化层与滚动归一化重构为「列语义分组（P/R/N/G）+ ColumnRule Registry + 三策略（relative/per_code/rolling）」，
全面替换旧默认 schema（51 raw + 18 mask = F=69 → 52 raw + 1 shared mask = F=53），
落地 E0–E5 单变量对照实验矩阵，并使 `featurenum` 由运行时实测派生、checkpoint 自描述。

## Architecture

- `data/schema.py` 引入分组注册表 `FEATURE_GROUPS{P:18,R:16,N:12,G:6}` 与共享 `g9_observed_mask`；
  `data/scaler.py` 集中注册 `ColumnRule`（列→变换）并提供 `RelativeScaler`（E0，无 fit）与重构后的 `PerCodeGroupedScaler`（E1，P 静态 robust）；
  `data/rolling_scaler.py` 扩展 `scope e0..e5` 并修复「入 scope 的 G9 列短路 mask」缺陷。
- 三种策略共用同一 `transform_code` 契约与 `feature_cols_out`（顺序 `[P→R→N→G→mask]`），
  `ParquetDataset.num_features = len(feature_cols_out)` 为唯一事实源，模型仅通过 `featurenum` 数值契约消费。
- 版本三处 bump（`CACHE_FORMAT_VERSION`/`SCALER_VERSION`/rolling payload），旧缓存与 scaler 自动失效；
  导出 `config.json` 必含 `feature_cols_out` 列名（含 mask）。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 理由 |
|---|---|---|---|
| 列分组 | 语义 P/R/N/G + `ColumnRule` Registry | 沿用 G1..G9 + transform 内列名 if/else | 规则集中注册，改列不散落分支 |
| `close` | 解禁进 P 组（`x/close[t-1]-1`） | 继续禁用 | `close[t]/close[t-1]-1`≡`return_1d`，E0 relative 必需；分母统一 `close[t-1]` |
| mask | 1 个 shared `g9_observed_mask`=OR(18 G9 列 finite) | 18 逐列 mask | 18 mask 有效秩≈1.05，通道冗余 |
| R 组变换 | `clip(asinh(x·scale),±5)`，amihud `scale=1e12` | per-code winsor 1/99 | 无界重尾比值，asinh 保符号并压缩极值 |
| P 组变换 | relative + robust + clip±5（E0 无统计量） | 保持 winsor | E0/E1/E2 仅统计量差异，单变量对照干净 |
| G 组 E0–E4 | 固定区间粗 clip（缺失填 0） | 无差别 `clip[0,1]` | 保留负值与量纲信息 |
| E 臂表达 | `normalize{relative,per_code,rolling}` × `rolling_scope{e0..e5}` × `--feature_cols` | 六值 `normalize` 枚举 | 归一化模式与列子集两维正交 |
| `featurenum` | 实测派生为权威，`--featurenum` 缺省 None | schema 常量 53 为权威 | F 变化不再卡死；checkpoint 自描述 |
| digest | 仅纳入活动组与 scope 子集 | 全量 `GROUP_DEFS`/`CONFIG` | 降低无关变更导致的缓存失效 |
| 版本 | 三处 bump（cache/scaler/rolling payload） | 不 bump | 旧语义缓存/scaler 自动失效 |

### 列分组表（F_out = 52 + 1 = 53，列序 `[P→R→N→G→mask]` 稳定写入 `feature_cols_out`）

| 组 | 列数 | 列 | 变换 | clip | E0–E4 / E5 |
|---|---|---|---|---|---|
| **P** | 18 | open,high,low,**close**,ma_5/10/20/60,ema_12/26,sar,trend_duokong,trend_shortline,macd,std_5/10/20,atr | `x/close[t-1]-1`(+robust) | ±5 | E0 无统计 / E1 静态 / E2+ 滚动 |
| **R** | 16 | dmi,adx,boll,kelch,trend_duokong_dev,volatility_5/10/20,volume_ratio_5/10,gross_margin,net_margin,roe,roa,debt_to_equity,amihud | `asinh(x·scale)` | ±5 | 一致（amihud 1e12，其余 1.0） |
| **N** | 12 | G9 rank 6 + `*_ts` 6 | 恒等 | [0,1] | 一致 |
| **G** | 6 | G9 `*_raw` 6 | 固定 clip / winsor | 见下 | E0–E4 固定 / E5 滚动 |
| **mask** | 1 | `g9_observed_mask` | OR(18 G9 列 finite) | {0,1} | 一致（恒追加末尾） |

- G9 `*_raw` E0–E4 粗 clip：`margin_net_buy_ratio_raw∈[-1,1]`、`margin_balance_chg_5d_raw∈[-1,5]`、`margin_buy_ratio_raw∈[0,1.5]`、
  `margin_balance_ratio_raw∈[0,1]`、`short_balance_ratio_raw∈[0,1]`、`short_sell_vol_ratio_raw∈[0,1]`；缺失填 0。

### E0–E5 实验矩阵（固定 seed 42 / epochs 50 / patience 5 / batch 1024 / lr 1e-4）

| 臂 | `--normalize` | `--rolling_scope` | 滚动列集（列数） | P 统计量 |
|---|---|---|---|---|
| E0 | relative | e0 | ∅（0） | 无（仅 relative+clip） |
| E1 | per_code | e1 | P（18，名称占位，静态使用） | 全历史静态 robust |
| E2 | rolling | e2 | P（18） | 252 滚动 robust |
| E3 | rolling | e3 | P + volatility_5/10/20（21） | 252 滚动 robust |
| E4 | rolling | e4 | + volume_ratio_5/10 + amihud（24） | 252 滚动 robust |
| E5 | rolling | e5 | + G9 `*_raw` 6（30） | 252 滚动 robust |

> `e1`/`e2` 列集相同，语义区别在 `normalize`（per_code 静态 vs rolling 动态）；metadata 必须同时记录 `mode` 与 `scope`。
> 非 scope 列在三种模式下均按 `COLUMN_RULES` 变换（R asinh、N clip01、G 固定 clip），保证 E 臂间仅「滚动列集」单变量变化。

### ModelConfig 与 featurenum=53 对齐

- `config/defaults.py` `CNNTransformerConfig.featurenum` 占位 69 → 53（仍被实测覆盖）。
- `models/cnn_transformer/config.py` 占位值保持（训练按 `train_dataset.num_features` 覆盖）。
- 唯一事实源：`ParquetDataset.num_features = len(feature_cols_out) = 53`；`train.py` 断言 `metadata.featurenum == train_dataset.num_features`，
  rolling 维度不符仅 warning（不再 raise）。
- 模型前向契约：`forward(x:[B,53,60]) -> (logits[B,52], ret_pred[B])`（`out[0]` 即 `[B,52]`）。
- checkpoint `config.json` 的 `preprocessing` 必须写 `feature_cols` 与 `feature_cols_out`（含 `g9_observed_mask`）。

## Impact

| 模块 | 文件 | 操作 | 风险 |
|---|---|---|---|
| schema | data/schema.py | modify | high |
| scaler | data/scaler.py | modify | high |
| rolling | data/rolling_scaler.py | modify | high |
| dataset | data/dataset.py | modify | high |
| cache | data/feature_cache.py | modify | medium |
| train/CLI | train.py, config/defaults.py | modify | high |
| 评估脚本 | scripts/eval_bins_mapping.py, run_eval_pipeline.py, run_eval_full.sh, multi_seed_train.py | modify | medium |
| 测试 | tests/unit/**（data/scripts/config/models/training） | modify/create | medium |
| 文档 | docs/per_code_normalization_spec.md, README_TRAINING_CHAIN.md, data/AGENTS.md, models/AGENTS.md, AGENTS.md | modify | low |

## Task Decomposition

### T01 数据分组重构（schema）
- **目标文件**: `data/schema.py` (modify)；`tests/unit/data/test_data_schema_labels.py` (modify)；`tests/unit/data/test_schema_groups.py` (create)
- **描述**: 引入 `FEATURE_GROUPS{P:18,R:16,N:12,G:6}`；`APPROVED_RAW_FEATURES` 51→52（close 解禁、顺序 P→R→N→G）；
  `G9_OBSERVATION_SOURCE`(18)、`G9_MASK_COLUMNS=("g9_observed_mask",)`；`PROHIBITED_COLUMNS` 移除 close；
  新增 `column_group`、`g9_observed_mask`、`default_feature_cols(normalize)`。
- **依赖**: 无
- **预估行数**: +200
- **验收标准**: `len(APPROVED_RAW_FEATURES)==52`；`column_group("close")=="P"`；未知列 raise；`g9_observed_mask` OR 语义（部分缺失→1）；
  `default_feature_cols` 顺序与 `FEATURE_GROUPS` 一致；`close not in PROHIBITED_COLUMNS`。
- **TDD**: 是（先 RED）
- **风险因子**: `dataset.py` 兼容别名 `_default_feature_cols` 签名变更需同步；`EXPORT_FACTORS` 不动。

### T02 ColumnRule Registry + RelativeScaler（E0）
- **目标文件**: `data/scaler.py` (modify)；`tests/unit/data/test_scaler_column_rules.py` (create)
- **描述**: 定义 `@dataclass(frozen) ColumnRule(group,transform,clip,robust,winsor,scale,relative_denominator)` 与 `COLUMN_RULES`（列→规则）；
  命名常量 `ASINH_CLIP=5.0`、`AMIHUD_SCALE=1e12`、`P_CLIP=(-5,5)`、G 固定区间；新增 `RelativeScaler`
  （P relative+clip、R asinh、N clip01、G fixed clip、末尾 shared mask、无 fit）。
- **依赖**: T01
- **预估行数**: +260
- **验收标准**: `COLUMN_RULES["amihud"].scale==1e12`；`RelativeScaler` 无 `fit` 且 `feature_cols_out` 末尾为 mask；
  P 值 = `x/close[t-1]-1` clip±5；R = `clip(asinh(x·scale),±5)`；N clip[0,1]；G 按列区间。
- **TDD**: 是
- **风险因子**: 与旧 `_asinh`/`_relative_transform` 重复，须删旧路径；`relative_denominator` 常量为 `"close"`。

### T03 PerCodeGroupedScaler 重构（E1）
- **目标文件**: `data/scaler.py` (modify)；`tests/unit/data/test_data_feature_pipeline.py` (modify)；`tests/unit/data/test_scaler_per_code.py` (create)
- **描述**: 删除 `GROUP_DEFS_PER_CODE`/`PER_CODE_CONFIG`/G1..G9 分支，改为按 `COLUMN_RULES` 路由；仅 P 组拟合 per-code
  median/IQR（静态 robust）；R/N/G 走确定性规则；支持 `feature_cols` 子集收窄（未分组列直接 raise）；
  `transform_config_digest` 仅纳入活动规则；`SCALER_VERSION`/`TRANSFORM_VERSION` bump 为 v4。
- **依赖**: T02
- **预估行数**: +220
- **验收标准**: E1 P 输出 `(x_rel-median)/(IQR/1.349)` clip±5；R asinh；N clip01；G 固定 clip；未见 code 回退 global 统计；
  `feature_cols` 收窄只影响 P 子集；旧 `v3_per_code` payload load 报错。
- **TDD**: 是
- **风险因子**: `validate_requested_schema`/`save`/`load` 的 `REQUIRED_STAT_KEYS` 需适配（仅 P 有统计量）；G8 白名单遗留清理。

### T04 rolling 重构（scope e0..e5 + G9 mask 修复）
- **目标文件**: `data/rolling_scaler.py` (modify)；`data/dataset.py`（`_RollingDatasetState.PAYLOAD_VERSION`，modify）；`tests/unit/data/test_rolling_normalization.py` (modify/create)
- **描述**: `ROLLING_SCOPE_FEATURES` 扩为 e0..e5（e0=∅、e1=P、e2=P、e3=+vol、e4=+vol_ratio/amihud、e5=+G9 raw）；
  `__post_init__` 校验 e0..e5；`output_feature_cols` 与 `transform_code` 实际列数严格一致；入 scope 的 G9 列仍输出 shared mask
  （mask 从原始 G9 列 finite 独立计算，不短路）；非 scope 列按 `COLUMN_RULES`；删除 `_validate_feature_cols` 的 close 禁令；
  bump `ROLLING_VERSION`/`ROLLING_TRANSFORM_VERSION`/`PAYLOAD_VERSION`。
- **依赖**: T02
- **预估行数**: +300
- **验收标准**: `ROLLING_SCOPE_FEATURES` 列数 {e0:0,e1:18,e2:18,e3:21,e4:24,e5:30}；E5 输出列数 == `len(output_feature_cols)`
  且 shared mask 恒在末尾；`close` 可入 feature_cols；异 scope digest 互异；G9 缺失→mask=0、G raw 固定 clip 保负值。
- **TDD**: 是
- **风险因子**: rolling 复用 `COLUMN_RULES` 的 import 方向（scaler 不 import rolling，安全）；fallback 宽度对齐；
  digest 变更使 E2/E3/E4 旧 digest 全部失效（预期）。

### T05 dataset 接入（relative 分支 / feature_cols_out / cache key）
- **目标文件**: `data/dataset.py` (modify)；`data/feature_cache.py` (modify)；`tests/unit/data/test_dataset_cache.py` (modify)；`tests/unit/data/test_context_warmup_windows.py` (modify)
- **描述**: `ParquetDataConfig` 增 `relative` 支持；`featurenum` 由 `len(feature_cols_out)` 实测；新增 relative 归一化分支
  （无状态、逐 code transform）与 `_resolve_scaler_on_cache_hit` relative 分支；`_cache_key` 增加 relative 分支
  （用 `RelativeScaler.transform_config_digest()`）；`_scaler_identity` 记录 `feature_cols_out`；
  `CACHE_FORMAT_VERSION` bump 为 `v3_relative_groups`。
- **依赖**: T03, T04
- **预估行数**: +220
- **验收标准**: per_code/rolling/relative 三模式 `ds.num_features==53`（默认 52 列）且 `ds[0][0].shape==(53,seq_len)`；
  `feature_cols_out` 末尾为 `g9_observed_mask`；缓存 key 对 mode/scope/feature_cols/版本敏感；验证/评估缓存命中不重 fit。
- **TDD**: 是
- **风险因子**: `_preprocess_features` per_code no-op 分支（dataset.py:460-465）应清理；warmup context 与 shared mask 兼容。

### T06 train/CLI + metadata/config 落盘
- **目标文件**: `train.py` (modify)；`config/defaults.py` (modify)；`tests/unit/test_train_metadata.py` (modify)
- **描述**: `--normalize` 增 `relative`；`--rolling_scope` choices e0..e5；新增 `--feature_cols`（nargs）与 `--featurenum`（default None）；
  `configure_preprocessing` 增 relative 分支（LOG_DIR=`./logs/relative`、SCALER_PATH=None）；删除 `build_preprocessing_metadata` 的
  `featurenum==69` 断言，改断言 `metadata.featurenum == 实测`；rolling 维度不符由 raise 改 warning；`config/defaults.py`
  `featurenum` 69→53；导出 `config.json` 必含 `feature_cols` 与 `feature_cols_out`（含 mask）。
- **依赖**: T05
- **预估行数**: +220
- **验收标准**: `parse_args([]).featurenum is None`；relative 装配成功且 SCALER_PATH/LOG_DIR 与 per_code/rolling 隔离；
  metadata `feature_cols_out[-1]=="g9_observed_mask"`；`build_preprocessing_metadata` 不再拒绝 53；rolling 不匹配仅 warning。
- **TDD**: 是
- **风险因子**: 显式 `--featurenum` 与实测冲突须报错；`config.json` 重写（featurenum 校正分支）需同步 `feature_cols_out`。

### T07 评估脚本层适配（69→53 / relative / scope e0..e5）
- **目标文件**: `scripts/eval_bins_mapping.py` (modify)；`scripts/run_eval_pipeline.py` (modify)；`scripts/run_eval_full.sh` (modify)；`scripts/multi_seed_train.py` (modify)；`tests/unit/scripts/test_eval_preprocessing.py` (modify)
- **描述**: mode 校验扩 {relative,per_code,rolling}；`rolling_scope` choices e0..e5 且默认按 checkpoint metadata 解析；
  `featurenum` 缺省 45 改为从 checkpoint metadata/实测派生（无 metadata 明确报错而非静默 45）；relative 模式 scaler 复用分支
  （无状态，允许按 rules 重建）；`_resolve_eval_rolling_scope` 随新 schema。
- **依赖**: T05, T06
- **预估行数**: +200
- **验收标准**: 旧 ckpt 缺 featurenum 不再静默 45；relative/rolling/per_code 三模式维度校验通过；异 scope 仍严格拒绝；
  preds 缓存字段契约不变（exp_ret/true_ret/dates/codes）。
- **TDD**: 是（评估维度契约）
- **风险因子**: relative 无持久 state，需以 rules digest + feature_cols 一致作为「不重 fit」的等价校验。

### T08 旧契约测试同步与全量单测绿
- **目标文件**: `tests/unit/data/test_data_dataset_triple.py`、`test_dataset_label_openopen.py`、`tests/unit/config/test_config_defaults.py`、`tests/unit/models/test_models_dual_head.py`、`tests/unit/training/test_training_trainer_dual.py`（modify）
- **描述**: 批量把 69/51/45 等旧维度断言改为 53/52（或与 mock 无关的结构断言）；确保全量单测与 lint 通过。
- **依赖**: T01–T07
- **预估行数**: +180
- **验收标准**: `uv run --project . python -m unittest discover tests/unit` 全绿；`uv run ruff check .` 无错误（line-length 120）。
- **TDD**: 否（同步收尾）
- **风险因子**: 遗漏隐式 69 断言；mock 维度与真实 schema 混淆。

### T09 文档同步
- **目标文件**: `docs/per_code_normalization_spec.md`、`README_TRAINING_CHAIN.md`、`data/AGENTS.md`、`models/AGENTS.md`、`AGENTS.md` (modify)
- **描述**: F 描述 69→53、列分组 P/R/N/G、E0–E5 矩阵、relative 模式、shared mask、featurenum 实测派生、版本 bump 与缓存失效范围全部同步。
- **依赖**: T01–T08
- **预估行数**: +200
- **验收标准**: 5 份文档无 `F=69`/`51 raw`/`18 mask` 残留（历史说明显式标注为历史）；`docs/per_code_normalization_spec.md` 与 schema/scaler 实现一致。
- **TDD**: 否
- **风险因子**: 根 `AGENTS.md` 多处 F=69 易漏改。

### T10 端到端验收（重建缓存 + E0–E5 重训/评估）
- **目标文件**: `docs/agent/task/20260913_2331_rolling-normalization-redesign/HARNESS_PROGRESS.md` (modify)；可选 `scripts/run_e0_e5.sh` (create)
- **描述**: `train.py --smoke --num_workers 0 --rebuild_cache` 冒烟通过；按 E0–E5 矩阵全量重训（seed 42/batch 1024/patience 5），
  每臂产出 checkpoint/config.json 与预测缓存，跑截面 IC/xs_spread + TopN rolling 回测。
- **依赖**: T01–T09
- **预估行数**: +60（脚本，无生产代码）
- **验收标准**: 六臂 config.json `preprocessing.featurenum==53` 且 `feature_cols_out[-1]=="g9_observed_mask"`；
  各臂评估报告与回测产物落 `logs/`；旧 `logs/scaler_per_code.pkl` 因版本 bump 被拒绝并重拟合。
- **TDD**: 否
- **风险因子**: 全量重训耗时长；smoke 会覆盖 `logs/scaler_per_code.pkl`（需按训练口径重拟合恢复 identity）；缓存 generation 累积需关注磁盘。
