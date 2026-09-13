# 进度跟踪 — context-warmup-windows

> 生成时间：2026-09-13 20:00
> Task Dir：docs/agent/task/20260913_2000_context-warmup-windows/
> 需求：评估/验证起点之前的历史行（context）作为时序窗口 warmup 输入，绝不作为标签日；训练/验证/评估全启用。
> 验收主指标：评估区间标签日 95 → ≈154（`R-(horizon+1)`，R≈160）。

## 任务列表

| Task | 名称 | 状态 | 依赖 | test_scope | Quality Gate | 备注 |
|------|------|------|------|-----------|--------------|------|
| T01 | dataset warmup 窗口核心 | pending | - | full | - | 最高风险：泄露/标签日边界 |
| T02 | 缓存语义失效（version bump） | pending | - | fast | - | 可与 T01 并行 |
| T03 | 既有测试对齐 + 覆盖集成 | pending | T01 | full | - | 改写 2 处冲突断言 |
| T04 | 文档事实源同步 | pending | T01 | fast | - | spec/README/AGENTS |

## 执行详情

### T01: dataset warmup 窗口核心
- **状态**：pending
- **依赖**：无
- **文件**：
  - `data/dataset.py` (modify)：`324` context_limit、`476-486` 去 keep/加 is_context、`496-501` valid_starts
  - `tests/unit/data/test_context_warmup_windows.py` (create)
- **预估行数**：源码 +45/−25；测试 +170
- **need_test**：true（TDD Red-Green-Refactor）
- **验收标准**：首日即出标签；context 恒非标签日；窗口末日==标签日；无 start_date 回归不变；F=69/`(69,60)`；验证集不重 fit
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: 缓存语义失效（CACHE_FORMAT_VERSION bump）
- **状态**：pending
- **依赖**：无
- **文件**：
  - `data/feature_cache.py` (modify)：`30` 常量 bump `v2_context_warmup`
  - `tests/unit/data/test_feature_cache.py` (modify)：旧 version → miss
- **预估行数**：源码 +6/−2；测试 +30
- **need_test**：true
- **验收标准**：旧 generation load miss；新 key 与 v1 不同；不覆盖/不自动删除；单测全绿
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: 既有测试对齐 + 覆盖集成
- **状态**：pending
- **依赖**：T01
- **文件**：
  - `tests/unit/data/test_rolling_normalization.py` (modify)：`162-177`
  - `tests/unit/data/test_data_feature_pipeline.py` (modify)：`80-97`
  - `tests/unit/data/test_context_warmup_windows.py` (modify/extend)：realistic 154 标签日用例
- **预估行数**：+70/−30
- **need_test**：true
- **验收标准**：语义从「context 不入窗口」转为「context 非标签日」；三个测试文件全绿
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 文档事实源同步
- **状态**：pending
- **依赖**：T01
- **文件**：
  - `docs/per_code_normalization_spec.md` (modify)：`69`、`81`
  - `README_TRAINING_CHAIN.md` (modify)：`46`
  - `data/AGENTS.md`、根 `AGENTS.md` (modify)
- **预估行数**：+30/−15
- **need_test**：false（纯文档）
- **验收标准**：无「context 不进入 windows」绝对表述；记录 warmup 语义与 cache 版本
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 证据区（实现后填写）

| 项 | 期望 | 实测 | 证据 |
|----|------|------|------|
| 评估标签日数（2026-01-01~08-31） | ≈154（现状 95） | - | - |
| 最早标签日 | 区间首个交易日 | - | - |
| context 作为标签日 | 0 例 | - | - |
| 训练口径 len/index | 与改动前一致 | - | - |
| full 冒烟 | PASS | - | - |
