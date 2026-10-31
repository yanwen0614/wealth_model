# Git worktree 生命周期只读盘点

日期：2026-10-28。范围：主仓 `D:/code/cnn_full_20260905/cnn` 的 `git worktree list` 四棵树；仅查询状态、文件清单、SHA及已有交付/QA证据。未调用 OpenChamber；未改工作树、stash/reset/切分支/提交/删除，也未编辑用户 WIP。

## 主仓与共通观察

- HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`，`main...origin/main [ahead 30]`。现有 WIP：修改 `.opencode/memory/{HISTORY,MEMORY}.md`、`backtest/cnn_adapter/staged_order_strategy.py`、`docs/research/20261026/{PARALLEL_WORKSPACES,f4_signal_delivery,state_acquisition_request_v2}.md`、`scripts/audit_walkforward_execution.py`、`tests/unit/backtest/test_staged_order_strategy.py`；未跟踪 `_check_signals.py`、`backtest/cnn_adapter/quantity_rules.py`、`tests/unit/backtest/test_quantity_rules.py`。
- 四棵树 HEAD 均为同一 `ce7d1c6`，各有独立未提交新增或修改。分支名 `openchamber/...` 只说明分支命名，不证明会话已结束。每棵当前 Git 状态不显示忽略文件，故其忽略产物/进程/会话活跃性没有被完整盘点。
- 会话状态未通过 OpenChamber 查询（按要求）。现有磁盘报告证明交付/QA历史，不足以证明会话已停止或当前无人继续修改；状态项因此按下表保守定级。建议主会话另派 lite_general 只核四个会话状态、最近 owner 活动和运行进程，再更新生命周期结论。

## 逐树判定

| 树 / 分支 | 状态与未提交文件 | 整合 / QA | 建议状态 |
|---|---|---|---|
| `.../board-quantity-rules-20261027` / `openchamber/board-quantity-rules-20261027` | 修改 `staged_order_strategy.py`、对应测试；新增 `quantity_rules.py`、对应测试。当前四文件 SHA 与主仓四文件逐一相同（分别 `d88ed93a…`、`4101d8af…`、`414855dd…`、`d391b88c…`）。 | `quantity_rules_main_integration_20261027/INTEGRATION_REPORT.md` 记录四文件从源精确移植、18项测试通过；`board_quantity_rules_independent_qa_20261027/.../QA_REPORT.md` 冻结版 PASS（307项、Ruff、Pyright）。独有 QA/RED 日志仍在 temp 归档。 | **needs preservation**；代码层面可候选 safe-to-retire，但当前会话状态/忽略产物未知。退役前先由 lite_general 确认 owner 已停、归档交付与 QA 日志，并复核主仓 WIP 无后续改动。不可仅因精确复制就删除。 |
| `.../corporate-action-context-20261027` / `openchamber/corporate-action-context-20261027` | 新增 context、snapshot loader 及两份测试（SHA 依次 `8af7729f…`、`c4820ab4…`、`e14ad259…`、`b78000ce…`）；状态未跟踪。用户告知此树此前重启会话后修改，按要求不得按旧状态视作废弃。 | 主仓未见这四个路径。较早独立 QA 报告标旧冻结版 FAIL，检测外部改动冲突；fix1 新树 QA PASS（37项），且报告明确“不读取或修改旧工作树”。故不能把 fix1 PASS 归到此树，也不能声称精确复制。该树与旧 QA 冲突文件 hash 不同；会话重启后的差异无当前 owner 说明。 | **active / needs preservation**（重启后活动由用户提供；当前是否仍运行未知）。明确禁止退休/覆盖。先由 lite_general 查询会话与 owner，再比较四文件与 `corporate_action_context_delivery_20261027/fix1` 冻结清单，保存树内唯一版本、diff、日志/忽略产物；即使相同也需确认会话终止后再评估。 |
| `.../staged-runner-v2-20261027` / `openchamber/staged-runner-v2-20261027` | 新增 `staged_candidate_runner.py`、对应测试（SHA `939a3cc6…`、`f8468d13…`）。 | 主仓有同路径 runner 与测试，但 SHA 分别为 `cee60d04…`、`0e1e1817…`，不是精确复制；主仓另有 `staged_production_inputs.py` 与测试。独立 `staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md` PASS 针对整合树16文件，非本树独立 QA。未找到本树专属 QA 报告。 | **needs preservation / unknown**。不是“精确复制且独立 QA”的可退役树；保留两文件 SHA/diff、owner 交付记录与本树产物。须查会话状态，并确认整合树实现是否吸收其语义而非仅同名后，才能考虑归档。 |
| `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027` / `research/corporate-action-fix-20261027` | 修改 `raw_market_inputs.py`、`raw_market_provider.py`、`staged_order_strategy.py` 与三份测试；新增 context、loader、quantity rules、runner、production inputs 及五份测试（总计13个变更路径）。相关 SHA 已采集，且部分文件与主仓或其它树同 SHA、部分不同。 | `staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md` 记录16/16冻结 hash 匹配、378 backtest测试（2 skip）、109定向测试、Ruff/Pyright通过；这证明整合树版本的 QA，不足以证明当前 fix 树与整合树所有变更精确相同。项目记忆记载该树未提交。独有实现与研究文档仍在树中。 | **needs preservation / unknown**。主仓已吸收其中多个实现但该树有独有/改动内容；生命周期状态未经会话核对。保存完整 diff、13文件版本及 `research/` 等产物，检查与 `SOURCE_HASHES_FINAL.json` 的逐文件对应和忽略文件后才可决定是否归档。 |

## 风险与后续核验

- `git status` 对每树显示的未提交路径见上表；工作树 status 命令未显示已暂存项。该检查不覆盖 ignored/untracked-excluded 文件、运行进程、会话状态和外置产物，不能据此声明“无唯一产物”。
- 唯一产物证据：board 独立 QA/RED/GREEN 证据仅在 temp QA 归档；corporate context 的旧版本 QA、fix1 交付/QA分属不同目录与版本；staged runner 没找到独立 QA；整合工作树带有大批机械回测输入、执行日志与 SOURCE_HASHES。上述证据不能随意删，尤其整合树的输入/日志不等同于其源码树，可独立保留但须核清引用关系。
- 盘点没有任何一棵树满足“会话确认已结束 + 所有用户WIP/唯一产物已归档 + 精确交付核验”的完整退休门槛。没有树被判定为现在可删除。对 corporate-action-context 树应用最严格保全：用户明确告知重启后改动，旧 QA 的冲突记录也要求不覆盖 owner 改动。
- 下一步只建议主会话派 lite_general 查询会话状态，不让其写代码；取得状态后，再由主会话逐树做文件哈希、ignored 文件/进程/外置产物清单与归档决策。本报告不执行这些清理或归档动作。
