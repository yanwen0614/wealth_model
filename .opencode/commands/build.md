---
description: 编码实现 - 执行完整 quant-model 流水线（兼容 cnn-harness，编码 + 审查 + 验证 + 自动提交，worktree 合入需手动 merge-worktree）
agent: build
---

触发 quant-model skill（兼容 cnn-harness 别名），以 `full` 模式（默认）执行完整流水线。验证与提交已自动化，worktree 合入 main 仍需手动触发 `merge-worktree`。

## 执行步骤

### 1. 模式推断

根据用户输入推断执行模式：

| 用户意图 | 模式 |
|---------|------|
| 「加功能」「新增」「修 bug」「重构」「优化」 | `full`（默认） |
| 「快速改」「直接改」「不用审查」 | `code_only` |
| 其他 | `full` |

用 question 工具向用户确认推断的模式。

### 2. 创建 Worktree 隔离工作区

在执行任何编码操作前，**必须**先调用 `using-git-worktrees` 技能创建隔离工作区：

1. 调用 `skill` 工具加载 `using-git-worktrees` 技能
2. 按技能指引创建 git worktree（基于新分支，前缀 `cnn_`）
3. 后续所有编码、审查、验证、提交操作均在 worktree 目录中执行
4. 合入 main 需手动执行 `merge-worktree` 流程（见 `merge-worktree.md`，脚本 `scripts/merge_worktree.sh`）

**注意**：
- 不要在主工作区直接编码，所有变更必须在 worktree 中进行。
- worktree 中的 `.venv` 和 `.env` 由 `post-checkout` hook 自动符号链接到 main repo，无需手动复制。

### 3. 执行 quant-model 完整流程（兼容 cnn-harness）

按照 `.opencode/skills/quant-model/SKILL.md`（兼容 `cnn-harness` 别名）中的流程执行（在 worktree 目录中）：

#### Phase 0: 环境准备
- `git status --porcelain` 检查工作区
- 从需求描述定位目标模块（见下表）
- 读取 `CLAUDE.md` + 目标模块 `AGENTS.md` + `MISTAKES.md`
- 生成 task_dir = `docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/`
- 检查未完成任务

| 语义输入 | 目标模块 |
|---------|---------|
| parquet / dataset / 数据加载 | `data/parquet_dataset` |
| scaler / 归一化 / per_code | `data/grouped_scaler` / `data/per_code_scaler` |
| model / CNN / Transformer / 任意模型架构 | `models/*`（任意模型：`model2`, `cnn_lstm_attention`, `attention` …） |
| training / 训练链路 / Trainer | `training` |
| loss / 损失 / EMD | `criterion` |
| inference / 推理 / 预测 | `inference` |
| config / 配置 | `config` |

#### Phase 1: 需求分析
- 派遣 `task-decomposer` 子代理
- 生成 `{task_dir}/REVIEW_CHECKLIST.md` + `{task_dir}/PLAN.md` + `{task_dir}/HARNESS_PROGRESS.md`

#### Phase 1.5: 用户确认 + 规划文档自动提交
- 展示需求理解、实施计划（PLAN.md 的 Goal/Architecture/Key Decisions）、影响分析、任务清单、验收标准、历史风险点
- 等待用户确认
- 确认后立即自动提交规划文档：`git add {task_dir}/REVIEW_CHECKLIST.md {task_dir}/PLAN.md {task_dir}/HARNESS_PROGRESS.md` → `git commit -m "docs: add plan for {task-tag}"` → `git push`（worktree 推分支；`--no-push` 可跳过）

#### Phase 2: 循环执行（按任务依赖顺序）

对每个子任务：

**full 模式**：
1. 派遣 `generator` 子代理编码（TDD：先测试后实现）
2. 派遣 `quality-gate` 子代理（mode=review_verify）：6 关卡审查 + lint/typecheck/test 一次完成
3. 如 FAIL → 用 task_id resume 同一 quality-gate 会话派 fix 指令（最多 2 轮），每次修复后 resume 派 re_verify 复验
4. 更新 `{task_dir}/HARNESS_PROGRESS.md`

**code_only 模式**：
1. 派遣 `generator` 子代理编码
2. 更新 `{task_dir}/HARNESS_PROGRESS.md`

#### Phase 3: 交付确认
- 输出变更摘要报告（变更内容、质量关卡结果；验证已由 Quality Gate 自动执行，命令仅供本地复现）

#### Phase 4: 自动提交与推送（增量第二提交）
- 全 PASS 时自动执行：`git status` + `git diff --stat` → 生成 Conventional Commits 消息 → `question` 确认（回车即采用）→ `git add -A && git commit -m` → `git push`（worktree 推分支，主区推 main；`--no-push` 可跳过）
- FAIL 时：`git diff` 展示后 `question` 询问 (a)仍提交 (b)回退
- 展示 `git log --oneline -3` 与 `git status`
- 注：Phase 1.5 已提交规划文档，此为代码增量提交；`merge-worktree --finish` 会 squash 为唯一 commit

#### Phase 5: 自动归档（分支感知）
- **worktree**：不就地归档，仅标注 HARNESS_PROGRESS 为「待合入归档」；归档由 `merge-worktree --finish` 统一完成（`git mv task/issue → *_archive/` + 引用修正 + MEMORY 同步，幂等跳过已归档）
- **主区**（无 worktree 小改）：就地 `git mv` 归档 + `git commit --amend`

### 4. 关键规则

- 任务间有依赖时，前置任务必须 PASS 后才能开始后续任务
- quality-gate fix 2 轮仍 FAIL → 展示 `git diff`，询问用户接受或回退
- 每个子代理完成后，更新 HARNESS_PROGRESS.md 中的对应状态
- 所有文件操作必须基于 worktree 路径，不得操作主工作区
- **无需 /ship**：提交已在 Phase 4 自动完成；合入 main 需手动 `merge-worktree --prepare/--finish`

### 5. 参数

| 参数 | 说明 |
|------|------|
| `--no-push` | 跳过 Phase 4 自动 `git push`，仅本地提交 |
| `--no-archive` | 主区场景跳过 Phase 5 就地归档（worktree 场景本身不归档，此参数无影响） |
