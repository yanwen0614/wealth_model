# 进度跟踪 — rolling-normalization-cnn

> 生成时间：2026-09-09 16:25
> 需求：仅在当前 CNN parquet -> ParquetDataset -> CNNTransformer 链路增加显式 opt-in rolling normalization 实验；默认 frozen per-code 不变，不做 quant exporter。

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 依赖 |
|---|---|---|---|---|
| T01 | 固化 rolling schema 与身份契约 | pending | - | 无 |
| T02 | 实现无前视 rolling kernel | pending | - | T01 |
| T03 | 接入 ParquetDataset 与 split context | pending | - | T01,T02 |
| T04 | 接入训练配置与 checkpoint 隔离 | pending | - | T03 |
| T05 | 评估链路身份校验 | pending | - | T03,T04 |
| T06 | 单元测试与对照验收 | pending | - | T02-T05 |
| T07 | 修正文档漂移并记录实验边界 | pending | - | T06 |

## 执行详情

### T01: 固化 rolling schema 与身份契约
- **状态**：pending
- **依赖**：无
- **文件**：`data/schema.py` (modify), `data/rolling_scaler.py` (create)
- **预估行数**：+90/-20
- **验收标准**：独立 mode/version/digest；51 raw + 18 mask = F=69；close 不在输出。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: 实现无前视 rolling kernel
- **状态**：pending
- **依赖**：T01
- **文件**：`data/rolling_scaler.py` (modify)
- **预估行数**：+140/-10
- **验收标准**：`[t-251,t]` 含 t；min 120；t+1 扰动不影响 t；fallback 和缺失可审计。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: 接入 ParquetDataset 与 split context
- **状态**：pending
- **依赖**：T01,T02
- **文件**：`data/dataset.py`, `data/scaler.py` (modify)
- **预估行数**：+100/-45
- **验收标准**：rolling 显式 opt-in；frozen 默认不变；context 不进 label/window/index；无二次归一化。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 接入训练配置与 checkpoint 隔离
- **状态**：pending
- **依赖**：T03
- **文件**：`config/defaults.py`, `train.py`, `models/cnn_transformer/config.py` (modify)
- **预估行数**：+55/-20
- **验收标准**：默认 per-code；显式 rolling；metadata 记录 preprocessing identity；forward 对齐 `[B,69,60]`。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: 评估链路身份校验
- **状态**：pending
- **依赖**：T03,T04
- **文件**：`scripts/eval_bins_mapping.py` (modify)
- **预估行数**：+60/-15
- **验收标准**：mode/schema/identity 不匹配失败；默认 frozen eval 回归；不接 quant exporter。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06: 单元测试与对照验收
- **状态**：pending
- **依赖**：T02-T05
- **文件**：`tests/unit/data/test_rolling_normalization.py` (create), `tests/unit/data/*` (modify)
- **预估行数**：+180/-30
- **验收标准**：kernel、前视、边界、context、identity、frozen 回归；logits `[B,52]`、ret `[B]`。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T07: 修正文档漂移并记录实验边界
- **状态**：pending
- **依赖**：T06
- **文件**：README、AGENTS、`docs/per_code_normalization_spec.md` (modify)
- **预估行数**：+55/-45
- **验收标准**：F=69 为当前事实；F=45 标注历史；rolling opt-in 和 quant 非目标清晰。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## Quality Gate Commands

本阶段不执行测试或静态命令。后续执行 focused unittest、py_compile、ruff、默认 frozen smoke 和显式 rolling smoke；full scope 由 Quality Gate 按高风险 data/models 变更决定。

## 工作区保护

只允许新增本目录三份任务文档。`uv.lock` 的既有未提交修改和 `scripts/run_eval_pipeline.py` 的用户文件必须保持原状，不得 staging、修改或删除。
