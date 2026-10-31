# 最短可执行研究路径（只读盘点，2026-10-29）

## 结论
- 不需要个人券商合同、真实账户持仓或W1碎股前缀证明；研究结论可基于预先冻结的保守费率与执行规则，清楚标明模拟边界。
- 目前最短可比较的完整候选组是W2四策略（B1/S1/S2/C70），不是2022–25旧回测；四者已用同一资金、输入、指数和侧车计算，全部结果都应并列报告。
- W2区间2021-07-01至12-31，不属于烧毁的2026-01~08；可作历史研究，但不能作为2026-09后独立验收。
- 其机械主期收益/沪深300：B1 +23.68%/-5.44%；S1 +7.88%/-5.44%；S2 +7.23%/-5.44%；C70 +16.96%/-5.44%。虽均满足数值门槛，四项状态均为INCOMPLETE，不能写成实际达标；逐日持仓峰值≤5，缓冲期已清算。
- W1四候选都在2021-06-08同一除权送转事件中fail-closed，结果不完整；无需重建它来推进目标。

## 可复用输入与真实工程
- W2信号：`C:\Users\yanwen\AppData\Local\Temp\opencode\three_day_signals\W2_F4_full_CPU_v1\signals.parquet`（538,599行/4,424码；SHA见`docs/research/20261026/f4_signal_delivery.md`）。模型训练止于2020-12-31，未训练到决策区间。
- W2机械账本：`C:\Users\yanwen\AppData\Local\Temp\opencode\staged_mechanical_results_20261028_v1\summary.json`及`W2_{B1,S1,S2,C70}\`；输入包`C:\Users\yanwen\AppData\Local\Temp\opencode\staged_prepared_inputs_20261027_v12\`含信号副本、raw代码日线、状态分片、费用/日历覆盖。
- 输入manifest指向raw `Z:/dev/kline/day`、沪深300 `Z:/dev/kline_index/day/000300.SH.parquet`、canonical state `.../staged_execution_input_snapshot_20261027_v1/task1_v3/data/canonical_state_v3.parquet`及CA delivery manifest v4。已复用原文件，未重扫训练源。
- 当前完整账户核心是已安装`backtest_core` wheel，经`backtest/cnn_adapter/runner.py::run_cnn_backtest`运行；市场源可用`data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`，不是4GB扫描。
- 主区CLI为`python -m scripts.run_backtest --parquet <train.parquet> --preds <npz...> --mode target --target_size 10 --sell_buffer 0 --topn 10 --index_dir Z:/dev/kline_index/day --benchmark_index 000300.SH --out_dir <新目录>`；已找到该沪深300文件。默认佣金万2/min5、卖印花万5、过户万1、core滑点。需核对其适配W2 staged信号格式；该CLI读NPZ四键，W2 Parquet不兼容，故不能声称一条命令即可替代现有账本。
- adapter单次全流程已有open-open逐笔费、执行/订单事件与账户指标；指数为沪深300收盘基准。持仓明细需从core事件/每日账户快照导出；现有W2 `daily_account.jsonl`与`decisions_orders_fills.jsonl`已具备逐日仓位及成交核查材料。

## 2022–25与2026-09后可行性
- 本机有旧训练parquet，footer已知覆盖至2025-12-31；但research/goal归档的`pred_test.parquet`、账户trades、执行缓存均明确未入库，本机`research/goal/artifacts`只有小JSON，没有二进制预测/成交工件。Z盘未发现旧研究源parquet。
- 当前`logs/preds_fullA_2025.npz`和`preds_fullB_2025.npz`各118万行、2025-01-02至12-16；其checkpoint配置TRAIN止于2024-12-31、VAL覆盖整个2025。它们可做验证期探索，不能当独立测试信号。不要据此挑A/B赢家。
- 2024无可见预测NPZ。补做2022–25需先找回归档清单指向的旧checkpoint/预测文件；若缺失，可用已有模型及训练段内数据推理，但必须逐模型核对训练截止早于所测窗口，不能拿含测试期训练的权重补造OOS。
- 2026-09后目前没有冻结预测/执行账本，现存行情只到2026-08-31；因此今天不能跑新样本独立验收。它不妨碍继续做2021H2历史研究。

## 建议的最快下一步与代价
- 先把W2四策略现有材料做一次不重跑模型的独立结果复核：逐策略汇总每日日末正持仓数峰值、现金/NAV、费用/滑点、沪深300同期NAV及清算状态；把missing-bar、unknown-state、CA税务与source-known限制列作模拟限制，不以这些限制否定普通保守成本回测。
- 工时估计：材料复核与统一表约2–4小时；若必须重新执行四策略，复用现成prepared inputs，预计准备/适配半天、运行数小时（全量原始准备曾耗约34分钟；八窗机械回测自然退出约数小时）。RAM按既往信号生成曾观测到至少6.77GiB，建议可用内存≥8GiB；重跑仍需核实时长与事件完整性。
- 预注册比较：B1/S1/S2/C70四者全部保留；每策略列净总收益、沪深300收益/差值、逐日日末持仓峰值、现金、费用和失败/未成交。不得因已见收益把C70单独晋级；若任何数据缺口致账本不完整，标INCOMPLETE而非删窗。
- 若目标是尽快触达最终干净考试，下一步不是再追历史排名，而是等待/取得2026-09后完整股票与指数行情，再用事前冻结模型（训练截止<2026-09）生成新信号，沿同一≤10持仓、成本与执行规则连续回测；该步骤目前受数据时段限制。

## 证据位置
- `C:\Users\yanwen\AppData\Local\Temp\opencode\staged_mechanical_results_20261028_v1\summary.json`
- `C:\Users\yanwen\AppData\Local\Temp\opencode\staged_prepared_inputs_20261027_v12\integration_inputs.json`
- `D:\code\cnn_full_20260905\cnn\docs\research\20261026\f4_signal_delivery.md`
- `D:\code\cnn_full_20260905\cnn\backtest\cnn_adapter\runner.py`、`historical_costs.py`；`scripts/run_backtest.py`
- 2025预测截止信息：`D:\code\cnn_full_20260905\cnn\logs\relative\run_20260929_162734\config.json`；历史目标策略审计：`research/goal/backtest/AUDIT.md`。
