# 研究脚本与证据索引

本清单记录显式研究工具及其当前状态。没有一个条目是默认生产 backtest 入口。2026-10-30 工作树退役时，一部分研究源码确未入库、随树删除；但其中 18 个文件已事后从会话数据库 `opencode.db` 快照恢复并随提交 `8cd25a9` 入库。本清单区分「已恢复但还跑不通」与「仅只读证据」，不把「源码可查」写成「工具链可用」。
外部材料路径均相对 `C:/Users/yanwen/AppData/Local/Temp/opencode/`；这些目录只是只读证据（报告、日志、清单），
不等于可运行代码，也不等于当前源码身份。

## 2026-10-30 工作树退役后的资产状态

2026-10-30 三棵 CNN 研究工作树已删除，worktree 与 `research/*` 分支一并删除，未生成也未保留任何 ZIP 归档：

- `corporate-action-fix-20261027`
- `w1-fractional-scenarios-20261028`
- `validation-2025-restricted-20261029`

主区现在只有 `D:/code/cnn_full_20260905/cnn`，分支仅 `main` 与 `feature/rolling-normalization-cnn`；退役当时 HEAD 为 `997bc71`，其后有恢复与收口提交，当前值以 `git log --oneline -1` 为准。资产分四类：

- 可复用：已随合并提交进入主区、可直接按主区路径引用并可运行的模块（见「主区已提交模块」）。
- 已恢复但接口未齐：源码已由 `8cd25a9` 入库、可查阅可演进，但缺 W1 版依赖导致按当前 HEAD 跑不通（见「已恢复的 W1 / 2025 研究源码」）。
- 确实无法回收：8 个 W1 版依赖模块，`git log --all` 0 命中，`raw_patches/` 621 补丁不含（见同节末）。
- 仅只读证据：外置审查/交付目录中的报告与日志仍在，是时间点冻结结论，与已入库源码互为交叉校验。

## 已恢复的 W1 / 2025 研究源码（可查阅，但当前跑不通）

恢复代理以只读方式访问 `C:\Users\yanwen\.local\share\opencode\opencode.db`，以 `read` 文件快照为字节级基线、重放其后变更事件，重建全部 18 个目标文件，提交 `8cd25a9`（6382 行新增），逐字节比对 MANIFEST 为 18/18 一致；`ff7e606` 再为 `run_2025_restricted.py` 加 `# noqa: I001` 守 CI 零告警。证据目录 `recovered_w1_20261030/`（`MANIFEST.json`/`REPORT.md`/`raw_patches/`/`recovered/`）。

已入库、可按主区路径查阅的源码：

- `backtest/cnn_adapter/fractional_scenarios.py`
- `backtest/cnn_adapter/fractional_prefix_gate.py`
- `backtest/cnn_adapter/fractional_scenario_cli.py`
- `backtest/cnn_adapter/prefix_attestor.py`
- `backtest/cnn_adapter/prefix_ledger_verifier.py`
- `backtest/cnn_adapter/validation_2025_bridge.py`
- `backtest/cnn_adapter/validation_2025_execution.py`
- `scripts/run_2025_ab_execution.py`
- `scripts/run_2025_restricted.py`

对应测试同样已入库：`test_fractional_scenarios.py`、`test_prefix_attestor.py`、`test_prefix_ledger_verifier.py`、
`test_validation_2025_bridge.py`、`test_validation_2025_execution.py`、`test_2025_restricted.py`、
`test_2025_restricted_fix2.py`、`test_2025_restricted_fix3.py`、`test_ca_evidence_adapter.py`。

**恢复 ≠ 可用。** 恢复出的是 2026-10-29 08:00 会话被中止时的真实未完成状态。按主区当前 HEAD 实测：`test_fractional_scenarios` 为 OK(skipped=7)——7 个用例依赖 W1 版 `staged_candidate_runner`/`staged_production_inputs` 接口（`fractional_scenario` 参数、prefix proof 前置门禁、`--prefix-stop-after-close`/`--information-cutoff` CLI），被显式 `@unittest.skip`，属**跳过而非通过**；`test_prefix_attestor` 1 error、`test_prefix_ledger_verifier` 1 error（pin 陈旧，删除前冻结于 07:00、被 pin 文件 07:58 被改；两个 pin 世代互相矛盾）；`test_2025_restricted*` 与 `test_ca_evidence_adapter` 全部报错，形态是运行期 `FileNotFoundError`（按绝对路径读已退役树或只在 `Temp/opencode` 下的契约文件；具体缺失项随工作区改动而变，以实时运行输出为准）。`test_validation_2025_bridge`(17)/`test_validation_2025_execution`(4) 全绿。

**确实无法回收的 8 个 W1 版依赖模块**（缺它们就无法跑 W1 条件模拟）：`staged_candidate_runner`、`staged_production_inputs`、`corporate_action_context`、`historical_costs`、`staged_order_strategy`、`raw_market_provider`、`raw_market_inputs`、`corporate_action_snapshot_loader`。区分要点：主区现有同名模块**已入库可复用**，但 W1 树上的**那版接口**在 `git log --all` 0 命中、`raw_patches/` 621 补丁中无记录。不得把主区版本套上 W1 名号后声称 W1 工具链已恢复。这些脚本仍全部不属于生产默认 backtest 入口。

## 主区已提交模块（可复用）

以下 6 个生产候选模块已合并入主区 `backtest/cnn_adapter/`，可直接按主区路径引用；对应 6 个测试同步在 `tests/unit/backtest/`：

- 原始行情通用层：`raw_market_inputs.py`、`raw_market_provider.py`。
- CA 上下文：`corporate_action_context.py`、`corporate_action_snapshot_loader.py`。
- 单窗候选 core 运行器：`staged_candidate_runner.py`。
- 冻结输入准备/编排：`staged_production_inputs.py`。

入口与证据：

- 输入准备入口：`python -m backtest.cnn_adapter.staged_production_inputs --prepare-only ...`；需完整的显式输入配置，并写入新的输出目录。
- 单窗运行入口：`python -m backtest.cnn_adapter.staged_candidate_runner ...`；属候选 API/CLI，门禁显式标注为未闭合，不能当作默认策略结论。
- 模块证据：`corporate_action_context_independent_qa_20261027/reverify1/REPORT.md`、`staged_runner_independent_qa_20261027/reverify1/REVERIFY_REPORT.md`、`staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md`。机械 PASS 有边界；来源血缘与真实业绩仍未签收。

## 仅只读证据（时间点冻结结论）

下列报告记录的是当时行为与审查结论，本身不是源码，也不能据此重跑；对应源码已由 `8cd25a9` 恢复到主区，但与报告所述状态并不等价，不能互相替代：

- 2025 边界：`validation_2025_bridge_independent_qa_20261029/REPORT.md`（身份 FAIL）、`validation_2025_bridge_fix1_20261029/REPORT.md`（fix 记录与 199 项定向测试，无独立最终身份验收）、`validation_2025_bridge_delivery_20261029/REPORT.md`、`validation_2025_data_preflight_20261029/REPORT.md`、`validation_2025_ca_two_event_audit_20261029/REPORT.md`、`validation_2025_ca_evidence_adapter_20261029/REPORT.md`、`validation_2025_ab_v2_abort_audit_20261029/REPORT.md`。均无年度 A/B NAV，须继续保留 `IDENTITY_LOCAL`、`PIT_UNPROVEN`、`INCOMPLETE` 与 `actual_after_tax_target_eligible=false`。
- W1 fractional：QA `w1_fractional_scenarios_independent_qa_20261028/`、交付 `w1_fractional_scenarios_delivery_20261028/EXECUTION_REPORT.md`。floor/ceil 结果与覆盖不完整，官方配售/PIT 证明缺失。
- W1 prefix/attestor：`w1_prefix_fix5_20261028/`、`w1_dual_core_identity_fix3_20261029/`、`w1_prefix_independent_qa_20261028/`、`w1_dual_core_identity_independent_qa_20261029/`。可信 pin 仍未设定，真实多路径证明与业绩 BLOCKED。
- W1 真实前缀/ceil：`w1_real_prefix_exploration_20261029/REPORT.md`、`w1_real_prefix_independent_audit_20261029/REPORT.md`、`w1_ceil_precision_independent_qa_20261029/REPORT.md`。记录为 INCOMPLETE，无生产证明。

## 冻结的无关研究报告（主区路径）

以下内容原位于 `corporate-action-fix-20261027` 树内，该树删除后一律改用主区或外置证据路径，不再引用原 worktree 路径：

- 历史基线：主区快照 `research/goal/REPORT.md`（READ ONLY，ruff 已 exclude）与 `research/goal_repro/REPORT.md`（2026-09-28 复现）；两者都不是 CA/W1/2025 验收材料。
- 整合状态与 CA 范围：`docs/research/20261026/ENGINEERING_STATUS.md`、`corporate_action_tax_tdd_plan.md`、`staged_order_strategy_delivery.md`。
- 合并决策、排除文件与源码状态：[`docs/research/worktree_consolidation_20261030/README.md`](../../docs/research/worktree_consolidation_20261030/README.md)。该文档已随 `79cc2b7` 合并入主区；源树已删除且未归档，但其研究源码已事后恢复入库（`8cd25a9`）。
