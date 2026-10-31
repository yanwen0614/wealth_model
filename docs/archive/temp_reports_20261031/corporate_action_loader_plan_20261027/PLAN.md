# Staged runner 最小公司行动加载与上下文钩子计划

## 目标与边界
- 为单窗 reset 的真实 Staged 候选 runner 提供可追溯公司行动输入与 core 账本钩子；复用 `CorporateActionProvider`、`account_actions_provider`、`StagedExecutionBridge`，不另建现金账或推测交易所规则。
- 本计划面向独立树 `staged-runner-v2-20261027`；实施前 Generator 应先读该树实际文件并对照差异，不假设主区 runner 即新树版本。
- 只承诺机械应用已知字段的税前现金/总送转权益；实际税后收益、零碎股、送转税、舍入及公告可知时点未证不得宣称已实现。
- 首个验收范围为明确 execution calendar、prior-close initial reset anchor 的单窗；continuous 状态延续另立任务。

## 已核架构与最小影响面
- 主区：`backtest/cnn_adapter/corporate_actions.py` 规范事件和日操作；`runner.py` 接入 action hook；`staged_execution_bridge.py` 将 `ExecutionUpdate.post_state` 投影给 allocation registry；`staged_allocation.py` 的 occupied 代码来自权益代码集合；E2E 在 `tests/unit/backtest/test_corporate_action_runner_e2e.py`。
- core：`engine/account_runner.py:1590-1612,1719-1808` 订单入口、时钟、observer；`engine/account.py:105-192` 行动账本语义。core 源保持只读。
- 优先只改新树 runner/加载适配和针对性测试；若发现必须改 core 契约，暂停并单列设计，不在本任务默默扩范围。
- 复用搜索结论：provider 已提供事件指纹、阶段操作和现金 stress；bridge 已读完整 post_state；无需增加平行账本。当前缺口是上下文过滤、有效权益占位过滤、输入字段证据映射。

## 接口草案
- 加载器只从冻结原始行/显式输入快照构造 `CorporateActionEvent`，每条事件保留 source table/id/hash/version、原始进度码及字段值证据；不把进度码“3”当官方完成证书。
- 组合 observer 顺序转发到 `StagedExecutionBridge`，同时只读保存最近完整 `ExecutionUpdate.post_state`；不得改写 update 或吞掉 observer 异常。
- `account_actions_provider(day)` 按阶段先筛本日事件；Record 日无条件为候选事件输出 `RecordPosition`，让 core 在开盘订单之后登记真实持仓。Ex/Pay/List 仅对已观察到对应 core record operation 且登记数量严格大于 0 的事件发操作。
- 对无登记记录（包括 reset anchor 前登记日）或登记数为零的事件，不创建/支付/上市，避免 missing_record 与零权益幽灵对象；有正登记权益时字段/规则不全立即 fail closed，保留部分运行证据并标 `INCOMPLETE`。
- 同一公司同一方案的 bonus+capitalization 只生成一条 `kind=capitalization` 的复合股权事件，`share_ratio=T`，来源元数据另存 B/C/T 分项；不将 B、C、T 相加重复计权益。比例缺项时不以 C 回退 T。
- 不持有权利认购；rights issue 保留为 coverage/unknown 证据，不凭公告日合成 record/ex/list 或成交。

## 实施任务（依赖顺序）
1. T01 新树侦察：核文件、调用签名、observer 是否可组合、reset 锚点、原始 loader 状态；列出偏离本计划处，冻结实现范围。
2. T02 规范输入映射：固定字段白名单、row identity/hash、进度原值、日期与比例校验；加入仅有可证字段的机械事件转换，未知项形成 coverage。
3. T03 上下文钩子：组合 observer 保存 post_state；provider 对 record/ex/pay/list 按登记操作 ID 和登记股数筛选；确保 action ID 稳定幂等。
4. T04 占位投影：bridge 的 `unlisted_entitlement_codes` 仅取 shares>0 的 core entitlement；若无法在新树安全改投影，则另提最小接口决策，不能只在展示层掩盖。
5. T05 合成真实 core E2E：覆盖下列清单，断言阶段顺序、账户现金/股数、部分证据及 provenance。
6. T06 单窗验收：运行新树指定窄测试与只读输入复核；验收通过后交主会话安排 Quality Gate，不由本计划代理启动编码。

## 冻结证据与验收门槛
- 输入快照共 8740 原始行；进度 `3`:3506、`1`:4112、`2`:1119；`1/2` 的 record/ex/pay/list 全缺，README 对 `1` 的“已实施”描述不作证书。
- 3148 行进度 `3` 且 ex 落观察窗；8 行 B、C 均正且 `T=B+C`。两固定样本仅证明 fixture：000001 现金 0.18；300896 现金 3.5、T=0.8。right_issue 仅有公告日期。
- P0 通过：未持仓未知事件不阻塞账户；同日开盘买入可登记；登记后除权前卖出仍获现金/股权益；锚点前无 record 不触发 missing_record；零登记无应收/无 entitlements/无 occupied code。
- 正权益未知上市日、非整数股、舍入/税未知时明确 fail closed + `INCOMPLETE`，不 floor；20% stress 只标现金压力场景。
- 回测产物必须标 source fingerprint、scope=single-window-reset、税务非实际、coverage 与 incomplete 原因；未证明实际税后目标不得进入排名/结论。
