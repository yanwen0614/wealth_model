# W1 截止 2021-06-07 费用 PIT 初步事实

范围：只读检查。未改项目代码，未运行历史回测/前缀，未安装依赖，未扫描无关大文件。

## 已确认

- `staged_prepared_inputs_20261027_v12/fees_W1.json` 声明 `calendar_dates=121`、`universe_codes=4186`、`precomputed_rows=0`，费用来源标为 `historical_costs.resolve_historical_costs`。只有 base config：佣金买卖双边 0.0002、最低 5；卖出印花税 0.001；过户费 0.00002。
- CNN `historical_costs.resolve_historical_costs(execution_date, market, commission)` 按执行日动态解析：2023-08-28 起卖税 0.0005，此前 0.001；2022-04-29 起过户费 0.00001，此前 0.00002。2021-06 每个支持市场、每个执行日都返回上述两个 base_config 费率。market 只校验 `SSE_A` / `SZSE_A`，没有按沪深区分费率；佣金由调用者提供，不按 code/date 自动变化。
- `staged_order_strategy._affordable_shares` 对信号日取日历下一交易日作为 `execution_date`，随后调用 resolver `(execution_date, code)`；代码作为 market 参数语义须继续核查 runner 的 code→market 映射。费用用于 BUY 可负担股数，可能影响订单股数/是否下单。执行日查询和预注册的固定历史政策是不同证据：后者可作为研究假设，前者是当前模拟实现；两者不能推出 2021 年当时已有冻结配置或实际个人税费证书。
- fix2 handoff / 独立 reverify 确认：真实 W1 缺 cutoff scoped PIT 输入包时 fail-close；mini 的静态成本仅属合成测试；真实 W1 fee bundle 流程与 12 路径 proof 尚 BLOCKED。上一轮 QA 指出 cutoff prefix 曾预读 6/8 费用，fix2 将其隔离为 cutoff 静态值，但没有证明真实历史费用输入来源及真实性。

## 核验收口

- W1 日历 `calendar_W1.txt` 行 103/104 为 2021-06-07、2021-06-08。静态穷尽源码规则后，6/8 成本与 6/7 cutoff 成本一致；对 `.SH`/`.SZ` 及全部 4186 code 同值，因为 resolver 不基于证券代码改变费率。
- 实际费记录无法抽样/流式比对：生成代码只落盘 fee 摘要且 `precomputed_rows=0`。尚缺逐行 fee 表或历史运行记录/生成时点证据；本次没有读 4GB 源。具体路径/哈希请求见 [REPORT.md](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_prefix_fee_pit_analysis_20261028/REPORT.md)。
- 对 prefix 订单结论仅为费用配置等价；未运行 W1，也未验证全体订单/交易输入等价。固定研究政策不能证明 2021 当时已冻结，更非实际佣金或税费证书。
- 输入 SHA-256：fees_W1 `a938e078771ce10037dfe85f861309ea9f242a9dcad15b53279e4631e15ab41a`；manifest `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；preregistration `1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae`。
