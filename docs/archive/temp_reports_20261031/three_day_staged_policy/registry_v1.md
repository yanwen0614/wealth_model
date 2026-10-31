# 分批预算 Registry v1

本目录说明纯预算/episode组件的策略规则与当前接口边界。代码位于仓库
`backtest/cnn_adapter/staged_allocation.py`，合成测试位于
`tests/unit/backtest/test_staged_allocation.py`。

## 固定规则

- 周期初始现金为 `C`，每个预算槽 `B=C/5`，最多五个槽。
- 新 episode 必须满足 `free_cash = cash - sum(未投入承诺额) >= B`。
- episode 取消后，未投入承诺额仍锁定至周期结束；亏损退出也不释放预算。
- 一个 instrument 有活跃 episode 时不能重复开启；多份同股持仓只计一个标的。
- 卖出现金只在 core 真实成交事件到达后入全局现金，不能预支未来卖款满足 T+1 库存。
- 红利归全局现金，不增加槽额度 `B`。
- 记账只接受显式关联 episode 的 filled `TradeEvent`，使用其 `amount` 与 `fees`。
  `OrderResult` 没有成交额，不能由股数差、股数乘价格等方式猜算现金。

## 桥接限制

目前 core `OrderStrategy` 只有 `orders_for(AccountView, MarketView)`，没有成交回调；
`TradeEvent` 和 `OrderResult` 也没有 `order_id`。因此该组件不负责把生产策略发出的
订单关联到 episode。调用方目前必须另外建立可信的明确归属并输入真实成交事件。
组件没有执行订单，也不能宣称端到端执行或现金/NAV 核账已接通。
