# Runner 接入契约

这两个模块已实现，runner owner 可仅接线，不需要复制账本。下列代码中的 `bridge` 是既有 `StagedExecutionBridge` 实例；`runner_kwargs` 是真实 core 入口的既有参数字典，包含 execution_calendar、signal_dates、anchor_date、strategy、market、execution_config、portfolio_config、run_id、model_id 等，不包含 observer/account_actions_provider。

```python
from backtest_core.engine.account_runner import run_account_backtest_from_orders
from backtest.cnn_adapter.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.corporate_action_snapshot_loader import load_corporate_action_snapshot

snapshot = load_corporate_action_snapshot(
    "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_execution_input_snapshot_20261027_v1",
    expected_manifest_sha256="e7b1a533a6853a1b995d4a84c713acbb62943cc55f785c472020d2d492b86bcf",
)
ctx = CorporateActionContext(
    snapshot,
    period_id="调用者的唯一窗口标识",
    reset_anchor=runner_kwargs["anchor_date"],
    empty_reset=True,
    delegate=bridge,
    strict_tax=True,
    tax_policy="pretax",
)
try:
    result = run_account_backtest_from_orders(
        **runner_kwargs,
        observer=ctx,
        account_actions_provider=ctx.account_actions_for_day,
    )
finally:
    corporate_action_evidence = ctx.evidence()
```

`ctx.post_state` 是最后一次 ExecutionUpdate 的完整原始 AccountState；`ctx.last_update` 是原始 update。全部回调按 core 顺序转交 `bridge.on_update`；delegate 异常原样传播，且记录 INCOMPLETE。调用者在异常路径也应保存 `corporate_action_evidence`，不得把失败转成通过。

默认 strict_tax=True：实际正登记遇未知税即终止。显式探索时可设 strict_tax=False；可机械入账的正权益仍标 INCOMPLETE。`cash_dividend_20pct_stress` 只对现金施加 20% 压力，不代表实际扣税。任何模式的 actual_after_tax_target_eligible 均为 false。

只在 core 真正完成的 `record_positions` 中取数。登记日 hook 不看开盘前持仓；零登记不建应收或未上市权益。现金登记后卖至零仍支付。股权在登记至除权前变仓时拒绝，原因 core_share_holdings_changed_unsupported。

精确整股必须同时满足来源十进制 T × 登记数为整数，且 core 的浮点乘积完全等于该整数。非整数或浮点不精确直接阻断，不 floor，不宣称官方零碎股证书。缺上市/付款日、缺 T、正登记 unresolved 均不能补日期或猜比例。

无 record 操作只在原 record_date 严格早于 reset_anchor 且 empty_reset=True 时跳过。anchor 当日或之后缺 record 时为 missing_record/INCOMPLETE。同日 record/ex 不受现有 core 时序支持，明确拒绝。配股固定不认购，仅导出来源覆盖。

snapshot.provider 可复用既有规范事件查询，但请将账户 hook 接到 ctx.account_actions_for_day；provider 原始逐日 hook 不具备这里的持仓上下文过滤。snapshot.descriptors 保留缺 ex 的记录及完全缺阶段方案，snapshot.evidence()/ctx.evidence() 导出全量原始行、原行哈希、文件 SHA、source ID 和 unknown。

四源码与哈希保持在交付工作树及 SOURCE_SHA256.json。仅修改四个约定新增文件，待主会话独立质量门；未改 runner、bridge、strategy 或 core。
