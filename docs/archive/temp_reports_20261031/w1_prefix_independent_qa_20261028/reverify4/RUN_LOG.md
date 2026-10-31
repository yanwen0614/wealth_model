# reverify4 命令与结果

环境：PowerShell；解释器 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；`PYTHONPATH=C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src`。未使用 uv。

1. CNN 定向集：`python.exe -B -m unittest tests.unit.backtest.test_prefix_attestor tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_production_inputs` — 94 tests，OK，46.104s。
2. 隔离 core：`python.exe -B -m unittest tests.test_account_orders` — 46 tests，OK，0.102s。
3. Ruff：`python.exe -B -m ruff check .` — All checks passed。
4. Pyright：使用项目虚拟环境解释器和隔离 core `PYTHONPATH` 检查 runner、production inputs、scenario、CLI、attestor、verifier、proof gate 和相关测试 — 0 errors/warnings/informations。

独立源码检查：`TRUSTED_PREFIX_PROOF_SHA256=None`、`TRUSTED_PREFIX_ATTESTATOR_SHA256=None`、`TRUSTED_PREFIX_ATTESTATION_SHA256=None`。Proof validator、attestor 状态与 verifier pin 检查均 fail-closed。

完整性：15 项固定 source/core pin 一致；审后 CNN/core git status 与审前记录一致。重点文件 SHA-256 见 `HASHES.sha256`。

测试包含合成/mini。未运行真实 W1 prefix、真实八分支、12 路径 proof、绩效或任何全量数据扫描；未修改源文件、wheel、数据、依赖；未提交或推送。
