# goal 三链在 cnn 侧的完整复现计划（goal 目录已删，源码见 research/goal 快照）

> 数据：F60 最新全集（70列/1225万行/2013-01~2026-08，cnn 软链→quant）。
> 代码栈：现行 cnn（F53/H10/backtest-core/统一实盘费率），不再用 goal 旧栈。

| goal 链 | cnn 复现 | 脚本 | 对比锚点（goal REPORT） |
|---|---|---|---|
| R1 基线信号存在性（HGB+5d截面） | HGB 回归（16 rank特征，CPU），年度walk-forward，IC+Q5利差 | `r1_baseline_hgb.py` | TEST IC 0.0616 / Q5-Q1年化49.85% |
| R2 可交易账户（realizable+T+1） | R1 preds → `cnn_adapter` rolling/target（统一费用万2/min5/印花万5/过户万1） | `r2_account_backtest.py` | opt_final分散Top100年化46.12% |
| R3 daily连续/joint（实验） | R1 preds → core直调日频再平衡TopN（连续持仓问题等价实验） | `r3_daily_continuous.py` | stride1 TEST 155信号日+5.28% |

口径声明：R1 沿用 goal H5/close-5d 标签保可比；R2/R3 用 H10/open-open 现行口径。
产物落 `research/goal_repro/runs/`（git忽略，大文件不入库），报告为 `REPORT.md`。
