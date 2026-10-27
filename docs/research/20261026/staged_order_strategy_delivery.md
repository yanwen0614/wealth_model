# 分批限价策略单窗模块交付

2026-10-27。实现由Luna独立工作树owner完成，15条独立oracle审查及第1轮最小修复复审由另一Luna完成；主会话收口提交。

## 已实现

- B1、S1、S2、C70的完整C/5预算槽、未投承诺和真实BUY借记；复用权威core观察器，不复制账户或撮合。
- 全ready/finite宇宙按预期收益降序、代码升序排名；BUY资格限制所有新买单含存量加仓，不删除排名或阻止SELL。
- t0/t3/t6收盘决策、原交易日历不顺延；S2持续排名区间、零股/拒单/部分成交及DAY终态不追补。
- 固定整数股数，T raw close×1.045向下取tick为买限价、×0.955向上取tick为卖限价；执行日法定界交core裁决，不用T日界夹价。
- 次日历史费用resolver或显式worst-case费用预算；已排单限价/股数、真实成交股数/现金借记进入tranche台账。
- 同代码周期和资产/活动单未清不重开，其他代码按槽位/free_cash/保守代码并集独立准入；退出取消计划，全清才释放。
- E收盘向首buffer开盘排身份限价SELL；buffer维护不读取不存在的预测，残仓/权益/锁仓如实保留。
- 明确来源占位（含unknown、空白和None）在快照构造时拒绝；生产文件hash绑定由运行器另验。

## 质量门

- 初次独立QA确认unknown占位可BUY，旧FAIL与最小反例保留。原owner仅修策略构造器及负测试，未放宽任何BUY门。
- 修复后54项unittest通过：allocation38、bridge5、strategy11；六目标文件Ruff及Pyright零错误，diff检查通过。
- 真实core合成端到端覆盖固定限价买卖、身份、DAY部分成交不重排及无预测buffer维护。
- 第1轮复审对单窗模块scope A明确PASS；源码及测试冻结SHA见原交付报告和ROUND1_QA_MANIFEST.json。
- core版本893fc96/schema1.3，wheel SHA256：76cc80e5fa8fa39513a21876137a5e1c99e001b7c74801a78b76345554d72470。
- 独立证据目录：临时根staged_policy_final_qa_20261027/及staged_policy_final_qa_round1_20261027/，原FAIL不覆盖。

## 尚待生产运行器验收

- source_id与实际信号/checkpoint/calendar/window/profile及完整排名摘要绑定。
- 生产日历恰好最多3个buffer交易日；四buffer日的模块压力夹具不能替代此边界。
- 连续年度用共享registry/bridge的上层路由保留真实资金、权益和计划，不能拼reset半年净值。
- 完整执行输入覆盖、逐日NAV/现金/持仓/成交/拒因输出，以及成本后非负和跑赢同时间基准要求。
- 当前结论只覆盖单窗模块，不是生产绩效或真实9:30成交验收。
