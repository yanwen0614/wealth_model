# Staged allocation 交付记录

## 冻结版本

- `backtest/cnn_adapter/staged_allocation.py`：362 行，SHA-256 `FF38AC271560BEB556E2C8E6F305CD97268AFE3C7D873B4FCAF88A37A12663F2`
- `tests/unit/backtest/test_staged_allocation.py`：318 行，SHA-256 `01C4610993DAE9EF6FA751E7AC5D20CA8FF26D5509CD4682900144E4C79F58B2`
- 上述两个文件现已冻结，交指定 QA `ses_e89bdac1fffeaMML79fIpjJ0X7` 只读复核。

## TDD 与验证

- RED：新增 `core_snapshot_sequence`、C70 0.7B 借记上限及 episode 终态用例后，旧接口因不支持序列字段而失败（19 项错误）。
- GREEN：`uv run --offline --no-sync python -m unittest tests.unit.backtest.test_staged_allocation`：21 项通过。
- Pyright：`uv run --offline --no-sync pyright backtest/cnn_adapter/staged_allocation.py tests/unit/backtest/test_staged_allocation.py`：0 errors / 0 warnings / 0 informations。
- Ruff：仅两个目标文件检查通过。
- 类型修复用已校验的 `CoreAccountSnapshot` 收窄 Optional；测试负向写入只对目标表达式使用 `cast(Any)`，运行时异常断言保留。
- 原 QA `ses_e89bdac1fffeaMML79fIpjJ0X7` 已按上述 SHA 只读确认类型收窄、负向运行时断言和既有业务契约未变；QA 未自行重跑命令，验证结果以本会话实跑记录为准。

## 原 10 项回归覆盖

1. 取消 episode 保留完整承诺与槽位；不释放预算。
2. C70 初始承诺完整 B；只投入 0.7B 后剩余 0.3B 仍锁定。
3. 持仓、未上市权益、活动订单按唯一 code 并集计数，同 code 跨集合不重复；旧同股 episode 未清时阻止重开。
4. 旧同 code episode 未由权威快照关闭前禁止重开；快照确认清除后才允许。
5. 同订单多笔 partial 以不同 fill_id 分别应用；重复 fill_id 先幂等 no-op，不回滚新快照。
6. 超预算成交失败后不污染 seen；修正同 fill_id 可重放成功。
7. advance 日期不解除 exit_pending；positions、权益、活动订单任一仍含代码时均保持 pending。
8. 股数展示完全来自 core positions 快照；不会用 shares_delta 累加制造持仓。
9. 金额、费用、available_cash、股数及 positions 拒绝 NaN、inf、负值/非法类型；episode、成交账本和快照对外只读。
10. core available_cash 原样替换本地展示值；成交账本追踪 fill_id、order_id、core_snapshot_id。

## 本轮追加契约

- C70 承诺仍为完整 B；累计真实 cash_debit（成交额+费用）上限为 0.7B，剩余 0.3B 留在承诺中。测试覆盖 140 接受、141 单笔拒绝、100+40 接受、再加 1 拒绝。
- 成交后快照必须提供严格递增整数 `core_snapshot_sequence`。拒绝陈旧/相同版本；重复 fill 完全相同则先幂等返回，不回滚较新快照。
- `core_snapshot_id` 只可用于一个新 fill；重用时拒绝，尤其拒绝同 ID 异内容。ID 字符串不参与时序比较。
- CANCELLED 禁止新买，但存在仓位时仍消费真实卖出反馈；卖清后快照解除并转 CLOSED。CLOSED 收到新 fill 抛出对账错误且不记幂等。

## 环境阻断

- 原 QA 提到的 uv wheel hash 不一致与 B 税务重建列为环境/外部 BLOCKED，不属于组件逻辑结论；未重建或回滚 wheel/lock。
- QA 只读复核再次确认 wheel hash mismatch 与 B 税务重建是环境 BLOCKED；未运行依赖同步或税务重建。
- 本组件使用现有环境 `--offline --no-sync` 测试。组件 PASS 不扩大为真实策略集成 PASS。

## 生产桥接边界

纯组件测试通过不代表真实策略集成通过。当前 runner/core 尚无真实成交回调与稳定 order_id/fill_id；也未见每笔成交后原子提供 available_cash、positions、unlisted entitlement codes、active order codes、core_snapshot_id 的桥接。因此生产接入仍 blocked，未声称策略集成或绩效 PASS。
