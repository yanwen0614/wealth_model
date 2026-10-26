# 公司行动现金税务接入：设计与实施记录

状态：实现与独立QA已通过，主会话另复验35项定向测试、目标Ruff与Pyright通过。下文保留任务启动前的缺口、设计及TDD顺序，最后一节记录实施结果。

## 实施前核实的源码链路与缺口

1. `CorporateActionProvider.account_operations_for_day`（`backtest/cnn_adapter/corporate_actions.py:148-188`）在除权日创建 `CreateCashReceivable`，目前只传 `event.gross_cash_per_share`；派息日产生独立 `CashPayment`。
2. core `CreateCashReceivable.cash_per_share` 与 `CashReceivable.amount` 没有税额/净额字段。`apply_account_actions` 按登记股数计算毛应收，支付时从应收全额增加 `cash` 并写入同额 `pending_cash`；操作 ID 提供阶段幂等。
3. CNN `run_cnn_backtest`（`backtest/cnn_adapter/runner.py`）只接收 `CorporateActionProvider` 和 `period_id`，以 provider 生成当日 actions 交 core runner；没有 corporate tax policy 参数。
4. `CorporateActionLedger.project(..., tax_policy=...)` 可算 `cash_dividend_20pct_stress`，但属于独立投影；它不改变 core 应收、到账或 NAV。若外部 projection 扣税、core 仍按毛额支付，会产生口径冲突。
5. 因此当前 core 现金公司行动执行路径是 pretax。不能将 20% projection 与毛额 core NAV 拼接，也不能把 broker stamp/transfer 费用通过称作全成本已齐。

## 最小设计建议

- 加显式 policy：`pretax` / `cash_dividend_20pct_stress`；通过 CNN runner 传至事件适配层，并写入运行 provenance/config 身份。缺省兼容策略需在实施前冻结；建议旧调用维持 pretax，成本后审计调用必须显式指定 policy。
- 应收阶段按登记股数得到 gross；stress policy 算 withholding=20%×gross、net=gross-withholding。账户状态/分录同时保留 gross、withheld、net，避免只有净额而丢失审计金额。
- NAV 在除权至支付前只计 net receivable（或 gross receivable 减 withholding payable，二者择一且不可同时叠加）；支付日只把 net 转为 cash，并将 withholding 记入 paid/withheld 分账；之后 NAV 仅计净现金。available_cash 仍到下一交易日释放，不计入 NAV 两次。
- `cash-ex`、`cash-pay` 和 withholding/paid 需使用稳定、独立的 event-phase operation IDs；每阶段重复和整段重放均不可重复计提、支付或扣缴。
- 明确 20% 是压力政策，不是实际个人税结果，不可声称保证税后收益下界。实际税制/FIFO lot/持有期规则不在本最小实现范围。
- 送股税务必须三态区分：来源核准的免税 capitalization、来源核准的应税 bonus（规则可执行）、税务未知。未知不得隐式按零税；无法计税时显式拒绝“税后/全成本”结论或 fail closed。300896 当前标记 unknown，不能先假定免税。

## TDD 顺序与独立验收

1. 契约 RED：policy 非法值拒绝；stress 的 gross/withheld/net 金额边界正确；未知送股税务不能静默通过税后检查。
2. provider RED/GREEN：同一事件生成含 policy 的除权/支付分录；稳定 operation IDs；pretax 与 stress 的金额/字段不同且 provenance 明示。
3. core RED/GREEN：应收只认一次；支付时仅净额进入 cash/pending_cash；paid 与 withheld 各记一次；重复 ex/pay operation 不重复变更；错误 pay date 或缺应收拒绝。
4. NAV 与时点：除权后净应收计一次；派息日开盘 available_cash 不增加；EOD 净额到账；次晨 available_cash 增加；三时点扩展 NAV 与现金/应收/withheld 分项闭合。
5. 回归：pretax 旧语义与现有公司行动基线一致；无 policy 的旧调用行为经显式断言固定；20% stress 不污染真实税报告字段。
6. 单独测试送股/转增免税已核准、应税规则已核准、税务 unknown 三类；unknown 必须显式标状态且不得报告完整成本后收益。
7. 本任务只跑新增/受影响的 TDD 测试和独立新范围 QA；不重跑旧的未含 CA 税 40 项门。完成后再评估是否进入收益核验，压力情景与实际税结论分开报告。

## 开始条件与写锁边界

主会话完成已冻结 raw/CA/fees/runner/identity 模块、相关 tests、wheel/`uv.lock` 的整体复验及分批 commit，并明确释放写锁后，才能按以上顺序修改 provider/runner/core 与必要契约。全程只派 GPT-6 Luna 或 DeepSeek，嵌套子代理亦同；不自动 push。当前阶段只保留本计划，不启动代码改动。

## 实施结果

- runner显式选择pretax或cash_dividend_20pct_stress，默认兼容pretax；policy进入配置身份和provenance。
- core应收与支付保留毛额、预提及净额；NAV计净应收，支付只把净额转现金，下一交易日释放可用额；阶段operation ID去重。
- 事件内容及来源快照的fingerprint进入config_hash；更换源事件身份会改变运行配置身份。
- 未知送转税在provenance中明示不完整；require_known_share_tax=True时拒绝该类运行，不静默称全成本齐备。
- 20%仅是统一现金红利税压力情景，不是实际持有期税制复刻；旧Z库pretax夹具记录保持原义。
- 主会话复验公司行动、真实runner端到端、runner契约、历史费用和身份五模块，共35项通过；目标Ruff/Pyright零错误。
