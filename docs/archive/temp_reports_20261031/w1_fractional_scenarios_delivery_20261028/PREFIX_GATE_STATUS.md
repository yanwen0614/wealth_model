# W1 prefix 门状态：未验证，禁止绩效

- 只读发现 `staged_mechanical_results_20261028_v1/W1_B1` 有冻结的失败尝试：execution_updates 872行（2020-12-31 至 2021-06-07）、daily_registry 103行（同区间）、strategy_decisions 102行（2021-01-04 至 2021-06-07）。其 manifest/batch_error 标为 `INCOMPLETE`，原因是目标权益非整数被默认 fail-closed。
- 该目录不是 floor/ceil 新运行的对照结果；不能单独证明逐事件 canonical 等价。
- 当前临时目录下未找到第二份可逐行对照的 W1 canonical `execution_updates.jsonl` / `daily_registry.jsonl`。因此没有创建 PASS prefix proof，也没有启动任何 W1/八分支绩效运行。
- `fractional_scenario_cli --execute` 还须源码预先 pin 由主会话复核的独立 proof SHA；校验要求状态 PASS、base HEAD、截止 2021-06-07、原前缀及 floor/ceil 前缀匹配。
- 当前源码 `TRUSTED_PREFIX_PROOF_SHA256=None`，因此即使提交自造且字段齐全的 proof 并自报其 SHA，也会在启动子进程前被拒绝。
- 独立 QA 需要先确认是否可从冻结输入得到可比较的完整原前缀。没有逐事件、core state、订单与 registry canonical 比较时，绩效阶段保持封锁。
