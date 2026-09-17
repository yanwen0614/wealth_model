# context-warmup-windows Implementation Plan

> Generated: 2026-09-13 20:00
> Task Dir: docs/agent/task/20260913_2000_context-warmup-windows/
> 类型: feature（data 层 warmup 窗口，训练 / 验证 / 评估全启用）
> 需求来源: 用户已确认「评估起点前的历史行可作时序窗口 warmup 输入，但绝不作为标签日；训练验证集与评估都启用」

## Goal

让 `start_date` 之前的历史行（context）作为滑动窗口的 **warmup 输入**，使验证/评估区间
**首个交易日即可产出标签**；context 永远不能成为标签日。现状 `data/dataset.py:476-481`
把 context 整段 `keep = ~group["_transform_context"]` 丢弃，导致评估区间
2026-01-01~08-31 每股 ~160 个交易日只产出 **95 个标签日**（`160 − 59 − 6`）。
目标：标签日覆盖 `R − (horizon+1) ≈ 160 − 6 = 154`（较现状 +59 ≈ seq_len−1）。

## Non-Goals

- 不改模型结构 / `ModelConfig` / 损失 / 训练循环 / 优化器调度。
- 不改标签公式（open-open）、`BINS`、`seq_len=60`、`horizon=5`、`num_classes=52`。
- 不改 per-code / rolling 归一化数值语义，不改「验证集复用训练 scaler、绝不重 fit」红线。
- 不动 `train.py:48` seed 与 `cudnn.deterministic/benchmark` 确定性设置。
- 不实现 quant 侧 exporter；**不保证已完成 E1-E4 的 val 数字可比**（用户已知并接受）。

## Architecture

单点数据层改造：`data/dataset.py` 的日期过滤与窗口构建。两处变更：
(1) `dataset.py:324` 的 `context_limit` 由「frozen=1 / rolling 非训练=251」提升为
`max(seq_len-1, 251 if rolling 且 role!=training else 1)`，保证首个真实交易日能凑满窗口；
(2) `dataset.py:476-486` 不再丢弃 `_transform_context` 行，改为保留在特征/价格/时间数组中，
并新增 `is_context` mask，在 `valid_starts` 过滤 `is_context[label_pos]`，从而窗口可含 context
作输入、但标签日恒为非 context 的真实交易日。`data/feature_cache.py` bump `CACHE_FORMAT_VERSION`
使携带旧「丢弃 context」语义的 memmap 缓存失效（start/end 已进 key，但语义变更未进 key）。
`_future_ret_open_open`（`data/labels.py:6`）、context 预取逻辑（`dataset.py:321-331`）、
缓存失效机制均为**复用**，不新增重复实现。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| context 去留 | 保留在 `groups` 数组（combined 长度 `N=c+real`），index 用绝对 start | 丢弃 context；或拆成两段数组运行时拼接 | 保留使 `__getitem__`/缓存/memmap 零结构改动；拆分需改 `_WindowIndex` 与 cache 落盘格式 |
| 标签约束 | `valid_starts` 过滤 `is_context[s+seq_len-1]`，并保留 `future_ret` NaN 过滤 | 仅靠 `s >= c-(seq_len-1)` 数学下界 | 显式 mask 对任意 context 缺失/截断更鲁棒，且直接表达「context 非标签日」不变量 |
| context 上限 | `max(seq_len-1, 251 if rolling 且非训练 else 1)` | 全场景固定 251 | frozen 只需 `seq_len-1` 即可覆盖首日；251 是全历史 rolling 统计需求，二者取大 |
| 短序列判定 | 改为 `real_n < horizon+2` 才 skip | 沿用 `n < seq_len+horizon+1` | 原判定按真实行数；warmup 后真实行少但 context 足够时仍能出标签，不应整股丢弃 |
| 训练窗口 | 公式对 training 同样生效；因 train_start≈数据起点，实测 context=0、窗口不变 | 仅对 validation/evaluation 生效 | 用户明确「全启用」；统一公式避免 role 分支；训练无历史时自然等价 |
| 缓存失效 | bump `CACHE_FORMAT_VERSION` → `v2_context_warmup` | 仅依赖 start/end 进 key | start/end 已随 `base_identity.fit_start_date/fit_end_date` 进 key，但**代码语义变更未进 key**，旧 val/eval generation 会被错误复用；bump 语义版本是既有标准机制 |
| 归一化 | context 仍先经 same scaler transform 再保留；fit 仍排除 context | 对 context 用独立统计 | 保持「验证/评估复用训练 scaler、绝不重 fit」红线；context 数值语义不变 |

> 缓存 bump 的副作用：所有旧 generation（含训练缓存）一律 miss，需重建。训练缓存语义未变，
> 属必要附带成本；可用 `--no_cache` 评估或接受一次性重建。

## Impact

| 模块 | 文件 | 操作 | 风险等级 | 改动点（行号锚点） |
|------|------|------|----------|--------------------|
| data | `data/dataset.py` | modify | high | `324` `context_limit`；`476-486` 去 `keep`、加 `is_context`、改 skip/max_s；`496-501` `valid_starts` 加 context 过滤 |
| data | `data/feature_cache.py` | modify | medium | `30` `CACHE_FORMAT_VERSION` bump；`84-107` key payload（可选加显式语义字段） |
| tests | `tests/unit/data/test_context_warmup_windows.py` | create | medium | 新增：context 非标签日 / 首日出标签 / warmup 入窗口 / 无未来泄露 / 覆盖条数 |
| tests | `tests/unit/data/test_rolling_normalization.py` | modify | medium | `162-177` 重写 `test_rolling_validation_context_is_not_a_sample` |
| tests | `tests/unit/data/test_data_feature_pipeline.py` | modify | medium | `80-97` 重写 `test_date_bounded_validation_uses_context_without_exposing_it` |
| tests | `tests/unit/data/test_feature_cache.py` | modify | low | `178-201` 增加 version/旧缓存 miss 断言 |
| docs | `docs/per_code_normalization_spec.md` | modify | low | `69`（§5）、`81`（§5.1）语义更正 |
| docs | `README_TRAINING_CHAIN.md` | modify | low | `46` 语义更正 |
| docs | `data/AGENTS.md`、根 `AGENTS.md` | modify | low | 缓存 key/cache version 说明；Data Contract/Normalization 补一句 warmup 语义 |

> 未受影响但需回归（无 `start_date`，不进入 context 分支，len/index/features 应逐元素不变）：
> `tests/unit/data/test_dataset_label_openopen.py`、`tests/unit/data/test_dataset_cache.py`、
> `tests/unit/data/test_data_dataset_triple.py`。

## Task Decomposition

### T01: dataset warmup 窗口核心（context 保留 + 标签约束）
- **文件**: `data/dataset.py` (modify)、`tests/unit/data/test_context_warmup_windows.py` (create)
- **描述**:
  1. `dataset.py:324` `context_limit` 改为 `max(cfg.seq_len-1, 251)`（rolling 且 `role!="training"`），
     否则 `max(cfg.seq_len-1, 1)`；`tail(context_limit)` 逻辑不变。
  2. `dataset.py:476-486` 删除 `keep = ~group["_transform_context"]` 全段丢弃；改为
     `is_context = group["_transform_context"].to_numpy()`，`group/feat/close/open_arr` 保留全部行，
     `n = len(group)`；`real_n = int((~is_context).sum())`，skip 条件改为 `real_n < cfg.horizon + 2`；
     `max_s = n - seq_len - horizon` 基于 combined `n`；`future_ret = _future_ret_open_open(open_arr, horizon)`
     基于 combined 数组（复用 `data/labels.py`）。
  3. `dataset.py:496-501` `valid_starts`：`label_pos = s + seq_len - 1`；`if is_context[label_pos]: continue`；
     再保留 `not np.isnan(future_ret[label_pos])`。
  4. 不改 scaler fit（仍 `df.loc[~df["_transform_context"]]`）、不改 `groups`/`index` 结构、不改缓存调用。
- **依赖**: 无
- **预估行数**: 源码 +45/−25；测试 +170
- **need_test**: true（强制 TDD Red-Green-Refactor）
- **test_scope**: **full**（命中「测试选择策略」升级规则 #1 data/dataset.py ⚡full、#6 风险 high）
- **验收标准**:
  - (a) 合成 parquet：pre-context 行数 `c=seq_len-1`、真实行 `R`，`start_date`=首个真实日；
    断言 `min(label_date) == start_date`（首日即出标签），且 `set(label_dates)` 数量 == `R-(horizon+1)`。
  - (b) 遍历 `ds.index`，`ds.groups[c]["kline_time"][s+seq_len-1] >= start`（**context 恒非标签日**）。
  - (c) 最早窗口 `kline_time[s+seq_len-1] == kline_time[s+seq_len-1]` 且窗口内 max date == 标签日（**无未来泄露**）。
  - (d) 无 `start_date` 的 dataset（训练口径）`len`/`index`/`features` 与旧实现逐元素一致（回归）。
  - (e) `num_features=69`、`ds[0][0].shape==(69,60)`、`rolling` 与 `per_code` 均通过；验证集仍复用训练 scaler，`fit` 调用次数不变。
- **风险因子**: 误删 `keep` 使标签日落入 context（→ (b) 断言）；`max_s` 仍用真实 `n` 导致漏首日；
  短序列 skip 条件放宽引入无标签 code（→ `real_n < horizon+2` 兜底）。

### T02: 缓存语义失效（CACHE_FORMAT_VERSION bump）
- **文件**: `data/feature_cache.py` (modify)、`tests/unit/data/test_feature_cache.py` (modify)
- **描述**: `feature_cache.py:30` `CACHE_FORMAT_VERSION: "v1_memmap_cache" -> "v2_context_warmup"`；
  （可选）在 `compute_cache_key` payload（`:96-106`）加显式 `context_semantics: "warmup"` 提升可读性。
  新增测试：写入 v1 版本 meta 的 generation 在 v2 下 `load()` 返回 `None`；`compute_cache_key` 对
  `version` 变化敏感（既有 `test_each_field_changes_key` 已覆盖 version，补一条 warmup 语义断言）。
- **依赖**: 无（可与 T01 并行；建议 T01 之后执行以便端到端验证 miss/hit）
- **预估行数**: 源码 +6/−2；测试 +30
- **need_test**: true
- **test_scope**: fast（同属 data 链路，实质常量/测试变更；若与 T01 合并验证则 full）
- **验收标准**: 旧 `cache_format_version` 目录一律 miss 并打印格式不匹配；新 key 与 v1 不同；
  `test_feature_cache.py` 全绿；旧 generation 不被覆盖、不自动删除。
- **风险因子**: 忘记 bump 会让旧 val/eval generation（丢弃 context、95 标签日）被静默复用（核心风险）；
  bump 使训练缓存也失效，属已知附带成本。

### T03: 既有测试对齐新语义 + 真实覆盖集成用例
- **文件**: `tests/unit/data/test_rolling_normalization.py` (modify)、
  `tests/unit/data/test_data_feature_pipeline.py` (modify)、
  `tests/unit/data/test_context_warmup_windows.py` (modify/extend)
- **描述**:
  1. `test_rolling_normalization.py:162-177` `test_rolling_validation_context_is_not_a_sample` 重写：
     断言 context **可作窗口输入但不可作标签日**；`val.groups["000001"]["n"] == 180`（combined）；
     最早标签日 == `2025-05-01`；删除/改写 `future_ret[0] == 124/122-1` 断言（0 现为 context 行）。
  2. `test_data_feature_pipeline.py:80-97` `test_date_bounded_validation_uses_context_without_exposing_it` 重写：
     改为「所有标签日 ≥ `2020-01-05`」；groups 可含 < start 的 context 行；窗口末日 == 标签日。
  3. 在 `test_context_warmup_windows.py` 增加 realistic 集成用例：`_dataset_frame` 风格
     pre=59 + real=160，`seq_len=60/horizon=5`，断言标签日数 == 160−6 == 154（对应评估口径）。
- **依赖**: T01
- **预估行数**: +70/−30
- **need_test**: true
- **test_scope**: full（继承 T01 的 data/dataset.py 变更）
- **验收标准**: `python -m unittest tests.unit.data.test_rolling_normalization tests.unit.data.test_data_feature_pipeline tests.unit.data.test_context_warmup_windows` 全绿；
  断言语义从「context 不入 window」转为「context 不作标签日」；无 `start_date` 的测试零改动通过。
- **风险因子**: 仅改断言数值不改语义 → 需人工确认断言体现「标签日非 context」；rolling `n` 语义变化可能波及其他断言。

### T04: 文档事实源同步
- **文件**: `docs/per_code_normalization_spec.md` (modify)、`README_TRAINING_CHAIN.md` (modify)、
  `data/AGENTS.md` (modify)、根 `AGENTS.md` (modify)
- **描述**: 更正 `docs/per_code_normalization_spec.md:69`（§5）与 `:81`（§5.1）、
  `README_TRAINING_CHAIN.md:46` 的「context 不进入 labels、windows 或 index」旧表述为：
  context 可进入 window 作 warmup 输入，但**绝不作为标签日、不产生样本标签**；
  frozen context 上限由 1 提升为 `seq_len-1`，rolling 沿用 251（≥ seq_len-1）；
  评估标签日覆盖 = 区间交易日数 − (horizon+1)；缓存 `CACHE_FORMAT_VERSION=v2_context_warmup` 使旧语义缓存失效。
- **依赖**: T01
- **预估行数**: +30/−15
- **need_test**: false（纯文档）
- **test_scope**: fast（`ruff check .` 不受影响）
- **验收标准**: 全文不再出现「context 不进入 windows/index」的绝对表述；新增 warmup 语义与 cache 版本说明；
  与 `data/dataset.py` 实现一致。
- **风险因子**: 文档与实现漂移（→ T03/T04 同 PR 提交）。

## Execution Order

```
T01 (dataset 核心 + 新测试) ──> T03 (既有测试对齐 + 覆盖集成)
        │
        └──> T04 (文档同步)
T02 (cache 版本 bump)  可与 T01 并行，建议 T01 后执行以便 miss/hit 端到端
```

- 串行硬依赖：T03 依赖 T01 的窗口语义；T04 依赖 T01 语义定稿。
- `test_scope`：T01 / T03 = **full**；T02 = fast（可与 T01 合并判定为 full）；T04 = fast。
- 每个 `need_test=true` 任务，Generator 必须走 TDD Red-Green-Refactor 并回报 `tdd_verification`。

## Acceptance Criteria（可测口径）

1. **首日即出标签**：评估区间首个真实交易日出现在标签集合中（现状该日无标签）。
2. **标签日 ≈160 天指标**：评估区间 `R` ≈ 160 个交易日时，标签日数从现状 **95**
   （`R − (seq_len−1) − (horizon+1)`）提升到 **≈154**（`R − (horizon+1) = 160 − 6`），
   即 **+59 ≈ seq_len−1**；若区间尾部仍有数据，则趋近 `R`（仅受 `horizon+1` 尾部截断）。
   度量：`len({ ds.groups[c]["kline_time"][s+seq_len-1] for c, s in ds.index })`（去重标签日）。
3. **context 恒非标签日**：`∀ (c,s) ∈ index, kline_time[s+seq_len-1] >= start_date`。
4. **无未来泄露**：窗口 `[s, s+seq_len)` 内最大时间 == 标签日 `s+seq_len-1`（输入恒 ≤ 标签日）。
5. **训练口径不变**：无 `start_date`（或 `start_date`==数据起点）时 `len/index/features` 与改动前逐元素一致。
6. **红线保持**：验证/评估仍复用训练 scaler，`fit` 只发生一次；`num_features=69`、`x.shape==(69,60)`。
7. **缓存不串旧语义**：`CACHE_FORMAT_VERSION=v2_context_warmup`；旧 generation load 返回 miss。
8. **门禁**：T01/T03 `test_scope=full`（`main_parquet.py --smoke` / `train.py --smoke --num_workers 0`）；
   T02/T04 fast；`ruff check .` 全绿；无 `start_date` 的 data 单测零改动通过。

## Risks & Rollback

| 风险 | 等级 | 缓解 |
|------|------|------|
| 忘记 bump cache version，旧 val/eval generation 被静默复用（95 标签日） | **high** | T02 强制；新增「旧 version → miss」测试；评审确认 |
| 标签日误落入 context（删 `keep` 后未加约束） | **high** | T01 显式 `is_context[label_pos]` + (3)(4) 断言 |
| 训练窗口意外改变 | medium | 训练 start≈数据起点时 context=0；(5) 回归断言 |
| 首日仍需 `seq_len-1` context，历史不足股票首日无法出标签 | low | 属数据边界，接受；不影响其他股票 |
| 内存增量：rolling eval 每股 251 context | low | ~5000×251×69×4 ≈ 0.35GB，可接受；文档注明 |
| E1-E4 val 数字不可比 | medium | 用户已知并接受；文档注明 |

**回滚**：改动集中在 `data/dataset.py`（两处）与 `data/feature_cache.py`（一行常量）。
回滚 = `git revert` 本任务 commit；缓存旧 version 在新代码下 miss，无需清理 generation。

## 复用与重复检测结论

- **可复用**：`_future_ret_open_open`（`data/labels.py:6`）、context 预取（`data/dataset.py:321-331`）、
  context 标记列 `_transform_context`、缓存失效机制 `CACHE_FORMAT_VERSION`、`_WindowIndex` 绝对 start 语义。
- **无重复实现**：无既有 warmup-window 逻辑；本需求是「修改现有丢弃点」而非新增模块。
- **概念易混**：rolling 的 `min_periods=120` / frozen fallback 亦叫「warmup」，指**归一化统计预热**，
  与本需求的**窗口输入预热**是两套机制，文档须区分，避免误合并。
- **必须改写的旧断言**：`test_rolling_normalization.py:162-177`、`test_data_feature_pipeline.py:80-97`
  现有断言语义（context 完全不入窗口）与新需求**直接冲突**，属「对齐」而非「重复」。
- **start/end 是否已进 cache key**：是（经 `base_identity.fit_start_date/fit_end_date`，
  `data/dataset.py:225`），但 **warmup 语义未进 key**，故仍需 bump version。

