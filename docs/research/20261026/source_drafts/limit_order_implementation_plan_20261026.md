# 4.5%受限开盘限价订单：最小实施方案

日期：2026-10-26。性质：只读设计稿；不是实现、成交验证或绩效结论。

## 结论与边界

有条件 GO：可作为固定股数 DAY 开盘限价订单的日线模拟基线，成交仅代表“开盘价价内且满足本模型限制”的合成裁决，不证明排队成交、容量可达或收益下界。候选策略共用同一执行机制。

信号日 T 收盘后构单，T+1 09:30 只裁决既有订单。参考收盘价须为来源确认的未复权 raw close 且 >1 元。tick=0.01：买入限价 floor(reference×1.045/tick)×tick；卖出限价 ceil(reference×0.955/tick)×tick。若取整后越过原百分比边界，向更保守的一档调整。缺参考价、单位、tick 或必需状态则拒单；除权日参考价未知须在开盘前 gate 拒单。

买入按 T 收盘时可用现金预算、买入限价和当时已知费率求最大可负担整手股数，订单携带固定 shares。不得用 T+1 open 重算股数、增量下单或预支尚未成交的卖款。预算费用函数应以买入限价估算佣金/税费并保留数值安全余量；core 仍按实际 fill_price 计真实现金及费用，现金不足则整单拒绝。卖出股数沿现有账户/T+1规则裁决。

## 已核实的接线缺口

- core `OrderIntent`（backtest-core/src/backtest_core/contracts/order.py）只有 shares/cash_amount，无 limit_price；买卖均需扩展可选正有限价格，并保留旧构造和互斥语义。
- core `MarketBar`（contracts/market.py）只有 limit_up/down 布尔值，无绝对法定价格上下界。涨跌幅 rate/布尔不得代替绝对价校验；边界来源、精度、时点未确定前，不能宣称法定上下限已覆盖。
- CNN `raw_market_inputs.py` 中 RawMarketRecord.reference_price 当前始终为 None、reference_state 为 unknown；provider 未映射 reference_price。公司行动 required+unknown 已可触发 REFERENCE_UNKNOWN，但普通参考价和限价订单参考收盘价仍需明确来源。
- `CnnRawMarketDataProvider` 只从已核验状态映射 trading/ST/reference/limit 布尔值。必须保证这些是执行日开盘前可知的权威状态；未知拒单，不能从执行日 close 推导开盘 gate。
- core `account_runner.py` 的 `_plan_order` 先算 SlippageV1 fill_price，再执行账户变更；应在账户记账前验证方向限价及绝对法定上下限。任一越界整单拒绝，无截价成交。限价应进入 `_OrderTicket` 并贯穿买卖执行。
- `CnnTargetOrderStrategy` 当前买单为 cash_amount，core 按执行价折股。新基线在策略收盘回调读取 T 日 raw close，预算折固定 shares+limit_price；旧模式保留 cash_amount。

## 最小实施步骤（唯一 owner，独立 worktree）

1. 先由 raw 数据 owner 明确 raw close/reference 来源、复权状态、tick 和执行日已知的绝对上下限字段；缺任何一项时保持拒单，不推断填充。公司行动 gate 继续只看已验证事件日期与 reference known。
2. core 扩展 OrderIntent.limit_price（可选）；校验正数有限，SELL/BUY 均可用，None 保持原行为。执行票据携带该字段；结果自动回显原订单。
3. CNN 增加显式 opt-in 限价策略配置，禁止悄悄改变现行策略。对每个候选以 T 日 raw close 计算限价和预算内整手 shares；无法取得可靠 close/tick 时显式跳过并计数。买卖限价都由信号日固定，不向 T+1 市场状态回写。
4. core 成交规划在滑点输出 fill_price 后、apply_buy/apply_sell 前统一校验：BUY fill_price<=limit_price，SELL fill_price>=limit_price；若 absolute lower/upper limit 已知，成交价格还须处于其区间。违反时无状态变更、REJECTED/明确 reason、零股零费；禁止把价格夹到边界后成交。
5. MarketBar 增加可选、显式单位为 raw currency/share 的 absolute_limit_up_price / absolute_limit_down_price（或等价类型）；构造校验有限正数及上下界顺序。未知不表示无限制；新基线缺 required boundary 时拒单。旧路径 None 不改变行为。
6. 延续一次性 T+1 DAY 生命周期、卖先买后、T+1 锁定、费用与滑点归因。不可成交余量不顺延；容量部分成交若允许，成交部分逐笔满足限价，余量当日结束并记 capacity reason。

## TDD 验收矩阵

- OrderIntent：旧 positional/keyword 调用通过；买卖限价 None/有效值通过；0、负数、NaN/Inf、bool 拒绝；现金预算互斥及卖单 shares 契约不退化。
- 方向与 tick：1元边界拒绝；正好 1 tick 内/外、比例边界需向保守档取整；买限价以上和卖限价以下各一档均拒绝。
- 执行价格：开盘价价内，滑点后仍在限价内则成交；滑点使价格越限则整单拒绝且现金、持仓、费用均不变；绝对上下界内成交、越界拒绝；绝不截价。
- 价格信息：参考价缺失、复权/单位未验证、required corporate action reference unknown、必需绝对边界未知，分别产生明确拒绝且没有成交；已知边界不得读取执行日 close。
- 时间与数量：只用 T close 生成限价及 shares；改动 T+1 open 不改变订单股数/限价；卖款不可资助同批买单；T+1 停牌/涨跌停与既有方向 gate 语义不变；DAY 未成交余量不跨日。
- 成本兼容：按限价估股后实际滑点价和费用不超订单预算；现金路径只扣成交金额与实际法定费用，滑点已在成交价中不得重复扣；legacy cash_amount 的原有测试不变。
- 集成：原始行情 provider 的 raw close/reference/来源状态只映射有效字段；未知仍 unknown；相同候选输入共享完全一致执行配置；TDD 单测先行，最后跑 core 与 CNN 相关回归门。

## 明确未覆盖

当前数据接线还不能证明 reference_price 可用，也没有 absolute legal limit price。该方案不能用于宣称真实开盘排队、部分成交容量真实性、全市场覆盖、策略收益通过或成本后跑赢基准。实施前必须先解决字段来源契约；本设计不授权训练、回测选参、绩效计算、提交或推送。
