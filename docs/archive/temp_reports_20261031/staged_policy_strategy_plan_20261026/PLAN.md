# StagedOrderStrategy 实施计划

> **实现约束：**主会话安排唯一编码者；按本计划逐项 TDD，完成独立规格与代码复审。此文档只定义工作，不授权并行修改 core 或 runner。

**目标：**按批准 registry v1 实现收盘决策、次开盘 DAY 执行的 B0/B1/S1/S2/C70 分批订单策略，并保持预算承诺、计划状态与 core 权威账户状态分离。

**架构：**策略读取 T 日已知排名、raw close 和实际账户视图，只生成带 episode/plan/tranche 归属的订单意图；预算登记簿只维护预算承诺和计划生命周期。成交、现金、持仓、锁仓、权益和活动订单由 core Observer 快照与事件驱动，禁止策略另建现金/撮合账本。

**技术栈：**Python 3.12；现有 `backtest_core` OrderIntent/OrderStrategy/AccountView；CNN `AllocationRegistry` 与 `ExecutionFeedback`；unittest 合成 core fixture。

---

## 事实源与冻结规则

- 规则事实源：`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_candidate_registry.md` v1；实施前记录其 SHA 和实施配置身份。
- 共用信号资格：收盘排名 `rank <= 5` 可买；`rank > 10` 触发退出；实际持仓/锁仓占用名额。
- 固定方案每周期完整承诺 `B=C/5`，最多五个 episode 槽，总承诺不超过 C。新 episode 必须 `core.available_cash - active_uninvested_commitments >= B`。
- B1 在首次合格决策投入 B。S1 在 t0/t3/t6 各计划 B/3；到期不合格则取消该份。C70 承诺完整 B，只能累计花费 0.7B（含费用），0.3B 始终锁定且不跨周期复用。
- B0 保留现有 target5/buffer5 动态现金分配，作为整体对照；只继承冻结 B0 配置中明确存在的 `min_edge` 门及数值。registry v1 未指定其数值：实施前从基线 config/identity 固定；若无门则关闭。不得给 B1/S1/S2/C70 添加隐含门。
- S2 t3 份额检查 t0 至 t3（含）每个收盘信号均 `rank <= 5`；t6 份额检查 t3 之后至 t6（含）每个收盘信号均 `rank <= 5`。t0 初份不成交不重启 t0，不追补；前份失格或未成交不改后续原定日期/区间。
- `t0/t3/t6` 是预定交易日计数的收盘决策日；每份对应次一可执行开盘的单次 DAY 裁决。开盘拒单、零成交或部分成交余量到期，不滚存、不追单。
- 退出 rank>10 时取消所有未来未投份额并进入 EXIT_PENDING。只有计划全部到期或明确取消，且 core 新鲜状态中 positions/locked/unlisted entitlement/active orders 全清，才关闭并释放周期预算。
- 红利按 core 实际可用现金/应收快照更新全局状态，不增加 B。亏损后 available_cash 不足 B 时拒绝新周期，不动用其他 episode 承诺。
- 只用 T 收盘已知 rank、raw close、T 时实际账户；不得先看 T+1 状态来筛/重排候选。unknown 来源或缺快照必须拒单并显式记录。

## 文件边界与最小公共接口

- 新增 `backtest/cnn_adapter/staged_order_strategy.py`：纯策略状态机、排名决策、份额计划与 OrderIntent 生成；不改 `runner.py`、`order_strategy.py`、core 或既有候选注册表。
- 新增 `backtest/cnn_adapter/staged_execution_bridge.py`：只映射 core ExecutionUpdate/Observer 到 `AllocationRegistry`；不得撮合、推算现金或持有影子 AccountState。
- 修改 `backtest/cnn_adapter/staged_allocation.py`：仅在冻结的 core 公共类型无法直接喂入时，最小扩充计划 ID/份额状态/周期完成状态；预算现金仍以 core `available_cash` 为输入，资产状态仍整体采用 core 快照。
- 新增 `tests/unit/backtest/test_staged_order_strategy.py`、`test_staged_execution_bridge.py`；只用微型日历、合成排名和合成 immutable AccountState/Observer 更新，不读大数据、不计算绩效。
- 暂不修改 `backtest_core`：core 唯一 owner 完成 public limit 字段和 observer/fill identity 后，实施者先按其最终签名调整 adapter；本计划不预写其字段树。
- **策略输入最小契约：**交易日/收盘信号时刻、当日完整且身份可核的排名映射、raw close（仅决策记录/限价计算，不用前复权替代）、core AccountView/AccountState（available_cash、positions、locked、未上市权益、活动订单）、固定配置/日历。
- **策略输出最小契约：**每笔订单有 episode_id、plan_id、tranche_id、side、整数 shares、T 日冻结 limit price、DAY 有效期、决策交易日/输入身份；不得使用 cash_amount 让 core 在 open 再折股。
- **Observer 最小契约：**稳定 event_id/sequence；每个逻辑 order 稳定 order_id；每次 partial fill 唯一 fill_id；明确 episode/plan/tranche 归属；实际 TradeEvent 与 pre/post 权威 AccountState 或精确账户现金转移；全量 positions/locked/现金应收/未上市权益及活动订单映射。订单终态另发更新。
- core `OrderResult.fees` 含 slippage，不能直接作为现金费用；金额、股数或成交价不用于猜现金变化。cash_debit 使用 core 实际前后现金转移核定；成交金额及三项真实费用用于逐项对账。

## 状态机与调用顺序

周期：`RESERVED → SCHEDULED → ACTIVE → EXIT_PENDING → COMPLETE`；取消未来份额仅标 `CANCELLED`，完整 B 承诺保持到 COMPLETE。份额：`PLANNED → DECIDED_ELIGIBLE/INELIGIBLE → ORDER_SUBMITTED → FILLED/PARTIAL/REJECTED/CANCELLED/EXPIRED`；终态不可重开，部分成交余量不补。

1. **开市前**：core 完成解锁/公司行动/应付现金与到期订单处理；bridge 按严格递增 sequence 消费账户快照和 order terminal 更新。旧日志按 event_id 幂等；旧 sequence 拒绝，不调用日期倒退或覆盖当前账户。
2. **开盘执行**：core 对上一收盘创建的 DAY 限价单作唯一裁决；每个 partial fill 先由 core 改账户，再发布含唯一 fill_id、order_id、episode/plan/tranche 归属及 post-state 的 observer 更新；无成交订单终态也必须更新活动订单快照。
3. **更新 registry**：先验证 event/fill ID、sequence、归属、金额费用/现金转移及 post-state，再原子登记 seen 与更新承诺；重复完全相同事件 no-op，ID 冲突报错，失败时不污染 seen、不改预算或 snapshot。
4. **收盘前账户输入**：消费当日最新 core 快照，保持 core 的 available_cash 与持仓/锁定/权益/活动订单为权威；该账户视图只用于当日收盘决策，不把 T+1 未知状态用于候选排序。
5. **收盘决策**：用 T 日排名筛 rank≤5 买入资格及 rank>10 退出；依原注册表更新当日已知持续资格，固定份额与限价，再发向下一可执行开盘的 DAY 单。rank 并列规则须与冻结信号身份一致，不新加重排键。
6. **advance/完成顺序**：`registry.advance(T)` 仅推进单调决策日，不执行到期/退出；先处理 T 收盘决策与 t6 份额决定，再调用 `finalize_close(T)` 标记日期届满的份额。t6 上午的 snapshot 绝不能因 `date == plan_end` 终结当日收盘尚未处理的份额。
7. **周期释放**：仅在所有预定份额均已终态（到期/明确取消/成交结算），且最新 core snapshot 中该代码 positions=0、locked=0、未上市权益为空、活动订单为空后 COMPLETE。现金应收留全局会计，不冒充可用现金；释放旧 B 不重置初始 C/B。
8. **buffer**：buffer 起点禁止新开仓和任何新 BUY（包括最后决策日排队单）；取消未执行 BUY/未来追加计划，等 core 终态与快照确认。允许卖出/清算；buffer 末仍持仓、锁仓、权益或活动单必须如实报告，不虚构全现金。

## 可直接执行的 TDD 任务与验收矩阵

所有阶段逐项 RED→GREEN；只跑对应新单测、静态检查由项目命令另行执行。禁止策略收益、IC、选参和大数据回测作为本计划验收。

### T01：registry 周期计划与槽位

- RED：测 C 固定后每周期 B=C/5；五个槽上限；free_cash 使用 core available_cash 减活动未投入承诺；可用现金少于 B（含亏损后）时新 episode 失败；取消与清仓不提前释放；C70 承诺 B、允许借记上限 0.7B（费用包含）、余 0.3B 保留；分红只改变 core 可用现金、不改 B。
- GREEN：最小状态仅保存 episode/plan/tranche 生命周期、承诺、已核实的累计 cash debit 和状态；不存第二份现金/持仓余额。增加状态的 dataclass 为 frozen，对外集合只读。
- RED：同一代码有旧非终态 episode、position、locked shares、未上市权益或活动单时禁止重开；仅完整计划完成且 core 全清后重置该代码 t0。其他代码可在满足五槽和 free_cash 时开周期，不得把“最多五个历史 episode”当生命周期限制。

### T02：资格、三次收盘时钟与份额计划

- RED：B1 仅 t0 一份 B；S1 t0/t3/t6 各 B/3；C70 首个合格收盘最多一份 0.7B，仍占 B 槽；共用资格 rank≤5、退出 rank>10。排序只使用 T close 已知完整榜单。
- RED：S2 单测枚举每个交易日：t3 份额只有 t0..t3（含）逐日 rank≤5 才计划；t6 份额只有 t3之后..t6（含）逐日 rank≤5 才计划。恰在 t3 的 rank 属 t3 tranche 的前区间，不重复算 t6 区间。
- RED：t0 初份不成交/整手零股/拒单后，t3/t6 的原日期不变；未成交余量不追补；S2 前段失败不改 t6 日期/区间；资格失败只取消对应份额且承诺保留到周期结束。
- RED：feed 缺日期、缺 rank、重复代码或来源未知，按 registry 明确拒单/标 unknown；不得使用 T+1 状态筛选候选或重排，也不得将 unknown 当 rank 合格。

### T03：订单限价与终态

- RED：决策日用 raw close、注册的限价安全系数/涨跌停约束、整手规则和 worst-case 费用求可买最大整数股；将该 shares 与限价冻结在 T 的 OrderIntent。断言订单无 cash_amount；价格/费用缺失或不可信时拒单并记录原因。
- RED：开盘只能对冻结的 DAY 单裁决一次。零成交、拒单、部分成交终态后不重建同份额；部分成交仅按 core fill 实际借记消耗该 tranche，余量/预算作为未投入或取消占用，不滚动到次日。
- RED：多张同 episode 订单及多个 tranche 各自具有稳定关联 ID；同 order 多 partial 使用不同全局唯一 fill_id；同 fill 完全重放无副作用，冲突载荷失败且不污染 seen。
- GREEN：限价字段签名以 core owner 最终公开 API 为准，只做适配；若字段未交付，T03 标 BLOCKED，不伪造 limit 结构或回退成 cash_amount。

### T04：退出、到期、buffer 与快照边界

- RED：rank>10 在 T 收盘转 EXIT_PENDING 并取消未投份额；SELL shares 只取 core 实际可卖状态，活动卖单不释放名额/预算。部分卖、取消、拒单或某项仍锁定时维持 pending。
- RED：positions、locked、未上市权益、活动订单分别非空时不得 close；四者全空且计划份额全终态时由新鲜 core snapshot close。一个 episode CLOSE 后迟到新 fill fail-closed 并要求对账。
- RED：同日快照先处理、随后 `advance(T)`、再算 T close 的 t0/t3/t6，最后才 `finalize_close(T)`；构造 t6 上午 plan_end snapshot，断言收盘 t6 tranche 仍可产生。`advance` 不得因旧 observer replay 回退日期。
- RED：buffer 开始时取消未执行 BUY 与后续份额，禁新开仓；SELL/清算继续经 core；buffer 结束仍有资产或活动单则保留状态并披露，不把退出缓冲期末主账改成现金。

### T05：连续资金路径、对照与回放

- RED：同一序列做“半年 reset 表”和“一路连续状态”夹具；reset 只能按其初始 C 单独报告，连续路径保留 cash、positions、locked、应收、权益、episode commitments、episode/tranche ID，禁止 reset 清除亏损或预留预算。
- RED：B0 路径复用既有动态现金 target5/buffer5，完整冻结既有 `min_edge` 值/开关及顺序；B1/S1/S2/C70 不调用 B0 的 min_edge，测试证明默认资格完全由 rank 注册规则决定。B0 参数身份缺失时阻止比较配置生成，不自行填阈值。
- RED：乱序旧 event、旧 sequence、重复 event、snapshot_id 相同异载荷均拒绝或幂等；失败后 registry snapshot、承诺、episode、seen ledger 全部与操作前一致。
- 验收：`uv run --offline --no-sync python -m unittest tests.unit.backtest.test_staged_allocation tests.unit.backtest.test_staged_order_strategy tests.unit.backtest.test_staged_execution_bridge`；再对目标文件运行 `uv run --offline --no-sync pyright ...` 与 `uv run --offline --no-sync ruff check ...`。只报告合成契约/类型/lint，不推导收益。

## Reset、连续路径与放行边界

- Reset 半年：每个窗口独立锚定其期初 C/B，结果明确标“独立 reset 机制实验”；旧周期已终态不代表可把实际连续账户清空。
- 连续路径：跨窗口沿用实际 core 现金、持仓、锁定、待上市权益、现金应收、活动单和未释放承诺；不按日历半年自动释放未完成周期，也不借用其他 episode 预留现金。
- 该计划只产出策略状态机、限价订单适配与合成 TDD。所有 source unknown 必须拒单并保留证据；已检查的 172 只股票子集不是完整宇宙或最终验收证据。
- 绩效/真实逐日成交验收另行审批：须先有 core observer/稳定身份/权威快照、状态源覆盖、完整行情与交易日历，通过后才能运行；本计划不跑收益或选参。
- 最小依赖顺序：①core owner 发布 limit/order identity/observer 公共接口；②冻结其 API 并确认安装 wheel 同版本；③唯一 CNN 实施者按 T01→T05 TDD；④独立只读 QA 按源码与测试 SHA 复核；⑤主会话决定是否批准绩效阶段。
