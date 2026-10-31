# 工作区整合计划

## Goal
- 在保护主区未提交 WIP 和用户证据的前提下，逐文件整合合适的研究成果，归档并退役符合条件的工作树；仅本地操作，不推送。
- 本计划是执行前的计划快照；创建计划时未执行代码、测试、提交或工作树写操作。实际执行结果与关卡偏离见同目录 `HARNESS_PROGRESS.md`。

## Architecture
- 主区是整合目标；CA 树内容已并入主区（`79cc2b7`），原树已于 2026-10-30 退役，是否进入生产仍须经语义审查及独立质量门。
- W1 fractional、attestor、ledger 和 2025 限制入口已由 `8cd25a9` 恢复进主区（`backtest/cnn_adapter/`、`scripts/`），不接默认生产路径。独立 backtest-core 的 W1 stop_after_close dirty patch 仅归档为纯文本，未并入生产。
- 原报告、QA、logs 外置产物保留原版本和时间线；另建主题索引与脚本清单，注明来源、用途、版本、运行边界和证据位置。

## KeyDecisions
- 已确认主区及三棵研究树基线均为 ce7d1c6（三树已于 2026-10-30 退役），不能靠合并提交判断内容；按路径、内容哈希和语义逐文件比较，包括未跟踪文件。
- 先冻结主区 WIP 清单与内容哈希；整合时不得覆盖或丢失，冲突须保留双方并记录裁决。主区已有 quantity_rules 与测试，先比较，内容一致才去重。
- staged_order_strategy、raw_market、corporate_action_context、runner/input 逐项审查调用链、失败模式和行为差异；来源和裁决未明则阻塞相关整合与退役。
- 每树退役前归档修改、未跟踪和逐项审阅后确定的重要 ignored 文件，建立源路径、大小、SHA-256 和恢复说明；从归档回读逐项校验后才可删除。保留 logs/KEEP、数据目录和用户证据，不执行清理。
- 独立 core 先识别实际仓库、基线和 dirty patch，完整归档其修改、未跟踪及重要 ignored，并回读验 hash；未完成则不得退役。

## Impact
- 主区：backtest/cnn_adapter、tests/unit/backtest、scripts、docs/research，以及已有主区 WIP；其余影响以盘点结果为准。
- 来源：corporate-action-fix-20261027、w1-fractional-scenarios-20261028、validation-2025-restricted-20261029 和独立 backtest-core；四树已于 2026-10-30 退役（退役记录见 `worktree_retirement_20261030/REPORT.md`）。
- 调用链重点：原始行情输入/provider → 公司行动 context → staged runner/input → strategy、执行桥及 core；核对数量规则、身份、时序和审计输出。
- 可复用项：现有 quantity_rules、staged_execution_bridge、execution_audit、相关单测和既有 QA 报告；scripts/frozen 为只读快照。

## TaskDecomposition
- T01 盘点与冻结：记录各仓库状态、基线、主区 WIP 和逐文件清单/hash；依赖无；验收：清单涵盖 tracked、untracked、ignored 分类及用户证据。
- T02 语义比较：比较三树与主区对应文件、quantity_rules 和调用链；依赖 T01；验收：差异矩阵含来源、行为、复用和冲突裁决。
- T03 分类整合：审查并整合 CA 生产候选，研究代码归档且隔离入口；依赖 T02；验收：WIP 完好、重复去除、研究代码不入默认路径。
- T04 证据与目录：整理报告、QA、脚本并建立主题索引及清单，保留原始时间线和外置产物；依赖 T01；验收：引用可回溯，未删除受保护数据。
- T05 独立质量门：由独立审查者审查最终代码、文档、脚本及必要验证证据；依赖 T03、T04；验收：问题关闭或明确阻塞，结论有冻结版本和证据。
- T06 归档与退役：逐树及独立 core 分别完整归档、回读验 hash，核实无活跃任务与未保存产物后退役可删树；依赖 T05；验收：归档清单、校验记录及退役记录齐全，失败则保留原树。**实际执行偏离**：归档与回读验 hash 未做即退役，详见 `HARNESS_PROGRESS.md`。
