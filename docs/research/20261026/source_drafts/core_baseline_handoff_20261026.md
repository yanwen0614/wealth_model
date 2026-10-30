# core 联合基线交接（只读冻结）

时间：2026-10-26。两个共享主区均未 stage/commit/push；本次仅更新本临时文件。

## 仓库状态
- CNN：`D:/code/cnn_full_20260905/cnn`，branch `main`，HEAD `ac1bd6bd971b9bd1c50b2e2fbaa4a271d3cc2f33`。
- CNN 已提交：`130e1f5` 税务、`3ce9876` 分批组件、`132f260` 桥接计划/技术29、`ac1bd6b` 质量门状态。
- CNN 未提交：`.opencode/memory/HISTORY.md`、`.opencode/memory/MEMORY.md`、`scripts/audit_walkforward_execution.py`；未跟踪 `_check_signals.py`。均保留，非本次税务批次。
- core：`D:/code/cnn_full_20260905/backtest-core`，branch `main`，HEAD `8aa82f2b4c3ea2af1a308f09e346663d08031ef6`；无 staged 文件。

## core 未提交 diff 归属（18 tracked + 2 untracked）
- 公司行动/税务：`src/backtest_core/contracts/account_actions.py`（新）、`src/backtest_core/contracts/account.py`、`src/backtest_core/contracts/__init__.py`、`src/backtest_core/engine/account.py`、`src/backtest_core/engine/__init__.py`、`tests/test_account_actions.py`（新）。
- 公司行动结果/schema/文档：`src/backtest_core/contracts/result.py`、`tests/test_contracts_outputs.py`、`docs/semantics.md`、`AGENTS.md`。
- 执行状态已知性：`src/backtest_core/contracts/enums.py`、`src/backtest_core/contracts/market.py`、`src/backtest_core/policies/tradability.py`。
- 日期费用：`tests/test_account_orders.py`（resolver 行为/无效返回）、`tests/test_account_engine.py`（resolver fixture 参数）。
- terminal/评估窗口：`src/backtest_core/evaluation/methodology.py`、`tests/test_order_contract_e2e.py`（`trade_end` override 透传）。
- 两个陈旧契约断言修复：`tests/test_contracts_config.py`（schema 跟随常量）、`tests/test_contracts_inputs.py`（补齐5个 MarketBar 状态字段）。
- `src/backtest_core/engine/account_runner.py` 混合以上研究改动：日期费用 resolver、状态拒单、terminal dates/评估截止、公司行动 hook/NAV/snapshot。整批中归属已确认均对应本三天授权研究；无可确认的无关他人 WIP。
- 独立 QA 建议逐行为检查 `account_runner.py`；批次当前含18 tracked、2 untracked，共20路径。未 stage。

## 全量基线验证（两项修复后实跑）
- `uv run --project . python -m unittest discover -s tests -v`：690 PASS。
- `uv run --project . ruff check .`：PASS。
- `uv run --project . pyright`：0 errors、0 warnings、0 informations。
- `git diff --check`：PASS；原始全量失败根因是 schema 期望1.0落后于常量1.1、MarketBar字段清单漏5个已批准字段；仅改测试期望。
- Pyright测试修补：故意错误 resolver 返回值用 `cast(Any, ...)` 保留运行时负测试；测试子类补传 `trade_end`。

## 独立 QA 与剩余问题
- Quality Gate 会话 ID：`ses_e88ee9cf5ffeLe3Tw2WHq5is0d`；VERDICT `FAIL`，lint/typecheck/test本身均通过，TDD记录门缺失。
- QA MEDIUM：`_build_account_view()` 的策略 NAV 是否应纳入现金应收/未上市权益；终端窗口/`trade_end` 缺行为测试；未知执行状态 reason 缺针对性断言。此轮未修改生产代码/新增测试。
- 复审结论：无范围外他人 WIP证据；`account_runner.py` 为多个已批准研究功能的集成文件；整批是否提交需主会话按QA findings决定。
- 暂无可单独保存的 QA markdown；完整结论在上述会话最终消息。本文件为临时交接副本。

## 下一步边界
- 共享主区保持冻结，现有未提交产物全部保留；不得从本会话写入/暂存/提交。
- 桥接计划已随 CNN `132f260` 提交；core 基线及 QA findings 收口后，另行拆解 Observer 实施计划，等待主会话释放再进入独立 worktree。
