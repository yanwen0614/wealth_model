# 独立合成闭环审查清单

当前结论：费用与终端最小实现完成；cnn/core定向验证通过；身份模块由并行执行者处理；真实候选实验NO-GO。

## 范围与重复检测
- [x] 核实core CostConfig、AShareCostModel、OrderStrategy、账户快照、订单入口现行协议。
- [x] 已读取两条指定费用来源；未发现三个同名模块/测试，现有静态费用与策略测试不替代新增契约。
- [x] 按用户后续授权新增费用/审计模块与测试，最小扩展 runner/core；不碰冻结日期文件、旧合同测试、memory、身份模块。
- [x] 中文分批写入；未提交推送删除，未启动训练/GPU/W4扫描。

## 历史费用
- [x] 覆盖2022-04-28/29与2023-08-25/28成交日断点，并核对10万元/小额最低佣金；细项见SYNTHETIC_TDD。
- [x] SSE_A/SZSE_A规则、2021下限、未知市场、datetime/字符串日期拒绝。
- [x] 费用函数委托AShareCostModel；保留调用者佣金与滑点配置，重建CostConfig校验。

## 终端与账户
- [ ] 非mark、非T1_OPEN、非逐日回调拒绝；缺X或buffer不足拒绝；节假日按交易日历。
- [ ] 固定样例：日历周一～下周一，evaluation_end=周五，X=周四，buffer=下周一；周四收盘开始退出，周五MTM分列。
- [ ] 周三买单周四开盘可执行；周四/周五收盘买单不产生；最后正常信号若下一执行日跨退出边界也被显式拦截。
- [ ] BUY过滤覆盖shares/cash_amount两种；包装决策留suppressed记录，不伪造core成交/拒单。
- [ ] 退出阶段不依赖预测覆盖，按实际账户正持仓发SELL；不预扣locked；部分/拒绝后下一日重试；末日保留残仓。
- [ ] 合成core运行确认execution_time>signal_time，无forced_exit，无X之后BUY；buffer内实际卖出/拒单可追溯。
- [ ] 每日cash+sum(shares×当日close)=NAV，有限值、完整日期、正持仓<=10；11只、缺当天价、NAV不等均失败。
- [ ] core允许last_marks回退不等于本门通过；daily_closes缺当日持仓报价直接失败，缺价不以0补。
- [ ] evaluation_mtm与post_buffer分列；filled/locked事件及partial/rejected原因保留，残仓按代码列shares/MV。
- [ ] 残仓合法时审计可通过但cleared=false；不得声称“至少一日buffer=保证清仓”。

## 逐路径身份
- [ ] 每个branch_label独立采集cnn/core真实SHA、dirty明细及模块实际路径；禁止全局复用身份。
- [ ] 必需模块与data/cache/checkpoint常规文件逐项SHA-256；缺失、不可读、采集期间变化、git失败均拒绝。
- [ ] 实际import的core.__file__对应源文件与提交路径一致；另一checkout同名模块不得冒充。
- [ ] 依赖版本缺失即失败，不能unknown；两label可同SHA，label重复或空值失败。
- [ ] dirty状态变化与模块/产物单字节变化可识别；不改真实仓库验证dirty，用mock或临时文件。
- [ ] 合成身份产物显式标synthetic；测试不创建git提交、不改冻结文件。

## 六关卡与验收边界
规范一致性、模块依赖方向、数据/时序安全、导入合规、显式错误、最小实现与性能逐项审查；流式hash不加载大型数据。
仅推荐后续命令：`uv run --project . python -u -m unittest tests.unit.backtest.test_historical_costs tests.unit.backtest.test_execution_audit tests.unit.backtest.test_run_identity`。
后续ruff仅检查这六个新文件；所有测试临时文件/TEMP/TMP均落本任务根，本轮不运行任何命令测试。
动态费用未接入实际engine，历史notional/完整信号/同时间基准未验证，禁止比较候选收益；不得用合成通过解除NO-GO。
