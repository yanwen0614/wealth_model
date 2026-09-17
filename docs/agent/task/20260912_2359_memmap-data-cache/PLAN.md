# memmap-data-cache Implementation Plan

> Generated: 2026-09-13
> Task Dir: docs/agent/task/20260912_2359_memmap-data-cache/
> 类型: feature（data 层，跨平台 memmap 数据缓存）

## Goal

为 `ParquetDataset` 增加跨平台（Windows/Linux）的 `np.memmap` 文件缓存层：把归一化后的
float32 特征矩阵与小数组（标签/价格/时间）落盘并复用，使多 worker 不再 pickle 复制整份常驻
特征矩阵（训练集 ~2.8GB），消除 Windows spawn 导致 `num_workers=1` / GPU 利用率 ~42% 的瓶颈，
并让 E1–E4 四组训练共享免去重复读取 SMB `Z:` 上 ~3.5GB parquet 与重建 ~3.16GB `groups`。

## Architecture

新增 `data/feature_cache.py`：缓存根目录解析（env/XDG/LOCALAPPDATA，`pathlib`）、缓存 key 派生
（在 `data/dataset.py:203` `_scaler_identity` 基础上追加 role/rolling_scope/scaler.identity_hash/
cache_format_version 及影响索引的 seq_len/horizon/max_windows_per_code/bins）、原子发布
（`tmp-<pid>-<uuid>` → flush → close → `os.replace` 到新 generation，写 `.ok` 标记）与两个轻量
访问器 `_WindowIndex`（list-like，支持 `__getitem__`(含负索引)/`__len__`/`__iter__`/`.index()`）
和 `_FeatureView`（持全局 memmap 引用 + offset，实现 `__array__/__getitem__/shape/dtype`）。
`data/dataset.py` 在 `_load_and_prepare` 顶部按 key 尝试缓存命中：命中则直接重建 groups/index 并
跳过 parquet 读取与 per-code/rolling 归一化，未命中则走原内存路径并在末尾落盘；`cache_enabled`
默认 `False` 保证单测/CI 零破坏，`train.py` 默认开启。只缓存 features（float32），标签、价格、
时间保留真实小数组，不做精度减半。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 平台分叉 | 两平台统一 memmap 同一代码路径 | Linux fork + Windows memmap 双路径 | 单一代码路径降低维护/测试面；平台差异仅体现在缓存根默认值与 worker 默认启动方式 |
| 开关门控 | `ParquetDataConfig.cache_enabled=False` 默认关，`train.py` 默认开 | 全局默认开 | 默认关保证既有单测/CI/评估脚本零改动；训练入口显式开启获得收益 |
| 缓存根 | env `CNN_DATA_CACHE` > 参数 > Linux `~/.cache/cnn`(XDG) / Windows `%LOCALAPPDATA%\cnn\cache`(回退 `~/AppData/Local`) | 硬编码 `Z:/E:` 盘符 | 禁止本机盘符硬编码，`pathlib` 拼路径，跨平台可移植 |
| 缓存 key | 既有 `_scaler_identity` + `role`/`rolling_scope`/`scaler.identity_hash`/`cache_format_version`，**并补 `seq_len`/`horizon`/`max_windows_per_code`/`bins` 摘要**，`sha256` 短哈希 | 仅用 `_scaler_identity` | `_scaler_identity` 不含 seq_len/horizon/max_windows/bins/role/scope，这些直接影响 index 与标签，缺失会跨配置串缓存；train/val、E1/E2/E3/E4 必须各自独立 key |
| 原子写 | `tmp-<pid>-<uuid>` → flush → 关句柄 → `os.replace` 到**新 generation** 目录，`.ok` 最后写；读侧只认 `.ok` | 就地覆盖同名 key（`os.replace` 覆盖） | Windows 下目标被 mmap 时 `os.replace` 报 `WinError 32`；绝不覆盖正在使用的 key；`--rebuild_cache` 写新 generation，运行期不自动删除 |
| 访问器 | `_FeatureView` 持全局 memmap + offset；`groups[code]["features"]` 不存 per-code memmap 切片 | 每 code 存独立 `np.memmap` 切片 | per-code 切片被 pickle 会整段复制，违背共享内存初衷 |
| index | `self.index` 默认仍为 list；仅缓存路径切换 `_WindowIndex` | 全局强制 `_WindowIndex` | `test_data_dataset_triple.py:24` 手工赋 list；`test_dataset_label_openopen.py:154,157` 依赖 `.index()`；默认 list 保持向后兼容 |
| 缓存范围 | 只缓存 features（float32） | 缓存全部数组/减半精度 | 小数组本身很小，保留真实数组可被评估脚本直接读取；不引入 bf16/fp16 避免精度回归 |
| 复用 scaler 语义 | 缓存命中仍要求 validation 传入训练 `scaler_stats`；key 用 scaler identity | 缓存绕过 scaler 校验 | `data/AGENTS.md`：验证集复用训练 scaler、禁止重 fit，缓存不得削弱该红线 |

## Impact

| 模块 | 文件 | 操作 | 风险等级 | 说明 |
|------|------|------|----------|------|
| data | `data/feature_cache.py` | create | high | 缓存根/key/原子写/访问器（`_WindowIndex`/`_FeatureView`）核心模块 |
| data | `data/dataset.py` | modify | high | `ParquetDataConfig` 新增 3 字段；`_load_and_prepare` 接入命中/落盘分支；groups/index 走访问器 |
| config | `config/defaults.py` | modify | medium | 新增 `CACHE_ENABLED/CACHE_DIR/REBUILD_CACHE` 默认键 |
| 入口 | `train.py` | modify | medium | CLI `--cache_dir/--no_cache/--rebuild_cache`，训练入口默认开启并透传 |
| 入口 | `scripts/multi_seed_train.py` | modify | low | 与 train.py 保持一致透传缓存配置（E1–E4 收益来源之一） |
| tests | `tests/unit/data/test_feature_cache.py` | create | medium | 缓存 round-trip/key 隔离/原子发布/访问器语义/小样本集成 |
| docs | `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`data/AGENTS.md`、根 `AGENTS.md` | modify | low | 记录缓存契约与验证命令 |

> 未受影响但需回归：`scripts/eval_bins_mapping.py:290-300`、`scripts/run_eval_pipeline.py:263-271`
> 读 `ds.groups[...]`/`ds.index[...]`（默认 `cache_enabled=False`，走原内存路径，须保持可用）。

## Task Decomposition

### T01: 缓存基础模块（key/根目录/原子写/访问器）
- **文件**: `data/feature_cache.py` (create)
- **描述**: 实现 `CACHE_FORMAT_VERSION`；`resolve_cache_root(cache_dir)`（env `CNN_DATA_CACHE` 优先，
  Linux `XDG_CACHE_HOME`/`~/.cache/cnn`，Windows `%LOCALAPPDATA%\cnn\cache` 回退 `Path.home()/AppData/Local`，
  全程 `pathlib`，禁止盘符硬编码）；`compute_cache_key(base_identity, role, rolling_scope,
  scaler_identity_hash, seq_len, horizon, max_windows_per_code, bins_digest, version)`（canonical JSON + sha256 短哈希）；
  `FeatureCache.load/save`：目录含 `features`(`<f4` memmap) + 小数组 + `meta.json`；原子写
  `tmp-<pid>-<uuid>` → flush → close → `os.replace` 到 `root/<key>-g<gen>/`，`.ok` 最后写，读侧只认 `.ok`；
  `--rebuild_cache` 写新 generation，不覆盖在用 key，不做运行期删除；`_WindowIndex`（list-like，支持
  `__getitem__` 含负索引/`__len__`/`__iter__`/`.index(value)`）；`_FeatureView`（持 memmap 引用 + offset，
  实现 `__array__/__getitem__/shape/dtype`，pickle 只复制引用不复制数据）。
- **依赖**: 无
- **预估行数**: +260
- **need_test**: true
- **验收标准**: (1) key 对 role/rolling_scope/seq_len/horizon/max_windows_per_code/bins/scaler identity/
  parquet size+mtime 任一变化而不同，同输入稳定；(2) save→load 后 features 逐元素 `float32` 相等、
  小数组与 index 完全一致；(3) 未写 `.ok` 前读不到，异 key 互不干扰，重复 save 生成新 generation 且
  旧目录不被覆盖；(4) `_WindowIndex` 的 `.index()`/负索引/迭代语义与 list 等价；(5) `_FeatureView`
  支持 `np.isfinite(v).all()`、切片、`.T`、`.shape`/`.dtype`；(6) 通过 monkeypatch env 断言
  Windows/Linux 根解析无盘符硬编码。
- **风险因子**: Windows `os.replace` 目标被 mmap 时报 `WinError 32`（→ 新 generation 规避）；
  `np.memmap` 若被逐 code 切片会触发 pickle 整段复制（→ `_FeatureView`）；generation 目录累积需在文档写明不自动清理。

### T02: dataset 接入与访问器兼容
- **文件**: `data/dataset.py` (modify)
- **描述**: `ParquetDataConfig` 新增 `cache_enabled: bool=False`、`cache_dir: str|None=None`、
  `rebuild_cache: bool=False`；`_load_and_prepare` 顶部计算 `_scaler_identity` 后派生缓存 key
  （per_code 用 `PerCodeGroupedScaler.identity_hash_for(expected_identity)`，rolling 用
  `_RollingDatasetState` 的 schema_manifest + source_identity 组合哈希）；`cache_enabled and not rebuild_cache`
  时尝试 load：命中则直接重建 `groups`（features 用 `_FeatureView`，标签/价格/时间用真实小数组）与
  `_WindowIndex`，跳过 parquet 读取与归一化，并恢复 `rolling_audit`/特征列/`num_features`；未命中或
  `rebuild_cache` 走原路径并在末尾 save；`validation` 命中时仍强制外部 `scaler_stats` 校验，绝不在
  验证集重 fit；`cache_enabled=False` 时保持 `self.index` 为 list、`features` 为 ndarray。
- **依赖**: T01
- **预估行数**: +180
- **need_test**: true
- **验收标准**: (1) 同一 parquet 下 cache on/off 的 `len(ds)`、`ds.index` 序列、`x/y/y_ret` 逐元素一致；
  (2) `ds.index.index((code,s))`、负索引、`sum(1 for c,_ in ds.index)` 可用；(3) `np.isfinite(ds.groups[c]["features"]).all()`
  与切片 `.T` 可用；(4) cache miss 自动回填、二次构造命中（日志可见）；(5) train/val/E2/E3/E4 的 key 互不相同；
  (6) `cache_enabled=False` 时 `tests/unit/data/*` 5 个既有测试零改动通过。
- **风险因子**: 缓存 key 漏字段导致跨配置串缓存（已补 seq_len/horizon/max_windows/bins）；
  命中路径遗漏 `_print_label_stats`/`rolling_audit` 等状态恢复；`_FeatureView` 在 spawn worker 内 reopen 失败。

### T03: 训练入口/配置默认开启与 CLI 透传
- **文件**: `config/defaults.py` (modify)、`train.py` (modify)、`scripts/multi_seed_train.py` (modify)
- **描述**: `config/defaults.py` 新增 `CACHE_ENABLED=True`、`CACHE_DIR=None`、`REBUILD_CACHE=False`；
  `train.py` 新增 `--cache_dir`、`--no_cache`、`--rebuild_cache`，将三项透传进 `ParquetDataConfig`
  并在配置打印中回显缓存状态与解析后的根目录；`scripts/multi_seed_train.py` 同步读取 `CACHE_*` 透传
  （E1–E4 多 seed 场景复用同一缓存根，但 train/val/scope key 隔离）。
- **依赖**: T02
- **预估行数**: +60
- **need_test**: true
- **验收标准**: (1) `make_default_config()` 含三键且 `CACHE_ENABLED is True`、`CACHE_DIR is None`；
  (2) `parse_args()` 默认 `cache_enabled=True`，`--no_cache` 时 `False`，`--rebuild_cache` 正确传递；
  (3) `--cache_dir` 显式路径优先于 env/默认；(4) `tests/unit/config/test_config_defaults.py` 仍通过
  （新增键不影响 BINS/EMLossConfig 独立复制断言）；(5) `python train.py --help` 呈现新参数且 `--smoke` 路径可跑。
- **风险因子**: 训练默认开启缓存首次会写盘（SMB/本机均可能较慢），需在日志提示一次性成本；
  `multi_seed_train` 未走 `configure_preprocessing` 时 rolling_scope 默认 e4，key 仍须带 scope 防串。

### T04: 单测与文档同步
- **文件**: `tests/unit/data/test_feature_cache.py` (create)、`README_TRAINING_CHAIN.md` (modify)、
  `docs/per_code_normalization_spec.md` (modify，§5 实现映射)、`data/AGENTS.md` (modify)、根 `AGENTS.md` (modify)
- **描述**: 新增缓存单测：round-trip（features/小数组/index）、异 key 隔离（role/seq_len/horizon/
  max_windows_per_code/bins/scaler identity）、原子发布（无 `.ok` 不可读、rebuild 新 generation）、
  访问器语义（`_WindowIndex` 负索引/`.index()`；`_FeatureView` `np.isfinite`/切片/`.T`）、
  `--max_codes` 小样本端到端（真实 mini parquet，`cache_enabled=True` 构造→复建命中→与 off 一致）、
  跨平台根解析（monkeypatch env）。文档记录缓存契约、开关语义、rebuild/不自动删除、验证命令。
- **依赖**: T01, T02, T03
- **预估行数**: +220
- **need_test**: true
- **验收标准**: (1) `uv run --project . python -m unittest tests.unit.data.test_feature_cache` 全绿；
  (2) `uv run --project . python -m unittest discover tests/unit` 全绿（缓存默认关回归）；
  (3) 文档含缓存根/key/原子写/访问器契约与 `uv run ruff check .` 通过；
  (4) 明确「验证集不重 fit、cache 命中仍校验 scaler identity」与「不做运行期自动删除」。
- **风险因子**: 单测在 CI(Linux) 与 Windows 的临时目录/生成目录清理差异；测试须用 `tempfile` 且改 env，
  不得污染真实 `~/.cache`。

## Execution Order

```
T01 (cache 基础模块)  →  T02 (dataset 接入)  →  T03 (入口/默认开启)  →  T04 (单测+文档)
```

- 串行依赖：T02 依赖 T01 的 `FeatureCache`/访问器；T03 依赖 T02 的 `ParquetDataConfig` 新字段；
  T04 依赖前三者全部 PASS。
- `test_scope`：T01、T02 = **full**（data 链路核心 + 风险 high，命中 full 升级规则 #1/#6）；
  T03、T04 = fast（`ruff` + `pyright` + `unittest tests/unit`）。
- 每个任务 `need_test=true`，Generator 必须走 TDD Red-Green-Refactor 并回报 `tdd_verification`。

