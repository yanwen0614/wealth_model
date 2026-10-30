# Worktree 退役记录（2026-10-30）

执行者：主会话唯一 owner。用户指示：**合并删除的树不需压缩存档，直接删除**。

## 前置状态

- 主区 HEAD `997bc717`（merge commit，父 `ce7d1c6` + `79cc2b7`）。
- 唯一合并的提交：`79cc2b71331a70af59ea8d1eaf652800887b460c`，14 路径（6 源码 + 6 测试 + 2 索引 README）。
- 独立质量门对 `79cc2b7` 复核 PASS：91 定向测试 / Ruff / 定向 Pyright 0 errors；TDD 按任务范围记 `skipped`（无新行为实现），未虚构 RED/GREEN。
- 主区 8 个已修改 + 6 个未跟踪 WIP 路径在合并前后完全一致，未被暂存或提交。

## 已删除的工作树

| 树 | 分支 | HEAD | 处置 |
| --- | --- | --- | --- |
| corporate-action-fix-20261027 | research/corporate-action-fix-20261027 | `79cc2b7` | 已提交内容已合并进主区；未提交研究代码按用户指示不存档直接删除 |
| w1-fractional-scenarios-20261028 | research/w1-fractional-scenarios-20261028 | `ce7d1c6` | 分支无提交，内容全部为未提交研究材料；按指示直接删除 |
| validation-2025-restricted-20261029 | research/validation-2025-restricted-20261029 | `ce7d1c6` | 分支无提交，内容全部为未提交研究材料；按指示直接删除 |
| backtest-core-w1-stop-20261028 | research/w1-prefix-stop-core-20261028 | `893fc96`（补丁未提交） | 树已删除；未合并的 `stop_after_close` 补丁单独保留为纯文本 |

四个分支均以 `git branch -d` 删除（未用 `-D`），工作树以 `git worktree remove --force` 删除并确认目录不存在。

## 唯一保留的非树产物

- `C:/Users/yanwen/AppData/Local/Temp/opencode/w1_stop_after_close_20261030.patch`
  - 8,143 字节，SHA-256 `D13E06BB908233510F9C919FD4E16D977A167C2F39F2A792D62AAC46C5FDFE3B`，145 行。
  - 内容：`src/backtest_core/engine/account_runner.py` + `tests/test_account_orders.py` 两个文件的完整二进制 diff。
  - 基线：core 仓库 HEAD `893fc96925e029098f6c758dba8724d187c6b512`。
  - 可恢复性已验证：在 `D:/code/cnn_full_20260905/backtest-core`（同基线）执行 `git apply --check` 返回 0，可干净重建。
  - 保留原因：这是唯一未进入任何提交的工作（主 core 的 `main` 尚无 `stop_after_close` 实现），删除即不可恢复。

## 已清理的占用

- 删除时发现遗留 tmux 会话以这些目录为 cwd 锁定句柄。逐个核对 `pane_dead=1` 且退出码为 0（任务已正常结束，仅空闲 shell 占目录），确认无运行中任务后才 kill-session。
- 其中 `cnn_2025_ab_restricted_v1` 实为 2025 A/B 真实回放会话，`runner_exitcode=0`、`runner_status=EXITED_0`，其结果保存在 `validation_2025_ab_real_20261029_v1/run_status.json`（A/B 均 `NOT_EVALUABLE`、`INCOMPLETE`、`main_end_nav=null`）。
- 未终止任何正在运行的进程。

## 未做与未触及

- 未触碰主区任何用户 WIP；未 stash/reset/checkout/restore/clean；未推送。
- 外置审查/证据目录（`*_independent_qa_*`、`*_delivery_*`、`*_real_*` 等）全部保留原位，未删除。
- 本轮先前生成的 ZIP 归档与辅助脚本已按用户指示删除，不再保留压缩副本。

## 当前状态

- `git worktree list`：仅剩主区 `D:/code/cnn_full_20260905/cnn 997bc71 [main]`。
- core 仓库：仅剩主区 `D:/code/cnn_full_20260905/backtest-core 893fc96 [main]`。
