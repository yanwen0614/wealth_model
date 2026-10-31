# 公司行动纯投影与权益台账计划

## 目标与边界

- 目标：提供可幂等、事件版本可追溯的现金应收/送转待上市权益投影；合成验证2021真实样本锚点。
- NO-GO保持：本阶段不证明真实成交/税后NAV，不接core执行，不改core账户现金/持仓，不读写真实DB。
- 文件所有权：仅新增 `backtest/cnn_adapter/corporate_actions.py`、`tests/unit/backtest/test_corporate_actions.py` 与本计划/进度。
- core `account_runner.py` 仍归费用/终端闭环owner，待其独立审查通过后才串行接 hook。
- 当前新增纯投影 RED/GREEN 已完成，见 `CORPORATE_ACTIONS_PROGRESS.md`；尚未接core，也未读真实DB。

## 投影接口

- 不可变规范化事件带event_id/code/kind/source row与snapshot hash/version、record/ex/pay/listing日、公告日/known_at质量、毛分红/比例/reference来源/confidence。
- provider首版接规范事件映射；不假定SQLite字段原生语义、不把日期公告当盘前可见、不查询真实DB。
- ledger仅读取逐日core持仓快照和raw close；登记日收盘冻结q_record，ex日生成gross receivable及精确未上市股权益。
- pay-date产生日终现金转账指令，ledger不更改available_cash；日终内应收→现金是重分类，不改NAV。
- listing日期默认EOD保守延后，listing当日开盘不释放；official时点政策必须含source/version。
- 缺reference/ratio/零碎股规则时输出unknown并拒该证券除权日订单标记；不推导reference、不整数化权益。
- 配股恒定不认购：原持股raw盯市不变；reference门控与权利价值unknown分离，不实现认购现金流。
- 税务只允许pretax与现金股息统一20%预提压力；真实FIFO持有期税、红股税和零股补偿不在首版实现。

## 验收测试与实施顺序

1. 先写测试RED：000001.SZ 2021-05-14 100/1000股应收18/180，开盘不可用、EOD重分类不变NAV。
2. 300896.SZ 2021-03-16 100/1000股应收350/3500、权益80/800；listing同日不代表开盘可卖。
3. record日持股归属/之后买入无权、同事件重复replay幂等、reference unknown拒单标记。
4. 20%压力与税前分列；真实FIFO/红股税请求明确失败；零碎权益保留精确数量并标unknown。
5. 单文件CPU unittest与ruff；不训练、不读大型数据、不改现有owner文件。
