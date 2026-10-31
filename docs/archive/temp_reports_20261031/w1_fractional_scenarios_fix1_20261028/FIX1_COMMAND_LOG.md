# fix1 验证命令日志

解释器：`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`。未安装依赖。

## RED（改门禁前）
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_direct_executor_rejects_before_output_or_subprocess tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_direct_full_runner_rejects_before_output_input_or_core tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_mini_labels_cannot_disguise_a_full_window
Ran 3 tests
FAILED: executor 已调用 subprocess（随后日志写入出现 MagicMock TypeError）；全窗 run_staged_window 未因 prefix proof 拒绝并已创建尝试输出；伪 mini 未在前缀门处拒绝。
```

## GREEN
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios tests.unit.backtest.test_corporate_action_context tests.unit.backtest.test_corporate_action_runner_e2e tests.unit.backtest.test_staged_candidate_runner tests.unit.backtest.test_staged_execution_bridge tests.unit.backtest.test_staged_order_strategy
Ran 91 tests in 9.326s — OK

python -B -m ruff check --no-cache backtest/cnn_adapter/fractional_prefix_gate.py backtest/cnn_adapter/fractional_scenarios.py backtest/cnn_adapter/fractional_scenario_cli.py backtest/cnn_adapter/staged_candidate_runner.py backtest/cnn_adapter/staged_production_inputs.py tests/unit/backtest/test_fractional_scenarios.py
All checks passed!

pyright --pythonpath D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe [上述六个目标文件]
0 errors, 0 warnings, 0 informations
```

RED 命令来自修复前真实运行；GREEN 为修复后运行。未运行完整窗口或训练。

## 第二轮 RED / GREEN（直接 mini context）
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_direct_mini_context_construction_requires_bounded_runner
修复前：FAIL — AssertionError: ValueError not raised（公开 mini context 构造可直接成功）。

完整定向 unittest（同上六个模块）
Ran 93 tests in 11.334s — OK

Ruff（六个目标文件）
All checks passed!

Pyright（六个目标文件）
0 errors, 0 warnings, 0 informations
```

第二轮修复后，mini 只能由有界输入 factory 构建；其他事件税务未知恢复严格 fail-closed。

## 第三轮 RED / GREEN（伪造 provider）
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_mini_factory_rejects_provider_with_forged_class_identity
修复前：FAIL — AssertionError: ValueError not raised（同名且伪造 __module__ 的 provider 被接受）。

最终定向 unittest（上列六个模块）
Ran 94 tests in 11.482s — OK

Ruff：All checks passed!
Pyright：0 errors, 0 warnings, 0 informations
```

修复后 mini factory 使用 `type(market) is SyntheticMarketProvider` 精确类型检查。

## 第四轮 RED / GREEN（移除可返回 context 的 factory）
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_no_publicly_callable_factory_returns_unbound_mini_context
修复前：FAIL — AssertionError: mini context factory 可被直接调用并返回 context。

最终定向 unittest（六个模块）
Ran 95 tests in 11.623s — OK

Ruff：All checks passed!
Pyright：0 errors, 0 warnings, 0 informations
```

mini context 现在只在已验证的 staged runner 中构造，并由该次调用直接传入 core；没有公开返回 context 的 factory。

## 第五轮 RED / GREEN（移除可直调 initializer）
```text
python -B -m unittest tests.unit.backtest.test_fractional_scenarios.FractionalScenarioTests.test_no_publicly_callable_factory_returns_unbound_mini_context
修复前：FAIL — name-mangled `__initialize_context(..., allow_mini=True)` 仍可直接访问。

最终定向 unittest（六个模块）
Ran 95 tests in 11.623s — OK

Ruff：All checks passed!
Pyright：0 errors, 0 warnings, 0 informations
```

修复后删除 mini initializer；公开 constructor 仅执行 W1 proof gate，mini context 只在 staged runner 内联初始化并立即进入同一路径 core 调用。
