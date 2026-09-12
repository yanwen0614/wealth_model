# 审查清单 — memmap-data-cache

> 生成时间：2026-09-13
> Task Dir：docs/agent/task/20260912_2359_memmap-data-cache/
> 需求类型：feature（data 层，跨平台 np.memmap 缓存）

## 需求理解

为 `ParquetDataset` 增加跨平台（Windows/Linux）`np.memmap` 文件缓存层，解决：
1. Windows 必须 spawn，每个 DataLoader worker pickle 复制整份常驻特征矩阵（训练集 ~2.8GB），
   16GB 内存只能 `num_workers=1`、GPU 利用率仅 ~42%；
2. Windows 默认 parquet 在 SMB `Z:`（`config/defaults.py:10`），E1–E4 每组训练都要重读 ~3.5GB
   并重建 ~3.16GB `groups`。

设计基线（上游已定，不推翻）：两平台统一 memmap 路径；`cache_enabled` 默认关、`train.py` 默认开；
缓存根 env > 参数 > 平台默认（禁盘符硬编码）；key 在 `_scaler_identity` 基础上扩展；原子写新
generation、`.ok` 标记、不自动删除；`self.index` 默认 list、缓存路径用 `_WindowIndex`；`groups`
feature 用 `_FeatureView`；只缓存 float32 features、不做精度减半。

### 显式假设（需用户确认）

| # | 假设 | 影响 |
|---|------|------|
| A1 | 缓存 key **必须**追加 `seq_len`/`horizon`/`max_windows_per_code`/`bins` 摘要（`_scaler_identity` 未含），否则会跨配置串缓存 | 若用户认为可省略，则 `--max_codes`/窗口参数实验会读到错误 index |
| A2 | `--rebuild_cache` 语义 = 写**新 generation 目录**并保留旧目录（不自动删除），读侧取最新 `.ok` | 若要求清理旧缓存，需另立任务 |
| A3 | 缓存命中路径仍要求 validation 传入训练 `scaler_stats` 做 identity 校验（不因缓存弱化防泄露） | 兼容既有 `create_dataloaders` 语义 |
| A4 | `scripts/multi_seed_train.py` 与 `train.py` 一样透传缓存配置（默认开启） | E1–E4 多 seed 收益一致 |
| A5 | 缓存仅加速 `ParquetDataset` 构建，不改变 `__getitem__` 返回三元组与标签口径 | 保持 open-open horizon=5 / 52 类 |
| A6 | 默认缓存根：Linux `~/.cache/cnn`(XDG)、Windows `%LOCALAPPDATA%\cnn\cache`；env `CNN_DATA_CACHE` 优先 | 跨平台可移植，不写盘符 |

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| data | `data/feature_cache.py` | 新增 | 缓存根/key/原子写；`_WindowIndex`/`_FeatureView` 访问器 |
| data | `data/dataset.py` | 修改 | `ParquetDataConfig` +3 字段；`_load_and_prepare` 命中/落盘分支；groups/index 访问器化 |
| config | `config/defaults.py` | 修改 | `CACHE_ENABLED/CACHE_DIR/REBUILD_CACHE` 默认键 |
| 入口 | `train.py` | 修改 | `--cache_dir/--no_cache/--rebuild_cache`；训练默认开启 |
| 入口 | `scripts/multi_seed_train.py` | 修改 | 透传缓存配置（默认开启） |
| tests | `tests/unit/data/test_feature_cache.py` | 新增 | 缓存正确性/隔离/原子/访问器/小样本集成 |
| docs | `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`data/AGENTS.md`、根 `AGENTS.md` | 修改 | 缓存契约与验证命令 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 结论 |
|------------|---------|------|------|
| memmap / np.memmap | 否 | — | 全项目无既有内存映射缓存，需新建 |
| cache_enabled / cache_dir / rebuild_cache | 否 | — | `ParquetDataConfig` 无缓存字段，需新增 |
| _FeatureView / _WindowIndex / CNN_DATA_CACHE | 否 | — | 无既有权重/访问器实现，需新建 |
| ParquetDataset / `_load_and_prepare` | 是 | `data/dataset.py:177,221` | 复用现有分组/索引/标签逻辑，不重写 |
| `_scaler_identity` | 是 | `data/dataset.py:203-219` | 缓存 key 基础，追加字段而非新造 |
| PerCodeGroupedScaler.identity_hash / `identity_hash_for` | 是 | `data/scaler.py:89-102` | 复用 canonical JSON sha256 派生 scaler identity |
| `_RollingDatasetState.identity_hash` | 是 | `data/dataset.py:112-117` | rolling key 复用其 manifest 哈希 |
| `PerCodeGroupedScaler.save/load` | 是 | `data/scaler.py:369-434` | 参考其「identity 不匹配即拒绝」的校验模式 |
| eval `ds.groups`/`ds.index` 读取 | 是 | `scripts/eval_bins_mapping.py:290-300`、`scripts/run_eval_pipeline.py:263-271` | 缓存默认关，须保证继续可用 |
| `.index((code,s))` 依赖 | 是 | `tests/unit/data/test_dataset_label_openopen.py:154,157` | `_WindowIndex` 必须实现 `.index()` |
| 手工赋 list index | 是 | `tests/unit/data/test_data_dataset_triple.py:24` | 默认 list 不破坏该测试 |
| `groups[...]["features"]` 读取 | 是 | `tests/unit/data/test_data_feature_pipeline.py:97` | `_FeatureView` 须支持 `np.isfinite` |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名/日志前缀(`[FeatureCache]`)/注释风格与 `data/*` 一致；line-length 120；无通配符/未使用 import | HIGH |
| 2 | 模块边界 | 缓存只落在 `data/`，不改 `models/*`/`training/*`/`criterion/*`；`train.py` 仅透传不改训练语义 | HIGH |
| 3 | 数据安全 | 无硬编码凭证/无盘符硬编码；缓存根用 `pathlib`；读写路径可被 env 覆盖 | HIGH |
| 4 | 缓存正确性 | key 覆盖 role/rolling_scope/scaler identity/seq_len/horizon/max_windows/bins/parquet size+mtime；命中内容与内存路径逐元素一致 | HIGH |
| 5 | 跨平台 | Windows `os.replace` 不被在用 mmap 阻塞（新 generation）；Linux/Windows 根解析与路径拼接均正确；spawn 下 `_FeatureView` 可 reopen | HIGH |
| 6 | 单测兼容 | `cache_enabled=False` 下 `tests/unit/**` 零改动全绿；`.index()`/负索引/list 赋值/`np.isfinite(features)` 语义保持 | HIGH |
| 7 | 时序防泄露 | 缓存命中仍复用训练 scaler、验证集绝不重 fit；`is_trading=False` 过滤不可被缓存绕过；val context 不进入 index | HIGH |
| 8 | 原子性/幂等 | 未写 `.ok` 前不可读；异 key 隔离；重复 save 生成新 generation 不覆盖旧目录；失败中途不产生半成品被误读 | HIGH |
| 9 | 错误处理 | 缓存损坏/`.ok` 缺失/`meta` schema 不符时回退内存路径而非静默吞异常；异常不静默 | MEDIUM |
| 10 | 性能风险 | 无 pickle 复制整份特征（禁 per-code memmap 切片）；memmap 全局共享；不引入 bf16/fp16；generation 不自动删除须文档说明 | MEDIUM |
| 11 | 精度/口径 | features 严格 float32；标签 open-open horizon=5 / 52 类不变；`num_features`（F=69）与 `feature_cols_out` 命中后恢复一致 | HIGH |

## 验证命令（Quality Gate 执行）

```bash
uv run --project . python -m unittest tests.unit.data.test_feature_cache
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
# T01/T02 full：允许追加 tmux 后台冒烟
uv run --project . python train.py --smoke --num_workers 0
```

> full 升级触发：#1（`data/dataset.py` 核心链路）+ #6（PLAN 风险 high）→ T01/T02 走 full；
> T03/T04 走 fast（ruff + pyright + unittest tests/unit）。

