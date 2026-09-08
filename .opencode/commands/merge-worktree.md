---
description: 合并 worktree 到 main - 先 squash 唯一 commit，验证文档后 amend，再把 main 合并进 worktree 后合并回 main（quant-model 兼容 cnn-harness）
agent: build
---

三步工作流：脚本在 worktree 内 squash → agent 审查并验证文档 → 脚本 amend 并完成双向合并。

> **与 /build 协同（quant-model 兼容 cnn-harness）**：`/build` 已在 worktree 自动 `git commit + push`（分支，前缀 `cnn_`），`--prepare` 仍会 squash 为唯一 `wip:` commit；`/build` 在 worktree 不做归档，归档唯一由 `--finish` 完成（幂等：已在 `*_archive` 则跳过）。底层由 quant-model（别名 cnn-harness）流水线驱动。

## 核心流程（与旧版差异）

| 步骤 | 位置 | 执行者 |
|------|------|--------|
| 1. 全部改动 squash 为唯一 commit | worktree 内 | 脚本 `--prepare` |
| 2. 审查 commits + 验证/更新任务文档与代码文档 | worktree 内 | Agent |
| 3. 归档 task 文档 + amend commit（并入文档更新） | worktree 内 | 脚本 `--finish` |
| 4. 把 main 合并进 worktree（更新分支基线） | worktree 内 | 脚本 |
| 5. 把 worktree 合并回 main | 主工作区 | 脚本 |
| 6. 清理 worktree 与分支 | 主工作区 | 脚本 |

## Phase 1: Prepare（脚本）

```bash
scripts/merge_worktree.sh <branch-name> --prepare
# 分支名示例：cnn_20250903_add-parquet-cache
```

如果不确定分支，先查看现有 worktrees：

```bash
git worktree list
```

`--prepare` 会：
1. 切换到 worktree 的目标分支（`cnn_*`）
2. 提取分支独有 commits 写入 `tmp/merge_commit_msg_*.txt`（**squash 之前捕获**）
3. 将 worktree 内全部改动（含未提交）squash 为一个 `wip:` commit
4. 排除 `.venv` 符号链接
5. 输出候选文件（含 commits 列表 + agent 验证清单）

## Phase 2: Agent 审查与文档验证

1. 审查 `tmp/merge_commit_msg_*.txt`，确定最终语义化 commit message
2. **验证 worktree 的主要任务文档**（`docs/agent/task/*`）是否已更新、可归档（`--finish` 会自动归档；`/build` 在 worktree 仅标注「待合入归档」，此处为唯一归档点）
3. **验证代码说明文档、注释是否已更新**；没有则立即更新
4. 以上文档改动**不要 commit**——`--finish` 会 amend 进唯一 commit
5. 幂等：若 `docs/agent/task/{tag}` 已不存在且 `task_archive/{tag}` 已存在，视为已归档，跳过 `git mv`

## Phase 3: Finish（脚本）

```bash
scripts/merge_worktree.sh <branch-name> --commit-msg "fix: description" --finish
```

`--finish` 会：
1. 校验 prepare 已执行（squash 标记存在）且 HEAD 位于 merge-base 之后
2. 归档匹配的 `docs/agent/task/` 目录到 `docs/agent/task_archive/`（幂等：已归档则跳过；`/build` worktree 场景的 task 首次在此归档）
3. `git add -A && git commit --amend -m "..."`（归档 + 文档更新并入唯一 commit）
4. 把 main 合并进 worktree（`git merge origin/main`）
5. 合并回 main（`git pull` + `git merge <branch>`）
6. 清理：删除 worktree、删除分支、清理临时状态文件
7. 展示最终 git log 与剩余 worktrees

## 冲突处理（--continue）

步骤 4「main 合并进 worktree」冲突时脚本会中止并打印指引。在 worktree 内解决冲突：

```bash
git -C <worktree-path> status                     # 查看冲突文件
# 手动编辑解决冲突
git -C <worktree-path> add <file>                 # 暂存解决后的文件
git -C <worktree-path> commit --no-edit           # 完成合并提交
scripts/merge_worktree.sh <branch-name> --continue
```

`--continue` 会校验 worktree 内已无未完成合并（`MERGE_HEAD`），然后跳过 amend/归档直接完成「合并回 main + 清理」。

## Notes

- 脚本自动解析 worktree 路径（分支名 `cnn_*` → `.worktrees/*/` 或 `../cnn_*`）
- `--prepare` / `--finish` 拆分的意义：commit message 与文档更新需要语义审查，无法完全自动化
- 如果 worktree 已被手动删除，运行 `git worktree prune`
- **`.venv` / `.env` 处理**：worktree 中的 `.venv` 和 `.env` 是符号链接，指向主分支的路径，不合并回 `main`。脚本在 prepare（squash 前）和 finish（amend 前）自动排除。
