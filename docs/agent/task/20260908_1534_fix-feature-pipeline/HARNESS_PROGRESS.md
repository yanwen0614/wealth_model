# 进度跟踪 — fix-feature-pipeline

> 生成时间：2026-09-08 15:34
> 需求：修复 parquet per-code feature processing 的 scaler 身份复用、缺失值、allowlist、schema 兼容、验证 context 与未见 code fallback，并增加单元测试。

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|---|---|---|---|---|
| T01 | 定义批准特征契约 | complete | PASS | 显式 39 raw -> 45 output |
| T02 | 添加 scaler identity 与 schema 校验 | complete | PASS | v3 payload |
| T03 | 修正变换、缺失与 fallback | complete | PASS | 共享语义 |
| T04 | 强制缓存策略与验证 context 边界 | complete | PASS | train-only fit |
| T05 | 打通已验证的训练/评估复用 | deferred | - | `scripts/eval_bins_mapping.py` 有用户脏改动，按范围限制未修改 |
| T06 | 更新规范并执行回归测试 | complete | PASS | synthetic fixtures |

## 执行详情

### T01: 定义批准特征契约
- **状态**：complete
- **依赖**：无
- **文件**：
  - `data/schema.py` (modify)
  - `data/dataset.py` (modify)
  - `tests/unit/data/test_data_schema_labels.py` (modify)
- **预估行数**：+55/-28
- **验收标准**：固定顺序的 39 raw feature allowlist；G9 mask 后 F=45；删除无效 `use_factor_only` 48-feature 行为。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: 添加 scaler identity 与 schema 校验
- **状态**：complete
- **依赖**：T01
- **文件**：
  - `data/scaler.py` (modify)
  - `tests/unit/data/test_data_feature_pipeline.py` (create)
- **预估行数**：+95/-18
- **验收标准**：v3 payload 的 manifest/hash 可复现；任一必需 identity 字段或 schema 不匹配即拒绝复用。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: 修正变换、缺失与 fallback
- **状态**：complete
- **依赖**：T01, T02
- **文件**：
  - `data/scaler.py` (modify)
  - `tests/unit/data/test_data_feature_pipeline.py` (create)
- **预估行数**：+90/-70
- **验收标准**：输出无 NaN/inf；缺失最终为 0；未见 code 的 relative/winsor/robust 与训练全局统计语义一致。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 强制缓存策略与验证 context 边界
- **状态**：complete
- **依赖**：T01, T02, T03
- **文件**：
  - `data/dataset.py` (modify)
  - `tests/unit/data/test_data_feature_pipeline.py` (create)
- **预估行数**：+95/-45
- **验收标准**：训练 hash mismatch 重拟合；验证不拟合；首个验证 relative 使用前收盘；context 无样本。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: 打通已验证的训练/评估复用
- **状态**：deferred（用户限制 `scripts/eval_bins_mapping.py` 不可改）
- **依赖**：T04
- **文件**：
  - `scripts/eval_bins_mapping.py` (modify)
  - `tests/unit/data/test_data_feature_pipeline.py` (modify)
- **预估行数**：+45/-12
- **验收标准**：评估提供训练 identity；不匹配/旧 scaler 失败；正常 train->val 复用无验证集 fit。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06: 更新规范并执行回归测试
- **状态**：complete
- **依赖**：T01, T02, T03, T04, T05
- **文件**：
  - `docs/per_code_normalization_spec.md` (modify)
  - `tests/unit/data/test_data_schema_labels.py` (modify)
  - `tests/unit/data/test_data_feature_pipeline.py` (create)
- **预估行数**：+95
- **验收标准**：规范同步 v3；data unit discovery 与 focused ruff 均通过；覆盖 F=45、`[B,45,60]` 和 52-class 标签。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 最终验证

- 任务范围 `ruff check`：PASS（0 errors）。
- 任务范围 `pyright`：PASS（0 errors）。
- `uv run --project . python -m unittest discover tests/unit`：PASS（77 tests）。
- `uv run --project . python train.py --smoke --num_workers 0`：PASS（F=45、52 类、训练 scaler 被验证集复用）。
- 全仓 `ruff check .` 仍有 63 个本任务范围外的既有错误；环境未安装 `pytest`，无法执行 pytest 门禁。用户已确认按任务范围验证结果提交。
