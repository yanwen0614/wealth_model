# 多代理隔离与合入规则

用户要求：每个工作区只允许一个编码代理修改，主会话控制向主工作区合入。

## 写入边界

- 编码代理使用独立Git worktree；不以“负责不同文件”替代工作区隔离。
- 共享主区由主会话统一管理；其他代理仅做冻结版本的只读审查。
- 所有代理禁止在共享主区执行stash、reset、切分支、批量restore、clean等操作。
- Git stash跨worktree共享，不能用于隔离并行任务。
- 每个worktree独立索引、依赖环境及产物目录；不共用可写venv，不并行更新同一wheel或锁文件。
- 审查记录源码版本或文件hash；冻结后才能运行独立质量门。

## 工作树记录

- 仓库：backtest-core。
- 分支：`openchamber/core-baseline-20261026`。
- 路径：`C:/Users/yanwen/.local/share/opencode/worktree/a3bebebafa6efc3e2a8265f962f0283cc57f50b6/core-baseline-20261026`。
- 唯一编码owner：`ses_e88eb5f7bffepQGeYHK5o7o7EI`，GPT-6 Luna。
- 已导入主区18个已跟踪改动和2个新文件；差异及blob核验一致，原主区WIP原样保留。
- 独立venv通过离线locked安装，以copy模式隔离，不链接主区环境。
- 基线、观察器及限价批次均已合入core main（最终893fc96）。2026-10-27 09:53已保存记忆差异和历史记录，移除该工作树与临时分支；此路径已退休，不再作为活跃编码目录。

### CNN分批桥接工作树

- 分支：`openchamber/staged-bridge-20261026`，基线`3fa7f9b`。
- 路径：`C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/staged-bridge-20261026`。
- 唯一编码owner：`ses_e88a8c46cffeT5Rm5PheHh6ny6`，GPT-6 Luna。
- 离线缓存不含torch原始wheel，使用已安装主环境的只读快照复制到私有site-packages；不是共享venv软链。
- Python、Torch、core包路径均核验在私有venv，21项原分批测试及目标Ruff/Pyright通过。
- 先实现权威快照同步/周期终止规则；实际core协议仅在公开契约冻结后接入，不引用其它代理可变源码。

## 合入流程

1. owner完成修改和验证后冻结，交确切文件范围、diff、hash及质量门证据。
2. 只读QA针对冻结worktree审查；需要修复时交回唯一owner。
3. 主会话审查并提交分支产出，核对主区现有WIP与冻结交接基线后处理合入。
4. 不通过stash或清空主区隐藏冲突；遇到重叠修改逐项核对，保留其他任务产物。
5. 合入后主会话复验受影响路径，再构建对应wheel/锁文件；未经授权不push。

本地HDF盘点只读源数据，脚本及结果写独有临时目录；不得修改仓库或共享缓存。

## 收尾与清理

- 任务结束必须明确决定“合入后清理”或“放弃后清理”，不长期保留无用途工作树；主会话统一处理。
- 先核对工作树状态、活跃代理/进程及所有未跟踪或忽略产物，保存必要的代码、权重、日志、QA和身份清单，再移除工作树及临时分支。
- cherry-pick合入用补丁等价及文件内容验证；需要保留原提交身份时先保存并验证Git bundle。未合入的必要记忆差异可导出Git补丁，不混入业务提交。
- 清理仅针对已完成且已交接的独立树；不误删活跃任务、未提交成果、原权重或唯一数据；不以stash/reset/restore/clean绕过检查。
- 2026-10-27 09:53，checkpoint修复树（原6a90a3b，合入b747f56）及上述core树已清理；归档位于临时根 `worktree_retirement_20261027/`。
- W2树仍存原模型/训练日志；策略、来源修复、采集及运行器树仍待合入或交接，暂保留并逐项收尾，不视为永久保留许可。
