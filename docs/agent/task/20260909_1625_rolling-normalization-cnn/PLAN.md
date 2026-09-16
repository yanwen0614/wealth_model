# rolling-normalization-cnn Implementation Plan

> Generated: 2026-09-09 16:25
> Task Dir: docs/agent/task/20260909_1625_rolling-normalization-cnn

## Goal

在当前 `parquet -> ParquetDataset -> CNNTransformer` 链路中增加显式 opt-in 的 CNN 内部 rolling normalization 实验，保持默认 frozen `per_code` 训练命令、标签、窗口和 split 语义不变，并产出可隔离、可审计的 rolling checkpoint/schema 身份。

## Non-goals

- 不修改 quant 项目，不生成或实现 quant rolling exporter/parquet 导出。
- 不默认启用 rolling，不改变 `normalize="per_code"` 的 frozen `PerCodeGroupedScaler` 行为。
- 不把原始 `close` 加入模型输入；它仅作为 rolling/relative 辅助列。若实现认为必须输入 close，必须先阻断并请求用户确认。
- 不改变 `is_trading` 过滤、`code,kline_time` 排序、open-open 标签、窗口索引或训练 fit/验证 reuse 逻辑。

## Current Baseline And Drift

当前工作树实际 `data/schema.py` 为 51 个 raw feature，G9 18 列各带 mask，默认输出/模型配置为 `F=69,T=60,C=52`。README、AGENTS、per-code spec、测试中仍有 F=45/39+6 的旧描述；实现计划以代码和 `config/defaults.py` 的 69 为运行基线，并在文档任务中统一或明确历史口径，禁止新 rolling checkpoint 复用旧 F=45 身份。

## Architecture

新增独立 rolling preprocessing/kernel（建议 `data/rolling_scaler.py`），由 `ParquetDataset` 仅在 `normalize="rolling"` 显式分支调用；frozen 分支保持原调用路径。kernel 按单 code、已过滤并排序的交易日序列计算 `[t-251,t]`、`min_periods=120` 的 expanding/rolling 统计，统计右端包含当前 t，不读取未来值；split 起点可用前一段历史 context，但 context 不进入 label、group、window 或 index。

rolling 与 frozen 使用不同 normalization 名称、transform digest、schema manifest、identity hash、scaler/checkpoint 目录或文件名；validation 只复用同一 rolling 训练 identity，禁止 rolling 后再次调用 frozen scaler。输出维度保持 51 raw + 18 G9 mask = 69，close 不进入 `feature_cols_out`。

## Key Compatibility Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|---|---|---|---|
| 默认路径 | `normalize="per_code"` 原样保留 | 默认切 rolling | 旧命令和结果必须回归 |
| opt-in 接口 | 新增明确 `rolling` 枚举/CLI 参数 | 隐式按配置或自动检测 | 防止无意改变训练口径 |
| rolling 窗口 | 252 日含 t，最少 120，有效不足时 frozen per-code fallback | 丢弃整行或使用未来数据 | 控制 warmup 样本损失并防前视 |
| 特征范围 | 首批按 issue：G1+macd，再支持 G3/G4 消融；close 仅辅助 | 将 close 作为第 52 个输入 | 用户约束，避免 F/旧 checkpoint 混淆 |
| 统计规则 | G1/relative 后 robust；G3/G4/macd winsor；G5 其他/G8 透传；G9 mask | 复用 frozen transform 全部规则 | rolling 与 frozen 语义需独立且可审计 |
| 身份隔离 | rolling schema/identity/checkpoint 必须含 mode、window、min_periods、feature order、digest | 复用 `scaler_per_code.pkl` 或旧 checkpoint | 禁止二次归一化和错误加载 |
| 维度事实源 | 以当前代码 F=69 为实现契约，更新漂移文档/测试 | 继续沿用 F=45 文案 | 防止实验结果与运行代码不一致 |

## Impact

| 模块 | 文件 | 操作 | 风险 |
|---|---|---|---|
| data | `data/rolling_scaler.py` | create | high |
| data | `data/dataset.py`, `data/schema.py`, `data/scaler.py` | modify | high |
| training/config | `train.py`, `config/defaults.py` | modify | high |
| inference/eval | `scripts/eval_bins_mapping.py` | modify | medium |
| models | `models/cnn_transformer/config.py`, `models/cnn_transformer/model.py` | inspect/compat only | medium |
| tests | `tests/unit/data/*` and focused model test | modify/create | high |
| docs | README/AGENTS/spec drift references | modify | medium |

## Task Decomposition

### T01: 固化 rolling schema 与身份契约
- **文件**: `data/schema.py` (modify), `data/rolling_scaler.py` (create)
- **描述**: 定义 rolling mode/version、window=252、min_periods=120、首批特征组、close 辅助列、fallback/mask/output 顺序和独立 manifest/hash；保留 69 输出契约。
- **依赖**: 无；**预估行数**: +90/-20
- **验收标准**: rolling/frozen manifest 任一不同即不相等；close 不在输出列；raw 51 + mask 18 = 69。

### T02: 实现无前视 rolling kernel
- **文件**: `data/rolling_scaler.py` (modify)
- **描述**: 逐 code 处理 relative、rolling/expanding median/IQR/winsor、缺失和 fallback，统计只使用截至 t 的有效观测，并暴露审计计数。
- **依赖**: T01；**预估行数**: +140/-10
- **验收标准**: t+1 扰动不影响 t；不足 120 使用约定 fallback；非有限值最终为有限值；不修改 close 输入。

### T03: 接入 ParquetDataset 与 split context
- **文件**: `data/dataset.py`, `data/scaler.py` (modify)
- **描述**: 增加显式 rolling 分支；保持过滤、排序、标签和窗口索引代码路径语义；训练生成 rolling identity，validation 只接受匹配训练对象/context，不二次归一化。
- **依赖**: T01,T02；**预估行数**: +100/-45
- **验收标准**: frozen 默认行为不变；rolling 训练/验证输出同 F/T；context 不产生样本、标签或 index；错误 identity 明确失败。

### T04: 接入训练配置与 checkpoint 隔离
- **文件**: `config/defaults.py`, `train.py`, `models/cnn_transformer/config.py` (modify)
- **描述**: 增加 rolling opt-in 参数和 run metadata；CNNTransformer 仍接收 `[B,69,60]` 并返回 `(logits[ B,52 ], ret_pred[ B ])`，rolling run 不覆盖 frozen 产物。
- **依赖**: T03；**预估行数**: +55/-20
- **验收标准**: 默认命令仍为 frozen；rolling 必须显式传参；模型 forward shape 与实际 dataset.num_features 一致；旧 F=45 checkpoint 不被 rolling 复用。

### T05: 评估链路身份校验
- **文件**: `scripts/eval_bins_mapping.py` (modify)
- **描述**: 评估按 checkpoint/run metadata 选择 frozen 或 rolling preprocessing，校验 mode/schema/identity/featurenum；不实现 quant exporter。
- **依赖**: T03,T04；**预估行数**: +60/-15
- **验收标准**: mode 或 schema 不匹配拒绝；同 mode 可复用训练 identity；默认 frozen 评估回归。

### T06: 单元测试与对照验收
- **文件**: `tests/unit/data/test_rolling_normalization.py` (create), `tests/unit/data/test_data_feature_pipeline.py`, `tests/unit/data/test_data_schema_labels.py` (modify)
- **描述**: 覆盖 kernel 数值、前视、边界、fallback、context、identity、frozen regression、69 维和 CNN forward；固定同样本 frozen-vs-rolling 对照。
- **依赖**: T02-T05；**预估行数**: +180/-30
- **验收标准**: synthetic parquet 全部通过；`x=[B,69,60]`；logits `[B,52]`；open-open/window count 不变。

### T07: 修正文档漂移并记录实验边界
- **文件**: `README.md`, `README_TRAINING_CHAIN.md`, `AGENTS.md`, `data/AGENTS.md`, `models/AGENTS.md`, `docs/per_code_normalization_spec.md` (modify)
- **描述**: 明确 F=69 实际契约、F=45 历史说明、rolling opt-in 和 quant exporter 非目标；保留 frozen 作为基线。
- **依赖**: T06；**预估行数**: +55/-45
- **验收标准**: 全项目关键文档不再把 F=45 写成当前默认；rolling 规则与代码 manifest 一致。

## Verification And Acceptance Commands

不在本次拆解阶段执行命令；编码阶段依次执行：

```bash
uv run --project . python -m unittest tests.unit.data.test_data_schema_labels tests.unit.data.test_dataset_label_openopen tests.unit.data.test_data_feature_pipeline tests.unit.data.test_rolling_normalization
uv run --project . python -m py_compile data/dataset.py data/scaler.py data/rolling_scaler.py train.py
uv run ruff check .
uv run --project . python train.py --smoke --num_workers 0
uv run --project . python train.py --smoke --num_workers 0 --normalize rolling
```

验收还需检查 frozen/rolling 相同样本的标签、窗口数、forward shape、fallback 比例、训练耗时和产物 identity；full smoke 由后续 Quality Gate 决定，本阶段不执行。

## Risks And Rollback

- **高风险**：context 误入窗口、rolling 右端越界、F=69/旧 F=45 漂移、scaler 二次调用。以合成时序测试和严格 manifest 校验阻断。
- **性能风险**：全量逐 code rolling 可能增加内存/耗时；保留审计计数，必要时限制首批特征或采用逐 code 处理，不改变默认路径。
- **回滚**：移除 `rolling` opt-in 注册和新增 rolling 文件/测试即可恢复；默认 `per_code` 分支、`logs/scaler_per_code.pkl`、旧 frozen checkpoint 不迁移不覆盖。
- **工作区保护**：只允许提交本任务三份文档；`uv.lock` 与 `scripts/run_eval_pipeline.py` 不加入 staging、不修改。
