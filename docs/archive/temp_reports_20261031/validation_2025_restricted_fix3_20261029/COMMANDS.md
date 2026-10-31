# fix3 复验与证据

工作目录固定为C:/Users/yanwen/AppData/Local/Temp/opencode/validation-2025-restricted-20261029。
verify.ps1在tmux validation2025_fix3_checks内显式Set-Location，使用原venv Python -B且保留总退出码。
完整日志GREEN/REGRESSION/PROBES/RUFF/PYRIGHT.log，各步和总退出码均为0；没有年度A/B调用。

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m unittest tests.unit.backtest.test_2025_restricted tests.unit.backtest.test_2025_restricted_fix2 tests.unit.backtest.test_2025_restricted_fix3
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m ruff check --no-cache .
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m pyright --pythonpath 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' --project 'C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_restricted_fix3_20261029/pyrightconfig.json'
```

pyrightconfig真实存在：include按工具要求相对本配置，script/test环境extraPaths均为明确绝对路径。
只读集成raw_provider实际提供history_bars（默认20、正整数的历史预热条数）；未删参数或忽略类型错误。
实际Python、模块路径、SHA及provider签名见IMPORT_CONTRACT.json和SOURCE_FINAL.json。

capture_inputs.py在生产修复前保存BEFORE.json和ORIGINAL_ROWS.json，后者含四条原始row及三项UNKNOWN pins。
RED_ORIGINAL_EVENTS.log使用原始103185、55290，证明旧guard在1/6误阻断，另复现公告同日过早中断。
test_2025_restricted_fix3.py新增7项：两原事件、公告后持仓中断、无/早/坏公告、最早预案、
有效日期先到、非持仓、同代码另一条更早公告不被未来条目覆盖；均经真实core回调，无mock账本。

produce_evidence.py仅运行12组8日左右窗口mini；行情和数量规则是合成fixture，原始事件原值保持不变。
不能用这些mini的金额/收益冒充v1年度真实账户；v1目录完全没有被本任务写入或覆盖。
重跑持久mini需新输出路径，现存core_*均排他创建。

原QA优先核：core_early_A/B中原始raw_row与ORIGINAL_ROWS一致，1/6真实buy并未提前中断；
core_after_public_A在7/25留deferred_future_publication，7/28正持仓未知登记才中断；B为8/29至9/1。
core_older_row_not_masked中先处理103186的3/28，不被103185的7/25覆盖；不能据progress2或0金额豁免。
core_no_publication/record_first/effective_first继续及时中断；core_unheld不影响其他代码。

每个core_*：core/execution_updates.jsonl保存pre/post_state、cash_delta、fill、positions/locked及登记量；
ca_observed_checks.json保存具体信息边界和日期假设。原始事件保留，未知pins未变已知。
旧31项与109相关回归仍通过；独立QA状态仍PENDING。不得据owner自测宣布目标通过。
