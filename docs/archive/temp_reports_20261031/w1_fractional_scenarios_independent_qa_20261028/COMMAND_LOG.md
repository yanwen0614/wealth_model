# QA 命令记录

工作目录：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`

解释器：`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`（既有环境；未安装依赖）。

| 检查 | 结果 |
|---|---|
| 定向 unittest：fractional scenarios、corporate action context/runner E2E、staged candidate runner/bridge/strategy | PASS — 84 tests in 8.000s |
| Ruff `python -B -m ruff check --no-cache`（5 个目标文件） | PASS — All checks passed |
| 定向 Pyright `--pythonpath <既有解释器>`（5 个目标文件） | PASS — 0 errors, 0 warnings, 0 informations |
| 官方 PDF SHA-256 | PASS — 与固定 SHA 一致 |
| core `account_runner.py` SHA-256 | PASS — 与固定 SHA 一致 |
| 目标 5 文件交付哈希 | PASS — 5/5 一致 |

外部只读数值探针：`resolve(1, floor)` 得精确权益 0.4002532、0 股；`resolve(2,500,000, floor)` 与 `resolve(5,000,000, floor)` fail-closed 于 core float entitlement 精确性校验；`resolve(10^20, floor)` 接受；`resolve(10^30, floor)` fail-closed。探针无文件输出。

未运行 1000+ 事件的全窗模拟、八分支绩效或训练；未向冻结树写文件。测试/ruff/pyright 标准输出如上留存；验证全过程为前台定向调用。
