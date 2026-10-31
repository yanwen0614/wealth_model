# 命令与输出摘要

工作目录均为冻结树。解释器：`.venv\Scripts\python.exe -B`；core 测试显式设置 `PYTHONPATH=C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src`。未调用 uv。

1. SHA：`Get-FileHash fractional_scenarios.py,test_fractional_scenarios.py -Algorithm SHA256`。输出分别为冻结值 `7112…7180`、`D810…31A5`；审后重核仍相同。
2. core 导入：`python -B -c "import inspect,hashlib,backtest_core.engine.account_runner as m; ..."`。输出实际路径为 `backtest-core-w1-stop-20261028\src\backtest_core\engine\account_runner.py`，SHA `4d3a28c4…2220a1819`。
3. fractional 回归：`python -B -m unittest tests.unit.backtest.test_fractional_scenarios`。输出 `Ran 28 tests in 14.789s / OK`。
4. 定向组合：`python -B -m unittest tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_prefix_attestor tests.unit.backtest.test_prefix_ledger_verifier tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_production_inputs tests.unit.backtest.test_dual_core_identity tests.unit.backtest.test_run_identity`。输出 `Ran 122 tests in 431.610s / FAILED (failures=8, errors=2)`。主要可复现错误为 external attestation source SHA mismatch、双 core 测试预期身份与当前白名单不一致；多个 staged production subprocess 加载 torch CUDA DLL 时 `WinError 1455` 页面文件不足。该组合结果不构成 PASS。
5. Ruff：`.venv\Scripts\python.exe -B -m ruff check --no-cache <上述 7 个生产模块及 7 个测试模块>`。输出 `All checks passed!`。
6. Pyright：`$env:PYTHONPATH=<隔离 core src>; .venv\Scripts\pyright.exe --pythonpath .venv\Scripts\python.exe <7 个生产模块及 5 个核心测试模块>`（排除 `test_run_identity.py`、`test_staged_production_inputs.py`）。输出 `0 errors, 0 warnings, 0 informations`。
7. Pyright 扩大到两项排除测试时输出 12 errors：11 项位于 `test_run_identity.py`，1 项位于 `test_staged_production_inputs.py`，为测试类型问题。
8. attestor 清单逐项比较：`fixed_source_sha256()` 共 15 项，14 项匹配；唯一差异是 `fractional_scenarios.py` 固定 `9e78eae5…e6f2f2`，实际 `7112BEDE…E37180`。验证命令完整输出在本会话 QA 执行记录中，审后摘要和全部 SHA 见 `HASHES.sha256`。

无真实 cutoff / prefix / 绩效命令。工作区原有变更清单在 QA 前已存在；QA 未触碰这些文件。
