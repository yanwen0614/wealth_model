# Harness 进度：Staged 公司行动 loader/hook

## 执行约束
- 当前角色：Task Decomposer，只读分析并产规划；不编码、不修改 repo/env/数据库、不派遣代理。
- 用户已授权三天自主研究；当前规划完成后交主会话调度 Generator。
- 目标编码树：`staged-runner-v2-20261027`；本任务没有在该树定位或改动文件。
- 文档独立输出于 `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate_action_loader_plan_20261027/`。

## 任务状态
- [x] 阅读主区 `corporate_actions.py`、`staged_execution_bridge.py`、`staged_allocation.py`、`runner.py` 与指定 E2E 测试。
- [x] 阅读 backtest-core `account_runner.py:1590/1719+` 与 `account.py:105-192` 的日时钟和权益应用逻辑。
- [x] 核对冻结 Task2 原始 JSON、metadata 与字段关系诊断；未将 README 进度标签当字段证书。
- [x] 完成 `PLAN.md`、`REVIEW_CHECKLIST.md`、本进度文档；每份均控制在 50 行以内。
- [ ] Generator 在独立目标树核对实际 runner 结构并按计划实施。
- [ ] 主会话调度 Quality Gate 与验收；本角色不启动代码或测试。

## 关键核验结论
- runner 的 action hook 在每个交易日开盘前调用；core 随后先应用 Ex，再执行当天已排程开盘单，再应用 RecordPosition，因此登记操作会记录当日开盘成交后的真实持仓。
- `CreateCashReceivable` 与 `CreateShareEntitlement` 要求 record operation 存在；`CashPayment`/`ListShareEntitlement` 要求恰有一条既有权益。日终 `ExecutionUpdate.SNAPSHOT.post_state` 可由组合 observer 完整留存供下一日上下文判断。
- 当前 provider 遍历全量事件，阶段规则可能先于持仓过滤失败；bridge 把所有 unlisted entitlement code 纳入 occupied，含零股幽灵权益风险。
- 冻结输入 8740 行：进度 3 为 3506，1 为 4112，2 为 1119；1/2 的 record/ex/pay/list 全缺。进度 3 且除权日在窗 3148 行；B/C/T 同时可见且 B、C 正值的 8 行均 T=B+C。
- right_issue 仅公告日期。实际税务、送转税、舍入与上市缺失、零碎股规则均无证据；对正登记权益必须 fail closed 并标 incomplete。
- 测试需覆盖“当日开盘买入可登记”与“登记后除权前卖完仍有权益”；不能按 actions hook 调用时的开盘前零持仓提前丢弃记录。

## 后续移交
- Generator 启动前应读取新树 AGENTS.md（若存在）及实际调用链，确认组合 observer 与 account hook 的真实接口。
- 若新树 runner 或 core 版本与本次只读快照不同，先更新计划判断；不把不存在的 API 当成既定事实。
- 任何 core 必需改动、实际税后目标或 continuous 状态延续均需独立影响评估。
