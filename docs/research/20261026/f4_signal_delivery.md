# W1 F4 完整信号交付

核对时间：2026-10-26 14:39。仅验证信号技术产物，没有计算IC、收益或候选排名。

## 模型与数据

- checkpoint：`logs/relative/run_20261026_100509/best_model.pth`。
- 训练2013-01-01至2020-06-30；验证2020-07-01至2020-12-31。
- 共训练5轮；最佳第2轮，checkpoint零起点epoch=1，验证损失0.050467。
- 输入仅有序open/high/low/close；relative、seq60、H10、excess、四维。
- OHLC仍来自原训练parquet；不声称已重建历史股票池或消除复权数据版本风险。

## 完整输出核验

证据目录：`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_signals/W1_F4_full_CPU_v1/`。
核对该目录的`verification.json`、`metadata.json`；信号数据不入Git。

- 478369行，4186代码，118个决策交易日，2021-01-04至2021-06-30。
- E日4186条记录，其中4033条ready，buy_eligible数量为0。
- 缓冲日2021-07-01/02/05无新信号；所有true_ret均NaN。
- 输出SHA256：`99198e069157e570ffc2fa83818d1738a4abe468a5d39c76fca30dfba5d762e9`。
- checkpoint SHA256：`a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde`。
- writer SHA256：`1e34c005475e617eb7c0af9ed1ce9a775c92adf4235db8767f1991d50645a62b`。
- 输入文件SHA复用此前采集记录；未再次全量hash约4.28GB源文件。

## 限制

资源包装器启动子进程后发生Popen/psutil调用错误；生成进程继续运行并产出完整文件。
已有最低可用内存采样6.77GiB，但没有完整RSS峰值记录，不能称连续保护监控完整通过。
信号覆盖及模型哈希核验不等于实际成交可行性；真实状态来源、税务和分批执行仍须各自验收。
