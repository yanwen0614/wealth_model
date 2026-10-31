# W1 2021-06-07 订单成本的 prefix 可用性分析

## 裁决摘要

就已冻结的研究成本配置和当前历史费用解析代码而言，6 月 7 日信号的下一执行日为 6 月 8 日；6/7 cutoff 费用与 6/8 执行日解析费用完全相同。因此，若在 cutoff 内构造固定 CostConfig 并供 6/7 信号预算计算，费用参数本身不会损失信息，也不会改变由该费用项导致的订单意图。这个结论是对代码中固定政策的等价性判断，不是 2021 年当时配置已冻结的证据，也不是券商实际佣金/个人税费证书。

## 精确费用字段与解析语义

- 预注册 [preregistration.json](C:/Users/yanwen/AppData/Local/Temp/opencode/staged_candidate_prereg_20261027_v1/preregistration.json)：双边佣金 0.0002、最低 5；印花税按执行日，2021 卖出 0.001；2021 双边过户费 0.00002。研究范围未承诺券商特定费率。
- v12 [fees_W1.json](C:/Users/yanwen/AppData/Local/Temp/opencode/staged_prepared_inputs_20261027_v12/fees_W1.json)：该文件标记 calendar_dates=121、universe_codes=4186、precomputed_rows=0；仅含上述费率及滑点模型固定参数。没有逐 code/date 费用行。
- [historical_costs.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/historical_costs.py) 的 resolver 字段为 `execution_date`、`market`、`commission: CostConfig`。它只校验 `SSE_A`/`SZSE_A`，佣金完全沿用传入配置；执行日早于 2022-04-29 时过户费 0.00002，早于 2023-08-28 时卖税 0.001。2021-06-07 与 2021-06-08 落在同一费率区间。
- 代码到市场映射在 [staged_production_inputs.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/staged_production_inputs.py)：`.SH`→`SSE_A`，`.SZ`→`SZSE_A`。策略 `_affordable_shares` 将信号日期的日历下一交易日传入 resolver，并按 `(execution_date, code)` 查找配置。W1 `calendar_W1.txt` 行 103/104 确认 6/7→6/8。
- Core [cost.py](C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src/backtest_core/policies/cost.py) 的成本计算使用买卖佣金字段、最低佣金、卖出单边印花税和双边过户费；配置不包含 code 专属费率。买入可负担股数由佣金+过户费影响；卖出执行成本另计印花税。预注册中未出现沪深、个股或 2021 年 6 月内日期差异。

## 费用覆盖判断

| 参数 | 6/7 cutoff 固定值 | 6/8 resolver 值 | 结论 |
|---|---:|---:|---|
| 买佣金率 | 0.0002 | 0.0002 | 一致；研究假设，非实盘券商证书 |
| 卖佣金率 | 0.0002 | 0.0002 | 一致；研究假设，非实盘券商证书 |
| 最低佣金 | 5 | 5 | 一致 |
| 卖出印花税 | 0.001 | 0.001 | 一致；6/8仅卖出收取 |
| 双边过户费 | 0.00002 | 0.00002 | 一致 |

当日与前日可能变化：实现只在明确阈值日切换印花税、过户费；2021-06-07至06-08不存在阈值。代码不允许按沪深/股票切换上述费率。预注册不描述佣金在不同券商、账户或成交金额下的实际合同差异；最低佣金规则以本次研究配置为准。

## 独立核验边界、hash 与阻塞

- 完成静态穷尽核验：resolver 不读取费率文件/数据库，费率只由两日期阈值与固定 CostConfig 决定；对 2021-06-08 以及沪深两市场，输出费率由同一分支确定。因 code 只用于后缀市场映射、两个市场被解析成相同费率，这覆盖 W1 4186 个代码和 6/7 信号日的任何候选买入代码。此为实现域上的穷尽比较，不是对 506,506 条已存 fee 行逐条比较。
- 实际费用记录核查被输入形态阻塞：生成器 [staged_production_inputs.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/staged_production_inputs.py) 明确写出 `precomputed_rows: 0`，v12 目录仅找到 `fees_W1.json`/`fees_W2.json`，manifest 也只登记这两个 fee summary。没有可供抽样或流式比较的 W1 fee parquet/jsonl。未读取 4GB 源。
- SHA-256：`fees_W1.json` `a938e078771ce10037dfe85f861309ea9f242a9dcad15b53279e4631e15ab41a`；v12 `manifest.json` `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；预注册 SHA 与 manifest 引用一致：`1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae`。
- 若要独立核验“已落盘表值/生成时点”，需要明确提供历史逐行费用表或生成器本次运行用的 resolver 版本/commit 和时间戳记录。具体可给 `fees_W1.parquet`/`fees_W1.jsonl` 的绝对路径（当前目录未发现）及其 SHA；或者确认接受只对当前 resolver 进行确定性穷尽核验。无需授权读取 4GB 行情源。

## 回答目标问题

依据 cutoff 内固定研究政策构造费用配置，可复现同一成本输入下 6 月 7 日的策略订单意图；没有证据表明查 6/8 prepared fee 记录带来任何额外信息。用截止日 resolver 产出的常量 bundle 可规避未来日期查询，但仍假设固定佣金和统一沪深费率政策成立。是否与原策略全部订单意图相同，尚不能仅凭费用分析声称完成：其他信号、市场状态、行情与订单参数仍须原策略同输入比较；本分析未运行 prefix 或回测。fix2 独立 QA 也记载真实 prefix 与 W1 12 路径未证明，真实 fee bundle 缺 PIT 输入时 fail-close。

## Prefix-only 输入包建议

1. 包含 cutoff 日期、代码宇宙哈希、输入 CostConfig、固定政策声明、resolver 源文件/版本哈希、canonical JSON 与包哈希；逐 code 行可压缩成两个市场费率 bundle，因为当前规则对代码无差异。
2. 为未来执行日订单记 `signal_date=2021-06-07`、`execution_date=2021-06-08`、`market=SSE_A|SZSE_A`、`fee_source=cutoff_policy`、`knowledge_cutoff=2021-06-07`。日期字段表示 T+1 执行对象，不得伪装成 cutoff 后新取到的记录；保留生成时点，不能把 2026 生成结果记成 2021 冻结证据。
3. 生成器只接受 cutoff 内已冻结规则；校验费率所需源版本、市场覆盖和 CostConfig 完整性，拒绝动态未来 resolver、缺项和未知市场。研究假设标 `research_policy`，实际费税认证标 `unverified`。
4. 测试建议：6/7→6/8 两市场 fees 完全相等；相同结果覆盖全 4186 code 后缀集合；佣金分拆/最低佣金保持；阈值边界测试（2022-04-28/29、2023-08-27/28）；spy resolver 证明截止日后的费率 lookup 未发生；对真实 6/7 策略快照作只读订单 intent 对照，明确仅费用输入受控且不运行完整历史绩效。
