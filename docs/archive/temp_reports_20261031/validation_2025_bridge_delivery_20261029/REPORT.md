# 2025 A/B 桥接交付记录

日期：2026-10-29。性质：**已观察验证期历史回放探索**，不是独立测试、前瞻结果或当时冻结的验证。A/B 均保留，不据指标择优。

## 本次实现与验证

- 新增 [validation_2025_bridge.py](../corporate-action-fix-20261027/backtest/cnn_adapter/validation_2025_bridge.py)：校验原始NPZ字节SHA、四键/一维/日期代码唯一/有限值、A/B行序与日期代码标签一致；绑定H10 config、checkpoint、外部来源报告和状态源真实字节SHA；分批独占写入runner可读Parquet，保留每个排名行、逐行资格/拒绝原因与来源字段。
- 新增 [run_2025_ab_execution.py](../corporate-action-fix-20261027/scripts/run_2025_ab_execution.py)：锚点2024-12-31收盘、首信号2025-01-02、共同E日2025-12-16、12/17–19仅buffer；校验完整指数日历/benchmark/输入SHA及覆盖；准备A/B桥接输入，不调用真实全年账户回测。
- 固定协议为B1一次投入五槽、每槽20万元、最多5槽、rank≤5入场、rank≥11退出、账户100万元、实际持仓≤10；佣金万2/min5、2025卖出印花万5、双边过户万0.1；滑点参数显式锁定既有σ-ADV默认值。现金分红20%仅压力税情景，不代表真实税后。
- 状态资格只使用信号日收盘时可知状态，避免窥视次日开盘；unknown 保留在完整榜单并设为不可买。状态缺键或CA/行情等输入缺失会给出INCOMPLETE/missing清单，不补空状态、不裁剪窗口。
- NPZ→Parquet保留完整键/score/true_ret，并记录H10训练标签期望收益映射及信号产生时刻；未将adapter固定H5声明套用到本桥接。

### TDD 与质量门

- RED：新增测试首次运行失败，`ModuleNotFoundError: backtest.cnn_adapter.validation_2025_bridge`（预期的缺实现失败）。
- GREEN：新测试 14/14 通过；覆盖首信号、日期锚点、四键/hash/重复/有限值、A/B逐元素一致、H10、Parquet内容对应、unknown拒单、manifest外部SHA、真实core mini账本守恒/持仓上限及buffer无买单、缺状态/CA清单与策略漂移拒绝。
- 定向回归合计 192 项通过：桥接/staged输入与策略114、公司行动37、raw行情/费用/数量/执行审计41。
- `python -B -m ruff check .`：通过。CLI `--help`：通过。
- 空manifest门禁行为：返回码2，列出benchmark/calendar/corporate_actions/historical_fees/quantity_rules/raw_market_manifest/verified_states缺失，且未创建输出目录。

## 实际命令

```powershell
# RED
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m unittest tests.unit.backtest.test_validation_2025_bridge
# GREEN + staged 接口回归（114项）
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m unittest tests.unit.backtest.test_validation_2025_bridge tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_order_strategy tests.unit.backtest.test_staged_execution_bridge tests.unit.backtest.test_staged_allocation tests.unit.backtest.test_staged_production_inputs
# CA 回归（37项）
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m unittest tests.unit.backtest.test_corporate_actions tests.unit.backtest.test_corporate_action_context tests.unit.backtest.test_corporate_action_snapshot_loader tests.unit.backtest.test_corporate_action_runner_e2e
# 行情/费用/数量/审计回归（41项）
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m unittest tests.unit.backtest.test_raw_market_inputs tests.unit.backtest.test_raw_market_provider tests.unit.backtest.test_quantity_rules tests.unit.backtest.test_historical_costs tests.unit.backtest.test_execution_audit
# 静态检查与CLI帮助
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m ruff check .
& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m scripts.run_2025_ab_execution --help
```

## 数据身份与实际边界

- A/B NPZ均为1,180,872行、232日、5,135码；四键为dates/codes/exp_ret/true_ret，datetime64[us]/U9/float64；重复键与非有限值均为0，A/B日期、代码、true_ret逐元素一致。SHA/配置/权重及小型指数文件哈希见 [DATA_IDENTITY.json](DATA_IDENTITY.json)。
- 指数原文件仅209,699字节，实读确认2025有243日、锚点及E日、三buffer日均有close。区间基准采用2024-12-31至2025-12-16 close-to-close价格指数，不含分红再投资。
- 已审冻结基线的16个源码hash全部匹配，零文件变化；逐文件hash及三个新增源码hash见 [SOURCE_HASHES.json](SOURCE_HASHES.json)。完整基线清单文件自身SHA-256为 `73aa08f4f0b075f2c311efc20d34f3a07fb952cefae4765e45341367cbf1998c`。
- 当地评估JSON记载HORIZON=10且checkpoint/config存在；它们没有绑定NPZ原始SHA、checkpoint/config SHA和信号产生时刻。因此本地身份复核值不是独立来源证书，桥接器要求另有SHA绑定的来源报告后才写输出。

## 当前阻塞与结论边界

- 独立状态探测会话的 [STOP_REPORT.md](../state_2025_probe_20261029/STOP_REPORT.md) 说明当前免费额度/无扣费证据不足，未发出SDK请求或准备2025状态数据。已存在raw行情schema没有停牌/ST/直接涨跌停字段。
- [数据preflight报告](../validation_2025_data_preflight_20261029/REPORT.md) 指出公司行动记录未覆盖/证实完整实施、碎股与税务；状态PIT时间、板别/上市信息及真实限价也未闭合。缺任一影响交易或估值都不得视作完成。
- 因此本次没有生成生产2025 signal parquet、没有读训练parquet、没有执行全年或部分真实A/B回测、没有产生或宣称任何绩效，也没有独立QA结论。当前交付是桥接实现、mini真实core验证和可审计输入门禁；需先由独立QA审查，再由独立数据会话提供合格的状态/CA/原始行情/费率manifest。
- 该交付未改原corporate-action/runner/core/wheel/W1树或共享环境；未安装依赖；未提交、push、stash、reset、切换分支或clean。
