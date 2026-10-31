# W1 prefix stop-core fix2

## 交付状态

- CNN worktree：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`
- CNN 基线 HEAD：`ce7d1c6e0bd64136f10759412c55f6da410f128f`
- Core worktree：`C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028`
- Core 基线 HEAD：`893fc96925e029098f6c758dba8724d187c6b512`
- 两棵树均未提交；本交付未安装依赖，未运行真实 W1、12 路径重放或绩效。

## 本轮修复

- Prefix fee 只允许 cutoff 内输入；真实 `W1` 缺 cutoff-scoped PIT 输入包时 fail-closed。限定的 `test_W1_mini` 使用静态成本，仅作为合成测试。
- 默认路径不再向旧 wheel 传 `stop_after_close`。prefix 路径才向隔离 core 传该参数。
- 增加原 wheel 与隔离 core 的独立进程 staged mini 对照，比较 cutoff 前账户快照、交易及观察账本，并断言两边实际导入文件 SHA。
- 五类账本只提供诊断性 `rows_identical`；同目录比较拒绝，空账本失败。调用者提供的任意文件无法生成生产 proof。
- 生产 proof 生成目前硬阻断；可选 BLOCKED 记录含四策略×三路径清单。`TRUSTED_PREFIX_PROOF_SHA256=None` 保持绩效门锁定。

## 验证摘要

- `tests.unit.backtest.test_prefix_ledger_verifier` 与 `tests.unit.backtest.test_staged_candidate_runner`：48 项通过；运行时 `PYTHONPATH` 指向隔离 core `src`。
- Ruff：指定五个实现/测试文件通过。
- Pyright：相同范围 0 errors、0 warnings、0 informations。
- 主区安装 wheel SHA 未变：`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。
- 隔离 core runner SHA：`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。

## 未解决边界

四策略×baseline/floor/ceil 的 12 次真实运行、源文件与原账身份绑定、完整 gate-compatible proof 尚未实现。当前只安全地产生 BLOCKED；不得宣称 W1 prefix 等价或解锁绩效。mini 对照不能证明历史 W1 等价。

独立复验目标：上一轮 quality-gate 会话 `ses_e7e05e9d7ffeiXuaQM6zldVkS9`。请只读复查本交付与两棵 worktree，不修改、不提交、不运行真实 W1/大重放。
