# 分批策略独立合成验收预言机

本目录是只读设计审查的交付物，依据 `three_day_candidate_registry.md` v1、`staged_policy_strategy_plan_20261026/PLAN.md` 及 backtest-core commit `893fc96925e029098f6c758dba8724d187c6b512`。产物是后续 QA 的合成输入与期望，不是策略收益、真实成交能力或全市场数据验收。

## 文件

- `fixtures.json`：15 条最小对抗轨迹（含 2026-10-27 主会话裁定后的 `ruling_2026_10_27` 标注）。金额和日期是人为构造，用于确定账户、承诺、持股、订单行为与拒绝原因。
- `REVIEW_CHECKLIST.md`：逐条执行时需要检查的断言、冻结冲突和裁定项；裁定后的旧意见保留在“历史审查记录”供审计。

每条轨迹中的交易日均为连续交易日序号 D0…；BUY/SELL 意图在该日收盘决策、下一个可执行开盘执行。未另行标注时，`available_cash` 是 core 权威可用现金，承诺是完整 B 槽的未投入部分。夹具不预设新策略 API，不可直接导入新实现；独立 QA 应在策略 API 冻结后写适配层，按行为比对。

## 执行边界

仅使用微型日历、合成账户快照、排名与订单反馈。检查失败原子性时比较操作前后的 registry/策略快照和去重账本。缺少冻结 API、事件或限价信息时应报告 BLOCKED，不通过臆造签名绕过。

禁止把 synthetic PASS 写成收益验收。任何绩效阶段仍须另行满足数据身份、完整信号、成本/价格、状态覆盖、连续资金与预先冻结的考核窗口要求。

## 关键冻结依据

- Registry v1 第 9–13、23–42 行：承诺、free cash、三份时钟、DAY 不追补、全清才释放、buffer 与连续路径。
- PLAN 第 17–24、33–49、55–86 行：策略输入/输出、Observer、调用顺序与验收矩阵。
- CNN `staged_allocation.py` 第 160–166、200–217、236–259、359–445、491–502 行：承诺计算、开槽、advance、snapshot/feedback、自动关闭。
- core `893fc96` `contracts/order.py`：OrderIntent 限价固定股数；`contracts/execution_feedback.py`：执行更新身份与账户前后态；`contracts/account.py`：T+1 locked/持仓/权益状态；`contracts/protocols.py`：observer 和 account view。
