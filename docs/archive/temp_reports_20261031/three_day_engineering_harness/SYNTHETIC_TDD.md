# 成交日费用与终端审计 TDD 记录

状态：实现完成；候选策略仍为 NO-GO。身份分支本会话未改。

## RED → GREEN

| 行为 | RED | GREEN |
|---|---|---|
| 历史费用接口 | `test_historical_costs` 初跑 ImportError：模块缺失 | 定向费用及 runner E2E 通过 |
| core 逐单 resolver | 参数/注入实现后由 102 项订单/账户/golden 回归锁定；新增测试按实际执行日核对费用与 force 清算 | `tests.test_account_orders`、`tests.test_account_engine`、两个 golden 模块 102 项通过 |
| 终端审计禁止 X 后 BUY | 临时移除该校验后单测失败：`ValueError not raised` | 恢复实现后同一单测通过 |
| 真实 runner 终端核验 | 合成 core runner + exit wrapper + 严格逐日审计 | 通过，signal/execution 严格递增 |

费用 E2E 从 `run_cnn_backtest` 经更新后的 backtest-core wheel 执行到现金快照；合成证据写入唯一目录：
`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness/cnn_fee_e2e_xv8fqoth/`
包含合成 parquet/cache 和 accounts/orders/trades/audit JSONL。重跑使用 tempfile 唯一目录，不覆盖既有证据。

末日使用 `final_liquidation=mark`。审计只记录最终真实持仓/现金/NAV 和真实事件；core mark 快照不暴露 locked shares，故不把末日持仓称作已证明锁仓。

## 精确验证命令与计数

- `uv run --project . python -m unittest tests.unit.backtest.test_historical_costs tests.unit.backtest.test_execution_audit`：10 项，PASS。
- `uv run python -m unittest tests.test_account_orders tests.test_account_engine tests.test_golden_basic tests.test_golden_edge`（backtest-core）：102 项，PASS。
- cnn 定向 `ruff check`（5 个改动文件）：All checks passed。
- backtest-core 定向 `ruff check`（3 个改动文件）：All checks passed。

未跑全套/全项目静态门、GPU、训练或真实候选收益比较；真实候选 NO-GO 未解除。
