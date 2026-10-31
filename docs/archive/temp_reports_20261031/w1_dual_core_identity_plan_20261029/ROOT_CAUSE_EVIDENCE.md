# 根因证据与执行事实

## 原始失败与数据流

- `w1_real_prefix_exploration_20261029/outputs/{W1_B1_floor,W1_B1_ceil,W1_S1_floor}.stderr.log` 三栈相同：`run_single_from_cli` → `_verify_prepared` → `file_sha256(core, manifest["core_sha256"])` → `ValueError`。每支 `branch_failure.json` 记录 exit 1；无业务账本。
- 隔离 runner 的 `run_single_from_cli` 第 733 行先 `_verify_prepared`，其后才读配置、CA snapshot、`_load_prepared_window`。因此 traceback 证明没有进入准备窗口信号/行情消费；manifest/artifact 与实际 core 文件校验此前已发生。
- `run_prefixes.ps1` 第 3 行设 `PYTHONPATH` 为隔离 core `src`，第 6 行切 CNN worktree，第 7 行启动 Python CLI。Python 导入优先级使同名模块可从该源码优先导入；三栈中的 `inspect.getfile` 解析路径及 hash 是实际文件证据，不是单凭环境变量推断。
- 隔离 `staged_production_inputs.py` `_finish_preparation` 第 549–557 行用 `inspect.getfile` 生成 manifest core path/hash；`_verify_prepared` 第 626–635 行同时验证 manifest sidecar SHA、artifact SHA、当前导入 core 字节 SHA 与路径。故 manifest 同时是输入准备血缘记录和强制 runtime 身份门。

## 版本与覆盖缺口

- 原 wheel `account_runner.py` SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`；隔离源码 SHA `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- 可见 diff：隔离版新增 `json`、`stop_after_close` 参数/日期与 T+1 校验、指定 close 后 break、pending orders provenance；末尾按 metric_end 截取 NAV 并传 `trade_end`。普通 wheel 不支持该参数。
- fix5 `RUN_LOG.md` 与 reverify4 `RUN_LOG.md` 明确设隔离 `PYTHONPATH`，但其 94 测试是 mini；`test_staged_production_inputs.py` 的 `test_eight_real_core_attempts...` mock `_verify_prepared` 返回手造 manifest。没有测试真实 v12 manifest 与隔离 import 的组合，所以未触发身份 SHA 冲突。

## prefix 与信任边界

- `--run-prefixes` 只构造固定 cutoff 命令并绕开“事先已有 proof”的 CLI 门；runner 对真实 W1 仍强制 prepared inputs、CA snapshot、数量规则、预注册费用与 cutoff。它不授权完整绩效。
- `_verify_prepared` 当前没有 prefix mode；因此准备 core SHA 与 runtime core SHA 被硬要求相等。attestor 只在八支全部 COMPLETE 后运行；现有三个 pin 均 None，UNPINNED 不能构成可信证明。
- v12 manifest hash、原始 wheel/baseline 身份、独立 runtime identity 必须分字段保存。external attestation 与 verifier 必须共同绑定双身份；不得把隔离 core 哈希写成 baseline core 或放宽现有 pin。

## tmux 核实与可靠执行模板

- `run_prefixes.ps1` 无 tmux 命令；证据树无 `process_status.txt`、tmux capture/pane 状态。stdout/stderr 顶层为空，已尝试 3 支的 branch JSON 各自 exit 1。报告一处称 pane 不可读，另一处称“以 tmux 启动”；后者无法由现存材料独立确认。
- 后续获准运行时，新建 wrapper 脚本并在脚本内 `Set-Location -LiteralPath '<绝对 worktree>'`；`try/catch/finally` 将 stdout、stderr、异常栈、最终 `$LASTEXITCODE` 和 UTC 结束时间写到新证据目录，状态写入采用独立文件。
- 启动模板：`tmux new-session -d -s cnn_w1_prefix_dual_v1 -c '<绝对 worktree>' "pwsh -NoLogo -NoProfile -File '<新证据目录>/run_prefixes_logged.ps1'"`。短轮询 `tmux display-message -p -t cnn_w1_prefix_dual_v1 '#{pane_dead} #{pane_dead_status}'`；对照 wrapper 状态与完整八支 JSON。仅 pane 已自然退出且三种退出记录一致才记成功；中断/错误仍保存全部分支，不复用或覆盖目录。
