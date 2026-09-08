---
description: 规划任务 - 分析需求、拆解步骤、生成实施计划（不编码）
---

触发 quant-model skill（兼容 cnn-harness 别名），以 `analyze` 模式执行 Phase 0-1.5。

## 执行步骤

### 1. 模式推断

根据用户输入推断为 `analyze` 模式（仅分析不编码）。如果用户同时表达了编码意图，提示使用 `/build` 命令。

### 2. 执行 quant-model Phase 0-1.5（兼容 cnn-harness）

按照 `.opencode/skills/quant-model/SKILL.md`（兼容 `cnn-harness` 别名）中的流程执行：

#### Phase 0: 环境准备
- `git status --porcelain` 检查工作区
- 从需求描述定位目标模块（见下表）
- 读取 `CLAUDE.md` + 目标模块 `AGENTS.md` + `MISTAKES.md`
- 生成 task_dir = `docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/`
- 检查未完成任务（glob `docs/agent/task/*/HARNESS_PROGRESS.md`）

| 语义输入 | 目标模块 |
|---------|---------|
| parquet / dataset / 数据加载 | `data/parquet_dataset` |
| scaler / 归一化 / per_code | `data/grouped_scaler` / `data/per_code_scaler` |
| model / CNN / Transformer / 任意模型 | `models/*`（任意模型：`model2`, `cnn_lstm_attention`, `attention` …） |
| training / 训练链路 | `training` |
| loss / 损失 / EMD | `criterion` |
| inference / 推理 | `inference` |
| config / 配置 | `config` |

#### Phase 1: 需求分析
- 派遣 `task-decomposer` 子代理执行需求分析
- 生成 `{task_dir}/REVIEW_CHECKLIST.md` + `{task_dir}/PLAN.md` + `{task_dir}/HARNESS_PROGRESS.md`

#### Phase 1.5: 用户确认
- 展示需求理解、影响分析、任务清单、验收标准
- 等待用户确认

### 3. 自动提交规划文档后终止

1. 用户确认后立即自动提交：`git add {task_dir}/REVIEW_CHECKLIST.md {task_dir}/PLAN.md {task_dir}/HARNESS_PROGRESS.md` → `git commit -m "docs: add plan for {task-tag}"` → `git push`（worktree 推分支，主区推 main；`--no-push` 可跳过）
2. 展示 `git log --oneline -1` 与 `git status`
3. `analyze` 模式至此终止，不进入编码阶段

生成的 `{task_dir}/PLAN.md` 记录本次方案的设计决策与任务拆解，可供后续 `/build` 命令参考使用（`/build` 会在 Phase 1.5 再次提交更新后的规划文档）。
如果用户确认后想继续编码，提示使用 `/build` 命令。
