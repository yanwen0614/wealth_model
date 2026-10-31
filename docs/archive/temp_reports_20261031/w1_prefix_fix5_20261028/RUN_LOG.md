# fix5 实际命令与结果

运行环境：PowerShell；CNN worktree；现有 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；`PYTHONPATH=C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src`。未运行 uv/安装依赖。

## RED（修复前）

1. `python.exe -B -m unittest tests.unit.backtest.test_prefix_ledger_verifier.PrefixLedgerVerifierTests.test_cutoff_ledger_rejects_2021_06_08_even_if_manifest_is_rehashed tests.unit.backtest.test_prefix_ledger_verifier.PrefixLedgerVerifierTests.test_qa_forged_audit_rehashed_manifest_and_june_8_rows_fail`
   实际输出：`Ran 2 tests ... FAILED (failures=2)`；两项均为 `AssertionError: ValueError not raised`，复现 cutoff 后行被裁掉、重签 audit/artifacts 仍被接受。
2. `python.exe -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_cutoff_command_set_is_buildable_without_existing_proof`
   实际输出：`TypeError: build_commands() got an unexpected keyword argument 'prefix_only'`。

## GREEN / 最终验证（2026-10-29 00:29）

1. `$env:PYTHONPATH='C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src'; & 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m unittest tests.unit.backtest.test_prefix_attestor tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_production_inputs`
   输出：`Ran 94 tests in 45.433s — OK`。
2. `& 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' -B -m ruff check .`
   输出：`All checks passed!`
3. `$env:PYTHONPATH='C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src'; & 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\pyright.exe' --pythonpath 'D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe' backtest/cnn_adapter/staged_candidate_runner.py backtest/cnn_adapter/staged_production_inputs.py backtest/cnn_adapter/fractional_scenarios.py backtest/cnn_adapter/fractional_scenario_cli.py backtest/cnn_adapter/prefix_attestor.py backtest/cnn_adapter/prefix_ledger_verifier.py backtest/cnn_adapter/fractional_prefix_gate.py tests/unit/backtest/test_prefix_attestor.py tests/unit/backtest/test_prefix_ledger_verifier.py tests/unit/backtest/test_fractional_scenarios.py tests/unit/backtest/test_staged_candidate_runner.py`
   输出：`0 errors, 0 warnings, 0 informations`。此前省略 Python/core 路径的探测命令报依赖解析错误；按已记录环境参数重跑后通过。
4. `rtk git diff --check`
   输出：退出码 0，无输出。

独立进程测试通过：attestor subprocess 的测试专用计划生成八分支输出哈希和外置只读访问记录；随后改写一个输出，实测输出 SHA 与见证记录不匹配。生产 source 清单与固定输入库存也在 94 项 mini 中校验。由于生产 attestor pin 仍为 None，正式计划的 attestation 状态仍是 UNPINNED，verifier 会拒绝。未运行真实八分支、prefix、绩效或完整 W1。

## 独立 QA 复审

- 只读复审确认 cutoff-only、cutoff 后行拒绝及 proof gate 的代码路径已修复；固定 CNN source 清单与 core SHA 共 15 项均匹配当前字节。
- 首次 QA 测试因默认解释器未加载 `backtest_core`/`pyarrow` 未运行；按本日志指定解释器与 `PYTHONPATH` 重跑后，94 项 mini 全部通过、Ruff 通过。
- 独立 QA 最终裁决：mini/synthetic PASS；真实生产 proof BLOCKED。三个生产 pin 保持 None，未运行真实 prefix、八分支或绩效。

## reverify4 独立复跑（2026-10-29）

- 环境：固定 CNN `.venv` Python `-B`；`PYTHONPATH` 指向隔离 backtest-core 源码。未运行 uv、未安装依赖。
- `python.exe -B -m unittest tests.unit.backtest.test_prefix_attestor tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_production_inputs`：94 项通过，46.104s。该集合包含合成/mini，不代表真实 W1 prefix。
- 隔离 core `python.exe -B -m unittest tests.test_account_orders`：46 项通过，0.102s。
- `python.exe -B -m ruff check .`：All checks passed。
- 固定解释器 Pyright 对 runner、prepared input、scenario CLI/verifier/attestor/gate 及相关测试：0 errors、0 warnings、0 informations。
- 静态核对：三个 gate pin 均为 None；`validate_prefix_proof` 首先硬拒；attestor 输出 `UNPINNED_ATTESTATOR`；verifier 因 attestation root/attestor SHA 未锚定而拒绝。
- 审后 source/core SHA 与冻结清单一致；CNN/core 的既有修改及未跟踪文件清单未变化。详见独立复验目录 `reverify4/`。
- 未运行真实 8 分支、12 路径 proof 或绩效；未修改代码、core、wheel、数据；未提交或推送。
