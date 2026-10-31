# W1 前缀证据盘点（只读研究）

## 范围和结论
- 检查对象：`staged_mechanical_results_20261028_v1/W1_{B1,S1,S2,C70}` 与情景树 `w1-fractional-scenarios-20261028`。
- 未运行任何回测、mini、情景或绩效；未改项目代码及原始产物。
- 四策略账本不是只有每日摘要：存在完整 `execution_updates`（含每事件前后 core state、活动订单、订单/成交/attempt 标识）、逐事件 registry transitions、每日 registry/core 快照、策略决策、账户状态、操作/数量规则及证据清单。
- 因此原 prefix 有逐事件比对材料；仍须用冻结源码从 anchor 重跑到同一 2021-06-08 异常，验证原账能被重现，不能仅凭现有日志自证来源。

## 原始日志计数及连续性
| 策略 | updates / 最后序号 | daily_registry | decisions | transitions | 最后交易日 |
|---|---:|---:|---:|---:|---|
| B1 | 872 / 872 | 103 | 102 | 974 | 2021-06-07 |
| S1 | 857 / 857 | 103 | 102 | 959 | 2021-06-07 |
| S2 | 850 / 850 | 103 | 102 | 952 | 2021-06-07 |
| C70 | 876 / 876 | 103 | 102 | 978 | 2021-06-07 |
- 四者 daily_registry 从 2020-12-31 anchor 至 2021-06-07 共 103 个唯一交易日；decisions 覆盖 2021-01-04 至 2021-06-07 共 102 个信号日；均与冻结 W1 日历前缀长度吻合。
- updates 与 partial_account_states 行数相同；updates 序号从 1 连续至末序号，末 event_id 与 audit.last_registry 的 core_snapshot_sequence/id 一致。
- 2021-06-07 末状态仍含 300502 持仓及次日待执行买卖单，不能把该快照等同“已结算”或把 E 日之前的持仓清空。
- 四策略均记录同一 CA 异常：`dividend:27726:5fb635…194462`，`noninteger_or_unrepresentable_share_quantity`，INCOMPLETE。禁止用此盘点推导后续收益。

## 事件状态与可比字段
- core state 可观测字段：现金/可用现金、持仓、锁定股、应收现金、待付现金、成本、最近标记价、已处理 CA operation IDs、登记日持仓/成本、未上市权益、累计股息/预扣税、fractional 标志；core snapshot 另含 active_orders（订单 ID、方向、剩余量、执行日、状态）。
- updates 逐行字段含 sequence_no、trading_date、phase、event_id、attempt/order/fill/episode IDs、order_status、reason、trade、cash_delta、active_orders、pre_state/post_state。
- bridge/registry 侧逐事件含 date/stage、core_snapshot/state、episodes/tranches、free_cash、occupied_codes、registry（slot/cash/commitment/最后 fill/order/快照序号）；决策账含信号日、订单明细、拒绝、position_usage。
- 主 canonical 比较应保留事件顺序并精确比较 phase、date、决策/成交/拒单、订单数量/限价/剩余量、core pre/post 状态和 registry；浮点按同一 JSON 数值精确序列化或先定义字段级容差，默认不容差吞差异。
- 目前未证明任何账本业务 ID 不稳定；这些 ID 含策略/窗口/固定运行身份且可串联订单、成交、快照。默认完整保留并精确比较。仅经重复受控运行证实会变化的字段（例如绝对输出根路径）才可加入显式 normalization 白名单；不得先验删改 ID、时间或行序。
- artifacts.json 的哈希对输出文件字节有用，但自身不是运行真实性证明；corporate_action_evidence 声明 `manifest_self_hash_trusted=false`，须追溯 manifest 与原输入哈希，不能把自报 SHA 当独立认证。

## 冻结输入身份
- 两份交付 `SOURCE_HASHES_FINAL.json`（情景树交付及 staged integration delivery）列 16 项，当前内容一致；共同源码 SHA 覆盖 quantity_rules、staged_order_strategy、staged_candidate_runner、staged_production_inputs、raw_market_inputs/provider、corporate_action_context、corporate_action_snapshot_loader 及测试。
- W1 信号 SHA256 `99198e069157e570ffc2fa83818d1738a4abe468a5d39c76fca30dfba5d762e9`；checkpoint SHA256 `a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde`。
- v12 manifest SHA256 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；预注册 SHA `1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae`；state/gap、benchmark、CA delivery、calendar、metadata 等另有 manifest 哈希。
- 情景计划固定 base HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`，并要求使用 `account_runner.py` SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00` 的实际 backtest_core wheel。
- 以上 SHA 是待复算的基线锚点；未来执行前必须从只读源逐个重算、拒绝缺文件/不符文件，并记录 Python/uv/OS、wheel 文件 SHA 与安装模块路径。
