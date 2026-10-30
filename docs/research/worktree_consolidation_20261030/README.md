# CA 整合树索引与退役后状态（2026-10-30）

范围：原 `corporate-action-fix-20261027` 工作树的代码收口；本文档只记录可审代码与材料索引，不运行历史账户。
本文档本身已随该树唯一提交 `79cc2b7`（"收口CA候选运行与研究索引"）合并入主区，合并提交为 `997bc71`；外置报告均为只读证据，不随提交复制或改写。

## 工作树退役结果

- 三棵 CNN 研究工作树已删除，worktree 与 `research/*` 分支一并删除，ZIP 归档也按指示删除、未保留：
  `corporate-action-fix-20261027`、`w1-fractional-scenarios-20261028`、`validation-2025-restricted-20261029`。
- 主区现在只有 `D:/code/cnn_full_20260905/cnn`，分支仅 `main` 与 `feature/rolling-normalization-cnn`；退役当时 HEAD 为 `997bc71`，其后有恢复与收口提交，当前值以 `git log --oneline -1` 为准。
- 因此下文不再使用原 worktree 相对路径作为追溯方式：已合并项按主区路径引用；退役时未合并、但事后已由会话数据库恢复并入库的研究源码，也按主区路径引用，并单独标注恢复提交。

## 主区已提交、可复用

以下 6 个生产候选模块与 6 个对应测试已随 `79cc2b7` 进入主区 `backtest/cnn_adapter/` 与 `tests/unit/backtest/`：

- 原始行情通用层：`raw_market_inputs.py`、`raw_market_provider.py` 及 `test_raw_market_inputs.py`、`test_raw_market_provider.py`。
- CA 上下文：`corporate_action_context.py`、`corporate_action_snapshot_loader.py` 及对应两个测试。
- 单窗候选 core 运行器：`staged_candidate_runner.py` 与 `test_staged_candidate_runner.py`。
- 冻结输入准备/编排：`staged_production_inputs.py` 与 `test_staged_production_inputs.py`。
- 以上只属于机械模块候选；生产来源血缘、权威日历、CA 实际实施/税务、官方碎股规则和绩效尚未签收。所有结果须保留 `INCOMPLETE`/`BLOCKED`，`actual_after_tax_target_eligible=false`。

主区 `quantity_rules` 已入库（不再有未跟踪 WIP）：

- `backtest/cnn_adapter/quantity_rules.py` 与 `tests/unit/backtest/test_quantity_rules.py` 曾为未跟踪文件，现由提交 `ab1138b`（补齐 quantity_rules 模块及其接线，4 文件）入库。
- `backtest/cnn_adapter/staged_order_strategy.py` 与对应测试中的 `quantity_rule_resolver` 接线随同一提交入库，不再是未提交修改。
- `.opencode/memory/*` 为会话记忆更新，不在本次代码收口范围内。

## 事后恢复的 W1 / 2025 研究源码（不再丢失）

退役时这两条研究线的源码确未进入任何 Git 提交，树与 ZIP 均已删除。但退役前的会话记录保存在 `C:\Users\yanwen\.local\share\opencode\opencode.db`，恢复代理以只读方式从 `read` 文件快照重建全部 18 个目标文件，提交 `8cd25a9`（6382 行新增），逐字节比对 MANIFEST 为 18/18 一致。`ff7e606` 随后为 `run_2025_restricted.py` 加 `# noqa: I001` 以守住 CI 零告警（不改导入顺序/语义）。恢复证据见 `C:/Users/yanwen/AppData/Local/Temp/opencode/recovered_w1_20261030/`。

现在可按主区路径查阅：

- `backtest/cnn_adapter/fractional_scenarios.py`、`fractional_prefix_gate.py`、`fractional_scenario_cli.py`。
- `backtest/cnn_adapter/prefix_attestor.py`、`prefix_ledger_verifier.py`。
- `backtest/cnn_adapter/validation_2025_bridge.py`、`validation_2025_execution.py`。
- `scripts/run_2025_ab_execution.py`、`scripts/run_2025_restricted.py`。
- 对应测试：`test_fractional_scenarios.py`、`test_prefix_attestor.py`、`test_prefix_ledger_verifier.py`、`test_validation_2025_bridge.py`、`test_validation_2025_execution.py`、`test_2025_restricted.py`、`test_2025_restricted_fix2.py`、`test_2025_restricted_fix3.py`、`test_ca_evidence_adapter.py`。

这些模块与脚本仍然不属于生产默认 backtest 包，该判断不变。**恢复 ≠ 可用**：恢复出的是 2026-10-29 08:00 会话被中止时的真实未完成状态。按主区当前 HEAD 实测：`test_fractional_scenarios` 为 OK(skipped=7)——其中 7 个用例依赖未回收的 W1 版接口，是**跳过而非通过**；`test_prefix_attestor`/`test_prefix_ledger_verifier` 各 1 error；`test_2025_restricted*` 与 `test_ca_evidence_adapter` 因缺 `staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json` 与 `validation_2025_local_inputs_20261029/ca_full174/delivery_manifest_v4.json` 报 `FileNotFoundError`；`test_validation_2025_bridge`/`test_validation_2025_execution` 全绿。运行 W1 条件模拟还需 8 个**未回收**的 W1 版依赖接口（`staged_candidate_runner`、`staged_production_inputs`、`corporate_action_context`、`historical_costs`、`staged_order_strategy`、`raw_market_provider`、`raw_market_inputs`、`corporate_action_snapshot_loader`；主区同名模块已入库，但 W1 版接口 `git log --all` 0 命中、`raw_patches/` 621 补丁不含）。`prefix_attestor.py` 的 pin 在删除前已陈旧（冻结于 07:00，被 pin 文件 07:58 被改），两个 pin 世代互相矛盾，不能同时成立。因此研究性 2025 bridge/execution 入口与 W1 fractional/attestor/prefix 入口**当前仍不可按原样执行**；证据结论仍以只读报告为准，不因源码恢复而升级，也不因 `436cb73` 让 `test_fractional_scenarios` 变为 OK 而升级（skip ≠ pass）。

## 研究结论的约束（继续生效）

- 原 bridge QA 的三文件 SHA 身份 FAIL；fix1 修正后未见可确认的独立最终身份 PASS。
- 即使将来重建等价实现并显式研究调用，标签仍为 `IDENTITY_LOCAL`、`PIT_UNPROVEN`、`INCOMPLETE`；缺源不得启动 core。
- 没有 2025 A/B NAV，不能据代码或报告推断策略结果。

## 外置审查与运行证据（只读）

以下路径均相对 `C:/Users/yanwen/AppData/Local/Temp/opencode/`；目录为审查时冻结版本，不能自动代表后续源码身份，也不是可运行代码。

- CA context：`corporate_action_context_independent_qa_20261027/reverify1/REPORT.md` + `SHA_AFTER.json`；fix1 机械模块 PASS，37 项、Ruff、定向 Pyright PASS；真实税后 BLOCKED。
- Runner：`staged_runner_independent_qa_20261027/reverify1/REVERIFY_REPORT.md`；87 项、Ruff、定向 Pyright PASS；生产仍 BLOCKED，source-known/日历/CA/数量资格未闭合。
- 整合：`staged_integration_independent_qa_20261028/QA_REPORT.md` 与 `reverify1/QA_REPORT.md`；后者撤回退出日志 P1，确认准备产物绑定；`source_known=false`、真实绩效未运行。
- 2025 bridge：`validation_2025_bridge_independent_qa_20261029/REPORT.md`（身份 FAIL、mini 有条件 PASS、INCOMPLETE）；`validation_2025_bridge_fix1_20261029/REPORT.md`（199 项等为交付方记录，真实年测未跑）。
- 2025 边界：`validation_2025_bridge_delivery_20261029/REPORT.md`、`validation_2025_data_preflight_20261029/REPORT.md`、`validation_2025_ca_two_event_audit_20261029/REPORT.md`、`validation_2025_ca_evidence_adapter_20261029/REPORT.md`、`validation_2025_ab_v2_abort_audit_20261029/REPORT.md`；均不提供完整绩效许可。
- W1 材料：`w1_fractional_scenarios_independent_qa_20261028/`、`w1_fractional_scenarios_delivery_20261028/EXECUTION_REPORT.md`、`w1_prefix_fix5_20261028/`、`w1_dual_core_identity_fix3_20261029/`、`w1_prefix_independent_qa_20261028/`、`w1_dual_core_identity_independent_qa_20261029/`、`w1_real_prefix_exploration_20261029/REPORT.md`、`w1_real_prefix_independent_audit_20261029/REPORT.md`、`w1_ceil_precision_independent_qa_20261029/REPORT.md`；可信 prefix/真实绩效仍 BLOCKED，分支结果 INCOMPLETE。
- CA 研究结论另见仓内 `docs/research/20261026/corporate_action_tax_tdd_plan.md`、`staged_order_strategy_delivery.md`、`ENGINEERING_STATUS.md`；单窗模块通过不等于运行器/策略验收。

## 脚本索引

研究脚本与证据的完整分类（可复用 / 已恢复源码但接口未齐 / 仅只读证据）见 [`scripts/research/README.md`](../../../scripts/research/README.md)。该文档同样已随 `79cc2b7` 合入主区；源码恢复后索引为状态说明，指明哪些能读、哪些还跑不通。
