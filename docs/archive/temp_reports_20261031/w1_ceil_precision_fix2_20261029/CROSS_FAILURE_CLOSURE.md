# 旧交叉回归失败逐项核对

## 可取得完整 traceback 的两项 SHA 错误

| 旧错误 | traceback 根因 | 新关闭证据 |
|---|---|---|
| `test_parent_attestation_plan_binds_runtime_import_identity_without_user_hashes` | `fractional_scenarios.py` 实际 SHA 与 fixed source map 中旧 `9e78...` 不符，`file_sha256` 抛 `输入 SHA256 不匹配`。 | pin 更新为实测 `7112...7180`；15 项实文件校验测试通过；主回归同名测试通过，见 `logs/tests_unit_backtest_test_dual_core_identity.log`。 |
| `test_machine_proof_recomputes_all_12_branches_and_stays_unpinned` | 外部 attestation 的 source SHA map 与当前源码不同，抛 `external attestation source SHA mismatch`。 | 同一固定 source map 修复后，主回归同名 proof 测试通过，见 `logs/tests_unit_backtest_test_prefix_ledger_verifier.log`；production pins 仍为 `None`。 |

旧 traceback 原文见独立 QA 归档 `w1_ceil_precision_independent_qa_20261029/CROSS_REGRESSION.log`。该文件记录 168 项运行中的这两项 errors；`RUNS.md` 另记录 122 项运行有 8 failures/2 errors，但该 122 项运行的逐项 traceback 未归档，两份材料的测试数不同。

## 页面文件 / DLL 类失败

- 新的分段主回归中 `test_staged_production_inputs` 12/12 通过；可用内存记录为 6880→6886 MiB，页面文件占用 2267 MiB，未出现 `WinError 1455` 或 `cufft64_12.dll`。
- 再单独串行复跑 `test_prepare_only_real_small_files_then_run_prepared_uses_cache`（子进程路径运行完整 8 次 mini prepared attempts）及 `test_cli_prepare_and_batch_are_callable`，均通过；复跑前后物理可用内存为 6622→6953 MiB / 6946→6921 MiB，页面文件占用 2190 MiB。日志为 `logs/failure_repro_eight_prepared_attempts.log` 与 `logs/failure_repro_cli_batch.log`。
- 旧 122 项运行的 8 个失败缺少逐项 traceback，故无法把每条旧异常与具体用例逐一匹配。新串行模块和专项子进程回归未复现；不据此推断旧故障当时的单一根因。
