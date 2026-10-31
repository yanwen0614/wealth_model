# 复验命令与结果

- 解释器：`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；隔离 core 运行时显式 `PYTHONPATH=C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src`。未调用 uv。
- 提交者 74 项：`python -B -m unittest tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_fractional_scenarios` → 74 OK。
- Core：`python -B -m unittest discover -s tests -p test_account_orders.py` → 46 OK。
- CNN 8 文件 Ruff → All checks passed；CNN Pyright → 0 errors/warnings/informations。
- Core 两文件 Ruff → All checks passed；core Pyright → 0 errors/warnings/informations。
- 74 tests 内含 `test_original_wheel_and_isolated_core_have_exact_staged_prefix`，独立子进程逐项断言 snapshots/trades/observer prefix 相等。wheel path `.../.venv/Lib/site-packages/backtest_core/engine/account_runner.py` SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`；隔离 path `.../backtest-core-w1-stop-20261028/src/backtest_core/engine/account_runner.py` SHA `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- 真实四 baseline `_baseline_identity` 独立复核：B1/S1/S2/C70 均 hash 验真，状态全为 INCOMPLETE。
- 对真实 v12 manifest + input config + PDF 调 `build_commands`（只构造、不执行）：生成 8 命令；每条 evaluation_end=2021-06-30，均缺 prefix cutoff 与 information cutoff 参数。
- `staged_w1_prefix_fix4_runs_20261028` 不存在。源码真实 W1 cutoff 用例在 74 tests 中验证 fail-close；fractional CLI 在执行/读取输入前要求 proof pin。
- `probe_forged_audit.py`：文件系统临时 fixture 中复制 ceil→floor，改 audit/evidence、重签 artifacts，并在五账附加 2021-06-08 行；生成与重验候选 proof = PASS。性能 Gate 随即拒绝：`prefix proof SHA is not independently pinned; performance is locked`。
- 该攻击探针仅为固定根路径而 patch verifier 常量；所有文件、账本、manifest 均实际落盘并由代码重读/重算。真实 baseline/pin 验真、命令预览和导入路径核验未 patch。
- 前后冻结哈希：源树/wheel 28 项 + baseline/冻结输入 42 项，共 70 项；审后重算 0 mismatch。完整清单在 HASHES_*_PRE/POST.txt。
- 未写两隔离树；未运行真实 prefix、12 路径、完整 W1 或绩效。
