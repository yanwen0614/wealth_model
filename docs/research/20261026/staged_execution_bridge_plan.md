# 分批组件与 core 真实成交反馈桥接方案

状态：只读设计；不改业务码、不运行绩效/IC/训练。本方案须等税务工程 owner 提交 runner/core 改动后再实施，并先复核其最终接口。

## 当前契约与缺口
- `OrderStrategy.orders_for(...)` 接收 `AccountView` 并只返回 `OrderIntent`；没有成交回调。`AccountView` 有 cash、available_cash、positions、locked、nav，但没有未上市权益和活动订单。
- `AccountState` 已是不可变权威状态，含 cash、available_cash、positions、locked、cash_receivables、unlisted_entitlements、pending_cash 等；`AccountSnapshot` 是日终估值，含available_cash/positions/unlisted权益，但不含locked与活动订单。成交后桥接优先用core的AccountState，不从快照或成交股数重建状态。
- `TradeEvent` 有实际成交价、股数、amount、佣金/印花税/过户费/slippage_cost，但无 episode_id/order_id/fill_id。`OrderResult`每个被执行订单回一条汇总结果，只有原OrderIntent、filled_shares、fill_price、fees、reason；不支持唯一partial fill身份。
- core先执行待执行单（卖后买），更新账户/T+1锁定，再运行收盘策略；结果当前主要累积在EvaluationResult返回时，策略运行中没有通用observer。
- 当前CNN `ExecutionFeedback`已有episode/order/fill字段与快照雏形，但core没有可映射ID；快照只带available_cash、positions、未上市权益代码、活动订单代码，缺locked、权威全权益对象和订单级活动状态。非fill事件不刷新快照/退出状态。
- `ExecutionFeedback`若把core `OrderResult.fees`用于 `cash_debit = amount + fees` 会错：core fees含slippage_cost，而账户现金按成交额与实际三项费用变化，滑点已体现在成交价，不再次扣现金。现金借记/贷记必须取core账户状态转移，不由股数×价格或OrderResult.fees推算。

## 最小桥接契约
- Episode归属由策略在 `OrderIntent` 生成时显式附 `episode_id`；同一episode可有多个order。`order_id`是一个逻辑订单跨partial fills的稳定ID；每次提交/重试另有 `attempt_id`；每笔实际partial fill有全局唯一且可重放的 `fill_id`。不得按证券代码/股数差猜归属。
- 每个observer更新带稳定 `event_id`、单调 `sequence_no`、phase、episode_id、order_id、attempt_id；fill更新另带fill_id及core原始TradeEvent。完全相同的重复fill/event幂等no-op；同ID不同载荷报错；旧sequence/snapshot不得覆盖新账户状态。
- 每次实际fill后的权威快照使用core不可变 `AccountState`（现金、available_cash、positions、locked、应收现金、未上市权益、pending cash）；另传core scheduler当前活动订单的不可变映射，至少含order_id、episode_id、代码、side、余量、执行日/状态。代码集合不能代替订单身份。
- core同时提供该次状态转换的精确现金delta，或pre/post AccountState；CNN据实际cash变化扣episode承诺。TradeEvent amount/三费/slippage用于核对与归因，不作为影子现金账。可用预算准入读取最新core `available_cash` 减去仍承诺预算。
- 拒绝、取消、过期也发带唯一event_id的终态更新及最新活动订单快照，但不得生成fill_id/成交/账户股数现金变化。failed若表示引擎错误应中止运行，不可静默当作拒单继续。
- exit_pending只由新鲜core快照确认解除：该代码positions=0且locked=0、无未上市股份权益、无活动订单。部分卖出、拒单/取消、advance日期均不清除。现金应收可作为已退出episode的单独未结权益结算，不得因此虚构持仓或漏记账户资产。

## 建议接口改动位置与兼容行为（owner提交后再实施）
- `backtest-core/src/backtest_core/contracts/order.py`：给 `OrderIntent` 追加可选 `episode_id/order_id`，旧构造默认None；启用分批桥接时强制非空。结果身份从OrderIntent沿用，增加attempt_id只在确有多次尝试需要时。
- `backtest-core/src/backtest_core/contracts/events.py`：给 `TradeEvent` 追加可选episode_id/order_id/fill_id/sequence_no；旧调用默认None。每次实际部分成交独立TradeEvent；OrderResult仍代表一次尝试的累计结果，不冒充fill事件。
- 新增 `backtest-core/src/backtest_core/contracts/execution_feedback.py` 定义冻结的 `ExecutionUpdate` 与 `ActiveOrderSnapshot`；复用现有AccountState，不复制账户模型。`contracts/__init__.py`导出公共类型。
- `backtest-core/src/backtest_core/contracts/protocols.py` 增加可选 `ExecutionObserver.on_update(update)` 协议；不在 `OrderStrategy` 增加必需方法，避免既有策略不兼容。
- `backtest-core/src/backtest_core/engine/account_runner.py` 仅给 `run_account_backtest_from_orders` 增加默认None的observer参数。observer=None时调用路径、EvaluationResult与旧策略行为不变；observer启用时异常向上传播，防止账本反馈失败后静默继续。
- `cnn/backtest/cnn_adapter/staged_execution_bridge.py` 只把core更新映射为分批组件反馈；`staged_allocation.py`只保留episode/预算策略状态，最新账户与活动单快照整体替换，禁止自行撮合或增减现金/持仓。

## 精确调用顺序
1. 交易日开盘前core先解T+1锁、释放应付现金并应用有效公司行动；分批registry只能接收该core快照，不能自行解锁/造权益。
2. 执行既有scheduled orders，core继续保证卖先买后。每笔实际partial fill先由core应用真实成交和费用、更新AccountState/T+1锁，再发fill更新（每fill唯一fill_id + 完整快照）；一次订单attempt结束后再发OrderResult终态与当前活动订单映射。
3. 拒单/取消/过期发终态更新和最新快照，不伪造成交。pending scheduler新增订单后发submitted更新；重试保留parent order_id、增加attempt_id，数量只传原剩余量。
4. 当日有效公司行动阶段完成及收盘策略回调前，发一次带sequence的权威快照；原 `orders_for(trading_date, signal_time, account, market)`签名不变。收盘支付/送转上市等阶段处理后再发snapshot，确保权益变化可见。
5. bridge按sequence消费更新；同一fill/event重放不重复改承诺或状态。若core snapshot倒退、episode/order映射缺失或反馈无法核对，立即失败关闭并保留最新已确认状态，不继续发新episode订单。

## 必要TDD与三个验收边界
- 有价值的core合成TDD：同一order两笔partial fill有不同fill_id、重复回放幂等/冲突ID失败；order尝试终态与fill事件顺序稳定；observer=None旧策略/旧构造保持兼容；observer在真实core状态更新后收到回调。
- CNN桥接合成TDD：现金delta来自core前后状态且不会二次扣slippage；available_cash不与cash混用；positions/locked/unlisted/活动订单的更新不丢；取消/拒单清除活动订单但不清除仍持仓的exit_pending；最后一股、锁仓、未上市权益、活动订单分别存在时均不能提前关闭episode；全清后仅由新鲜快照关闭。
- **合成通过**只证明接口、幂等与账本状态机在mock/mini AccountState下闭合；本审查未运行测试，不能宣称本轮已PASS。税务owner提交后按其最终接口重建/调整fixtures并执行独立TDD。
- **真实行情状态来源：BLOCKED。** bridge不补造历史ST/限价/停牌状态；需独立确认MarketDataProvider逐日字段来源、有效时间与unknown语义。合成回调通过不能升级为真实状态数据已验证。
- **策略绩效：未验收。** 本桥只准备真实core账户路径，不运行收益、IC、训练或候选比较；接口闭合和合成通过不代表交易可行性或最终收益目标达成。

## 实施冻结
- 工作区当前 `backtest-core` 的 `account_runner.py`、contracts、account actions等存在税务owner未提交改动。本设计不触碰这些文件；待owner提交后先检查最终diff/API，再由主会话安排Luna/DeepSeek实施与复核。不得并行改runner/core或替owner提交。
- 当前CNN生成器会话 `ses_e89c0199bffelOolRanu1xfy58`仍在修复。本计划只界定桥接边界；先由生成器交付稳定组件，再按上文adapter映射，不反向改写组件契约抢占其工作。
