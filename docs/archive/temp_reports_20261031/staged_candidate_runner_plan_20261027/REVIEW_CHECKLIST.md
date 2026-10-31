# Runner 实施与只读复核清单

## 冻结身份及调用

- [ ] 记录规则 registry v1、oracle 15 cases、策略/bridge 最终源码与测试 SHA；明确实际运行的是哪一冻结版本。
- [ ] 记录 core 893fc96/schema 1.3 与安装 wheel 身份；CNN 主区34bd8e4及 provider ead9fc6合入身份；确认 dirty 状态不会混淆实际导入模块。
- [ ] 按 core 真实签名调用单个 `run_account_backtest_from_orders`；全交易日历、信号日、anchor、maintenance/buffer 日严格单调且真实；observer、账户行动、历史成本 resolver 原样接入。
- [ ] 禁止传统 `ExitOnlyStrategy` 改写 staged SELL；E/buffer SELL 保留 episode/order/plan/tranche、shares、冻结限价；buffer 内所有 BUY（含已排队）被取消/禁止并留证。
- [ ] 使用 `final_liquidation=mark`，不生成 `FORCED_EXIT`；close NAV 与现金、应收、未上市权益、持仓估值守恒；主窗点固定半年 close。

## 信号、政策和资金

- [ ] 每日以 ready+finite 全宇宙排名，exp_ret 降序/code 升序；期末排名照留；buy_eligible 仅 BUY 门；未知 coverage 不先筛后重排；rank<=5 BUY、rank>10 EXIT。
- [ ] B1/S1/S2/C70 共用同 cache/checkpoint/raw/成本/容量/滑点/账户初始资金；没有隐含 min_edge。S1、S2 时间和持续资格按冻结 registry 与 oracle。
- [ ] B0 因既有 min_edge 身份未明，默认 BLOCKED；只有基线 config/源码证据冻结其开关/数值和订单身份后才可加入，不冒充完全对照。
- [ ] B 固定 C/5；最多5个活动预算槽；新 episode 检查 core available_cash 减活动未投入承诺 >=B；回撤/退出不得挪用他槽预留，不以清仓或半年边界扩容。
- [ ] C70 承诺完整 B、累计 BUY 实际现金借记上限0.7B（含真实费用）；剩余承诺直到 episode 完成仍占槽；卖出收入不冲回投入额。
- [ ] 持股证券代码≤10；另报持股/权益/活动订单各类及去重代码占位并集；未确认卖出不腾位。
- [ ] 使用现金分红20%压力政策并标“非实际税制”；分享/送转未知、事件来源缺失须明确拒绝/不完整，不伪装税后结果。

## 窗口和结果审查

- [ ] Reset W1、W2 分开跑；各自 C=1,000,000，W1/W2 benchmark 固定 +0.244709%/-5.435019%；C=100,000敏感性预登记且全报。
- [ ] 主收益锚为前一市场交易日 close，终点半年最后交易日 close；闲置现金照算。分别列半年 close 主绩效和最多3日 buffer 后绩效及同时间基准。
- [ ] Continuous 为单次 core 调用；跨半年度只切换已冻结信号，不清空 core account/registry/episode/承诺/预算/权益/活动单/历史NAV。
- [ ] 事前冻结每窗禁买执行日集合。W1 buffer 与 W2 首个开仓的衔接按 PLAN：buffer 全部3日禁买，W2 BUY 执行日须严格晚于 buffer；未终态事项跨窗延续。
- [ ] 任一单窗失败不可由全年覆盖；残仓、locked、应收、未上市权益、活动订单全量报告。终端现金非零或未清算不构成自动失败，但不得宣称已全现金。
- [ ] 覆盖不足只报受限日线机械模型/INCOMPLETE；拒单与机会归因完整。不得把unknown全拒单结果称盈利验证，也不得声称真实队列成交。

## 必要的数据/执行断言

- [ ] 真实指数交易日与基准端点吻合；前收锚、半年 close 与 buffer 末日期逐项来源一致。
- [ ] 逐日 snapshots、持仓代码数、NAV 恒等式、现金借记=成交额+佣金+印花税+过户费、限价裁决、DAY 单次终态、T+1锁仓、费用断点通过。
- [ ] 保存 orders/fills/rejections/locked/capacity/unknown/coverage 逐行身份；同一事件重复幂等、冲突与旧 sequence fail closed。
- [ ] 日线执行所需完整宇宙、来源完整性、状态、官方绝对界、raw OHLCV、公司行动、缺bar原因满足 PLAN 数据清单；缺队列数据不阻断日线机械回放资格，但限制成交表述。
- [ ] 写入源码、wheel、checkpoint、prediction cache、raw、状态证据、公司行动、指数、配置的 SHA-256 manifest；运行前后核验导入模块及仓库身份未变。
