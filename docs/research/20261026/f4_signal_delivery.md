# W1/W2 F4 完整信号交付

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

## W2交付与独立复核（2026-10-27）

- 决策期2021-07-01至2021-12-31，共125个真实交易日；buffer为2022-01-04/05/06，未生成buffer预测。
- 训练2013-01-01至2020-12-31、验证2021-01-01至06-30；9轮早停，最佳第6轮（epoch=5），不因loader兼容报错而重训。
- 输出根：临时目录 `three_day_signals/W2_F4_full_CPU_v1/`，含Parquet、NPZ、metadata、manifest、逐码状态及核验报告。
- 共538599行、4424码；ready522748、历史不足14909、不交易817、当日无行125；全期BUY资格518444行。
- E日4424行，其中4304条ready且全部禁止BUY；末11个决策日保留，全部true_ret为NaN且label_availability为not_loaded。
- 主会话独立读取产物，核验代码/日期无重复、125日覆盖、ready预期收益有限、BUY门与E边界、F4/seq60/H10，以及所有manifest文件大小/SHA。
- NPZ与Parquet的预期收益、日期、代码逐值一致，真值全NaN。未重跑模型、未读标签、未算IC或收益。
- signals.parquet SHA256：`dc39dd8c0287d8ed4c3fb2313961518969534c633de451303dad7b9fd8178d9c`。
- signals.npz SHA256：`48f20031d0164be4ef72ffb93d49f058d507a1734e86400924a44187bc0bad18`。
- checkpoint SHA256：`03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4`；loader修复main b747f56、W2树70638ab。
- CPU FP32、batch256、OMP/MKL线程2；连续可用RAM停线2.5GiB，resource日志和handoff保留于信号父目录；不得把旧运行中状态当作未生成而重复启动。
- 原W2权重及完整run日志仍在训练树，已交owner迁移到稳定独立模型目录，哈希核验后再清理树；信号metadata的历史源路径不回写。
- 技术产物通过不代表状态/税务/执行可行性或盈利要求通过，候选账户绩效仍待完整证据链。
