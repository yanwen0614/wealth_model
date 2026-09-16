# 进度跟踪 — rolling-normalization-cnn

> 生成时间：2026-09-09 16:25
> 需求：仅在当前 CNN parquet -> ParquetDataset -> CNNTransformer 链路增加显式 opt-in rolling normalization 实验；默认 frozen per-code 不变，不做 quant exporter。

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 依赖 |
|---|---|---|---|---|
| T01 | 固化 rolling schema 与身份契约 | PASS | schema/identity focused gate PASS | 无 |
| T02 | 实现无前视 rolling kernel | PASS | rolling kernel focused gate PASS | T01 |
| T03 | 接入 ParquetDataset 与 split context | PASS | dataset/context focused gate PASS | T01,T02 |
| T04 | 接入训练配置与 checkpoint 隔离 | PASS | config/checkpoint focused gate PASS | T03 |
| T05 | 评估链路身份校验 | PASS | eval preprocessing focused gate PASS | T03,T04 |
| T06 | 单元测试与对照验收 | PASS | 100 tests + frozen/rolling smoke + artifact validation PASS | T02-T05 |
| T07 | 修正文档漂移并记录实验边界 | PASS | 文档同步与 diff gate PASS | T06 |

## 执行详情

### T01: 固化 rolling schema 与身份契约
- **状态**：PASS
- **依赖**：无
- **文件**：`data/schema.py` (modify), `data/rolling_scaler.py` (create)
- **预估行数**：+90/-20
- **验收标准**：独立 mode/version/digest；51 raw + 18 mask = F=69；close 不在输出。
- **Quality Gate 结果**：PASS；rolling mode/version/digest、51 raw + 18 mask = F=69，close 不输出。
- **修复轮次**：0/2

### T02: 实现无前视 rolling kernel
- **状态**：PASS
- **依赖**：T01
- **文件**：`data/rolling_scaler.py` (modify)
- **预估行数**：+140/-10
- **验收标准**：`[t-251,t]` 含 t；min 120；t+1 扰动不影响 t；fallback 和缺失可审计。
- **Quality Gate 结果**：PASS；`[t-251,t]` 含 t、min 120、无前视、fallback/缺失审计通过 focused tests。
- **修复轮次**：0/2

### T03: 接入 ParquetDataset 与 split context
- **状态**：PASS
- **依赖**：T01,T02
- **文件**：`data/dataset.py`, `data/scaler.py` (modify)
- **预估行数**：+100/-45
- **验收标准**：rolling 显式 opt-in；frozen 默认不变；context 不进 label/window/index；无二次归一化。
- **Quality Gate 结果**：PASS；rolling 显式 opt-in，split context 不进入 label/window/index，无二次归一化。
- **修复轮次**：0/2

### T04: 接入训练配置与 checkpoint 隔离
- **状态**：PASS
- **依赖**：T03
- **文件**：`config/defaults.py`, `train.py`, `models/cnn_transformer/config.py` (modify)
- **预估行数**：+55/-20
- **验收标准**：默认 per-code；显式 rolling；metadata 记录 preprocessing identity；forward 对齐 `[B,69,60]`。
- **Quality Gate 结果**：PASS；默认 per-code/frozen，rolling 输入与 checkpoint metadata 使用 F=69，身份隔离。
- **修复轮次**：0/2

### T05: 评估链路身份校验
- **状态**：PASS
- **依赖**：T03,T04
- **文件**：`scripts/eval_bins_mapping.py` (modify)
- **预估行数**：+60/-15
- **验收标准**：mode/schema/identity 不匹配失败；默认 frozen eval 回归；不接 quant exporter。
- **Quality Gate 结果**：PASS；评估严格校验 mode、state、schema、feature order 和 evaluation role，未接 quant exporter。
- **修复轮次**：0/2

### T06: 单元测试与对照验收
- **状态**：PASS
- **依赖**：T02-T05
- **文件**：`tests/unit/data/test_rolling_normalization.py` (create), `tests/unit/data/*` (modify)
- **预估行数**：+180/-30
- **验收标准**：kernel、前视、边界、context、identity、frozen 回归；logits `[B,52]`、ret `[B]`。
- **Quality Gate 结果**：两种 discover 均 100 tests PASS；frozen/rolling smoke 与 artifact validation PASS。
- **修复轮次**：2/2

#### 测试兼容修复 TDD（2026-09-10）

```yaml
tdd_verification:
  - behavior: "schema 测试使用当前 51 raw + 18 G9 masks = F=69 契约"
    red_passed: true
    red_result: "FAILED (errors=1): 旧 EXPORT_FACTORS fixture 缺少 12 个 G9 raw/ts 列"
    green_passed: true
    green_result: "Ran 6 tests in 0.003s; OK"
  - behavior: "feature pipeline context fixture 跟随 APPROVED_RAW_FEATURES"
    red_passed: true
    red_result: "FAILED (errors=1): context fixture 缺少 12 个 G9 raw/ts 列"
    green_passed: true
    green_result: "Ran 6 tests in 0.214s; OK"
  - behavior: "tests/unit/training shim 与生产 training 包导出兼容"
    red_passed: true
    red_result: "FAILED (errors=1): cannot import name 'Trainer' from 'training'"
    green_passed: true
    green_result: "两种 focused discover 装载均 Ran 4 tests; OK"
```

附加 focused 回归：rolling 16 tests PASS，eval 5 tests PASS；scoped ruff 与 py_compile PASS。
Generator 阶段未执行完整 discover（按阶段约束由 Quality Gate 执行）；最终 frozen/rolling smoke 尚未执行，T06 保持进行中。

### T07: 修正文档漂移并记录实验边界
- **状态**：PASS
- **依赖**：T06
- **文件**：README、AGENTS、`docs/per_code_normalization_spec.md` (modify)
- **预估行数**：+55/-45
- **验收标准**：F=69 为当前事实；F=45 标注历史；rolling opt-in 和 quant 非目标清晰。
- **Quality Gate 结果**：PASS；允许文档已同步 F=69、历史 F=45、rolling opt-in、context 与 quant 阶段边界。
- **修复轮次**：0/2

## Quality Gate Commands

已执行 T01-T05 的 focused gate；T06 仍待最终 frozen smoke、rolling smoke 和 frozen-vs-rolling 对照。完整回归由 Quality Gate 按高风险 data/models 变更决定。

## T07 Verification

```text
$ git diff --check
PASS
```

仅同步允许范围内的文档；未修改源码、`uv.lock`、`scripts/run_eval_pipeline.py` 或 quant。

## 工作区保护

只允许新增本目录三份任务文档。`uv.lock` 的既有未提交修改和 `scripts/run_eval_pipeline.py` 的用户文件必须保持原状，不得 staging、修改或删除。

## T01/T02 TDD Verification

> 补录时间：2026-09-09；依据同一任务会话中的实际 RED/GREEN 命令输出补录，未重写测试或算法。

```yaml
tdd_verification:
  - behavior: "rolling schema/identity、因果窗口、fallback、NaN、常数 IQR、透传、G9 mask 与审计计数"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    red_result: "FAILED (errors=1): ModuleNotFoundError: No module named 'data.rolling_scaler'"
    red_reason: "独立 rolling 模块尚未实现，测试因目标功能缺失而失败"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    green_result: "Ran 8 tests in 0.055s; OK"
  - behavior: "接受 frozen scaler 带 G9 masks 的 69 列 fallback 结果"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    red_result: "FAILED (errors=1): ValueError: frozen_fallback 必须与 raw features 形状一致"
    red_reason: "实现当时仅接受 raw fallback，尚未支持带附加 mask 的 frozen 输出"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    green_result: "Ran 9 tests in 0.057s; OK"
```

本次审计补录后复验：

```text
$ uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py
.........
Ran 9 tests in 0.059s
OK
```

## T05 独立 TDD Verification

```yaml
tdd_verification:
  - behavior: "评估 preprocessing 按 checkpoint metadata 选择 per_code/rolling，并严格校验 state、schema identity、feature order 与 evaluation role"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/scripts/test_eval_preprocessing.py"
    red_result: "FAILED (errors=4): load_eval_preprocessing 缺失，build_val_loader 尚不接受 preprocessing"
    red_reason: "评估脚本尚未实现 checkpoint preprocessing metadata 解析和 rolling state loader 配置"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/scripts/test_eval_preprocessing.py"
    green_result: "Ran 5 tests in 0.010s; OK"
```

## T03/T04 Generator TDD Verification

以下为此前同一任务 Generator 的实际回报补录。

```yaml
tdd_verification:
  - task: "T03"
    behavior: "rolling 显式 opt-in、split context 不进样本、不调用 frozen 主变换、identity mismatch 拒绝"
    red_passed: true
    red_result: "上述行为在接入前均按预期失败"
    green_passed: true
    green_result: "最终 rolling focused: Ran 15 tests; OK"
  - task: "T04"
    behavior: "默认 per_code、rolling opt-in 独立路径、metadata F=69 维度约束与 JSON 序列化"
    red_passed: true
    red_result: "训练配置与 preprocessing metadata 接入前按预期失败"
    green_passed: true
    green_result: "default/opt-in path、metadata dimension、JSON checks 均通过"
  - task: "T04"
    behavior: "rolling state save/load"
    red_passed: true
    red_result: "RED: rolling state 缺少 save"
    green_passed: true
    green_result: "最终 rolling focused: Ran 16 tests; OK"
```

## Quality Gate Fix Retry 1 TDD Verification

```yaml
tdd_verification:
  - behavior: "rolling training 只 fit 一次 frozen fallback；validation 复用；warmup/mature 分流；state round-trip；dataset-local audit"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    red_result: "FAILED (failures=1, errors=2): fallback 未 fit，state 无 fallback_scaler"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/data/test_rolling_normalization.py"
    green_result: "Ran 19 tests in 0.372s; OK"
  - behavior: "per_code evaluation 使用 51 raw + 18 masks = 69 output schema，并拒绝错序/错维"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/scripts/test_eval_preprocessing.py"
    red_result: "FAILED (errors=1): validate_preprocessing_dimensions 尚不存在"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/scripts/test_eval_preprocessing.py"
    green_result: "Ran 6 tests in 0.023s; OK"
```

## T06 Final Verification 与 Identity Fix

- 两种 unittest discover：各 `Ran 100 tests; OK`。
- frozen smoke：train/val `56,639/1,220`，`F=69,T=60,C=52`，loss `0.0647/0.0550`，`127.99s`。
- rolling smoke：train/val `56,639/1,220`，`F=69,T=60,C=52`，loss `0.0647/0.0552`，`252.48s`。
- rolling train audit：fallback `42,740`，neutral `0`，ratio `0.046105`，rolling `884,284`。
- rolling validation audit：fallback `38,280`，neutral `0`，ratio `0.317308`，rolling `82,360`；未重新 fit fallback。
- 真实 frozen checkpoint/scaler eval preprocessing：PASS，51 raw -> 69 output 未误拒绝。

```yaml
tdd_verification:
  - behavior: "rolling metadata 直接采用含 fitted fallback 的 RollingDatasetState schema_manifest/identity_hash，并通过 eval load"
    red_passed: true
    red_command: "uv run --project . python -m unittest tests/unit/test_train_metadata.py"
    red_result: "FAILED (errors=2): build_preprocessing_metadata 仍要求 normalizer/source_manifest 旧 API"
    green_passed: true
    green_command: "uv run --project . python -m unittest tests/unit/test_train_metadata.py tests/unit/scripts/test_eval_preprocessing.py"
    green_result: "Ran 11 tests in 0.062s; OK"
```
