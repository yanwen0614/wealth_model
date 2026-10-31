# W1 v3 预检补充报告

## 裁定

策略运行保持 **BLOCKED**。遵照用户指令，未来公司行动描述缺可靠 `known_at` 时 fail-closed；八个分支均未启动，没有 6/8 策略/API 调用、账本、proof 或完整绩效结果。v1/v2、源码、prepared inputs、三项 pins 均未改。

## 冻结输入 hash 审计

- tmux：`w1_v3_v12_hash_preflight`；自然结束 `pane_dead=1`，`pane_dead_status=0`；退出码文件为 `hash_audit.exitcode`，值 `0`。
- v12 manifest SHA 与 sidecar：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；4,812 项 **4,812 PASS、0 mismatch**。完整逐块哈希读取 `2,221,465,003` 文件字节，时间 `2026-10-28T23:37:52.691677Z`–`23:39:03.778731Z`。
- 文件路径、预期 SHA、大小：[v12_declared_artifacts.jsonl](v12_declared_artifacts.jsonl)；实测 SHA、读取字节：[v12_artifact_hashes.jsonl](v12_artifact_hashes.jsonl)；摘要：[v12_hash_audit.json](v12_hash_audit.json)。原 4GB 训练源未读、未重哈希。
- 固定源码 hash 15/15 匹配；fix2 交付清单既有独立核验为 32/32 匹配。prepared/original 与 isolated core 身份未变。proof、attestor、attestation pins 均为 `None`。

## 公司行动证据与可得时间

- 本地目标行为 `dividend:27726`、代码 `300502.SZ`、row SHA `5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462`：登记日 2021-06-07、除权及红股上市日 2021-06-08，行内 `公告日期=2021-06-01`。
- CNINFO 原始公告：[2021-06-01 路径下的公告 PDF](https://static.cninfo.com.cn/finalpage/2021-06-01/1210131886.PDF)，公告编号 2021-030，正文确认登记日 6/7、除权日 6/8，落款 2021-05-31。[Sina](http://money.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/300502.phtml) 与 [Hexun](https://stockdata.hexun.com/2008/ggqw.aspx?page=5&stockid=300502) 公告列表均列 2021-06-01；[雪球](https://www.xueqiu.com/S/SZ300502/181394661) 页面标示 5/31 并链接该 CNINFO PDF。故目标公告在日期层面有证据显示不晚于 6/1 已发布；没有可靠时分秒或独立历史抓取时间，不能把具体 `known_at` 时刻钉死。
- 冻结行清单共 8,740 条 dividend、12 条 right_issue。公告日期字段均存在且可解析；但没有公告时间戳字段。loader 对每个 descriptor 固定加入 `known_at_unknown`，所以目标以外 **8,751 条**仍无独立可得时间证据。
- 其余 8,739 条 dividend：公告日期范围 2020-12-26–2022-08-20，登记日范围 2020-12-30–2022-08-26，除权日范围 2021-01-06–2022-08-29；12 条 right_issue 的公告日期范围 2021-01-09–2021-12-28，快照没有其登记/除权日期字段，配股覆盖仍 UNKNOWN。分项 SHA、字节数与统计：[ca_known_at_audit.json](ca_known_at_audit.json)。

## 代码路径与读取边界

- CLI 固定传入 `--prefix-stop-after-close=2021-06-07` 与 `--information-cutoff=2021-06-07`：[fractional_scenario_cli.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/fractional_scenario_cli.py:51)。runner 的 `_verify_prepared` 对 manifest 全部 artifacts 逐块 SHA：[staged_production_inputs.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/staged_production_inputs.py:771)。
- SHA 完成后，`run_single_from_cli` 无 cutoff 过滤地载入公司行动 snapshot，再加载截止日窗口：[staged_production_inputs.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/staged_production_inputs.py:921)。snapshot loader 读取完整 dividend/right_issue 文件并构造 descriptors：[corporate_action_snapshot_loader.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/corporate_action_snapshot_loader.py:122)；`known_at_unknown` 在 descriptor 构造时设置：[corporate_action_snapshot_loader.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/corporate_action_snapshot_loader.py:64)。
- 情景 context 接收整个 snapshot：[staged_candidate_runner.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/staged_candidate_runner.py:1057)；父 context 在账户更新与逐日操作中遍历 descriptors：[corporate_action_context.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/corporate_action_context.py:95)。情景类固定 6/8 ex/listing 并在登记持仓回调校验目标 descriptor：[fractional_scenarios.py](C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/backtest/cnn_adapter/fractional_scenarios.py:24)。core 在 6/7 close 后 break：[account_runner.py](C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src/backtest_core/engine/account_runner.py:1818)；这阻断 6/8 日回调，但不阻断未有 `known_at` 证据的其他 descriptors 进入 6/7 策略上下文，故不得运行。
- v12 全文件 SHA 是冻结身份的文件字节读取，不是策略使用、业务 API 读取或可信 PIT 证明。另有离线 `known_at` 核验读取 dividend 文件 3 次（每次 7,774,052 字节）、right_issue 文件 4 次（每次 4,738 字节）；manifest 1,029,809 字节共读 7 次、64 字节 sidecar 读 1 次。上述 v12 输入、公司行动数据和 manifest 合计 2,252,014,838 个文件字节；不含源码 hash 检查的代码文件读取。这些数据解析仅用于本报告，未传给策略或执行。Windows 设备层缓存未监测，故不声称实际磁盘介质 I/O 字节数。

## 产物状态

- v3 `outputs/` 不存在；八支 **NOT_STARTED**；没有分支 stdout/stderr 或退出码。
- hash 审计辅助脚本及退出码留在本目录；本报告未修改旧 `PREFLIGHT_BLOCKED.md`、源码、manifest、snapshot 或训练数据。
- 下一阶段须由主会话独立设计 cutoff-safe 公司行动输入；当前 runner 不满足该边界。
