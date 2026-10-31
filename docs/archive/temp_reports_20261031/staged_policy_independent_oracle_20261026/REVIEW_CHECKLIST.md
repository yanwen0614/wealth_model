# 独立审查清单

## 15 条合成行为

- [ ] 01 亏损退出后可用现金低于 B，且另有活动槽承诺：拒绝新 episode；不借预留现金。
- [ ] 02 C70：完整 B 槽占用，只累计投资至 0.7B（费用计入）；commitment=B−累计BUY借记，余0.3B继续占用至 CLOSED，不得重复扣完整B。
- [ ] 03 t0 拒单：t3/t6 仍按原交易日计数；拒单不重启时钟。
- [ ] 04 S2 边界：t3 tranche 检查 t0…t3；t6 tranche 检查 t3 之后…t6，t3 不重复归入后段。
- [ ] 05 t6 上午/开盘前快照：不能终结 t6 收盘决策份额。
- [ ] 06 无持仓但未来份额未全部取消/终态：保留 episode/槽；先取消全部未来份额，且仓位、锁仓、权益、活动单全空才释放。
- [ ] 07 T+1 locked、未上市权益或活动卖单各自非空：退出后继续占槽；不重开同代码；其他代码不受 exit_pending 全局禁开影响（按裁定改为仅同代码）。
- [ ] 08 部分 BUY / DAY 余量：订单终态后不追补、不滚存；仅允许原定后续 tranche；DAY 由真实 runner pending.pop 留证。
- [ ] 09 buffer 起点：拒绝新 episode 和所有 BUY（包括最后决策日排队 BUY），BUY 禁次日 buffer；SELL 保留身份与限价继续允许。
- [ ] 10 实际股数、worst limit 与费用预算：固定整数股数；现金路径按 core 前后现金及三项真实费用核对。
- [ ] 11 缺 rank、重复 rank/代码、缺 close、source unknown：fail closed；不得偷看 T+1。
- [ ] 12 重放同事件幂等；冲突 ID、乱序 sequence 与失败输入原子拒绝。
- [ ] 13 跨半年连续状态：不得 reset 现金、预算承诺、持仓、权益、应收或活动单。
- [ ] 14 E/buffer 退出路径：E 日完整排名仍可用于退出判定；ExitOnlyStyle SELL 必须带 episode/order 身份与冻结限价；BUY 在 buffer 起点即禁。
- [ ] 15 名额口径：正持股代码数≤10；正持股/权益/活动单的去重代码并集≤10；未确认卖出不腾位；报表分别列三类与并集。

## 需在独立 QA 留证

- [ ] 每步记录日期/阶段、core cash/available_cash、活动承诺、持仓/locked/权益/活动单、候选订单及理由。
- [ ] 事件拒绝后逐项比较 registry、策略计划、快照游标与 seen/event/fill ledger 未改变。
- [ ] 核验订单只含整数 shares + 冻结 limit，不含 cash_amount；开盘裁决后有终态反馈。
- [ ] 仅 synthetic contract verdict；不运行收益、IC、调参或大数据。

## 冻结规格冲突 / 裁定项

| 分类 | 证据 | 最小例与判定 |
|---|---|---|
| 已裁定 | 用户 2026-10-27 裁定；registry v1 第 9–13、33–34 行；PLAN 第 17–18、57 行 | `commitment = B - 累计真实 BUY 现金借记`。未投入/取消部分保持占用至周期 CLOSED；C70 余0.3B仍在承诺。完整B槽计一次；不得在买入后再次从可用现金重复扣除完整B。夹具02须断言借记后未投入承诺相应减少、剩余继续占用、槽数仍为1、open_episode 的 free_cash 检查只按减后的承诺一次计算。 |
| 已裁定 | 用户 2026-10-27 裁定；PLAN 第 22、40、48 行；CNN staged_allocation.py 第 491–502 行 | 退出须先取消全部未来份额；有任何资产/锁仓/权益/活动单不关闭；仅 mark_exit_pending 而尚未取消计划不能自动关闭。现实现的 `_sync_exit_state` 在 exit_pending + 代码不在 active_codes 即 CLOSED，与裁定冲突（见下方仍待修的实质错误行）。 |
| 已裁定 | 用户 2026-10-27 裁定；CNN staged_allocation.py 第 203–213 行 | 只禁止同代码重开；`any(exit_pending)` 全局禁开是额外限制，应移除。其他代码仍须通过五槽、free_cash 与保守代码并集名额检查。 |
| 已裁定 | 用户 2026-10-27 裁定；registry v1 第 35、40 行 | 固定预算策略实际正持股证券代码数≤10；同时记录权益/活动单占位。未确认卖出不腾名额。报告须区分“正持股代码数”与“权益/活动单占位数”，不得把占位误报为正持仓，也不得漏计占位。 |
| 已裁定 | 用户 2026-10-27 裁定；core `account_runner.py` 第 1738–1740、1776–1786、1366–1381 行 | DAY 语义由真实 runner 留证：`pending.pop(trading_date, ())` 单次取出执行，余量不重新排程并发布 terminal。不需要新增 TIF 字段；独立 QA 应用真实 core runner（893fc96）夹具取证，不靠接口形状推断。 |
| 已裁定（新增边界） | 用户 2026-10-27 补充；CNN `ExitOnlyStrategy`（runner 内退出/buffer 路径） | 既有 ExitOnlyStrategy 在 E 及 buffer 重建的 SELL 不带 episode/order/limit，不可直接套给新 staged 桥接。验收要求：E 日仍有完整排名用于退出判定；BUY 在次日进入 buffer 时必须被禁；所有 SELL 保留 episode/order 身份与冻结限价。策略 owner 自行处理终端，本验收只查行为，不读其实现。 |
| 实质错误（仍待修） | PLAN 第 47 行；CNN staged_allocation.py 第 236–239、494–497 行 | `advance(D6)` 设 current_day=D6 后，任一 snapshot/feedback 触发 `_sync_exit_state`，因 `current_day >= plan_end_date` 关闭空仓 episode，早于 D6 收盘 tranche。日期推进与 close-finalize 应分开。 |
| 实质错误（仍待修） | CNN staged_allocation.py 第 491–502 行 | `_sync_exit_state` 未检查未来份额是否全部取消/终态即按 exit_pending/plan_end 关闭；且买入后 commitment 扣减已发生，CLOSED 时机错误会提前释放仍被未投份额占用的资金。需按裁定以“全部未来份额已取消/终态 + core 四项全清”为准。 |
| 明确保守政策 | PLAN 第 24、66 行；core AccountState/Observer | 缺 rank/close/source unknown fail closed 是安全拒单额外政策；须区分数据拒绝和 rank 不合格，不可静默缩小 universe 后重排。 |
| 明确保守政策 | PLAN 第 35–45 行；core ExecutionUpdate | 同一 update 必须有 post_state；乱序 sequence 严格拒绝；core 契约有前后状态、event_id/sequence、fill 身份，属可实现的 fail-closed 规则。 |

## 历史审查记录（保留供审计，已被上方裁定取代）

- 旧裁定项：commitment 语义与 C70 台账归属（原“需主会话裁定”）→ 已由 commitment=B−累计BUY借记 裁定取代。
- 旧裁定项：`any(exit_pending)` 是否全局禁开（原“需主会话裁定”）→ 已改为仅同代码禁开。
- 旧裁定项：持仓≤10 是否计入权益/活动单跨代码占位（原“需主会话裁定”）→ 已裁定为正持股≤10且占位单独记录。
- 旧“冻结契约缺口”：core OrderIntent/ExecutionUpdate 无 DAY/TIF 字段 → 已由真实 runner 证据（`account_runner.py:1738–1740,1776–1786,1366–1381`）解决，保留为历史意见。
- 初版两条重复的 `_sync_exit_state` 实质错误行已合并为上方“仍待修”两行。

## 关键接口核对

- core `893fc96` `OrderIntent` 支持 `shares` 与 `limit_price`，带 limit 时拒绝 `cash_amount`；没有 `time_in_force`/DAY 字段。
- core `ExecutionUpdate` 有 event_id、sequence_no、phase、trading_date、episode/order/attempt/fill IDs、pre/post `AccountState`、cash_delta、active_orders；Observer 是 callback protocol。
- core `AccountState` 提供 cash、available_cash、positions、locked、cash_receivables、unlisted_entitlements、pending_cash；活动订单在 `ExecutionUpdate.active_orders`，不是 AccountState 字段。
- Registry 以代码并集 positions/locked/entitlements/active orders 算 active_codes（CNN 第 173–179 行）；snapshot 输入的 `active_order_codes` 必须来自 update 的订单快照。

## 本清单适用的冻结旧基线（不是 owner 当前实现声明）

- CNN commit `ead9fc6ca13844dc262132a39f036fe385040206`。
- `staged_allocation.py` blob `204cb54b09072f6167d3c6ef92356bd74042565a`。
- `staged_execution_bridge.py` blob `758087278a307792a3f7c6e868dc644d1df33761`。
- 该冻结基线存在的待修结论只适用于以上身份；禁止外推为 owner 独立树当前状态。
