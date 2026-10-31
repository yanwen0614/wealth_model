# Re-verify 命令与实测结果

工作目录：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`
解释器：既有 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；未安装依赖。

| 检查 | 实测结果 |
|---|---|
| 六模块定向 unittest（95 项） | PASS — Ran 95 tests in 11.506s; OK |
| Ruff `--no-cache`（六个修复目标） | PASS — All checks passed |
| 定向 Pyright（六个修复目标，指定 pythonpath） | PASS — 0 errors, 0 warnings, 0 informations |
| 11 个 proof/入口/fail-closed 回归用例 | PASS — Ran 11 tests in 3.597s; OK |
| 独立直接调用 `_run_staged_window_impl` 全窗反例 | PASS — ValueError: prefix proof SHA is not independently pinned; 在读 signal/core 前拒绝 |
| 6 个 fix1 源码 SHA（检查前/后） | PASS — 全部匹配 FIX1_HASHES.json |
| core runner / 官方 PDF SHA-256 | PASS — 匹配固定 SHA |
| HEAD | PASS — 前后均 `ce7d1c6e0bd64136f10759412c55f6da410f128f` |

未运行绩效/全窗；未改工作树、未安装依赖、未提交推送。Mini 的真实 core 验证包含于定向测试，不作为 prefix proof。
