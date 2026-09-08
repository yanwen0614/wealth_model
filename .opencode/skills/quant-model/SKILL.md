---
name: quant-model
description: Use when any code change is needed on the quant-model (cnn) project - enforces quality gates for all model/data/training/inference changes using 3-agent Harness pipeline, supports CNN/LSTM/Transformer
---

# 量化模型项目质量管控流水线（通用模型 harness）

## Overview

量化模型项目（quant-model，当前仓库为 cnn）的**所有模型相关变更**（模型结构/训练/损失/数据流水/推理/可视化）都应通过本 SKILL 执行，不局限于 CNN。

本项目已演进为多架构共存：`models/model2/CNNTransformer`（CNN+Transformer）、`models/cnn_lstm_attention.py:CNN_LSTM_Attention`（CNN+LSTM+Attention）、`models/attention.py:SelfAttention`，需支持 **pluggable 模型架构**。本 SKILL 采用 3-agent 架构和 VERDICT 协议，在现有代码基础上安全地做增量变更：
- **Generator 策略**：读现有代码上下文 → 遵循设计原则 → 增量变更
- **架构约束**：遵循 AGENTS.md / README_TRAINING_CHAIN.md / docs/per_code_normalization_spec.md 中的模块边界和编码规范
- **模型通用约束**：所有模型实现 `forward(x: [B, F, T]) -> [B, num_classes]` 通用接口（F=featurenum 48/55, T=seq_len 60），通过 `ModelConfig(featurenum/seq_len/num_classes/d_model/nhead/...)` 约束，新增模型只需实现接口并注册 ModelConfig 即可接入训练/推理链路

核心链路（通用）：`parquet (48/55维) → data/* (parquet_dataset+scalers) → models/* (pluggable: model2/CNNTransformer, cnn_lstm_attention, attention) → criterion/* / training/* → main*.py → inference.py`，说明新增模型只需实现 `forward(x: [B, F, T]) -> [B, num_classes]` 接口并注册 ModelConfig

> 以 CNNTransformer 为例，泛化至所有 `models/*`：任一模型变更均走同一 harness 流水线，不再区分 CNN 专属路径。

### 关键约束

| 约束 | 说明 |
|------|------|
| **允许自动跑测试** | 默认 `uv run python scripts/run_unit_tests.py --tier fast`（若脚本不存在则回退至 fast 回退链：`ruff check .` + `pyright` + `uv run python -m data.parquet_dataset --max_codes 10`）；命中「测试选择策略」触发条件时升级 `uv run python scripts/run_unit_tests.py --tier full`（若脚本不存在则回退至 full 回退链：`uv run python main_parquet.py --smoke` 全量训练冒烟，tmux 后台） |
| **Lint 检查** | 执行 `ruff check .` 做代码规范检查 |
| **TypeCheck 检查** | 执行 `pyright` 做类型检查 |
| **禁止在项目根目录创建临时文件** | 输出重定向必须使用 `/tmp/opencode`，禁止在项目根目录创建 `.txt`、`.log` 等临时文件 |
| **子代理不能询问用户** | Generator/TD/QualityGate 无法使用 question 工具；需要用户决策时返回 `status: "blocked"`，由主编排器代为询问后恢复会话 |
| **子代理必须使用 foreground 模式** | 所有子代理（Generator/TD/QualityGate 等）必须使用 `foreground` 模式派遣，禁止使用 `background` 模式 |
| **Python 执行** | 所有 Python 脚本通过 `uv run python -u <脚本>` 执行 |
| **自动提交与归档** | Phase 3 全 PASS 后自动 `git add -A && git commit && git push`（worktree 推分支，主区推 main）；归档 `docs/agent/task → task_archive`：worktree 委托 `merge-worktree --finish`（手动触发合入），主区就地自动完成 |

## 智能体团队

| 角色 | 职责 | subagent 名字 |
|------|------|---------------|
| **Task Decomposer** | 需求分析 + 影响范围 + 全项目重复检测 | `task-decomposer` |
| **Generator** | 读现有代码上下文 → 遵循设计原则 → 增量变更 | `generator` |
| **Quality Gate** | 6 关卡审查 + lint/typecheck/test 验证（review_verify）；FAIL 时修复（fix）+ 复验（re_verify），resume 同一会话 | `quality-gate` |

## 执行模式

| 模式 | 说明 | 触发关键词 |
|------|------|-----------|
| `full`（默认） | 完整流水线 | 「加功能」「新增」「修 bug」「重构」「优化」 |
| `analyze` | 仅分析，不编码 | 「分析」「评估」「看看」「影响范围」「方案」 |
| `code_only` | 编码但跳过审查 | 「快速改」「直接改」「不用审查」 |
| `review_only` | 仅审查，不编码 | 「审查」「review」「检查质量」 |

**推断后必须确认**：用 question 工具展示推断结果，让用户确认或切换模式。

## 全局写入规则

**所有写文件操作必须分批写入，每批不超过 100 行。** 先用 Write 工具写入第一批，后续用 Edit 工具在文件末尾追加。派遣子代理时必须在 prompt 中明确要求子代理同样遵守此规则。

## AGENTS.md 强制读取规则

**修改任何模块代码前（Phase 2 Generator 启动前），必须先检查并读取目标模块目录下的 `AGENTS.md`（如存在）。**

- 路径：`{module}/AGENTS.md`（如 `data/AGENTS.md`、`models/AGENTS.md`、`models/model2/AGENTS.md`、`training/AGENTS.md`）
- 状态为「已创建」→ **强制读取**，模块级规范优先级高于全局规范
- **派遣 Generator / Quality Gate 子代理时，必须在 prompt 中附上模块 AGENTS.md 的关键规范内容**

同时必须读取：
1. 根目录 `CLAUDE.md` / `AGENTS.md`（全局规范，如存在）
2. `README_TRAINING_CHAIN.md`（训练链路契约：数据入口、特征维度、scaler 语义）
3. `docs/per_code_normalization_spec.md`（per-code 分组归一化共识，涉及 data 层必读，训练/模型层亦需传入 per_code 分组信息）
4. `models/AGENTS.md` 总纲（如存在，pluggable 模型注册/ModelConfig 约束）+ 目标子模块 `AGENTS.md`（如 `models/model2/AGENTS.md`）
5. `models/model2/config.py` 中 `ModelConfig` 通用字段定义（featurenum/seq_len/num_classes/d_model/nhead 等）

## 交付件

| # | 产物 | 生成阶段 | 路径 |
|---|------|---------|------|
| 1 | `HARNESS_PROGRESS.md` | Phase 1 创建，全程迭代 | `{task_dir}/HARNESS_PROGRESS.md` |
| 2 | `REVIEW_CHECKLIST.md` | Phase 1 生成 | `{task_dir}/REVIEW_CHECKLIST.md` |
| 3 | `PLAN.md` | Phase 1 生成 | `{task_dir}/PLAN.md` |
| 4 | 代码变更 | Phase 2 生成 | 直接修改源码 |
| 5 | `MISTAKES.md` | Phase 2d FAIL 时追加 | 根目录 `MISTAKES.md` |
| 6 | 变更摘要报告 | Phase 3 输出 | 终端输出，可直接用作 commit 描述 |
| 7 | git commit（含 task 文档） | Phase 4 自动提交 | `git log`（worktree 为分支 commit，主区为 main commit） |

> `task_dir` = `docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/`，在 Phase 0.4 生成；worktree 场景由 `merge-worktree --finish` 归档至 `task_archive/`，主区由 Phase 5 就地归档。

---

## 完整流程概览

```
[模式推断] 分析意图 → question 确认模式
    |
    v
[Phase 0] 环境准备                                        ★全模式
    - git status 检查工作区 / 定位模块 / 读取 AGENTS.md + README_TRAINING_CHAIN.md + per_code_normalization_spec.md + MISTAKES.md
    - 生成 task_dir，检查未完成任务
    |
    v
[Phase 1] 需求分析 (Task Decomposer)                      ★全模式
    - 影响分析 / 重复检测 / 任务拆解（覆盖所有模型架构：CNN/LSTM/Transformer/Attention/混合）
    - 生成 {task_dir}/REVIEW_CHECKLIST.md + PLAN.md + HARNESS_PROGRESS.md
    |
    v
[Phase 1.5] 用户确认 + 规划文档自动提交                   ★全模式
    - 展示需求理解/计划/影响/任务/验收/风险/task_dir（含模型选型/消融对比）
    - 用户确认后立即 git add/commit/push 规划文档（analyze 止于此）
    |
    v
[Phase 2] 循环执行（按任务依赖顺序）
    full:        Generator（TDD Red-Green-Refactor 内环，遵循 ModelConfig 通用接口） ★ → Quality Gate ★
                 （review_verify 单次完成审查+验证，含 per_code 分组正确性）
    code_only:   Generator（TDD 内环） ★
    review_only: Quality Gate ★（对指定文件 review_verify）
    FAIL 时:     → resume Quality Gate（fix，最多 2 轮）→ resume 复验（re_verify）
    |
    v
[Phase 3] 交付确认 — 输出变更摘要报告（验证已自动执行）    ★全模式
    |
    v
[Phase 4] 自动提交与推送                                  ★full/code_only
    - 全 PASS 自动 git add/commit/push（worktree 推分支，主区推 main）
    - FAIL 经用户确认后仍可提交（标 known-issue）
    |
    v
[Phase 5] 自动归档                                        ★full/code_only
    - worktree：委托 merge-worktree --finish 归档（需手动触发合入 main）
    - 主区：就地 git mv task/issue → *_archive/ + 引用修正 + MEMORY 同步
```

---

## Phase 0: 环境准备

### 0.1 检查工作区状态

```bash
git status --porcelain
```

- **通过条件**：输出为空，或仅有 untracked 文件（`??` 开头的行）
- **不通过**：存在未提交的修改（M/A/D/R 开头的行）→ 提示用户先 commit 或 stash，再继续

### 0.2 定位目标模块

从需求描述中推断涉及的模块（通用模型覆盖）：

| 关键词 | 目标模块 |
|--------|---------|
| parquet/ParquetDataset/scaler/归一化/per-code | `data/parquet_dataset` ⚡full, `data/per_code_scaler` ⚡full, `data/grouped_scaler` |
| CNN/Transformer/Attention | `models/*` ⚡full |
| LSTM/时序/序列 | `models/*` ⚡full |
| 新增模型/架构选型/消融 | `models/*` ⚡full |
| 模型结构/ModelConfig/注册/工厂/pluggable | `models/*` ⚡full, `models/model2/config.py` (ModelConfig 通用接口) |
| 训练/Trainer/早停/调度/训练循环 | `training/` ⚡full |
| 损失/EMD/HalfClassWeighted/不平衡 | `criterion/` ⚡full, `training/custom_loss.py` |
| 数据处理/processor/NPZ/CSV预处理 | `data_processor.py` / `data/npz_data_load.py` |
| 推理/inference/预测/部署 | `inference.py` |
| 日志/LoggerManager/log_manager | `log_manager/` |
| 可视化/visualization/曲线/混淆矩阵 | `visualization/` |
| 配置/config/yaml/main_parquet | `config/` / `main_parquet.py` / `config2.yaml` |
| 特征选择/feature-select/降维 | `data/parquet_dataset` ⚡full（feature_cols） + `models/*/config.py` (ModelConfig.featurenum) |

> ⚡full = 命中此模块的变更时 QA 升级 full 档（见「测试选择策略」触发规则）；`models/*` 表示任意模型文件（`models/model2/**`, `models/cnn_lstm_attention.py`, `models/attention.py` 及未来新增模型）均触发 full

### 0.3 读取约束文件

1. 读取 `CLAUDE.md` / `AGENTS.md`（根目录，全局规范，如存在）
2. 读取 `MISTAKES.md`（根目录，如存在 — 历史错误记录）
3. 读取 `README_TRAINING_CHAIN.md`（训练链路契约：55/48维、scaler、时序切分）
4. 读取 `docs/per_code_normalization_spec.md`（per-code 归一化共识，data 层必读，模型/训练层需传入 per_code 分组字段）
5. 读取 `models/AGENTS.md` 总纲（如存在，pluggable 注册与通用接口）+ `{目标模块}/AGENTS.md`（模块级，如存在，含 `models/model2/AGENTS.md` 等）
6. 读取 `models/model2/config.py` 中 `ModelConfig` 定义（featurenum/seq_len/num_classes 通用接口约束）

### 0.4 生成任务目录（task_dir）

从需求描述中提取 `task-tag`（小写英文 + 连字符，最长 30 字符，去掉介词）：
- 示例：「修复 per-code scaler 未见 code 回退逻辑」→ `fix-percode-unseen-fallback`
- 示例：「给 CNNTransformer 添加残差分支」→ `add-cnn-residual-branch`
- 示例：「新增 LSTM 时序模型并注册 ModelConfig」→ `add-lstm-model-registry`
- 示例：「Transformer 消融对比 CNN_LSTM_Attention」→ `ablation-transformer-vs-lstm`

生成 `task_dir`：
```
task_dir = docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/
```

**在 Phase 1.5 用户确认时展示 task_dir，允许用户修改 task-tag。**

### 0.5 检查未完成任务

glob 扫描 `docs/agent/task/*/HARNESS_PROGRESS.md`，检查是否存在含有未完成任务标记（`pending`）的进度文件。

- 若有未完成文件 → 展示列表，让用户选择「继续某个任务」或「忽略，开始新任务」
- 若选择继续 → 从目录名解析 `task_dir`，跳过 0.4 步骤
- 若选择新任务 / 无未完成文件 → 使用 0.4 生成的 `task_dir`

---

## Phase 1: 需求分析 & 任务拆解

派遣 `task-decomposer` 子代理，传入：需求描述、需求类型、目标模块列表、`task_dir`、CLAUDE.md/AGENTS.md 路径、README_TRAINING_CHAIN.md、per_code_normalization_spec.md、MISTAKES.md 路径、`models/AGENTS.md` 总纲及 `ModelConfig` 通用字段。

子代理负责创建：
- `{task_dir}/REVIEW_CHECKLIST.md`（审查清单：影响范围 + 质量关卡，含模型通用接口校验）
- `{task_dir}/HARNESS_PROGRESS.md`（进度追踪：任务列表 + 依赖 + 状态）
- `{task_dir}/PLAN.md`（轻量实施计划：设计决策 + 任务拆解，需注明模型架构选型/ModelConfig 约束/per_code 分组，供编码前后审阅）

子代理需额外评估：
- 若涉及新增模型/架构选型：对比已有多模型（CNNTransformer/CNN_LSTM_Attention/SelfAttention）的复用与差异，明确是否需注册新 ModelConfig、是否需新增 `models/*` 文件或扩展现有模型
- 若涉及训练/损失/数据流水：验证 per_code 分组维度与 ModelConfig featurenum/seq_len 的对齐
- 若涉及消融/对照：规划 ablation 对比维度

子代理返回后，Read 三个文件确认已生成。

---

## Phase 1.5: 用户确认

向用户展示：
1. **需求理解**：AI 对需求的理解（附显式假设列表，含模型架构假设）
2. **实施计划**：`PLAN.md` 中的 Goal、Architecture、Key Decisions（设计方案与决策理由，含 ModelConfig 通用接口决策）
3. **影响分析**：涉及的模块和文件（标注 `models/*` pluggable 影响面）
4. **任务清单**：拆解的任务列表（含预估行数）
5. **验收标准**：完成的标准和验证命令（含模型前向 shape 验证 `forward(x:[B,F,T])->[B,num_classes]`）
6. **历史风险点**：MISTAKES.md 中相关的历史错误
7. **任务目录**：`task_dir` 路径，允许用户修改 task-tag

等待用户确认后继续执行（`full` / `code_only` / `custom` / `analyze` 模式）。

### Phase 1.6: 规划文档自动提交（★全模式，analyze 含）

用户确认后**立即自动提交**本阶段产出的规划文档，避免文档悬空：

1. 执行 `git add {task_dir}/REVIEW_CHECKLIST.md {task_dir}/PLAN.md {task_dir}/HARNESS_PROGRESS.md`（若任务含 `spec` 产出的 `*_MODULE_DESIGN.md` / `*_INTERVIEW_LOG.md` / `*_DESIGN_SPEC.md`，一并加入）
2. 生成 commit message：`docs: add plan for {task-tag}`（spec 场景为 `docs: add spec for {MODULE}`）
3. 执行 `git commit -m "{message}"`（worktree 提交到分支，主区提交到 main；`--no-push` 可跳过推送则仅本地提交）
4. 执行 `git push`（失败仅提示不阻塞）
5. 展示 `git log --oneline -1` 与 `git status`

> `analyze`（`/plan`）模式止于此提交后终止；`full`/`code_only`（`/build`）模式携带此 commit 继续 Phase 2，Phase 4 的代码提交为增量第二 commit，最终由 `merge-worktree --finish` squash 为唯一 commit（主区场景则为两次独立 commit）。

---

## Phase 2: 循环执行

> **子代理执行模式**：Phase 2 中派遣的所有子代理（Generator、Quality Gate 以及其后续可能再派遣的子代理）必须使用 `foreground` 模式派遣，禁止使用 `background` 模式。使用 foreground 模式可确保验证结果实时返回，避免异步丢失。

按 `execution_order` 中的顺序逐任务执行。

### 2a: Generator 编码（含 TDD 内环）

派遣 `generator` 子代理，传入：task_id、任务名、目标文件列表、操作类型（create/modify）、Task Decomposer 的详细设计、需求摘要、是否需要测试（`need_test`）、CLAUDE.md/AGENTS.md 关键规范、`{task_dir}/PLAN.md`（供 design 设计决策参考）、`task_dir`、README_TRAINING_CHAIN.md 链路约束、per_code_normalization_spec 分组归一化决策（per_code 分组字段）、`ModelConfig` 通用字段（featurenum/seq_len/num_classes 通用接口）、`models/AGENTS.md` pluggable 约束（`forward(x:[B,F,T])->[B,num_classes]`）。

**TDD 要求**（由主编排器在 prompt 中明确声明）：
- `need_test = true` 时，Generator **必须执行 TDD Red-Green-Refactor 循环**
- TDD 验证仅限 `uv run python -m unittest <本次测试文件>`（单文件运行），禁止跑完整套件
- Generator 返回中须包含 `tdd_verification` 字段，记录各行为的 red/green 结果（含模型前向 shape 断言）
- 公共接口变更、核心算法实现、Bug 修复、新模型结构 — 强制 TDD（新模型需验证 forward shape 与 ModelConfig 对齐）
- 纯数据层/配置变更（如 model 仅增字段、YAML 配置调整）— 可 skip TDD，但须说明理由

### 2b: Quality Gate 审查 + 验证（★ full 模式）

单次派遣 `quality-gate` 子代理（mode=review_verify），传入：task_id、变更文件列表、CLAUDE.md/AGENTS.md 路径列表（含 `models/AGENTS.md`）、`{task_dir}/REVIEW_CHECKLIST.md` 路径、`{task_dir}/PLAN.md` 路径（对照设计约束审查，含 ModelConfig 约束）、生成的测试文件列表、需求类型、目标模块、`test_scope`（`fast`/`full`，由主编排器按「测试选择策略」触发规则计算）、`task_dir`、Generator 返回的 `tdd_verification`、per_code 分组与 ModelConfig 对齐信息。

子代理内部依次执行 6 道质量关卡审查 → ruff/pyright/单元测试 → TDD 验证检查，一次返回统一 VERDICT 与 all_issues（详见 `.opencode/agents/quality-gate.md`）。

**TDD 验证要求（由 Quality Gate 执行）**：
- 检查 `tdd_verification` 字段：所有 `red_passed` 和 `green_passed` 必须均为 `true`
- 若 `need_test = true` 但无 `tdd_verification` → 标记 FAIL，记录 "TDD 验证缺失"
- 若 `tdd_verification` 中存在 `red_passed = false` → 标记 FAIL，记录 "RED 验证未通过"
- 若涉及 `models/*` 但未验证 `forward(x:[B,F,T])->[B,num_classes]` shape → 标记 FAIL
- 上述判定独立于 lint/typecheck/test，TDD 没走好就 FAIL，不进 test 环节

### 测试选择策略

Quality Gate 的单元测试范围由 `test_scope`（fast/full）控制：默认 fast 保证低于 120s 工具超时且无网络依赖；仅在命中高风险触发条件时升级 full 覆盖全量训练冒烟与数据链路完整验证。`test_scope` 仅控制单元测试范围，lint（ruff）与 typecheck（pyright）不受 scope 影响，始终全量执行。fast 集已含全部纯单元模块及跨模块影响（如 data/per_code_scaler→data/parquet_dataset、criterion→training 均在 fast 内），**full 增量 = 全量 parquet 冒烟 + per-code 分组验证 + 任意模型前向验证**。

#### 测试范围决策表

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 默认档 fast | `uv run python scripts/run_unit_tests.py --tier fast`（若脚本不存在则回退至：`ruff check .` + `pyright` + `uv run python -m data.parquet_dataset --max_codes 10` 前台直跑，~15s） | 低于 120s 超时阈值；不依赖真实 GPU 全量训练；与 ruff+pyright 分层一致 |
| 升级档 full | `uv run python scripts/run_unit_tests.py --tier full`（若脚本不存在则回退至：`uv run python main_parquet.py --smoke` + `uv run python -m data.parquet_dataset --max_codes 100`，tmux 后台） | 覆盖 per-code 归一化 + 全量链路（scaler 拟合/验证集复用）+ 任意模型前向，仅高风险变更需要 |
| full 运行方式 | tmux 后台 + sleep 链式跟踪（会话 `cnn_` 前缀，输出 `/tmp/opencode`） | full 含训练冒烟 ~30s，前台亦可，但保留 tmux 后台机制（输出可回溯，符合长任务约定，禁 while 循环） |
| smoke 档 | `uv run python -m data.parquet_dataset --max_codes 10`（快速 sanity，~5s） | 保存后即时 sanity / 轻量子集，harness 不做 QA 决策用档，仅 Generator 自检 |
| 备选验证 | `uv run python -m pytest tests/` 或 `uv run python -m unittest discover tests` | 若项目新增 tests 目录，优先使用；当前 cnn 暂无分级脚本时以 ruff+pyright+冒烟为主 |

> **完整场景决策表**（日常开发/commit 前/CI/睡前/全量训练回归等场景 → 档位 → 命令）的详细版见未来 `tests/AGENTS.md`「何时跑什么测试」。Quality Gate 的 `test_scope` 仅用 fast/full 两档决策（smoke 不参与 harness 门禁）。
> **脚本缺失回退说明**：cnn 当前仓库暂无 `scripts/run_unit_tests.py`；若脚本不存在，fast/full 自动回退至上表「回退链」命令，待创建脚本后无缝切换至 tier 机制，不得阻塞 harness。

#### full 升级触发规则（任一命中即升级）

| # | 触发条件 | 原因 |
|---|---------|------|
| 1 | 变更涉及 `data/parquet_dataset.py` ⚡full | 数据链路核心，滑动窗口/标签离散化/过滤逻辑，单测需覆盖全量扫描 |
| 2 | 变更涉及 `data/per_code_scaler.py` 或 `data/grouped_scaler.py` ⚡full | per-code 分组归一化核心，未见 code 回退、winsor、robust 逻辑，上游影响面大 |
| 3 | 变更涉及 `models/*` ⚡full（任意模型结构：`models/model2/**`、`models/cnn_lstm_attention.py`、`models/attention.py` 及未来新增模型） | 任意模型结构变更需全量前向+训练冒烟验证（通用 pluggable 接口） |
| 4 | 变更涉及 `training/` ⚡full（含 trainer、early_stopping、metrics） | 训练循环/早停/调度，上游需冒烟训练验证 |
| 5 | 变更涉及 `criterion/` ⚡full（EMDLoss/HalfClassWeightedCrossEntropy） | 损失函数变更需验证梯度与不平衡加权 |
| 6 | PLAN.md Impact 风险 = high | 设计阶段已判高风险 |
| 7 | 用户显式要求 | 最高优先级 |
| 8 | 变更涉及 `tests/` 被 fast 排除的目录或新增测试位于需 full 验证的路径 | 被排除测试默认不随 fast 运行，改测试本身须升级 full 验证 |

#### full 档 tmux 运行方式（遵循全局长任务约定）

```bash
# 1. 启动：cnn_ 前缀会话 + 输出到 /tmp/opencode（禁止操作 tmux 0/1）
#    -c 以当前仓库根为基准（harness 在仓库根运行，$PWD 即仓库根；worktree 场景同理）
# 优先尝试 tier 脚本，回退至冒烟：
tmux new-session -d -s cnn_qa_full -c "$PWD" \
  "if [ -f scripts/run_unit_tests.py ]; then uv run python scripts/run_unit_tests.py --tier full > /tmp/opencode/qa_test_full_output.txt 2>&1; else uv run python main_parquet.py --smoke > /tmp/opencode/qa_test_full_output.txt 2>&1; fi; echo EXIT_CODE=\$? >> /tmp/opencode/qa_test_full_output.txt"

# 2. 跟踪（禁止 while 循环，sleep 链式；full ~36s，sleep 60 后首查）
sleep 60 && tmux capture-pane -t cnn_qa_full -p | tail -40

# 3. 未完成则再等一轮
sleep 60 && tmux capture-pane -t cnn_qa_full -p | tail -40

# 4. 完成判定：grep EXIT_CODE= 于输出文件；结果解析 /tmp/opencode/qa_test_full_output.txt
# 5. 清理会话
tmux kill-session -t cnn_qa_full
```

### 2d: Quality Gate 修复轮次（FAIL 时）

如果 Quality Gate 返回 VERDICT = FAIL：

1. 汇总所有 issues
2. **将 critical issues 追加到根目录 `MISTAKES.md`**（避免重蹈覆辙）
3. **判断 TDD 问题类型**：
   - 若判定为 **TDD 验证缺失**（无 `tdd_verification`）或 **RED 验证未通过**：
     - **不进入 fix 轮次**
     - **直接重置 generator 子代理**，重新执行 Phase 2a（要求补全 TDD 循环，含模型前向 shape 验证）
     - 然后重新走 2b 完整流程（不消耗修复轮次）
   - 其他普通问题，进入 fix 轮次
4. **fix 轮次**（仅限编码/逻辑类 FAIL）：
   - 用 task_id **resume 同一 quality-gate 子代理会话**，派 `mode=fix` 指令：传入 issues 列表、retry_count、max_retries=2
   - 修复完成后再次 resume 同一会话派 `mode=re_verify` 指令复验
   - 复验仍 FAIL → 再次派 fix（最多 2 轮）
   - 2 轮后仍 FAIL → 执行 `git diff` 展示当前变更，询问用户：(a) 接受当前变更继续 (b) 回退本任务变更

### 任务间依赖处理

- 如果任务 T02 依赖 T01：**T01 必须 VERDICT = PASS 后才能开始 T02**
- **特殊情形 — TDD 强制重置**：
  - T01 在 2a 因 TDD 验证缺失/RED 失败被 Quality Gate 拒绝 → **不消耗重试次数**，直接 reset 2a（重写测试+走 TDD，补模型接口断言），重新走 2b
- **普通 FAIL**：
  - quality-gate fix 最多 2 轮后仍 FAIL → 询问用户：(a) 接受当前变更继续 (b) 回退本任务变更 → 若接受则 T02 可开始
  - 若选择回退 → 整个流程暂停（后续任务也停止）

---

## Phase 3: 交付确认

完成所有任务后，输出变更摘要报告：

```
## 变更摘要报告

### 需求
{原始需求描述}

### 变更内容
| 文件 | 操作 | 行数 | 模型接口 |
|------|------|------|---------|
| ...  | 新增/修改 | +N | forward(x:[B,F,T])->[B,num_classes] 是否对齐 |

### 质量关卡结果
| 任务 | TDD 验证 | Quality Gate | 最终结果 |
|------|----------|--------------|---------|
| T01  | PASS     | PASS         | ✅      |

**TDD 验证列**：当 `need_test = true` 时，显示 Generator 阶段各 TDD 循环的 RED/GREEN 是否全通过（含模型前向 shape）；当 `need_test = false` 时显示 "skipped"。

### 验证结果（已自动执行）
Quality Gate 已自动执行 ruff / pyright / unittest（见上表 gate_results），per_code 分组与 ModelConfig 对齐已校验，无需手动重跑。

<details><summary>本地复现（可选）</summary>

ruff check .
pyright
# 测试命令按本次 test_scope（fast 前台直跑；full 走 tmux 后台，见「测试选择策略」）
# fast:  uv run python scripts/run_unit_tests.py --tier fast  # 回退: ruff+pyright + python -m data.parquet_dataset --max_codes 10
# full:  uv run python scripts/run_unit_tests.py --tier full  # 回退: uv run python main_parquet.py --smoke
</details>

### 已知问题（范围外发现）
{如有发现但不在本次变更范围内的问题，列出供后续处理}
```

---

## Phase 4: 自动提交与推送

全量任务 `VERDICT = PASS` 时**自动执行**，无需 `/ship`：

1. 汇总 `git status --porcelain` 与 `git diff --stat`，按 Conventional Commits 生成 commit message（`{type}: {task-tag} {摘要}`，type 由变更特征推断：feat/fix/refactor/test/docs/chore）
2. 用 `question` 展示自动生成的 message 让用户确认（回车即采用，可直接修改）
3. 执行 `git add -A && git commit -m "{message}"`
4. 执行 `git push`（worktree 推送当前分支，主区推送 main；`--no-push` 可跳过；失败仅提示不阻塞）
5. 更新 `{task_dir}/HARNESS_PROGRESS.md` 标注已提交的 commit 哈希
6. 展示 `git log --oneline -3` 与 `git status`

**FAIL 分支**：2 轮 fix 仍 FAIL 时先 `git diff` 展示并 `question` 询问：(a) 仍提交（标 known-issue） (b) 回退；选 (a) 则按上述流程提交。

## Phase 5: 自动归档

**分支感知**（worktree 合入 main 仍需手动触发 `merge-worktree`）：

| 上下文 | 归档时机 | 执行内容 |
|--------|---------|---------|
| **worktree**（`build` 必经路径） | **委托** `merge-worktree --finish` 时归档 | Phase 5 仅做收口准备：issue 状态头改「待归档」+ HARNESS_PROGRESS 标注「待合入归档」；归档 `git mv task/issue → *_archive/`、旧路径 grep 修正、MEMORY 同步 均由 `--finish` 统一完成（幂等：已在 `*_archive` 则跳过） |
| **主区**（无 worktree 的小改） | **就地** Phase 4 后自动归档 | 1. issue 状态头改「已解决并归档」+ commit 短哈希，正文补收口记录 2. HARNESS_PROGRESS 头部标最终状态 3. `git mv` 至 `*_archive/`；grep 旧路径修正（含 MEMORY） 4. `git add -A && git commit --amend --no-edit` 或单独 commit（保持单 commit 语义） |

> worktree 下 `build` 不在此阶段执行 `git mv`，避免与 `--finish` 重复；`--finish` 内置幂等守卫。

---

## 模块级 AGENTS.md 查找路径

| 模块 | AGENTS.md 路径 | 说明 |
|------|---------------|------|
| data/parquet_dataset | `data/AGENTS.md` | Parquet 直通链路、时序切分、scaler 落盘契约 |
| data/per_code_scaler | `data/AGENTS.md` | per-code 分组归一化、median/IQR/winsor、未见 code 回退 |
| data/grouped_scaler | `data/AGENTS.md` | 分组 scaler 兜底逻辑 |
| models/* 通用总纲 | `models/AGENTS.md` | **pluggable 模型总纲**：`forward(x:[B,F,T])->[B,num_classes]` 通用接口、ModelConfig 约束、注册/工厂机制、新增模型接入流程 |
| models/model2/CNNTransformer | `models/model2/AGENTS.md` | CNNTransformer 结构、featurenum/seq_len/num_classes、config 约束（已泛化为 `models/*` 实例） |
| models/cnn_lstm_attention | `models/AGENTS.md` + 源码注释 | CNN_LSTM_Attention 混合架构、input_dim/seq_len/num_classes、Attention 集成 |
| models/attention | `models/AGENTS.md` + 源码注释 | SelfAttention 自注意力机制、hidden_dim 约束 |
| training | `training/AGENTS.md` | Trainer/early_stopping/metrics、调度与早停，需校验 ModelConfig 与 data 维度对齐 |
| criterion | `criterion/AGENTS.md` | EMDLoss/HalfClassWeightedCrossEntropy 有序分类损失，适配任意模型 logits |
| data_processor | （暂无，根目录 `data_processor.py`） | 旧 NPZ 预处理兼容层 |
| inference | （暂无，根目录 `inference.py`） | 推理与部署，适配 `models/*` pluggable 加载 |
| log_manager | `log_manager/AGENTS.md` | LoggerManager、run_log_dir、config 持久化 |
| visualization | `visualization/AGENTS.md` | Visualizer、training_curve、混淆矩阵，支持多模型对比 |
| config | `config/AGENTS.md` | data_path.yaml / config2.yaml / main_parquet 配置，含 ModelConfig 映射 |

> 若模块级 AGENTS.md 暂无，遵循根目录 `AGENTS.md` / `CLAUDE.md` 及 `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md` 的全局约束；新增模块时应同步创建 AGENTS.md。`models/AGENTS.md` 为新增总纲优先级高于各子模型 AGENTS.md，子模型 AGENTS.md 补充架构特有约束。

---

## 后续 TODO：模型通用 Skills

以下 skills 按需添加，暂不实现（对标 quant 的 daily-update/backtest 等，适配 quant-model 通用链路，覆盖 CNN/LSTM/Transformer/混合架构）：

| Skill | 描述 |
|-------|------|
| `daily-train` | 拉取最新 parquet → per-code scaler 拟合 → `main_parquet.py` 增量/全量训练（支持 `models/*` 任意架构切换 via ModelConfig） → 日志归档 |
| `inference` | 加载 `logs/run_*/best_model.pth` + `logs/scaler.pkl` → 批量推理（适配 `models/*` pluggable 加载） → 生成 predictions.csv |
| `per-code-normalization` | 按 `docs/per_code_normalization_spec.md` 执行 G1~G9 分组归一化 → 校验 `x [F,T]` 无 NaN/inf（F=featurenum 通用） |
| `feature-select` | 48/55 维特征选择/消融 → 对比 `use_factor_only` 与全量特征的收益分布与 Acc（跨模型通用） |
| `label-analyze` | `analyze_label_distribution.py` 标签 52 类分布分析 + horizon 对比（5/10/20日） |
| `data-validate` | 数据校验：is_trading 过滤、OHLC 完整性、因子缺失率、per-code 统计一致性 |
| `model-registry` | 模型注册/工厂/自动发现：扫描 `models/*`、校验 `forward(x:[B,F,T])->[B,num_classes]` 接口与 ModelConfig 约束、注册表生成 |
| `ablation` | 消融实验：CNN vs LSTM vs Transformer vs Attention vs 混合架构对照，固定 per_code/data/criterion 变量对比 |
| `hyperparam-search` | 超参搜索：基于 ModelConfig（d_model/nhead/num_layers/dropout 等）+ 训练调度网格/贝叶斯搜索，支持多模型并行评估 |

> 已从 `CNN 专属 Skills` 泛化为 `模型通用 Skills`：新增 `model-registry / ablation / hyperparam-search` 三项通用能力，原有项描述已泛化至 `models/*` 与 ModelConfig 通用接口。

