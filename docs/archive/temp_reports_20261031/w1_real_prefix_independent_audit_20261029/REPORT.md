# W1 cutoff 真实前缀独立审计

审计输入：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1_real_prefix_exploration_20261029_v2/`。基线：`C:/Users/yanwen/AppData/Local/Temp/opencode/staged_mechanical_results_20261028_v1/W1_{B1,S1,S2,C70}`。

## 结论

- 顶层 wrapper `EXITED_ZERO`、exit 0；开始/结束 UTC 为 2026-10-28 20:38:44.5006146Z / 2026-10-28 22:13:19.2684810Z，耗时 1:34:34.768。当前 `tmux list-sessions` 中没有该 session；退出码以留存的process_status和八个分支状态/日志交叉核对。
- 8个分支中5个 exit 0 / INCOMPLETE，3个 exit 1 / FAILED；全部 mechanical_status=INCOMPLETE。不是完整收益回测，没有实际税后目标资格。PIT、实际券商费率、source availability 均为 UNKNOWN。
- cutoff 为 2021-06-07。账本包含6/7登记快照及execution_date=6/8的待执行单。截止登记可能检查次日权益；这些记录不证明6/8交易、除权、交割或到账已经发生。
- 3个ceil失败均因 `dividend:27726` 股数校验 `noninteger_or_unrepresentable_share_quantity; INCOMPLETE`。floor exit 0仅表示实验按状态完成，不能视为收益成功，也不能证明floor=ceil。

## 五类账本对照

按严格物理行序比较实际前缀与对应 W1_B1/W1_S1/W1_S2/W1_C70 基线。逐行比较解析后的字段集合和值及原始JSON行文本；无浮点容差或格式归一。失败分支只比较实际存在的前缀，不以行数相同推定相等。

|分支|exit / 状态|execution_updates|daily_registry|strategy_decisions|registry_transitions|partial_account_states|
|---|---|---:|---:|---:|---:|---:|
|W1_B1_floor|0 / INCOMPLETE|872|103|102|974|872|
|W1_B1_ceil|0 / INCOMPLETE|872|103|102|974|872|
|W1_S1_floor|0 / INCOMPLETE|857|103|102|959|857|
|W1_S1_ceil|1 / FAILED|857|103|102|959|857|
|W1_S2_floor|0 / INCOMPLETE|850|103|102|952|850|
|W1_S2_ceil|1 / FAILED|850|103|102|952|850|
|W1_C70_floor|0 / INCOMPLETE|876|103|102|978|876|
|W1_C70_ceil|1 / FAILED|876|103|102|978|876|

八个分支的上述账本与基线现存行均逐行、字段及原始文本一致；未发现缺字段或差异。该结论只覆盖表中已存在的前缀记录。

分支日志内每支顺序执行的起止时刻（本地记录时间，2026-10-29）：B1_floor 04:39:01–04:51:30，B1_ceil 04:51:55–05:03:48；S1_floor 05:04:14–05:15:47，S1_ceil 05:16:13失败；S2_floor 05:27:31–05:38:51，S2_ceil 05:39:17失败；C70_floor 05:50:41–06:01:57，C70_ceil 06:02:20失败。失败时间为分支窗口启动日志时间，ValueError堆栈在其后。各段运行约11分半至12分，失败段时长未从日志确定。顶层运行时长覆盖准备与全部分支。

## 截止访问与时间语义

- ranking日志最大 `trading_date=2021-06-07`；market访问最大 `start=end=2021-06-07`；fee bundle `information_cutoff=2021-06-07`。
- quantity规则调用的 `signal_date` 与 `rule_lookup_date` 最大为6/7；`execution_date` 最大为6/8，是待执行订单日，不是行情/规则查询日，也不应改写为“所有日期字段均不晚于截止”。
- access日志是调用层逻辑访问证据。SHA或审计器流式扫描完整物理文件只表示审计读取，不代表交易程序曾读取未来行情。

## 失败、资格与范围

S1_ceil、S2_ceil、C70_ceil的stderr均在公司行动hook校验股数处抛出上述ValueError。完整窗口收益、真实碎股分配、PIT可得性和实际税后现金均未证实；前缀不能当作收益。floor、ceil是不同条件情景，不能互换。

独立核验使用Python标准库，不调用既有`audit_prefix_ledgers.py`。重要前缀/基线账本文件SHA-256、运行状态、启动材料、原始stderr、逐行差异及四种访问日志的最大日期汇总存于`audit.json`。SHA用于文件身份核验，不是时序访问证明。

- `audit.json`：机器可读核验细节与哈希。
- `compact.py`：将审计中间结果缩减为交付所需摘要的标准库脚本。
- 分支stderr中记录各分支实际开始、完成或失败时间；顶层状态时间来自`process_status.json`。
