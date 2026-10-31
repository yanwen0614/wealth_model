# 分批候选账户运行器设计

范围：只读设计交付。执行实现必须等 StagedOrderStrategy/bridge 及其规则和接口冻结；本计划不认定当前 owner 分支的临时行为。

## 最小实现方案

1. 新增独立入口模块，不在现有 `run_cnn_backtest` 上套 `ExitOnlyStrategy`。加载冻结的完整 prediction cache 与执行日历，按 `date` 构造完整 rank map：ready 且 exp_ret finite 的全宇宙按 exp_ret 降序、code 升序；buy_eligible 只门 BUY，不删榜、不压缩排名。rank<=5 为买资格，rank>10 为退出信号。
2. 每个策略臂单独构建 `AllocationRegistry(C)`、冻结策略、`StagedExecutionBridge`、raw provider、公司行动 hook 和运行身份。策略本身管理 E/buffer 与 SELL，使 SELL 保留 episode/order/limit 身份；终端治理只拦截所有进入 buffer 的 BUY、取消后续未投份额，不重建订单。
3. 直接调用 core `run_account_backtest_from_orders(execution_calendar=全真实日历, signal_dates=完整策略决策日, strategy=staged_strategy, market=raw_provider, observer=bridge, account_actions_provider=..., cost_config_resolver=resolve_historical_costs, ...)`。使用 `ExecutionConfig(t1_open, final_liquidation=mark)` 与 daily rebalance；anchor 为期初前一市场交易日 close。不得以 `force` 尾清仓替代真实退出，所有评估依 snapshots 标记 NAV。
4. observer 的每个快照/成交/终态驱动 registry；同日核心实际账户状态是现金、持仓、locked、应收、未上市权益、活动单事实源。策略预算仅承诺登记，不复制撮合或资金账。现金红利采用 `cash_dividend_20pct_stress`，明确不是实际税制；历史佣金假设、历史印花税/过户费、同一 core 滑点/容量配置各臂一致。
5. 每个信号日生成全宇宙 rank 快照，即使买入资格为零或落在期末；coverage unknown 不允许先筛股票再重排。拒单/unknown 形成带候选 rank、side、数据源及原因的事件，结果只能标“受限日线机械模型/覆盖不足”，不能用全拒单零收益声称策略验证。

## 窗口、buffer 与资金路径

- Reset W1、W2：分别从冻结的 1,000,000 元 C 独立开始，各自 `B=C/5`；属于独立 reset 实验，绝不拼成连续收益。C=100,000 元可预登记为成本敏感性全报告，不替代主表。W1/W2 基准端点固定为沪深300价格指数 +0.244709%、-5.435019%；基准暂用，不代表最终验收基准已定。
- 半年主收益从前一市场交易日 close 的初始现金锚定至半年末 close；等待、空仓照算。E 后最多3个真实市场交易日 buffer，只可 SELL/公司行动结算，结束报告残仓、locked、应收、未上市权益、活动单；另列 buffer 后同时间基准结果，不能覆盖半年末主收益。
- 每窗预先生成 `禁买执行日集合`：所有执行日落入各窗口 buffer 的 BUY 均禁止，包含 buffer 首日前一信号排队的 BUY；E 日信号仍用完整排名决定退出。不得隐式把 buffer 的 SELL 换成无身份清仓指令。
- W1 buffer 与 W2 决策若连续日历相接，建议以连续年路径的实际日历定义唯一全局禁买集合：W1 E 次日开始的3个交易日全部禁 BUY；W2 首个可执行 BUY 必须执行日严格晚于该集合末日。W1 buffer 未清仓、订单未终态、未上市权益或预算槽未完成时均保留原账户和 registry 状态，W2 不得 reset/释放旧预算；新 W2 episode 仍须 `available_cash - active_uninvested_commitments >= B`。将禁买日集合及上述跨窗衔接作为开跑前冻结项。
- Continuous 年度仅一次 core runner 调用，保留真实账户、预算、episode、活动单及事件账；半年度标签只是 NAV 切片与对应基准，不是重建 initial_state。当前 core 无 `initial_state` 输入，故不得把两个 reset 结果拼接。
- 每个半年窗口独立给 PASS/FAIL/INCOMPLETE；全年正收益不能覆盖单窗不达标，buffer 清算收益亦不得替代半年 close 主绩效。

## 阻塞与放行

- W2 信号阻塞：W2 checkpoint `logs/relative/run_20261026_212052` 的 loader 修复 QA 未通过前不生成信号；W1 checkpoint 为 `logs/relative/run_20261026_100509`。模型、缓存和信号须各有 hash 身份。
- 当前机会诊断 879 需求仅4条日线机械条件 GO，875 条 unknown/需广覆盖假设；另有5个缺 bar 日期有已存逐码停牌事件证据，必须不撮合并持仓等待。190 HDF 子集不能缩小宇宙。±4.5%只是数学条件包络，SQL 无行不证明正常，也不等同官方价。
- 日线模型绩效放行至少需要：完整股票日历/退市与上市生命周期宇宙；逐码逐日状态响应完整性/缺码重试证据；权威 ST、停牌、官方 reference 与绝对上下限及来源版本；完整 raw OHLCV/amount 和缺 bar 解释；公司行动完整性、可审计的 ex/record/pay/listing、股数舍入及权益估值；指数真实交易日及端点；模型信号/cache/checkpoint/raw/状态/公司行动文件 hash；成本、容量和限价参数冻结；重复行/缺数据归因与账户守恒通过。无需队列/盘口/订单到达证据来跑日线机械模型，但没有它们不能称真实9:30成交。
- 必须输出受限覆盖运行的拒单归因及“可解释机会覆盖率”；覆盖不达预登记门槛时绩效状态为 INCOMPLETE，不能把拒单当经济性证明。具体门槛先由主会话在绩效运行前固定。
