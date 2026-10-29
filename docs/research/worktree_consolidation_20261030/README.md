# CA 整合树索引（2026-10-30）

范围：`corporate-action-fix-20261027`；仅收口可审代码与材料索引，不运行历史账户。
源码身份以该 worktree 提交时的 Git tree 为准；外部报告均为只读证据，不随提交复制或改写。

## 本次 production-candidate changeset

- 原始行情通用层：`backtest/cnn_adapter/raw_market_inputs.py`、`raw_market_provider.py` 及 `tests/unit/backtest/test_raw_market_inputs.py`、`test_raw_market_provider.py`。
- CA 上下文：`corporate_action_context.py`、`corporate_action_snapshot_loader.py` 及对应两个测试。
- 单窗候选 core 运行器：`staged_candidate_runner.py` 与 `test_staged_candidate_runner.py`。
- 冻结输入准备/编排：`staged_production_inputs.py` 与 `test_staged_production_inputs.py`。
- 以上只属于机械模块候选；生产来源血缘、权威日历、CA 实际实施/税务、官方碎股规则和绩效尚未签收。所有结果须保留 `INCOMPLETE`/`BLOCKED`，`actual_after_tax_target_eligible=false`。
- 依赖 `quantity_rules.py` 与 `staged_order_strategy.py` 的接口；两者及对应测试不在本次提交，主区已有同名实现，strategy 存在 W1 差异，合并前须由主会话核对。

## 研究封存与不纳入默认入口

- `validation_2025_bridge.py`、`validation_2025_execution.py`、`tests/unit/backtest/test_validation_2025_bridge.py`、`test_validation_2025_execution.py`、`scripts/run_2025_ab_execution.py`：留在当前树未提交研究代码；不接入生产默认 backtest 包。原 bridge QA 的三文件 SHA 身份 FAIL；fix1 修正后未见可确认的独立最终身份 PASS。
- 即使显式研究调用，标签仍为 `IDENTITY_LOCAL`、`PIT_UNPROVEN`、`INCOMPLETE`；缺源不得启动 core。没有 2025 A/B NAV，不能据代码验证推断策略结果。
- `quantity_rules.py`/测试、`staged_order_strategy.py`/测试以及 `.opencode/memory/*`：本提交排除；保留原树状态，不搬动、不覆盖。
- W1 fractional、attestor、prefix 与 2025 restricted/adapter 脚本不进入 `backtest` 默认包。索引见 [`scripts/research/README.md`](../../../scripts/research/README.md)，按原 worktree 相对路径追溯。

## 外置审查与运行证据

以下路径均相对 `C:/Users/yanwen/AppData/Local/Temp/opencode/`；目录为审查时冻结版本，不能自动代表后续源码身份。

- CA context：`corporate_action_context_independent_qa_20261027/reverify1/REPORT.md` + `SHA_AFTER.json`；fix1 机械模块 PASS，37 项、Ruff、定向 Pyright PASS；真实税后 BLOCKED。
- Runner：`staged_runner_independent_qa_20261027/reverify1/REVERIFY_REPORT.md`；87 项、Ruff、定向 Pyright PASS；生产仍 BLOCKED，source-known/日历/CA/数量资格未闭合。
- 整合：`staged_integration_independent_qa_20261028/QA_REPORT.md` 与 `reverify1/QA_REPORT.md`；后者撤回退出日志 P1，确认准备产物绑定；`source_known=false`、真实绩效未运行。
- 2025 bridge：`validation_2025_bridge_independent_qa_20261029/REPORT.md`（身份 FAIL、mini 有条件 PASS、INCOMPLETE）；`validation_2025_bridge_fix1_20261029/REPORT.md`（199 项等为交付方记录，真实年测未跑）。
- 2025 边界：`validation_2025_bridge_delivery_20261029/REPORT.md`、`validation_2025_data_preflight_20261029/REPORT.md`、`validation_2025_ca_two_event_audit_20261029/REPORT.md`；均不提供完整绩效许可。
- W1 材料：`w1_fractional_scenarios_independent_qa_20261028/`、`w1_prefix_independent_qa_20261028/`、`w1_real_prefix_independent_audit_20261029/REPORT.md`、`w1_dual_core_identity_independent_qa_20261029/`、`w1_ceil_precision_independent_qa_20261029/REPORT.md`；可信 prefix/真实绩效仍 BLOCKED，分支结果 INCOMPLETE。
- CA 研究结论另见仓内 `docs/research/20261026/corporate_action_tax_tdd_plan.md`、`staged_order_strategy_delivery.md`、`ENGINEERING_STATUS.md`；单窗模块通过不等于运行器/策略验收。

## 源树归档约定（未执行）

- 未来 ZIP 目标：`C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027_source_20261030.zip`。
- ZIP 应绑定 Git commit/tree hash，并附 `git status --short` 与白名单 SHA 清单；排除 logs、数据缓存、模型权重及外置审查目录。此处只约定路径，本次不生成归档、不删除 worktree。
