# W1 Prefix Fix3 交接记录

日期：2026-10-28

## 本轮变更

- `staged_candidate_runner._freeze_fees` 只预解析不晚于 `information_cutoff` 的 prepared/resolver 费用日期。cutoff 后日期不会触碰未来费用表。
- Prefix 使用 `historical_costs.resolve_historical_costs` 按截止日分别构造 SSE/SZSE 静态研究费用 bundle，记录截止日、规则来源、市场配置和 canonical JSON SHA-256 到 `prefix_fee_policy.jsonl`。
- 加强回归：证明未来费用键未查询、resolver 被 fail-closed 拒绝、bundle 两市场配置一致且摘要可重算。

## 验证

- RED：旧 `_freeze_fees` 对 cutoff 后日期访问 prepared fee table，定向回归失败。
- GREEN：指定 core worktree `src` 为 `PYTHONPATH` 后，`test_staged_candidate_runner` 与 `test_prefix_ledger_verifier` 共 50 项通过；其中含原 wheel/core 独立进程 mini 对照。
- Ruff：目标两文件通过。
- Pyright：目标两文件 0 errors / 0 warnings / 0 informations。
- `git diff --check` 通过。

## 仍阻断的目标

- 真实 12 路径 W1 执行及可信 proof 未完成，也未启动真实执行或绩效。
- 当前 W1 原运行账本来自 CA 异常中断的 `INCOMPLETE` 尝试；没有独立绑定的 canonical baseline 身份及三路逐事件比较结果。
- `generate_prefix_proof` 保持硬阻断，`TRUSTED_PREFIX_PROOF_SHA256=None`；BLOCKED 记录和 mini 结果不能升级为生产 proof。
- 独立只读 QA 对 fee 修复复验 PASS；其同时确认上述 W1 proof 缺口仍未解决。

## Worktree

- CNN：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`，分支 `research/w1-fractional-scenarios-20261028`，HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。
- Core：`C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028`，分支 `research/w1-prefix-stop-core-20261028`，HEAD `893fc96925e029098f6c758dba8724d187c6b512`；保留既有 stop-core 修改，本轮未改动。
- core worktree 中一次诊断命令曾由 `uv run` 创建临时 `.venv` 并安装 16 个包；该 `.venv` 已删除，core worktree 状态恢复为仅保留原有 stop-core 两处修改。CNN 验证均使用 `uv run --no-sync`；未提交、未推送。
