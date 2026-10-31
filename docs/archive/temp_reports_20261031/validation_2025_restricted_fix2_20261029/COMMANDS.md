# fix2 原QA复验命令

工作目录：C:/Users/yanwen/AppData/Local/Temp/opencode/validation-2025-restricted-20261029。
全部Python使用指定venv的绝对路径和-B；不需要安装或更新依赖。
实际运行脚本为本目录verify.ps1，tmux会话validation2025_fix2_final，显式Set-Location并保留退出码。
完整日志：GREEN.log、REGRESSION.log、RUFF.log、PYRIGHT.log、PROBES.log；各步和tmux脚本总退出码均0。

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m unittest tests.unit.backtest.test_2025_restricted tests.unit.backtest.test_2025_restricted_fix2
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m ruff check --no-cache .
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m pyright --pythonpath 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' --project 'C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_restricted_fix2_20261029/pyrightconfig.json'
```

Pyright配置实际存在并纳入FREEZE：三个include是相对配置文件的显式文件，两个executionEnvironments
分别设置脚本/测试路径；extraPaths指定只读集成树、当前树和实际site-packages。
脚本按集成树优先；测试先定位当前树的scripts，再使用脚本自己的环境；不存在import错误豁免。
无配置时解析到当前树旧raw_provider，history_bars参数错误是路径不匹配，不能据此删真实关键字参数。
真实运行时路径和inspect.signature见IMPORT_CONTRACT.json。

独立复验必须用干净Python进程先导入入口，不先混入当前树旧backtest包。
两份QA原始probe由test_2025_restricted_fix2.py直接读取原信号/CA raw_row，未修改任何QA源文件。
RED_QA_PROBES.log在改生产实现前产生，两个真实问题分别为无成交、错误返回收益可用。
GREEN新增七项覆盖：两个原probe、正登记及不同公告、非持仓未知、登记日开盘已卖、
停牌/未知ST/缺价锁仓、日期全未知。旧24项保留core手续费、现金分红、容量、ST卖出等门。

持久证据由produce_evidence.py运行，共11个core_*新目录；重复执行须换输出路径，禁止覆盖。
回调在core/execution_updates.jsonl；记录了pre_state、post_state、cash_delta、active_orders、
原生fill、positions、locked、record_positions、receivables；daily_account仅在完整运行后生成。
ca_observed_checks.json关联真实core_event_id、日期、正股数与源event_id，不是另一个账本。
异常账户保留前缀与库存，不伪造完整daily_account或E日终值；无仓未知不阻断其他代码。

独立QA优先复查：core_late_rights和core_late_cash目标成交与core_none一致；
core_missing_record_future买入后中断，19,100持仓/锁仓保留；core_positive_rights在1/6正登记中断；
core_record_open_already_sold登记量0不阻断；core_unrelated_unknown不阻断。
这只是owner交付，仍需原QA独立复验；未运行全年，不宣称用户收益目标通过。
