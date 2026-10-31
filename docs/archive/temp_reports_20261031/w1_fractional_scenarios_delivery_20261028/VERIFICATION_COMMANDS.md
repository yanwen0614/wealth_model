# 可复现命令与八分支调度

以下命令以隔离 worktree 为 cwd，使用主区只读解释器，不安装或同步依赖。

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m unittest tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_corporate_action_context tests.unit.backtest.test_corporate_action_runner_e2e tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_execution_bridge tests.unit.backtest.test_staged_order_strategy
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m ruff check --no-cache backtest/cnn_adapter/fractional_scenarios.py backtest/cnn_adapter/fractional_scenario_cli.py backtest/cnn_adapter/staged_candidate_runner.py backtest/cnn_adapter/staged_production_inputs.py tests/unit/backtest/test_fractional_scenarios.py
pyright --pythonpath 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' backtest/cnn_adapter/fractional_scenarios.py backtest/cnn_adapter/fractional_scenario_cli.py backtest/cnn_adapter/staged_candidate_runner.py backtest/cnn_adapter/staged_production_inputs.py tests/unit/backtest/test_fractional_scenarios.py
```

计划命令（只打印八个 branch argv，不运行绩效）：

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m backtest.cnn_adapter.fractional_scenario_cli --prepared-manifest 'C:/Users/yanwen/AppData/Local/Temp/opencode/staged_prepared_inputs_20261027_v12/manifest.json' --input-config 'C:/Users/yanwen/AppData/Local/Temp/opencode/staged_prepared_inputs_20261027_v12/integration_inputs.json' --official-pdf 'C:/Users/yanwen/AppData/Local/Temp/opencode/ca_300502_official_search3_20261028/cninfo_2021-030_1210131886.PDF' --output-root 'C:/Users/yanwen/AppData/Local/Temp/opencode/w1_fractional_scenarios_delivery_20261028/runs'
```

未来只有 prefix proof 独立核签通过后，才可在上面的命令末尾追加：

```text
--execute --prefix-proof <独立核签的prefix-proof.json> --expected-prefix-proof-sha256 <该proof的SHA256>
```

执行器目前被锁定：源码 `TRUSTED_PREFIX_PROOF_SHA256` 为 `None`，任意自带 proof 与调用者自报 SHA 都会被拒绝。独立 QA 和主会话核对完成 prefix 后，须先将准确 proof SHA 固定到此源码常量，再运行；proof 必须 `status=PASS`、base HEAD 为 `ce7d1c6e0bd64136f10759412c55f6da410f128f`、canonical floor/ceil 注入前缀逐项一致并覆盖至 2021-06-07。缺证时不得启动全窗。

执行器对 `B1/S1/S2/C70 × floor/ceil` 各启动独立 core 进程，使用不同输出目录；每支保留 stdout、stderr、core audit/manifest 和 exit code。退出码非0标 `FAILED`；退出码为0但 core `mechanical_status != PASS` 标 `INCOMPLETE`；只有真实 core `PASS` 才标 `COMPLETE`。八支都会继续并汇总到 `branch_status.json`。CLI 不改 v12 inputs、费用、税压力口径、日历、信号或初始资金。
