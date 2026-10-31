# W2 公司行动与 coverage 独立审计

日期：2026-10-28。范围：W2_B1、W2_S1、W2_S2、W2_C70 已完成结果目录，只读核验；不重跑交易、不改源码或原始数据，也未读取训练源 parquet。

## 结论摘要

1. W2 runner 确实将 `CorporateActionContext` 作为 observer 接入，并传入 `ctx.account_actions_for_day`。`corporate_action_provider="none"` 只说明旧 provider 参数为空，不能据此推断公司行动链路未接线。
2. 四策略均实际触达 3 笔股息事件：000799.SZ、002821.SZ、600098.SH。逐日 `record_positions`、processed operation IDs 和账户累计收款彼此吻合；record、cash-ex、cash-pay 阶段均可见。
3. 实际数值按 `cash_dividend_20pct_stress` 的机械压力假设计算，不能当作真实税后结果。各策略 CA evidence 均为 `INCOMPLETE`，3 个有持仓事件均标记 `tax_unknown`。
4. W2 coverage 总摘要报告 expected=570,696、missing bar=15,620、unknown=16,605，但文件仅列出 34,059 行：其中 120 行缺 bar（110 行状态为 suspended，10 行状态为 unknown）。摘要差额没有逐条来源行可供本次复核，不能声称全部 missing 都是停牌，也不能把总体 unknown 说成实际 unknown=0。
5. 四策略各自 `opportunity_coverage.jsonl` 的 1,247 个输入覆盖行均无 `unknown_fields`，且无 missing bar。这只证明策略输出列出的这些机会输入，不代表 W2 全市场摘要的 unknown 已消除。
6. 每策略快照含 12 条配股源记录；逐日持仓核对未发现四策略在公告日后持有这些配股证券。配股条目仍带来源/时点未知标记，策略预注册为不认购；不能据此宣称配股源数据已正式认证。

## 公司行动触达明细

各事件每股现金和日期在四策略源行一致：000799.SZ 登记 2021-07-08、派息 2021-07-09、每股 0.70 元；002821.SZ 登记 2021-07-12、派息 2021-07-13、每股 0.60 元；600098.SH 登记 2021-07-29、派息 2021-07-30、每股 0.17 元。事件 000799 的原始行没有送转（每股送转=0），此前将其描述成送转事件的说法不成立。

| 策略 | 登记持仓（000799 / 002821 / 600098） | 三事件税前现金合计 | 20% 压力扣缴 | 压力后到账 |
|---|---:|---:|---:|---:|
| W2_B1 | 700 / 500 / 30,200 股 | 5,924.00 元 | 1,184.80 元 | 4,739.20 元 |
| W2_S1 | 200 / 100 / 10,000 股 | 1,900.00 元 | 380.00 元 | 1,520.00 元 |
| W2_S2 | 200 / 100 / 10,000 股 | 1,900.00 元 | 380.00 元 | 1,520.00 元 |
| W2_C70 | 500 / 300 / 21,100 股 | 4,117.00 元 | 823.40 元 | 3,293.60 元 |

上述持仓来自对应登记日 `core_state.record_positions`，不是用登记日收盘持仓推算。对应日的账户 `gross_cash_dividends_paid` / `withheld_cash_dividends_paid` 累计值与按三事件计算的数值相符。实际适用税率与投资者税务资格未认证，20% 是运行配置的 stress policy。

## Coverage 逐条证据边界

`coverage_W2.json` 顶层：`expected_count=570696`、`missing_bar_count=15620`、`unknown_count=16605`、`source_known=false`，且说明真实快照血缘尚未独立验收。文件 `rows` 实际 34,059 条；其中 33,939 条 bar_present=true、120 条 false。120 条缺 bar 中，110 条 `verified_state.market_state=suspended`，10 条为 unknown。故只能确认已枚举明细中的这 120 条状态，不能将其外推至 15,620 条汇总缺口。

逐条 unknown 字段组合（枚举行）：110 条 `bar|limit_known`、10 条 `bar|verified_states`、10 条 `limit_state_known|absolute_limit_up_price|absolute_limit_down_price|limit_known`。其中后 10 条 bar 存在，不等于缺 bar。总摘要 unknown=16,605 远大于枚举行中的 unknown，缺少剩余差额的逐条表；报告不对差额归因。

策略侧机会输入另见每个结果目录的 `opportunity_coverage.jsonl`：审计脚本逐行遍历每个 `input_coverage`，四策略各 1,247 行，missing bar=0、unknown_fields 非空=0。该计数是策略输出的实际机会输入，不是 coverage 总体明细的替代品，也不证明底层来源已验收。

## 配股与资格限制

四个策略的 CA evidence 各含 12 条 `right_issue` 原始记录。审计将代码、公告日期与逐日账户快照持仓对照，未发现公告日后持仓；另外 runner 的 `account_actions_for_day` 明确跳过 `right_issue`，与本窗“不认购”设定一致。源条目仍有 `implementation_not_certified`、`known_at_unknown`、`rights_no_subscription_coverage_unknown`，所以结论限于“本次四个账户未持有这 12 个配股代码”，不能扩展为全市场配股已完成核验。

所有 W2 机械回测仍是 `INCOMPLETE`。本文证实接线和三笔股息在模拟账本中的触达、记账与压力扣缴；它不把压力税务解释为实际税后绩效，也不解除真实快照血缘未验收这一限制。

## 可复核产物与重跑方式

- `audit_w2.py`：只读审计脚本；按 JSONL 行流式读四策略账户及机会文件，另解析 CA evidence 和 coverage JSON。
- `audit_summary.json`：脚本生成的机器可读汇总，包含逐策略实际正登记事件、源行、操作日期、配股暴露检查及 coverage 枚举计数。
- 运行：`python audit_w2.py`（Python 3 标准库即可）。输入目录在脚本开头的 `ROOT`、`RESULTS`、`PREPARED` 常量中指定；不会写入或更改输入文件。

关键原始证据：`staged_mechanical_results_20261028_v1/W2_{B1,S1,S2,C70}/corporate_action_evidence.json`、各目录 `daily_account.jsonl` 与 `opportunity_coverage.jsonl`、`staged_prepared_inputs_20261027_v12/coverage_W2.json`。runner 接线依据：`corporate-action-fix-20261027/backtest/cnn_adapter/staged_candidate_runner.py` 和 `corporate_action_context.py`。
