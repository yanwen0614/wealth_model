# 进度跟踪 — memmap-data-cache

> 生成时间：2026-09-13
> 需求：为 `ParquetDataset` 增加跨平台 np.memmap 数据缓存层，解决 Windows spawn 下每 worker
> pickle 复制 ~2.8GB 特征矩阵导致 `num_workers=1`、GPU 利用率 ~42%，以及 E1–E4 各组重复读取
> SMB `Z:` ~3.5GB parquet 并重建 ~3.16GB `groups` 的问题。
> 依赖顺序：T01 → T02 → T03 → T04（严格串行）

## 任务列表

| Task | 名称 | 状态 | 依赖 | test_scope | need_test | 预估行数 | Quality Gate | 备注 |
|------|------|------|------|-----------|-----------|----------|--------------|------|
| T01 | 缓存基础模块（key/根目录/原子写/访问器） | pending | 无 | full | true | +260 | - | 风险 high |
| T02 | dataset 接入与访问器兼容 | pending | T01 | full | true | +180 | - | 风险 high；依赖 T01 PASS |
| T03 | 训练入口/配置默认开启与 CLI 透传 | pending | T02 | fast | true | +60 | - | `train.py` + `multi_seed_train.py` |
| T04 | 单测与文档同步 | pending | T01,T02,T03 | fast | true | +220 | - | 回归 `unittest discover tests/unit` |

## execution_order

```
T01 → T02 → T03 → T04
```

- T01 必须 VERDICT=PASS 才能开始 T02；其余同。
- 风险=high 任务（T01/T02）`test_scope=full`，Quality Gate 追加 `train.py --smoke` 冒烟。

## 执行详情

### T01: 缓存基础模块（key/根目录/原子写/访问器）

- **状态**：pending
- **依赖**：无
- **文件**：
  - `data/feature_cache.py` (create)
- **预估行数**：+260
- **need_test**：true
- **test_scope**：full
- **验收标准**：
  1. `compute_cache_key` 对 role/rolling_scope/seq_len/horizon/max_windows_per_code/bins/scaler identity/
     parquet size+mtime 任一变化而不同，同输入稳定；
  2. save→load 后 features `float32` 逐元素相等，小数组与 index 完全一致；
  3. 未写 `.ok` 前读侧不可见，异 key 互不干扰，重复 save 生成新 generation 且不覆盖旧目录；
  4. `_WindowIndex.__getitem__`（含负索引）/`__len__`/`__iter__`/`.index()` 与 list 等价；
  5. `_FeatureView` 支持 `np.isfinite(v).all()`、切片、`.T`、`.shape`/`.dtype`；
  6. `resolve_cache_root` 经 env monkeypatch 验证 Linux/Windows 默认且无盘符硬编码。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
- **风险因子**：Windows `WinError 32`（新 generation 规避）；per-code memmap 切片触发 pickle 复制；
  generation 目录无自动清理需文档说明。

### T02: dataset 接入与访问器兼容

- **状态**：pending
- **依赖**：T01
- **文件**：
  - `data/dataset.py` (modify)
- **预估行数**：+180
- **need_test**：true
- **test_scope**：full
- **验收标准**：
  1. cache on/off 的 `len`/`index` 序列/`x,y,y_ret` 逐元素一致；
  2. `ds.index.index((code,s))`/负索引/迭代可用；
  3. `np.isfinite(ds.groups[c]["features"]).all()` 与切片 `.T` 可用；
  4. cache miss 自动回填、二次构造命中；
  5. train/val/E2/E3/E4 key 互不相同；
  6. `cache_enabled=False` 时 `tests/unit/data/*` 既有测试零改动通过；
  7. validation 命中仍强制训练 `scaler_stats` 校验、绝不重 fit。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
- **风险因子**：key 漏字段串缓存；命中路径遗漏 `rolling_audit`/标签统计状态恢复；spawn worker reopen。

### T03: 训练入口/配置默认开启与 CLI 透传

- **状态**：pending
- **依赖**：T02
- **文件**：
  - `config/defaults.py` (modify)
  - `train.py` (modify)
  - `scripts/multi_seed_train.py` (modify)
- **预估行数**：+60
- **need_test**：true
- **test_scope**：fast
- **验收标准**：
  1. `make_default_config()` 含 `CACHE_ENABLED=True`/`CACHE_DIR=None`/`REBUILD_CACHE=False`；
  2. `--no_cache` 关、`--rebuild_cache` 与 `--cache_dir` 正确透传；
  3. `--cache_dir` 优先于 env/平台默认；
  4. `tests/unit/config/test_config_defaults.py` 仍通过；
  5. `train.py --help` 呈现新参数，`--smoke` 可跑。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
- **风险因子**：训练默认开启首次写盘成本；`multi_seed_train` rolling_scope 默认 e4 需带 scope 防串 key。

### T04: 单测与文档同步

- **状态**：pending
- **依赖**：T01, T02, T03
- **文件**：
  - `tests/unit/data/test_feature_cache.py` (create)
  - `README_TRAINING_CHAIN.md` (modify)
  - `docs/per_code_normalization_spec.md` (modify)
  - `data/AGENTS.md` (modify)
  - `AGENTS.md` (modify)
- **预估行数**：+220
- **need_test**：true
- **test_scope**：fast
- **验收标准**：
  1. `uv run --project . python -m unittest tests.unit.data.test_feature_cache` 全绿；
  2. `uv run --project . python -m unittest discover tests/unit` 全绿（默认关回归）；
  3. 文档含缓存根/key/原子写/访问器契约与验证命令，`ruff check .` 通过；
  4. 明确「验证集不重 fit、cache 命中仍校验 scaler identity」「run-time 不自动删除缓存」。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
- **风险因子**：Linux CI 与 Windows 临时/生成目录清理差异；测试须用 `tempfile` 且 monkeypatch env，
  不得污染真实 `~/.cache`。

## 状态图例

- `pending`：未开始；`in_progress`：编码中；`pass`：Quality Gate PASS；`fail`：待修复；`blocked`：需用户决策。

