# 审查清单：Staged 公司行动 loader/hook

## 范围与依赖
- [ ] 编码前确认目标是 `staged-runner-v2-20261027` 独立树，核对实际文件/签名；不改主区或 backtest-core。
- [ ] 改动只覆盖输入映射、runner hook/observer 组合、必要的 entitlement occupied 投影和合成测试。
- [ ] 现金与股数的唯一权威仍是 core；无第二套现金/持仓账本。
- [ ] 单窗 reset 有明确 anchor 与完整 execution calendar；continuous 未被伪称已支持。

## 数据来源与字段诚实性
- [ ] 保留原始方案进度、行 ID、来源表、冻结快照 hash/version；身份稳定且重复行冲突显式失败。
- [ ] 不把进度 `3` 解释成已完成官方证书；README 的进度 `1` 标签不参与判定。
- [ ] 只把记录日、除权日、派息日、上市日、税前每股现金、T 等实际字段映射到同义事件字段；没有字段就保持 unknown。
- [ ] 方案进度 `1/2` 的 record/ex/pay/list 全缺，不参与账户操作；rights issue 只有公告日期，不造权利时点或认购。
- [ ] B/C/T 关系只作为冻结诊断：8 个观察行支持 T=B+C；合并为 T 一条股权事件并保留 B/C 来源，不 C fallback、不重复计。
- [ ] 两个固定样本只标 fixture evidence；除息/除权语义不从历史字段名或 fixture 泛化。
- [ ] 20% 仅为现金分红 stress；不标实际税后结果，bonus tax 未知须可见。

## Core 时钟与权益上下文（P0）
- [ ] 对日内全部事件先按 instrument/date/operation phase 过滤；无关未知事件不使全账户 hook raise。
- [ ] RecordPosition 在该日开盘订单执行后应用，登记值来自 core 当时实际持股；当日开盘新买入仍取得登记资格。
- [ ] observer 透明组合：完整转发所有 ExecutionUpdate，并保存 `post_state`；错误照常传播，不能丢字段/重排。
- [ ] Ex/Pay/List 以已观察的 core `record_positions` 操作 ID/数量为上下文；登记后卖空不取消既有权益。
- [ ] reset anchor 前无 record 操作的 Ex/Pay/List 跳过，不触发 core missing_record。
- [ ] 登记数量为 0 时不建应收/股权、不支付、不上市；零 shares entitlement 不得出现在 occupied code 集合。
- [ ] 正登记权益遇到缺关键日期、非整数股、舍入规则未知或税未知，fail closed 且留下部分证据和 `INCOMPLETE`。
- [ ] 同方案 bonus+capitalization 只进行一次成本基准分配；操作 ID 稳定，重复重放幂等。

## 合成真实 core 测试清单
- [ ] 无关代码的未知 share/list/pay 字段不会阻止当前账户继续；同代码 active 未知阶段会明确终止并保存部分证据。
- [ ] record 日开盘买入、record 日无持仓、anchor 前 record 三种路径分别验证登记值与后续阶段。
- [ ] record 日持有、除权前卖完：Ex 应收/总股数按记录数量；付款与上市不依赖当前持仓。
- [ ] 0 股登记：无 receivable/entitlement/pending cash/listed shares/occupied code。
- [ ] 单一复合 T 与拆分 B+C fixture 对照，确认 core 成本基准只变更一次且数量一致。
- [ ] 正权益非整数股、上市日缺失、舍入未知分别 fail closed；没有 floor 或猜测日期。
- [ ] 现金支付、listed shares 与 core snapshots/NAV 对账；observer post_state 与最终 snapshot 一致。
- [ ] 输出 provenance 包含冻结源指纹、单窗范围、coverage、不完整原因、非实际税务声明。

## 质量门槛与结论边界
- [ ] 新树相关窄测试通过；复核全量测试由主会话按 harness 调度。
- [ ] 未验证的税后个人收益不进入排名或“实际收益”描述；coverage 只能披露缺失，不能校正排名。
- [ ] 若 core 当前版本无法满足上述时序/可观察性，停止实现并提出 core 契约缺口，不以猜测 API 继续。
