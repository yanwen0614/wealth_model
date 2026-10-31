# 修复版接入 API

工作树固定为 `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027`；分支 `research/corporate-action-fix-20261027`，基线 `ce7d1c6`。源码已冻结，哈希见 SOURCE_SHA256.json；历史 final 目录不代表本轮版本。

`bridge` 为既有 StagedExecutionBridge 实例，`runner_kwargs` 为真实 core 入口参数，含 execution_calendar、anchor_date、strategy、signal_dates、market、execution_config、portfolio_config、run_id、model_id 等，不含 observer/account_actions_provider。日历必须来自调用者实际执行输入；以下指纹编码明确为顺序 ISO 日期的紧凑 JSON。

```python
import hashlib
import json
from backtest_core.engine.account_runner import run_account_backtest_from_orders
from backtest.cnn_adapter.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.corporate_action_snapshot_loader import load_corporate_action_snapshot

snapshot = load_corporate_action_snapshot(
    "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_execution_input_snapshot_20261027_v1",
    expected_manifest_sha256="e7b1a533a6853a1b995d4a84c713acbb62943cc55f785c472020d2d492b86bcf",
)
calendar = tuple(runner_kwargs["execution_calendar"])
calendar_sha = hashlib.sha256(json.dumps(
    [day.isoformat() for day in calendar], separators=(",", ":")
).encode("utf-8")).hexdigest()
ctx = CorporateActionContext(
    snapshot, period_id=period_id, reset_anchor=runner_kwargs["anchor_date"],
    empty_reset=True, strict_tax=True, tax_policy="pretax", delegate=bridge,
    window_end=calendar[-1], calendar_sha256=calendar_sha,
)
try:
    result = run_account_backtest_from_orders(
        **runner_kwargs, observer=ctx,
        account_actions_provider=ctx.account_actions_for_day,
    )
finally:
    corporate_action_evidence = ctx.evidence()
```

新增可选参数 `window_end: date | None`、`calendar_sha256: str | None`。省略时导出 None，不制造日期或指纹。SHA须64位小写十六进制，终点须不早于anchor。evidence 导出 period_id、anchor/reset_anchor、window_end、calendar_sha256 与原始 metadata。`window_identity_validation` 始终为 `pending_runner_validation`：当前模块只记录调用者声明，未来 runner 必须验证实际日历、终点与 anchor 一致。

P1-01：同日 record/ex 的 hook 只返回 RecordPosition，core 开盘订单之后完成登记；零登记后续跳过。正登记 observer 保存完整 post_state、透明转交 delegate 后，抛出 same_day_record_ex_unsupported 并留 INCOMPLETE。探索模式也不会伪造同日除权账。

P1-02：原始现金 None 保持 None、来源标 cash_amount_unknown；实际正登记严格模式拒绝，探索模式保留 INCOMPLETE、不补零或虚造现金。明确0保持已知零；零登记未知事件不全局阻断。

既有规则保留：现金按record数支付，卖至零不消灭权益；零登记无幽灵；股权record至ex变仓拒绝；T仅构造一次，B/C不重复；非整数与浮点不精确拒绝，不floor；正权益缺阶段拒绝；配股只coverage；所有模式实际税后目标资格为false，20%仅现金压力场景。

37项定向回归与QA原始两项反例通过；四文件Ruff/Pyright通过。完整日志见 targeted.log、independent_boundaries.log、RED_P1.log/GREEN_P1.log、RED_P2.log/GREEN_P2.log。此结果为编码owner自检，独立QA复验仍由主会话安排。
