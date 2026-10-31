# W1 双 core 身份隔离计划

## 调试结论

- v12 `manifest.json` 的 `core_path/core_sha256` 是准备输入时实际导入引擎的身份，同时 `_verify_prepared` 将其作为运行前强制身份门；它既记录数据准备血缘，也约束当前 runtime。准备阶段没有“仅血缘”模式。
- 三份原始 traceback 均在 `staged_production_inputs.py::_verify_prepared` 的 `file_sha256(core, manifest["core_sha256"])` 抛错，发生于 runner 读窗口信号/行情之前。manifest 原 SHA `aa156e…daa00`；隔离 runtime 文件 `4d3a28…1819`。
- `PYTHONPATH` 只改变 Python import 搜索优先级；本次 traceback 的 `inspect.getfile(...)` 路径直接证明实际选中隔离 core。仅凭脚本设值不能证明读取次序；这次在 core 身份门前停止，未进入 `_load_prepared_window` 的信号与市场读取。manifest/artifact 文件在 `_verify_prepared` 中先验读校验。
- fix5/reverify4 mini 未覆盖“真实 v12 manifest + 实际 import 路径 + `_verify_prepared`”组合：reverify4 明确仅合成/mini；现有 `test_eight_real_core_attempts...` mock `_verify_prepared`（测试行 378），且 mini window 不含 v12 manifest。故 94 项通过不检验此次身份组合。

## 最小改动设计（待另行授权实施）

1. 仅在 CNN 隔离 worktree 修改 `backtest/cnn_adapter/staged_production_inputs.py`、`fractional_scenario_cli.py`、必要时 `prefix_ledger_verifier.py`；不改 v12 manifest、原 baseline、wheel、core 或既有 pin。
2. `_verify_prepared` 默认维持现状：manifest SHA、artifacts、core 路径及 core SHA 全部精确匹配；生产入口不得接受 override。新增显式 `prefix_experiment` 身份上下文，仅 `--run-prefixes` 可构造。
3. 实验模式仍先验证冻结 manifest 原始 SHA `a8ad…4441`、其 `core_path/core_sha256` 原值及全部 artifacts；再单独核 runtime `inspect.getfile` 路径与 SHA，允许值仅为原 wheel `aa156e…daa00` 或审定隔离源码 `4d3a28…1819`。路径/hash 必须成对精确命中 allowlist；任一其它 core 差异 fail closed。
4. 将 `prepared_core_path/hash` 与 `runtime_core_path/hash` 写入独立新建的 experiment identity 配置及每分支 controlled identity/attestation，不回写原 manifest。`prefix_ledger_verifier` 校验其双字段、预期实验配置 SHA 和 runtime allowlist；新 core 绝不能重标为 original baseline。
5. 保持 proof、attestor、attestation-root 三个生产 pin 不变；只有独立审查后才另行锚定。UNPINNED 仍拒绝正式 proof/完整绩效。source/input/PDF SHA、cutoff、五类账本完整字节比较、外置见证要求一项不降。

## 实验与逐事件 baseline

- 不重写/重签 v12 manifest。新配置放在独立 experiment 目录，记录原 manifest SHA、原 core 身份、runtime core 身份、代码/配置 SHA、固定 cutoff 与启动命令。
- 对原 wheel 与隔离 core 建立独立 cutoff-only 双跑；逐事件比对 execution updates、daily account、decisions、transitions、partial states 的原始行、顺序、字段及 SHA。比较范围到 2021-06-07 close；同时核对 6/7 收盘后待执行订单状态。不得把新 core 的结果称为 baseline。
- 再以隔离 core 的八策略情景前缀逐一对 pinned 原始 baseline 的 cutoff 前缀作完整字节比较。原四份 baseline 仍为 INCOMPLETE；相等只证明此前缀机械事件一致，不补足 6/8 公司行动获配、税务 PIT 或真实绩效。
- 若任一身份、输入、测试、事件差异、 attestation 或退出状态门失败，停止后续分支；保留已生成的全八分支目录/状态/日志，不覆盖，不挑选成功分支，不运行全窗绩效。

## 文件与验证范围

- 计划修改：`backtest/cnn_adapter/staged_production_inputs.py`、`backtest/cnn_adapter/fractional_scenario_cli.py`、`backtest/cnn_adapter/prefix_ledger_verifier.py` 及对应 `tests/unit/backtest/test_staged_production_inputs.py`、`test_fractional_scenarios.py`、`test_prefix_ledger_verifier.py`；若 identity 独立模块化，再新增模块和专属单测。
- 必测：默认生产路径原 wheel exact pass；默认生产拒绝隔离 core；prefix allowlist 两身份各自 pass；路径/hash错配与第三身份拒绝；manifest 原始 SHA/字节不变；准备输入/artifact SHA 不变；PYTHONPATH import 证据绑定；cutoff 后读取/账本行拒绝；全八分支失败仍完整留存；proof/pin 缺失继续 fail closed。
- 集成门：真实输入双 core cutoff-only逐事件比较及八策略×floor/ceil prefix。只在身份单测、隔离审查和输入 SHA 全通过后运行；不得运行 E 日之后或绩效。

## tmux 执行记录要求

- 现有 `run_prefixes.ps1` 是普通 PowerShell 脚本：自身没有 tmux 调用；REPORT 的“tmux 启动”无 pane/session 输出、`process_status.txt` 或启动器证据佐证。可确认脚本尝试运行 CLI；无法独立确认它由 tmux 启动。CLI 顶层日志为空，3 个 branch failure 各记 `exit_code=1`。
- 后续先用新脚本把工作目录显式 `Set-Location`，用 `try/catch/finally` 分别追加 stdout/stderr 与 `exit_code/finished_utc/error` 状态；tmux 命令显式 `cd` 到隔离 worktree，保存 session 名、启动命令、pane dead/status 与日志路径。自然退出后核对脚本状态码、tmux pane 状态、八分支 `branch_status.json` 三者一致；信号中断也写中断状态并保留目录。
