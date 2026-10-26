# 固定股数限价与法定价格界交付

## 版本与身份

- core提交：`893fc96`，基于观察器提交 `987ee0f`，已快进合入core主分支。
- CNN依赖提交：`7db4062`；`backtest_core`输出schema为 `1.3`。
- wheel：`wheels/backtest_core-0.1.0-py3-none-any.whl`。
- SHA256：`76cc80e5fa8fa39513a21876137a5e1c99e001b7c74801a78b76345554d72470`。
- 临时根保留独立构建包：`core_limit_final_893fc96/`。
- 旧机械回放继续引用其冻结core包，不以本次升级覆盖原证据身份。

## 行为

- `OrderIntent.limit_price` 可选，必须为正有限数；携带限价时必须固定 `shares`，不接受 `cash_amount`。
- `MarketBar.absolute_limit_up_price` 与 `absolute_limit_down_price` 表达执行日法定绝对价格界，缺失为未知。
- 新限价单缺任一法定界时以 `limit_boundary_unknown` 拒绝。
- 实际含滑点及tick处理的成交价越过法定界时，以 `absolute_limit_exceeded` 拒绝。
- 买价高于订单限价或卖价低于订单限价时，以 `limit_price_exceeded` 拒绝。
- 拒单在账户记账前裁决：零股数、零费用，现金和持仓不变；不夹价、改股数或顺延追单。
- 允许限价内容量部分成交；DAY余量终止，观察器发布真实权威账户变化和订单终态。
- 无限价的历史订单维持原行为。新法定界字段不自动更改交易/ST/参考价等已知状态。

## 验证

- 独立QA对冻结改动复审通过；主会话另跑core全部716项unittest、Ruff、Pyright，全部通过。
- CNN安装最终wheel后，显式设置 `CNN_ALLOW_LEGACY=1` 运行回测测试，共284项通过。
- 未设legacy开关的首次discover有40项旧引擎拦截错误，保留此检查记录；生产默认禁用旧引擎。
- 39个core Python模块的主分支源码、wheel内容与CNN实际安装文件逐字节一致。
- 本次只提交明确业务范围；core与CNN既有memory及执行审计WIP未混入。

## 行情适配交付

- raw provider直接透传官方上下界已由独立Luna复审通过；独立树提交 `5e384e0`，主区拣入为 `ead9fc6`。
- 仅接收已核验状态条目中的直接上下界；缺键为None，有价格不自动将known状态设真，无效值明确拒绝。
- 主会话在主区复跑13项目标测试、两文件Ruff及Pyright，全部通过。
- 早期报告将新增测试的类型错误误称为既有问题，独立审查已纠正；最终类型检查零错误。

## 尚未完成

- 分批策略的冻结股数、限价求解、三次收盘计划和退出缓冲仍须真实账户端到端验证。
- 本契约不生成官方参考价或涨跌停价；4.5%自定价格带不能冒充官方边界。
- 日线开盘成交仍有撮合模型假设，不证明真实队列或9:30订单成交。
- 工程测试通过不等于成本后非负、跑赢大盘或完整策略验收。
