# 公司行动税务批次冻结交接

日期：2026-10-26。状态：代码/tests/wheel/lock 已冻结；未 stage、commit 或 push。

## 独立 QA

- Quality Gate 会话完整 ID：`ses_e8904bb97ffeW3wokpSr0mHpr3`。
- 会话报告：OpenCode 该会话的最终 review/re_verify 消息（不是仓库内文件）。本交接文件是可保存/审查的副本摘要。
- 最终 verdict：PASS。先前两项 HIGH 已关闭：未知送转税务的状态与严格拒绝开关；公司行动源事件 fingerprint 纳入 config_hash/provenance。
- wheel SHA-256：`5de72c3d9934849d694532f091f02cf7dbb360f5a45f396a99e4abb5bb4e2ffe`。

## CNN 仓库：本批可整文件提交清单

- `backtest/cnn_adapter/corporate_actions.py`
- `backtest/cnn_adapter/runner.py`
- `tests/unit/backtest/test_corporate_actions.py`
- `tests/unit/backtest/test_corporate_action_runner_e2e.py`
- `tests/unit/backtest/test_cnn_adapter_runner.py`
- `wheels/backtest_core-0.1.0-py3-none-any.whl`
- `uv.lock`

`docs/research/20261026/corporate_action_tax_tdd_plan.md` 是相关未跟踪计划文档；是否与代码批次一起提交由主会话决定。

CNN 其他并行 WIP 请排除：`.opencode/memory/HISTORY.md`、`.opencode/memory/MEMORY.md`、`scripts/audit_walkforward_execution.py`、`_check_signals.py`、`backtest/cnn_adapter/staged_allocation.py`、`tests/unit/backtest/test_staged_allocation.py`。

## backtest-core 仓库：本批候选文件

税务/公司行动相关且可整文件提交：

- `src/backtest_core/contracts/account_actions.py`（新增）
- `src/backtest_core/contracts/account.py`
- `src/backtest_core/contracts/__init__.py`
- `src/backtest_core/engine/account.py`
- `src/backtest_core/engine/__init__.py`
- `tests/test_account_actions.py`（新增）
- `tests/test_contracts_outputs.py`（含 AccountState 字段与 schema 断言）
- `src/backtest_core/contracts/result.py`（schema 1.1）
- `docs/semantics.md`、`AGENTS.md`（公司行动 NAV/hook 语义）

**必须按 hunk 选择、不可整文件提交：**

- `src/backtest_core/engine/account_runner.py` 同时包含公司行动账务与非本税务批次改动（历史费用 resolver、market/execution state gate、评估窗口/terminal 指标等）。只选公司行动操作、应收/权益 NAV、快照、支付/上市阶段 hook、除权日估值校验相关 hunks；不要整文件 `git add`。

## 必须排除的 core 并行 WIP

- `src/backtest_core/contracts/enums.py`
- `src/backtest_core/contracts/market.py`
- `src/backtest_core/evaluation/methodology.py`
- `src/backtest_core/policies/tradability.py`
- `tests/test_account_engine.py`
- `tests/test_account_orders.py`

这些文件对应执行状态/费用 resolver/评估窗口改动，不属于本税务批次。core 当前 wheel 是从含这些改动的完整工作树构建，故 wheel 与完整源码一致，但包含这些未提交模块变更；若要发布 wheel，需由主会话结合 core 提交范围决定是否接受该组合。

## 验证记录

- CNN backtest 全目录：`CNN_ALLOW_LEGACY=1`，263 项 PASS。
- CNN 三个税务相关测试模块：21 项 PASS；目标 Ruff PASS、Pyright 0 errors。
- core 受影响测试：226 项 PASS；目标 Ruff PASS、Pyright 0 errors。
- core 全量 unittest 曾有 2 项非税务失败（`test_contracts_config.TestGroupDefaults`、`test_contracts_inputs.test_valid_construction_and_field_set`）；未纳入本批修改。
- wheel 与 core 源码 38 个 Python 模块核对一致；CNN 环境已安装该本地 wheel，`uv.lock` 哈希与 wheel SHA 一致。
- 两仓 `git diff --check` PASS。当前 CNN HEAD 为 `132f260`；core HEAD 为 `8aa82f2`。两个仓库均无 staged 文件。
