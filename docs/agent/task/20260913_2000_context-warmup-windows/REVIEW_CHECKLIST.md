# 审查清单 — context-warmup-windows

> 生成时间：2026-09-13 20:00
> Task Dir：docs/agent/task/20260913_2000_context-warmup-windows/
> 面向 Quality Gate：泄露安全 / 缓存失效 / 滚动 state 复用 / 测试覆盖 / 文档同步

## 需求理解

让 `data/dataset.py` 中按 `start_date` 过滤时保留的 context 行（`_transform_context=True`）
**参与滑动窗口作为 warmup 输入**，但**绝不作为标签日**；训练、验证、评估三类 role 全部启用。

**显式假设**（用户已确认）：
1. context = 严格早于 `start_date` 的历史行，仅作「过去」输入，无未来泄露。
2. 首个真实交易日要出标签，需 `seq_len-1` 行 context 凑满窗口 → frozen 的 `context_limit` 由 1 提升。
3. 训练集 `start_date≈数据起点`，实际 context=0，训练窗口不应改变。
4. 已完成 E1-E4 的 val 数字**不可比**（val 样本增加 ~59 天/每股），用户接受。
5. 标签公式/BINS/seq_len/horizon/归一化数值语义/seed 均不变。
6. `criterion/EMD_loss.py`、`models/*`、`training/*`、`inference.py` **不涉及**。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| data | `data/dataset.py:324` | modify | `context_limit`=`max(seq_len-1, 251 if rolling&非训练 else 1)` |
| data | `data/dataset.py:476-486` | modify | 取消 context 丢弃；加 `is_context`；改 skip/max_s |
| data | `data/dataset.py:496-501` | modify | `valid_starts` 过滤 `is_context[label_pos]` |
| data | `data/feature_cache.py:30` | modify | `CACHE_FORMAT_VERSION` bump `v2_context_warmup` |
| tests | `tests/unit/data/test_context_warmup_windows.py` | create | warmup/标签日/泄露/覆盖 |
| tests | `tests/unit/data/test_rolling_normalization.py:162` | modify | context 断言对齐 |
| tests | `tests/unit/data/test_data_feature_pipeline.py:80` | modify | context 断言对齐 |
| tests | `tests/unit/data/test_feature_cache.py:178` | modify | 旧 version miss |
| docs | `docs/per_code_normalization_spec.md:69,81` | modify | 语义更正 |
| docs | `README_TRAINING_CHAIN.md:46` | modify | 语义更正 |
| docs | `data/AGENTS.md`、根 `AGENTS.md` | modify | cache/warmup 说明 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 结论 |
|------------|---------|------|------|
| `_transform_context` | 是 | `data/dataset.py:320,326,330,383,402,477` | 复用现有标记，不新增 |
| `context_limit` | 是 | `data/dataset.py:324` | 修改取值，不新增逻辑 |
| `_future_ret_open_open` | 是 | `data/labels.py:6` | 复用，禁止重写 |
| `warmup`（窗口） | 否 | —（rolling 的 warmup 指归一化预热） | 无重复实现 |
| `CACHE_FORMAT_VERSION` | 是 | `data/feature_cache.py:30` | 复用失效机制 |
| `_WindowIndex` | 是 | `data/feature_cache.py:198` | 绝对 start 语义可复用 |
| `start_date` 进 cache key | 是 | `dataset.py:225` → `base_identity.fit_start_date` | 已含日期；但语义未含 → 需 bump |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名/日志/注释风格；无新增未使用 import；`ruff check .` 通过 | HIGH |
| 2 | 模块边界 | 仅 `data/` 层；未侵入 `models/*` / `training/*` / `criterion/*` / `inference.py`；`ModelConfig` 与 `featurenum=69` 不变 | HIGH |
| 3 | 泄露安全 | `∀(c,s)∈index` 标签日 `kline_time[s+seq_len-1] >= start_date`；窗口末日==标签日（输入 ≤ 标签日）；context 不产生标签 | HIGH |
| 4 | 缓存失效 | `CACHE_FORMAT_VERSION` 已 bump；旧 generation `load()` 返回 miss；不覆盖/不自动删除 generation；val/eval 旧语义产物绝不被复用 | HIGH |
| 5 | 滚动 state 复用 | rolling 训练只 `fit` fallback 一次；val/eval 复用训练 state；**绝不重 fit**；context 仍先经 same transform 再保留；`rolling_audit` 字段不变 | HIGH |
| 6 | 测试覆盖 | 合成 fixture 覆盖：首日出标签 / context 非标签日 / 窗口含 context warmup / 无未来泄露 / 覆盖条数 `R-(horizon+1)`；无 `start_date` 回归不变；TDD `red_passed`/`green_passed` 全 true | HIGH |
| 7 | 文档同步 | spec/README/AGENTS 无「context 不进入 windows」绝对表述；记录 cache 版本与 warmup 语义 | MEDIUM |
| 8 | 错误处理 | context 缺失/历史不足时安全退化（首个真实日无标签但不抛错、不静默 NaN 标签）；异常不静默吞掉 | MEDIUM |
| 9 | 性能/内存 | 不引入 O(N²) context 查找；context 仅 `tail(limit)`；内存增量 rolling eval ≈0.35GB 可接受 | MEDIUM |
| 10 | 接口兼容 | `groups[code]["kline_time"][s+seq_len-1]` 绝对定位对 `eval_bins_mapping.py:300`、`run_eval_pipeline.py:264-270` 仍成立；`len(ds)`/`ds[0]`/`x.shape==(69,60)` 不变 | HIGH |

## 验证命令（Quality Gate）

```bash
# 1. 新增/改动单测（TDD 单文件）
uv run --project . python -m unittest tests.unit.data.test_context_warmup_windows
uv run --project . python -m unittest tests.unit.data.test_rolling_normalization tests.unit.data.test_data_feature_pipeline
uv run --project . python -m unittest tests.unit.data.test_feature_cache
# 2. 全 data 单测回归（含无 start_date 的三件套）
uv run --project . python -m unittest discover tests/unit
# 3. lint / smoke（full）
uv run ruff check .
uv run --project . python train.py --smoke --num_workers 0
# 4. 评估标签日覆盖（可选端到端，记录证据）
#    构造 evaluation dataset 后统计 len({ kline_time[s+seq_len-1] for c,s in ds.index })
```

## 阻塞/移交决策点

- 若实现者发现必须新增 `groups[code]["n_context"]` 字段才能表达 context 边界 → 需评估 cache
  `n_per_code`/meta 扩展，属超出当前设计的范围，返回 `blocked` 交主编排器确认。
- 若要求「评估标签日 == 160」而非 `R-(horizon+1)` → 与 horizon 尾部截断口径冲突，返回 `blocked`。
