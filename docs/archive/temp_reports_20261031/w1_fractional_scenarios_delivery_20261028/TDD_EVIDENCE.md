# TDD / mini 证据

## RED
- 先添加 `tests/unit/backtest/test_fractional_scenarios.py`，实现模块尚未存在时运行：
  `python -B -m unittest tests.unit.backtest.test_fractional_scenarios`
- 结果为导入失败：`ModuleNotFoundError: No module named 'backtest.cnn_adapter.fractional_scenarios'`。

## GREEN 与真实 core mini
- 同一测试模块在实现后通过；最终定向回归为 **83 tests passed**。
- 使用已安装且 SHA 固定的 `run_account_backtest_from_orders`：2021-06-07 开盘买入后记录持仓，2021-06-08 处理 ex/listing。
- 登记100股时，原比例精确权益 `40.0253200`；floor 添加40股、ceil添加41股，核心最终持仓分别为140和141股。
- 固定卖价46.18、高价34.55；core真实拒绝限价不合规卖单，没有改价。
- core成本基础总额守恒；显式记录按 `effective_ratio` 分配basis是情景假设。
- 送转先由 core 创建未上市权益、后由 `ListShareEntitlement` 上市的两阶段测试通过；T+1锁定股份拒卖、解锁后零股全部清仓通过。
- 测试还验证部分零股请求返回 `ZERO_LOT`、完整可卖余额允许odd-lot清仓，0持仓、错误事件、源文件/PDF SHA、日期、比例或row hash不匹配均阻断。
- 正常 `CorporateActionContext` 在相同非整数送转上仍返回 `noninteger_or_unrepresentable_share_quantity`。
- 真正 `run_staged_window` mini 经过 `StagedExecutionBridge`，记录 W1-mini episode/slot 日志并维持 active slots ≤ 5。
- 八分支执行器用隔离假进程验证失败分支继续、所有8个目录保留，并区分 `FAILED` 与 `INCOMPLETE`。
- 前缀门禁测试确认：当前没有可信 SHA pin 时，自制字段齐全的 PASS JSON 和自报哈希不能启动绩效执行。
- 税务证据为 gross cash 27.17082、20% stress withholding 5.434164；明确 `tax_unknown`，不得解释为真实税后结果。

所有以上 mini 使用真实 core engine；没有运行完整 W1/walk-forward绩效或训练。
