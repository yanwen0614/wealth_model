# W1/W2 指数基准与执行前冻结核验 v2

范围：只读批准注册表、控制/证据矩阵、当前分批组件/core接口及沪深300小型parquet；不算策略收益/IC，不改仓库/环境/Git。

## 指数源与日历
- 源：`Z:/dev/kline_index/day/000300.SH.parquet`；3,338行，209,699 bytes；SHA-256 `97a99b8ec472299960f56c3cc38c8e69adc8358482dda53eba1d722c210fe599`；唯一代码`000300.SH`。
- schema含`kline_time: timestamp[us]`、OHLC；时间戳无timezone属性。下列日期是指数真实交易日行，按沪深交易所本地市场日（Asia/Shanghai）解释；文件未存UTC偏移，不能说物理字段带该时区。
- W1 anchor后至主终点有118个指数收盘观测；W2有125个；各buffer三日均在该文件中逐日存在。没有用周末/自然日填交易日。

## 按冻结端点计算的价格指数收益
收益公式：终点close / anchor close − 1。Buffer累计列仍从同一个半年anchor计算；另列相对主终点的buffer增量，避免混端点。

| 窗口 | anchor close | 主终点 close / 累计收益 | buffer末 close / anchor累计收益 | 主终点→buffer末 |
|---|---:|---:|---:|---:|
| W1 | 2020-12-31 5211.2885 | 2021-06-30 5224.0410 / **+0.244709%** | 2021-07-05 5085.7763 / **-2.408468%** | **-2.646700%** |
| W2 | 2021-06-30 5224.0410 | 2021-12-31 4940.1134 / **-5.435019%** | 2022-01-06 4818.2318 / **-7.768109%** | **-2.467182%** |

buffer逐日close/anchor累计收益：W1 07-01 5229.6642/+0.352613%；07-02 5081.1172/-2.497872%；07-05 5085.7763/-2.408468%。W2 01-04 4917.7653/-5.862812%；01-05 4868.1202/-6.813132%；01-06 4818.2318/-7.768109%。

旧报告W1 `-0.9331%`复算为 **2021-01-04 close 5267.7181 → 2021-06-15 open 5218.5648**，即截短信号路径末日开盘强平端点；它不是冻结W1（2020-12-31 close→2021-06-30 close）基准。相同起点至06-15 close 5166.5597为-1.920346%。旧数值不替换本次半年口径。

`000300.SH`当前是控制台暂定沪深300**价格指数**close，不含分红再投资；以上仅是指数价格收益。用户最终验收基准口径/区间尚未最终指定，不能把暂定指数结果称为最终目标基准已冻结。

## 候选、纯组件与观察器接线
- 批准registry v1固定：B0为target5/buffer5动态按可买候选分现有available cash；B1固定B=C/5一次投入；S1在t0/t3/t6按B/3到期、失格份额作废；S2两段分别持续rank≤5且不挪固定日期；C70占完整B槽、最多投0.7B，非严格暴露匹配。B0与B1只比较整套差异。
- 当前`staged_allocation.py`只管五槽/承诺上限、C70 `investment_cap=0.7B`、fill去重与core snapshot序列；它不生成B1/S1/S2订单或rank状态，故这些候选尚未接成执行策略。当前`OrderIntent`无episode/order ID，`TradeEvent`无fill ID；core仍无observer/逐笔反馈桥。
- B0名额没有提前由计划卖单释放：`target_strategy.py`在信号时按现有positions算held_count，核心runner卖先买后；若卖单未成交，旧持仓仍占位。卖单成功后的实际现金/持仓仅能由core更新，不靠策略预支。该行为保守，可能少用一次刚释放的名额，不是超持仓漏洞。
- 现金重复计入风险**尚未实际接线发生**，但必须在bridge封口：core `OrderResult.fees`含滑点，现金已按实际成交金额与现金费用变化、滑点体现在成交价；registry当前要求买入`cash_debit == amount + fees`。若bridge把`OrderResult.fees`直接映射为该`fees`，会把滑点再纳入预算借记。应由core前后账户现金/真实cash delta权威赋值；未明确字段语义前不得生产接线。
- 准入现金术语待统一：候选registry公式写`cash − commitments`，当前组件以`available_cash − commitments`检查新episode；latest control又要求以core `available_cash`作为可花现金。建议冻结为可投资准入看`available_cash`、NAV/会计恒等式看total cash及应收/权益，不能混用。
- C70在批准registry、交付记录及当前component均占完整B槽/仅0.7B投资；报告应继续称固定70%预算对照，不称严格暴露匹配。半年reset与连续NAV已在registry明确分开；当前纯组件没有NAV/连续账户账本，不得将reset实验说成连续资金路径。

## 执行前冻结清单与剩余门
1. 固定W1/W2 anchor、主终点close、三日buffer与buffer独立披露；价格指数仅暂定，最终benchmark须用户确认。禁止拿06-15 open替代半年close。
2. 逐路径冻结checkpoint/预测日历/代码身份、raw价格与股数单位、公司行动reference/权益，以及交易日费率；数据语义仍在核，不能因信号完整解除执行门。
3. observer接通前固定`episode_id/order_id/fill_id`、多partial顺序/幂等、可用现金、positions/locked/未上市权益/活动订单权威快照；拒绝/取消不得伪造fill，退出只由core快照确认。
4. 明确现金delta与`OrderResult.fees`/slippage口径；B预算承诺和未投入份额不复用；卖单失败不放名额；股息/公司行动应收不能当可用现金。
5. 逐日实持仓≤10、cash/receivable/持仓/权益/NAV恒等式、期末close与buffer清算分列；reset半年与连续资金路径分别给出，不互相替代。

用户本次告知：完整F4信号与core `40f697`测试已通过；本次未复跑。当前证据矩阵第17行仍写“完整全量进行中”，需主会话按证据同步；该状态差异不改变数据语义仍在核、候选绩效未验收。当前候选绩效仍NO-GO；本报告只给出基准和机制冻结事实，不包含任何策略绩效。
