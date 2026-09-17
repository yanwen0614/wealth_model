# quant-model 项目 - 归一化层（grouped_scaler）模块现状设计文档（兼容 cnn-harness）

> Module: `grouped_scaler` | Version: v1.0 | Date: 2026-09-13 | Scope: `data/scaler.py` + `data/rolling_scaler.py` + `data/schema.py` + `data/dataset.py` 接入
>
> 说明：本文所有结论均来自仓库实际代码并标注行号（行数为实际统计）。凡属项目记忆/任务方观测而非代码可证的内容，均显式标注。本文只读分析，未修改任何文件。

## 1. 模块概述

### 1.1 模块定位（在 pluggable 体系中的位置）

归一化层位于 `data/` 包内，是「配置注入 + 策略选择」的可插拔中间层。调用方只设置 `ParquetDataConfig.normalize`（`data/dataset.py:71`，取值 `per_code|none|rolling`），由 `ParquetDataset._load_and_prepare`（`data/dataset.py:274`）在三条分支（`353`/`396`/`400`）中选择具体实现：

- `per_code` → `PerCodeGroupedScaler`（`data/scaler.py:71`，frozen 事实源，默认）；
- `rolling` → `RollingNormalizer`（`data/rolling_scaler.py:93`）+ `PerCodeGroupedScaler` 作为 element fallback，由 `_RollingDatasetState`（`data/dataset.py:90`）封装；
- `none` → 仅填 0 透传（`data/dataset.py:692-699`）。

上层入口 `train.py` 通过 `configure_preprocessing`（`train.py:52`）把 `NORMALIZE` / `ROLLING_SCOPE` / `SCALER_PATH` / `LOG_DIR` 装配进 `config`，再由 `ParquetDataset.create_dataloaders`（`data/dataset.py:749`）训练集 `fit`、验证集复用。归一化产物经 `data/feature_cache.py` memmap 缓存，最终以 `[F_out, T=60]` 张量进入 `CNNTransformer`（`models/cnn_transformer/model.py:65`）。

### 1.2 模块职责

1. **列白/黑名单与默认特征选择**：`data/schema.py` 的 `APPROVED_RAW_FEATURES`（51）、`G9_RAW_FEATURES`（18）、`G9_MASK_COLUMNS`（18）、`PROHIBITED_COLUMNS`（含 `close`）、`_default_feature_cols`（`data/schema.py:25-88`）。
2. **per-code frozen 归一化**：按 code 独立拟合/应用 median/IQR/winsor，G1 相对化、G6 asinh、G3/G4/G7 winsor、G8 透传、G9 `clip[0,1]`+mask（`data/scaler.py:55-64,117-366`）。
3. **rolling 因果归一化**：按 `[t-251,t]`（`window=252,min_periods=120`）rolling median/IQR 或 winsor，历史不足时回落到 frozen per-code 输出（`data/rolling_scaler.py:51-72,251-310`）。
4. **G9 observation mask**：为 18 个 G9 列各生成 `*_mask`（`data/scaler.py:215-220,286-291`；`data/rolling_scaler.py:129,240-243`）。
5. **identity / digest / 持久化**：`PerCodeGroupedScaler.save/load`（`data/scaler.py:369-434`）、`_RollingDatasetState.save/load`（`data/dataset.py:146-185`），canonical JSON SHA-256 绑定数据快照、特征顺序、变换配置。
6. **缓存 key 参与**：`_scaler_identity`（`data/dataset.py:214`）与 `_cache_key`（`data/dataset.py:240`）把 scaler identity 纳入 memmap 缓存键（`data/feature_cache.py:84-107`）。
7. **warmup context 接入**：`start_date` 前的历史行保留作窗口输入，但绝不作标签日（`data/dataset.py:318-336,481-504`）。

### 1.3 模块边界（与 data/training/criterion/config/models 的契约）

- **data 不依赖具体 model**：`data/*` 仅 import numpy/pandas/pyarrow/torch DataLoader 与同包模块（`data/dataset.py:25-48`）；`models/cnn_transformer/model.py` 不 import `data/*`。二者仅通过 `num_features` 数值契约耦合。
- **训练复用，不重拟合**：训练集 `fit` 并保存；验证/评估通过 `scaler_stats` 入参复用（`data/dataset.py:355-364,796,417`），缓存命中路径仍强制校验 identity/schema（`data/dataset.py:601-665`）。
- **评估复用**：`scripts/eval_bins_mapping.py:82-137` 与 `scripts/run_eval_pipeline.py:103` 从 checkpoint 同目录 `config.json` 解析 scaler/state 路径，禁止评估临时 fit（`eval_bins_mapping.py:228-234`）。
- **config 边界**：`config/defaults.py:24-25,37` 提供 `NORMALIZE`/`SCALER_PATH`/`ROLLING_SCOPE` 与 `featurenum=69` 默认；`models/cnn_transformer/config.py:1-14` 仅占位默认值，实际由 `train.py:200,308-321` 覆盖。
- **criterion 边界**：归一化不触碰标签/损失；标签纯函数在 `data/labels.py:6-19`，训练入口另于 `train.py:34` 定义 `BINS`。

## 2. 架构设计

### 2.1 整体架构

```
                    ┌──────────────────────────────────────────────────────────────┐
                    │ config/defaults.py + train.py CLI                             │
                    │ NORMALIZE={per_code,rolling}; ROLLING_SCOPE={e2,e3,e4}        │
                    │ featurenum=69（硬编码, train.py:90-91）                       │
                    └───────────────┬──────────────────────────────────────────────┘
                                    │ ParquetDataConfig(normalize, rolling_scope,
                                    │                    feature_cols, per_code_add_mask,…)
                                    ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ data/schema.py                                                              │
   │ APPROVED_RAW_FEATURES(51) │ G9_RAW_FEATURES(18) │ G9_MASK_COLUMNS(18)        │
   │ PROHIBITED_COLUMNS{…, close} │ _default_feature_cols()  校验缺列/未知列告警   │
   └───────────────┬────────────────────────────────────────────────────────────┘
                   │ feature_cols（默认 51）
                   ▼
   ┌───────────────────────────────┐     normalize 分支（Strategy, dataset.py:353-424）
   │ data/dataset.py               │◄──────┬────────────────┬────────────────┐
   │ ParquetDataset                │       │ per_code        │ rolling        │ none
   │  _load_and_prepare            │       ▼                 ▼                ▼
   └──────┬─────────┬──────────────┘  ┌────────────┐  ┌──────────────────┐ ┌───────────┐
          │         │                 │PerCode     │  │RollingNormalizer │ │ NaN→0      │
          │         │                 │GroupedScaler│ │  + frozen        │ │ 透传       │
          │         │                 │  (frozen)  │  │  fallback        │ │           │
          │         │                 └─────┬──────┘  └────────┬─────────┘ └─────┬─────┘
          │         │                       │                  │                 │
          │         └────── 归一化后 features [N,F_out] ────────┴─────────────────┘
          ▼
   ┌──────────────────────────────┐   miss: new generation   ┌───────────────────────────┐
   │ data/feature_cache.py        │◄───────────────────────── │ FeatureCache.save         │
   │ compute_cache_key            │                          │ features.npy + small npy  │
   │ _FeatureView / _WindowIndex  │   hit: shared mmap        │ + meta.json + .ok 原子发布 │
   │ _MMAP_REGISTRY               │                          └───────────────────────────┘
   └───────────────┬──────────────┘
                   ▼
   ┌──────────────────────────────┐
   │ ParquetDataset.__getitem__   │  x:[F_out,60] float32; y:long(52); y_ret:float32
   └───────────────┬──────────────┘
                   ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │ models/cnn_transformer                                                      │
   │ stem Conv1d(F_out→128)+BatchNorm1d → Inception×4 → proj → Transformer        │
   │ → mean pool → fc_cls[52] / fc_reg[1]                                        │
   └────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计模式

| 模式 | 体现 | 代码位置 |
|---|---|---|
| Strategy（策略） | `normalize` 三值分支选择不同 scaler；rolling 用 `scope` 选择列子集 | `data/dataset.py:353,396,400`；`data/rolling_scaler.py:43-47,104-105,219` |
| Config 注入 | `ParquetDataConfig` / `RollingNormalizationConfig` 冻结参数，`asdict` 参与 digest | `data/dataset.py:51-87`；`data/rolling_scaler.py:51-72,107-125` |
| Registry（映射表） | `GROUP_DEFS_PER_CODE`/`COL_TO_GROUP_PER_CODE`/`PER_CODE_CONFIG` 注册列→组→变换；`_MMAP_REGISTRY` 进程内共享 memmap | `data/scaler.py:37-64`；`data/feature_cache.py:41-52` |
| Template Method | fit/transform/save/load 生命周期；fallback chain（per-code → global；rolling → frozen per-code） | `data/scaler.py:117,263,369,400`；`data/rolling_scaler.py:202,251` |
| Canonical identity | JSON sort_keys+separators → SHA-256，跨进程可复现 | `data/scaler.py:89-102`；`data/rolling_scaler.py:99-102`；`data/dataset.py:125-128` |

## 3. 文件清单

| 文件路径 | 类/函数名 | 职责 | 行数 |
|---|---|---|---|
| `data/schema.py` | `APPROVED_RAW_FEATURES`(25-38), `G9_RAW_FEATURES`(40-47), `G9_MASK_COLUMNS`(48), `PROHIBITED_COLUMNS`(50-54), `_default_feature_cols`(76-88) | 列白/黑名单与默认特征选择 | 88 |
| `data/scaler.py` | `PerCodeGroupedScaler`(71), `GROUP_DEFS_PER_CODE`(37-50), `PER_CODE_CONFIG`(55-64) | per-code frozen 归一化、mask、identity、持久化 | 434 |
| `data/rolling_scaler.py` | `RollingNormalizer`(93), `RollingNormalizationConfig`(51), `RollingAudit`(75), `RollingTransformResult`(86), `ROLLING_SCOPE_FEATURES`(43-47) | 因果 rolling 归一化 kernel（无 fit/持久化） | 310 |
| `data/dataset.py` | `ParquetDataConfig`(51), `_RollingDatasetState`(90), `ParquetDataset`(188) | 数据加载、归一化接入、窗口/标签、缓存接入 | 870 |
| `data/feature_cache.py` | `FeatureCache`(278), `_FeatureView`(123), `_WindowIndex`(198), `compute_cache_key`(84) | 归一化后 features 的 memmap 缓存与原子发布 | 485 |
| `data/labels.py` | `_future_ret_open_open`(6) | open-open 未来收益纯函数 | 19 |
| `train.py` | `configure_preprocessing`(52), `build_preprocessing_metadata`(79), `parse_args`(117), `main`(161) | 唯一训练入口、CLI、metadata 校验 | 386 |
| `config/defaults.py` | `make_default_config`(44), `_BASE_CONFIG`(17) | 训练默认配置（含 `featurenum=69`） | 51 |
| `models/cnn_transformer/config.py` | `ModelConfig`(5) | 模型维度占位默认值 | 17 |
| `models/cnn_transformer/model.py` | `CNNTransformer`(65) | 双头前向（logits + ret_pred） | 186 |
| `models/cnn_transformer/inception_blocks.py` | `MultiWindowInceptionCNN`(192), `LightInceptionBlock1D`(6) | 首层 Conv1d→BN1d 与多尺度 CNN | 220 |
| `scripts/eval_bins_mapping.py` | `load_eval_preprocessing`(82), `validate_preprocessing_dimensions`(152), `build_val_loader`(208) | 评估复用 scaler/state、维度校验 | 494 |
| `scripts/run_eval_pipeline.py` | `resolve_eval_scaler_path`(103), `build_scaler`(136) | 全流程评估脚本的 scaler 复用 | 375 |
| `scripts/build_ohlc_path.py` | — | 构建回测 OHLC 路径（依赖评估 preds） | 112 |
| `scripts/run_backtest.py` | — | TopN rolling 回测 | 197 |
| `scripts/plot_topn_curve.py` | — | TopN 曲线绘图 | 121 |
| `docs/per_code_normalization_spec.md` | — | G1~G9 决策唯一事实源 | 100 |
| `tests/unit/data/test_rolling_normalization.py` | — | rolling kernel + scope + state 契约 | 589 |
| `tests/unit/data/test_data_schema_labels.py` | — | schema/标签契约 | 65 |
| `tests/unit/data/test_data_feature_pipeline.py` | — | scaler identity/fallback/G9 mask 契约 | 105 |
| `tests/unit/data/test_context_warmup_windows.py` | — | warmup context 契约 | 200 |
| `tests/unit/data/test_dataset_cache.py` | — | dataset 接入缓存契约 | 370 |
| `tests/unit/data/test_feature_cache.py` | — | 缓存原语契约 | 468 |
| `tests/unit/data/test_data_dataset_triple.py` | — | `__getitem__` 三元组契约 | 50 |
| `tests/unit/scripts/test_eval_preprocessing.py` | — | 评估 preprocessing 契约 | 184 |
| `tests/unit/config/test_config_defaults.py` | — | 默认配置隔离契约 | 71 |
| `tests/unit/test_train_metadata.py` | — | train CLI / metadata 契约 | 169 |

## 4. 核心数据模型

### 4.1 张量契约

- Dataset 单样本：`x` 为 `[F_out, 60]` float32（`data/dataset.py:730-744`，窗口 `window.T`），`y` 为 `long`（52 类），`y_ret` 为 `float32`（clip ±0.5，`data/dataset.py:742`）。
- DataLoader 默认 collate：`x:[B,F_out,60]`；模型首层为 `Conv1d(F_in, 128, kernel=7)`（`inception_blocks.py:199`），故 `F_out == config.featurenum`。
- 标签：`future_ret[t]=open[t+1+horizon]/open[t+1]-1`（`data/labels.py:6-19`），`horizon=5`；`BINS=linspace(-0.25,0.25,51)`（`config/defaults.py:15`），`C=52`。

### 4.2 F 的组成（当前默认 `F=69`）

`APPROVED_RAW_FEATURES` 共 51 列（`data/schema.py:25-38`）：

| 组 | 列数 | 列 | 处理 |
|---|---|---|---|
| G1_Price | 12 | `open,high,low,ma_5,ma_10,ma_20,ma_60,ema_12,ema_26,sar,trend_duokong,trend_shortline` | `/prev_close-1` → per-code robust `(x-med)/(IQR/1.349)` + clip±5 |
| G3_Vol | 7 | `volatility_5d/10d/20d,std_5/10/20,atr` | per-code winsor 1/99 |
| G4_Volume | 3 | `volume_ratio_5d/10d,amihud` | per-code winsor 1/99 |
| G5_Tech | 6 | `macd,dmi,adx,boll,kelch,trend_duokong_dev` | 仅 `macd` relative；其余 5 列透传 |
| G8_Quality | 5 | `gross_margin,net_margin,roe,roa,debt_to_equity` | 透传（缺失填 0） |
| G9_Margin | 18 | 6 基础 + 6 `*_raw` + 6 `*_ts` | `clip[0,1]` + 每列 1 mask |

- 51 = 12+7+3+6+5+18。`G9_MASK_COLUMNS` = 18（`data/schema.py:48`），故 `F_out = 51+18 = 69`。
- 注意：`GROUP_DEFS_PER_CODE`（`data/scaler.py:37-50`）额外注册了 **G6_Valuation(pe/pb/pcf/ps) 4 列** 与 **G7_Growth(4 列)**，共 59 列；这 8 列不在 `APPROVED_RAW_FEATURES` 中（`data/scaler.py:42-43`）。`PER_CODE_CONFIG` 也为 G6/G7 定义了配置（`data/scaler.py:60-61`），默认路径永不触达。
- 历史 `F=45`（39+6 mask）为旧 schema，见 `train.py:15`、`docs/per_code_normalization_spec.md:7,21`。

### 4.3 per-code group 定义与变换决策

`PER_CODE_CONFIG`（`data/scaler.py:55-64`）：

```
G1_Price    : transform="relative", robust=True,  clip=(-5,5)
G3_Vol      : transform=None,       robust=False, winsor=(1,99)
G4_Volume   : transform=None,       robust=False, winsor=(1,99)
G5_Tech     : transform="relative_macd_only", robust=False, winsor=(1,99)
G6_Valuation: transform="asinh",    robust=True,  clip=(-5,5)     # 默认不触达
G7_Growth   : transform=None,       robust=False, winsor=(1,99)   # 默认不触达
G8_Quality  : transform=None,       robust=False, 跳过
G9_Margin   : transform=None,       robust=False, clip=(0,1)
```

### 4.4 G9 mask

- `mask_col = f"{col}_mask"`，`mask=1` 表示原值有限（observed），`0` 表示缺失（`data/scaler.py:286,291`）。
- mask 在输出列末尾按 `feature_cols` 中 G9 列出现顺序追加（`data/scaler.py:359-362`；`data/scaler.py:217,220`）。
- rolling 分支：`output_feature_cols` 同样为每个 `G9_RAW_FEATURES` 列追加 mask（`data/rolling_scaler.py:129`），但实际 mask 仅在 passthrough 分支生成（`data/rolling_scaler.py:240-243`）。

### 4.5 rolling state

`_RollingDatasetState`（`data/dataset.py:90-185`）聚合：`normalizer`（rolling 参数+scope）、`feature_cols`、`fallback_scaler`（已拟合 `PerCodeGroupedScaler`）、`schema_manifest`、`identity_hash`。持久化 payload version `v1_rolling_state`（`data/dataset.py:93`）。rolling 训练集只 `fit` fallback 一次；验证集通过 `scaler_stats` 复用（测试 `test_rolling_normalization.py:225-246`）。

## 5. 核心类详解

> 特别说明：任务模板中提及的 `ParquetScalerConfig` / `ScalingConfig` **在本仓库中不存在**（全局搜索无匹配）。实际配置载体为：`ParquetDataConfig`（dataset 层）、`RollingNormalizationConfig`（rolling 层）、`PER_CODE_CONFIG` 字典（per-code 层）、`_RollingDatasetState`（rolling 运行时状态）。

### 5.1 `PerCodeGroupedScaler`（`data/scaler.py:71`）

- **职责**：按 code 独立拟合/应用统计量，G1/G5 relative、G6 asinh、G3/G4/G7 winsor、G8 透传、G9 clip+mask；身份绑定与 pickle 持久化。
- **关键方法**：
  - `identity_hash_for(manifest)` 静态，`:89-92`
  - `transform_config_digest()` 静态，`:94-97`（payload = groups+config+version）
  - `set_identity(manifest)` `:99-102`
  - `validate_requested_schema(feature_cols, add_mask=True)` `:104-115`（校验 `feature_cols`/`add_mask`/`feature_cols_out`/`mask_cols`/`fitted`/统计完整性）
  - `fit(df, feature_cols=None) -> self` `:117-223`；默认 `feature_cols=None` 时仅排除 `code/kline_time/is_trading`（`:119-120`，会包含 close 等，dataset 恒显式传参）
  - `_fit_global_fallback(df)` `:225-251`（未见 code 回退）
  - `_relative_transform(vals, close)` `:253-261`（`np.roll(close,1)`）
  - `transform_code(code, feat, feature_cols, close=None) -> [N,F_out]` `:263-366`
  - `save(path)` `:369-398`；`load(path)` classmethod `:400-434`
- **分支要点**：
  - G8/未分组：填 0 透传，无 mask（`:276-283`）
  - G9：`observed=(~missing)`、`clip(0,1)`、追加 mask（`:284-292`）
  - G1 relative（`:307-308`）、G5 relative_macd_only（`:309-316`）、G6 asinh+robust（`:317-331`）、robust（`:335-348`）、winsor-only（`:349-357`）
  - 末尾 `np.stack(out_cols)` + `np.concatenate(masks)`（`:359-362`），NaN/inf→0（`:363-366`）
- **依赖**：numpy/pandas/hashlib/json/pickle/os；无其他 data 模块 import（`data/scaler.py:19-28`）。

### 5.2 `RollingNormalizer` / `RollingNormalizationConfig`（`data/rolling_scaler.py:51,93`）

- **职责**：无 fit、无持久化的纯变换 kernel；`[t-251,t]` 因果窗口，历史不足回落到调用方提供的 frozen fallback。
- **`RollingNormalizationConfig`**（`:51-72`，frozen dataclass）：`window=252,min_periods=120,include_current_t=True,lower/upper_percentile=1/99,robust_clip=5.0,add_g9_masks=True,scope="e4"`；`__post_init__` 校验（`:64-72`）。
- **scope 预设**（`:43-48`）：`e2=ROLLING_PRICE_FEATURES(9)+("macd",)=10`；`e3=e2+3 volatility=13`；`e4=ROLLING_FEATURES=16`。
- **关键方法**：
  - `scope_features()` `:104-105`
  - `transform_config_digest()` `:107-125`（scope 解析成子集列进 digest；`scope` 字段本身从 config 明细剔除）
  - `output_feature_cols(feature_cols)` `:127-130`（`feature_cols` + 所有 G9 列的 mask）
  - `schema_manifest` `:132-145`；`identity_manifest` `:147-153`；`identity` `:155-156`
  - `_validate_feature_cols` `:158-163`（**close 禁止入列**；去重）
  - `_validate_inputs` `:165-188`（形状校验；fallback 截到 `[:values.shape[1]]`）
  - `_relative` `:190-200`
  - `transform_code(features, feature_cols, close, frozen_fallback=None)` `:202-249`
  - `_rolling_column` `:251-310`（已向量化，pandas rolling；robust vs winsor）
- **依赖**：`data.schema.G9_RAW_FEATURES`（`:12`），numpy/pandas/hashlib/json/dataclasses。

### 5.3 `_RollingDatasetState`（`data/dataset.py:90`）

- **职责**：rolling 训练/验证的 identity 载体，封装 `RollingNormalizer` + 已拟合 frozen fallback；绝不重新 fit。
- **关键方法**：`__init__` `:95-123`；`_identity_hash` `:125-128`；`validate(source_manifest, feature_cols, scope=None)` `:130-144`；`save` `:146-160`；`load` `:162-185`。
- **依赖**：`RollingNormalizer`/`RollingNormalizationConfig`、`PerCodeGroupedScaler`/`SCALER_VERSION`（`data/dataset.py:46-47`）。

### 5.4 `ParquetDataConfig` / `ParquetDataset`（`data/dataset.py:51,188`）

- **`ParquetDataConfig`** 关键字段：`seq_len=60`(54)、`horizon=5`(55)、`bins`(56)、`feature_cols=None`(61)、`filter_is_trading=True`(63)、`role`(65)、`start/end_date`(67-68)、`normalize="per_code"`(71)、`rolling_scope="e4"`(72)、`scaler_path`(75)、`per_code_add_mask=True`(83)、`cache_enabled=False`(85)、`cache_dir`(86)、`rebuild_cache`(87)。
- **`ParquetDataset` 关键方法**：
  - `__init__` `:203-212`（强制 `filter_is_trading`、role 校验）
  - `_scaler_identity` `:214-230`（parquet path/size/mtime/rows/schema digest + fit 日期 + feature_cols + normalize + mask + transform_digest + version）
  - `_rolling_source_identity` `:232-238`（剔除 `fit_*`/`transform_digest`/`scaler_version`/`max_codes`）
  - `_cache_key` `:240-272`
  - `_load_and_prepare` `:274-559`（读取/过滤/context/归一化/窗口/标签/缓存写入）
  - `_apply_cache_hit` `:561-599`；`_resolve_scaler_on_cache_hit` `:601-665`；`_save_cache` `:667-687`
  - `_preprocess_features` `:689-702`；`_print_label_stats` `:704-725`
  - `__len__` `:727`；`__getitem__` `:730-747`
  - `create_dataloaders` `:749-810`
- **归一化接入**：per_code `:353-395` + 循环 `:456-465`；none `:396-399`；rolling `:400-422` + 循环 `:466-477`。

### 5.5 `FeatureCache` / `_FeatureView` / `_WindowIndex`（`data/feature_cache.py:278,123,198`）

- `CACHE_FORMAT_VERSION="v2_context_warmup"`（`:30`）。
- `_MMAP_REGISTRY` + `_open_shared_mmap`（`:41-52`）保证同进程同路径单一只读 memmap，修复 Windows spawn 下 WinError 1455。
- `compute_cache_key`（`:84-107`）纳入 `cache_format_version/base_identity/role/rolling_scope/scaler_identity_hash/seq_len/horizon/max_windows_per_code/bins_digest`。
- `_FeatureView` 仅 pickle path/offset/n/num_features（`:178-195`）；`_WindowIndex` 以 `code_ids/starts` 紧凑存储（`:198-251`）。
- `FeatureCache.save` 新 generation + `os.replace` 原子发布（`:368-414`）；`clear_cache` 仅显式调用（`:468-485`）。

### 5.6 消费方要点

- `train.py:52-63` `configure_preprocessing`：校验 `normalize` 并隔离 rolling 产物路径（`logs/rolling_{scope}/…`）。
- `train.py:79-114` `build_preprocessing_metadata`：`:90-91` 硬校验 `featurenum==69`；rolling 记录 scope/digest/identity/schema_manifest。
- `train.py:308-321` featurenum 自动校正；rolling 分支维度不符直接 raise（`:310-314`）。
- `models/cnn_transformer/model.py:98-118`：`forward` 返回 `(logits, ret_pred)`，首层经 `MultiWindowInceptionCNN`（`inception_blocks.py:192-203`）。
- `scripts/eval_bins_mapping.py:82-185`：评估复用与维度校验；`:250` 默认 `featurenum` 缺省 45（历史值）。

## 6. 核心流程

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 1. 入口装配  train.py:226-241 ParquetDataConfig(normalize, rolling_scope, scaler_path) │
│    configure_preprocessing: SCALER_PATH/LOG_DIR 按 normalize/scope 隔离               │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 2. 特征列选择  dataset.py:279-291                                                       │
│    feature_cols 显式传入 → 否则 _default_feature_cols(APPROVED 51)                     │
│    num_features = len(feature_cols)（temp；归一化后可能追加 mask）                      │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 3. 缓存 key  dataset.py:214-272 → feature_cache.py:84                                    │
│    per_code: identity_hash_for(_scaler_identity)                                        │
│    rolling : RollingNormalizer.identity(source_identity, feature_cols)                  │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                       cache_enabled? ──┤
                     hit│                │miss
                        ▼                ▼
┌──────────────────────────────┐  ┌─────────────────────────────────────────────────────┐
│ 3a. _apply_cache_hit          │  │ 4. 读 parquet → is_trading 过滤 → 时间过滤+context   │
│  _FeatureView/_WindowIndex    │  │    dataset.py:304-349                                │
│  _resolve_scaler_on_cache_hit │  │    context: start 前 max(seq_len-1,251/1) 行         │
│  （仍校验 scaler identity）    │  │    标 _transform_context=True                        │
└───────────────┬───────────────┘  └───────────────────────┬─────────────────────────────┘
                │                                            ▼
                │                 ┌─────────────────────────────────────────────────────┐
                │                 │ 5. normalize 分支 dataset.py:353-424                  │
                │                 │  per_code: fit(~context) 若训练；否则 load/复用        │
                │                 │  rolling : fit fallback(~context) 若训练；构造 state   │
                │                 │  none    : 无 scaler                                  │
                │                 └───────────────────────┬─────────────────────────────┘
                │                                            ▼
                │                 ┌─────────────────────────────────────────────────────┐
                │                 │ 6. 逐 code transform dataset.py:445-479               │
                │                 │  per_code: scaler.transform_code → [N,51+18mask]      │
                │                 │  rolling : fallback.transform_code →                   │
                │                 │            normalizer.transform_code(..., frozen_fb)  │
                │                 │  none    : NaN→0                                      │
                │                 └───────────────────────┬─────────────────────────────┘
                │                                            ▼
                │                 ┌─────────────────────────────────────────────────────┐
                │                 │ 7. 窗口/标签 dataset.py:481-534                        │
                │                 │  label_pos = s+seq_len-1                              │
                │                 │  valid_starts: 非 context & future_ret 非 NaN         │
                │                 │  discrete = digitize(future_ret, BINS)                │
                │                 └───────────────────────┬─────────────────────────────┘
                │                                            ▼
                │                 ┌─────────────────────────────────────────────────────┐
                │                 │ 8. _save_cache（新 generation + .ok）dataset.py:558    │
                │                 └───────────────────────┬─────────────────────────────┘
                └────────────────────────────────────────┤
                                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 9. DataLoader collate → x[B,F_out,60] → CNNTransformer(stem Conv1d→BN) → [B,52]       │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 7. 模块依赖关系

- **data 不依赖具体 model**：`data/*` 无 `models` import；模型仅通过 `featurenum` 数值对齐（`train.py:308-321`、`scripts/eval_bins_mapping.py:254-255`）。
- **训练/评估复用 scaler state**：
  - 训练：`create_dataloaders` 训练集 fit 并保存（`data/dataset.py:382-395`），验证集传 `train_dataset.scaler_stats`（`:796`）。
  - per_code 复用持久化文件：`:368-381`（`identity_hash` 必须匹配 `expected_identity`，否则重拟合覆盖）。
  - rolling 复用持久化 state：`:414-422`（`_RollingDatasetState.validate` 校验 scope/identity/schema）。
  - 评估：`scripts/eval_bins_mapping.py:82-137` 从 checkpoint metadata 解析并严格校验；正式评估禁止临时 fit（`:228-234`）。
- **缓存命中红线下沉**：命中路径不读 parquet 但仍校验 scaler（`data/dataset.py:592-593,601-665`）；训练命中若缺 scaler 显式失败（`:634-639`）。
- **warmup context 依赖**：dataset 保留 context → `is_context` 过滤标签日（`:499-504`）；rolling 归一化统计预热由 `min_periods`/fallback 单独处理（两套机制，spec:70）。rolling 评估 context 上限 `max(seq_len-1,251)`（`:326-329`）。
- **缓存对归一化的依赖方向**：缓存只存归一化后 features（float32）+ 小数组；key 含 scaler identity，故 identity 变更自动失效（`data/feature_cache.py:30,84-107`）。

## 8. 已知问题与痛点

1. **G9 `*_raw` / `*_ts` 被 `clip[0,1]` 抹掉负值与量纲**
   - `PerCodeGroupedScaler.transform_code` 对所有 `G9_Margin` 列无差别 `np.clip(vals_filled, 0, 1)`（`data/scaler.py:284-289`）。
   - `RollingNormalizer.transform_code` 对所有 `G9_RAW_FEATURES` 列同样 `clip(0,1)`（`data/rolling_scaler.py:240-241`）。
   - `G9_RAW_FEATURES` 含 6 个 `*_raw` 与 6 个 `*_ts`（`data/schema.py:40-47`），且被列入 `APPROVED_RAW_FEATURES`（`:34-37`）与 `GROUP_DEFS_PER_CODE`（`data/scaler.py:46-49`）。
   - "G9 已是截面 rank [0,1]" 的假设（`docs/per_code_normalization_spec.md:40`）仅对 6 个基础列成立；`_raw` 未定义任何专门变换，负值/大于 1 的真实值被不可逆截断；`_ts` 语义在代码与文档中均无定义。

2. **18 个 G9 mask 高度冗余（任务方观测有效秩≈1.05；代码侧成因可证）**
   - mask 逐列独立生成：`data/scaler.py:217`（列名列表）、`data/scaler.py:286-291`（值）；`data/rolling_scaler.py:129`、`:240-243`。
   - 但两融列缺失是结构性的（非标的股整列全空，spec:40），同一股票 18 列 mask 几乎完全一致，通道间近似线性相关，18 维有效秩趋近 1。
   - 后果：69 通道输入中有 18 个近似重复通道，首层 `Conv1d`（`inception_blocks.py:199`）无差别卷积，浪费通道/参数，并可能使紧随的 `BatchNorm1d`（`:200`）统计退化。
   - 数值 1.05 属任务方观测，代码侧只能确认「逐列独立 + 缺失结构共享」这一成因。

3. **rolling 对入 scope 的 G9 列不生成 mask，且 `output_feature_cols` 与实际列数不一致**
   - `output_feature_cols` 无条件为每个 `G9_RAW_FEATURES` 列追加 mask（`data/rolling_scaler.py:127-130`）。
   - `transform_code` 先判断 `column in rolling_cols`，命中即 `continue`（`:224-236`），**永不进入** G9 mask 分支（`:240-243`）；最终 `np.stack(output_columns + masks)`（`:247`）列数会少于 `output_feature_cols` 声明值，`fallback_mask` 宽度（`:216-217`）也与实际输出不符。
   - 当前 `e2/e3/e4` 均不含 G9 列（`:43-47`），故无现网故障；一旦按"E5 scope 扩到 G9 raw"演进会立即触发列数/索引错位。
   - 附带：入 scope 的 G9 列会被当作 winsor 列（robust=False 分支，`:304-307`）而非 frozen 的 `clip[0,1]+mask`，语义与 per-code 分支不一致。

4. **`close` 被硬性禁止进入 feature_cols**
   - `RollingNormalizer._validate_feature_cols` 直接 raise（`data/rolling_scaler.py:158-161`）；`PROHIBITED_COLUMNS` 含 `close`（`data/schema.py:52`）；spec 明确 close 仅辅助（spec:17,33,80）。
   - dataset 始终读取 close（`data/dataset.py:306`），但只作为 relative/rolling helper 传入（`:452,459,469-474`）。
   - 该禁令直接阻断 "close 入特征 / E0 relative-only" 类新设计；且两套 scaler 对 close 的处理不一致：`PerCodeGroupedScaler` 无显式禁止，未分组列按 `grp=None` 静默透传（`data/scaler.py:276-283`）。

5. **`train.py` 硬编码 featurenum=69**
   - `build_preprocessing_metadata` 在 `:90-91` 对 `featurenum != 69` 直接 raise。
   - rolling 分支 `:310-314` 对实际维度与 `config['CNNTransformerConfig']['featurenum']` 不符直接 raise；该默认值 `config/defaults.py:37` 固定 69。
   - 任何 F 变化（G9 单 mask、close 入特征、E0 relative-only、子集消融）都会在该契约处被卡死，需同步改 `train.py`、`config/defaults.py`、测试与模型配置。

6. **E1 per_code 无法收窄到子集**
   - `train.py` 无 `--feature_cols` 选项（`parse_args` `:117-149`）；`train.py:226-241` 构造 `ParquetDataConfig` 时未传 `feature_cols`，而 `create_dataloaders` 直接透传 `config.__dict__`（`data/dataset.py:766-768,784-792`）。
   - 因此 per_code 恒用默认 51 列（`data/dataset.py:279-282`），无法做"只 G1"等静态归一化消融。
   - 对比 rolling 已有 scope 预设与 CLI（`data/rolling_scaler.py:43-47`、`train.py:39,142`）。基础设施（cache key/identity 已含 feature_cols，`data/dataset.py:227`、`data/feature_cache.py:99`）其实支持子集，只是入口未暴露。

7. **warmup / 缓存版本耦合**
   - `CACHE_FORMAT_VERSION="v2_context_warmup"`（`data/feature_cache.py:30`）与 context warmup 语义强绑定，版本进入 cache key（`:96`）与 load 校验（`:327-332`）。
   - context 语义分散在 `data/dataset.py:318-336,481-504`；rolling 归一化统计预热在 `data/rolling_scaler.py:251-310`。两类 warmup 易混（spec:70）。
   - `min_periods=120`/`window=252`（`data/rolling_scaler.py:55-56`）与 `context_limit=max(seq_len-1,251)`（`data/dataset.py:326-329`）通过 251 隐式耦合，单独改动易失配。
   - 命中路径从 `meta.extra` 恢复 `rolling_audit`（`data/dataset.py:576-577,670-672`），格式变更需同步。

8. **digest 纳入了默认路径不可达的组**
   - `transform_config_digest` payload 含完整 `GROUP_DEFS_PER_CODE` 与 `PER_CODE_CONFIG`（`data/scaler.py:96`），其中 G6/G7 共 8 列默认不出现（`data/scaler.py:42-43,60-61`）。改动这些"无关"组也会导致所有 scaler identity/缓存失效，增大变更面。

9. **代码坏味道 / 潜在缺陷**
   - `data/dataset.py:460-465`：per_code 分支的 `if len(...)!=...: pass / else: _preprocess_features(...)` 是 no-op 或重复处理，逻辑冗余。
   - `data/scaler.py:139-142`：未分组列（UNKNOWN）静默按原值透传，不告警；与 `_default_feature_cols` 的白/黑名单保护（`data/schema.py:81-87`）不一致。
   - `none` 分支把 NaN 直接填 0（`data/dataset.py:692-699`），既不生成 mask 也不区分"真实 0/缺失"，缺失信息丢失（该分支当前不被 `train.py` CLI 暴露，`train.py:141` 仅 `per_code|rolling`）。
   - `data/rolling_scaler.py:186-187`：frozen fallback 被截断到 `[:values.shape[1]]`，滚列入 scope 时 fallback 对齐依赖列顺序天然一致，缺少显式断言。
   - `models/cnn_transformer/inception_blocks.py:219` 注释写 `cnn_out_channels*4`，与最后一个 block 输出 `cnn_out_channels`（`model.py:78` 取 `config.cnn_out_channels`）不符，属陈旧注释，易误导通道数理解。
   - `GROUP_DEFS_PER_CODE` 共 59 列（含 G6/G7），`APPROVED` 仅 51 列，二者差集 8 列无测试守护。

10. **项目记忆中的训练/评估结论（非代码结论，供演进参考）**
    - E1(per_code)/E2(e2)/E3(e3)/E4(e4) 四臂均 epoch 1 达最优、约 6 epoch 早停；warmup 修复后（154 交易日）四臂 TopN 回测全部跑输基准，仅 E2/E4 截面 IC 弱正，E2 最强。说明当前默认 69 维 schema 与 frozen 归一化未带来正超额，是本次 redesign 的直接动机。

## 9. 演进方向建议（仅方向，不含实现）

1. **`close` 入特征 / E0 relative-only**：解除 `data/rolling_scaler.py:158-161` 与 `data/schema.py:52` 的 close 禁令，新增 "relative-only" 变换路径（复用 `_relative`，不接 rolling 统计），并提供独立 `feature_cols`/scope 表达。
2. **R 组 asinh + clip**：为极右偏/重尾组引入 asinh（可参考 `PerCodeGroupedScaler` 的 G6 asinh 分支 `data/scaler.py:317-331`），并统一 `clip` 边界；rolling 侧目前完全没有 asinh，需要新增变换族。
3. **G9 单 mask（去 18 重冗余）**：用 1 个共享 observation mask 替代 18 个逐列 mask，同步改 `G9_MASK_COLUMNS`、`F_out`、`train.py:90-91`、`config/defaults.py:37`、`models` 输入通道；可先加实验性 epoch 级对照。
4. **E5：scope 扩到 G9 raw**：必须先修复问题 3（`output_feature_cols` vs 实际列数、mask 分支短路），并把"入 scope 的 G9 列不使用滚动统计"明确编码，避免 winsor 误用。
5. **静态/动态逐级对照**：扩展 `ROLLING_SCOPE_FEATURES` 增加 `e0`（空集，纯 relative）/`e1`（仅 G1）等预设；为 per_code 增加子集 CLI（`--feature_cols` 或静态 scope），使 E 系列可在同一框架逐级对照。
6. **去 `featurenum` 硬编码**：让模型输入维度完全由 `dataset.num_features` 推导，删除 `train.py:90-91` 的 69 断言与 rolling 维度硬失败，仅保留 metadata 记录与一致性校验。
7. **identity/digest 收敛到活动组**：`transform_config_digest` 只纳入实际参与的特征组与 scope 子集（参考 `RollingNormalizer.transform_config_digest` 的 scope 子集做法），降低无关变更导致的缓存失效。
8. **mask 策略与缺失语义统一**：为 `none`/新相对组补齐显式缺失通道或统一"缺失填 0 + 可选 mask"策略，避免 `none` 分支信息丢失；同时为 G9 `_raw`/`_ts` 明确语义与变换，杜绝 `clip[0,1]` 的静默信息破坏。
9. **文档同步**：`docs/per_code_normalization_spec.md` 为 G1~G9 决策唯一事实源，任何组/变换/mask 变更须同步该文档与 `data/AGENTS.md` 的 F 描述，并 bump `CACHE_FORMAT_VERSION`（`data/feature_cache.py:30`）使旧语义缓存失效。

## 附录 B：变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-09-13 | 首版：归一化层现状分析（Phase 1 交付） |







