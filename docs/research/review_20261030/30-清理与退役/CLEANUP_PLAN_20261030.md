# 临时目录清理方案（2026-10-30）

范围：`C:/Users/yanwen/AppData/Local/Temp/opencode/` 一级条目，共 365 条（242 目录 + 123 文件，52,364 个文件，约 26.9 GB）。

## 红线遵守声明

1. 仅处理 `C:/Users/yanwen/AppData/Local/Temp/opencode/`；`D:/code/` 全程只读（用于 Grep 引用判定与哈希比对）。
2. `recovered_w1_20261030/` → KEEP_ACTIVE，不删。
3. `worktree_retirement_20261030/`、`worktree_retirement_20261028/` → KEEP_ACTIVE，不删（后者含 3 个已校验 ZIP）。
4. 8 个含 `.git` 的沙箱（`rmtest_*`/`rm2_*`/`rm3_*`/`rm4_*`/`fin_*`/`fin2_*`/`ex_*`/`ign_*`）→ KEEP_ACTIVE，不删。
5. 被 `docs/` 或 `scripts/` 引用的 75 条 → KEEP_EVIDENCE，不删。
6. 删除前已核对 17 个 tmux 会话的 `pane_current_path`：只有 `D:\code\cnn_full_20260905\cnn` 与 `...\validation_2025_local_inputs_20261029`，与删除目标无交集。

## 判定方法

- **引用判定**：把 `docs/`（114 文件）+ `scripts/`（64 文件）全文读入内存，对每个一级条目名做**词边界**正则 `(?<![A-Za-z0-9_])NAME(?![A-Za-z0-9_])`。先做过一次纯子串匹配，发现 `attr`/`precision`/`opencode`/`e0e5` 等短词假命中（例如 `attribute` 命中 `attr`、`precision` 命中普通英文词），故改用词边界口径，既保留 `NAME/子路径` 的真实路径引用，又剔除假阳性。
- **体积统计**：递归枚举时跳过 reparse point（symlink/junction）子树，避免把链接目标和主副本重复计入。
- **空目录判定**：递归后文件数为 0（不是"看起来没内容"）。实测 85 个空目录全部为 0 文件，`attr/`、`clientjar/`、`sdkdl/` 这类只有空壳子目录的也算空。

## 总表

| 名称 | 类型 | 大小(MB) | 文件数 | 类别 | 处置理由 | 被文档引用 |
|---|---|---:|---:|---|---|---|| worktree_retirement_20261027 | DIR | 183.05 | 20 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 是(1) |
| worktree_retirement_20261028 | DIR | 36.22 | 4 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 是(2) |
| recovered_w1_20261030 | DIR | 0.41 | 6 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| fin2_1057940297 | DIR | 0.03 | 45 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| fin_513914240 | DIR | 0.03 | 42 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| rm3_888891012 | DIR | 0.03 | 45 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| ign_1555585458 | DIR | 0.03 | 41 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| ex_900259024 | DIR | 0.03 | 38 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| rm2_1737917526 | DIR | 0.03 | 32 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| rm4_1314648040 | DIR | 0.03 | 32 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| rmtest_1409618984 | DIR | 0.03 | 31 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| _ro_probe4_33380.py | FILE | 0 | 1 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| worktree_retirement_20261030 | DIR | 0 | 1 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| cmp_1896710164 | DIR | 0 | 1 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| sy_1850558909 | DIR | 0 | 1 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| sym_245847389 | DIR | 0 | 1 | KEEP_ACTIVE | 红线保护（recovered_w1_20261030 / worktree_retirement_*）或含 .git、为当日 symlink/junction 测试沙箱且进程仍在写 | 否 |
| state_acquisition_20261027 | DIR | 109.9 | 9216 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\state_acquisition_request_v2.md | 是(2) |
| validation_2025_restricted_independent_qa_20261029 | DIR | 35.61 | 1259 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(1) |
| three_day_signals | DIR | 19.88 | 34 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\f4_signal_delivery.md | 是(1) |
| state_evidence_W1_luna_qa_v1 | DIR | 19.49 | 11 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\state_semantics_followup.md | 是(1) |
| w1_dual_core_identity_independent_qa_20261029 | DIR | 10.77 | 375 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| w1_dual_core_identity_fix3_20261029 | DIR | 8.98 | 436 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| state_gap_lifecycle_20261027_v2 | DIR | 7.63 | 13 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(2) |
| validation_2025_local_inputs_20261029 | DIR | 6.41 | 285 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(1) |
| state_acquisition_main_audit_20261027_v3 | DIR | 4.81 | 4 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(2) |
| validation_2025_000601_official_20261029 | DIR | 3.42 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| signal_probe_W1_two_codes | DIR | 1.53 | 15 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\margin_artifact_probe_2021h1.json | 是(2) |
| staged_production_integration_delivery_20261027 | DIR | 1.53 | 53 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(1) |
| staged_runner_independent_qa_20261027 | DIR | 0.92 | 61 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| w1_real_prefix_exploration_20261029 | DIR | 0.85 | 15 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| validation_2025_000506_official_20261029 | DIR | 0.71 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| execution_opportunity_coverage_20261026 | DIR | 0.67 | 16 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\execution_opportunity_coverage.md | 是(1) |
| validation_2025_bridge_fix1_20261029 | DIR | 0.56 | 8 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| corporate_action_context_independent_qa_20261027 | DIR | 0.36 | 36 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| board_exposure_audit_20261027_v1 | DIR | 0.28 | 7 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\state_collection_and_board_rules_20261027.md | 是(1) |
| precision | DIR | 0.18 | 8 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(8) |
| w1_ceil_precision_independent_qa_20261029 | DIR | 0.16 | 48 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| core_limit_final_893fc96 | DIR | 0.12 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\limit_order_delivery.md | 是(1) |
| w2_mechanical_risk_review_20261028 | DIR | 0.09 | 6 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| w1_real_prefix_independent_audit_20261029 | DIR | 0.06 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(4) |
| w2_exposure_evidence_20261028 | DIR | 0.06 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| w1_prefix_independent_qa_20261028 | DIR | 0.06 | 23 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(3) |
| staged_policy_independent_oracle_20261026 | DIR | 0.03 | 5 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\staged_policy_rulings.md | 是(1) |
| w1_fractional_scenarios_delivery_20261028 | DIR | 0.03 | 8 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| w2_tax_fifo_independent_qa_20261029 | DIR | 0.02 | 14 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| staged_policy_final_qa_20261027 | DIR | 0.01 | 4 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\staged_order_strategy_delivery.md | 是(1) |
| prospective_exam_feasibility_20261028 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(1) |
| existing_oos_evidence_inventory_20261028 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(1) |
| staged_policy_strategy_plan_20261026 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20261027_staged-order-strategy\PLAN.md | 是(2) |
| staged_integration_independent_qa_20261028 | DIR | 0.01 | 4 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(3) |
| w1_fractional_scenarios_independent_qa_20261028 | DIR | 0.01 | 8 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| clean_exam_data_inventory_20261028 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(1) |
| w1_prefix_fix5_20261028 | DIR | 0.01 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(3) |
| validation_2025_bridge_delivery_20261029 | DIR | 0.01 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| audit_z_corporate_actions.py | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\z_corporate_actions_audit.json | 是(2) |
| eight_windows_second_audit_20261028 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| w1_ceil_failure_root_cause_20261029 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| validation_2025_ca_evidence_adapter_20261029 | DIR | 0.01 | 7 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(3) |
| technical29_prefix_probe.py | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\technical29_time_audit.md | 是(1) |
| validation_2025_data_preflight_20261029 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| three_day_user_data_claims_check.md | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\user_data_claims_check.md | 是(1) |
| validation_2025_bridge_independent_qa_20261029 | DIR | 0.01 | 3 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| staged_policy_final_qa_round1_20261027 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20261027_staged-order-strategy\HARNESS_PROGRESS.md | 是(2) |
| w2_goal_acceptance_review_20261029 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\final_delivery_20261030.md | 是(2) |
| state_acquisition_audit_delivery_20261027_v2.json | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\state_collection_and_board_rules_20261027.md | 是(1) |
| audit_full_state_main_20261027.py | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\state_collection_and_board_rules_20261027.md | 是(1) |
| price_lineage_aggregate.py | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\price_lineage.md | 是(1) |
| three_day_price_lineage_aggregate.json | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\price_lineage.md | 是(1) |
| validation_2025_ca_two_event_audit_20261029 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\worktree_consolidation_20261030\README.md | 是(2) |
| validation_2025_ab_v2_abort_audit_20261029 | DIR | 0.01 | 2 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\three_day_strategy_report_20261029.md | 是(3) |
| three_day_execution_freeze_v2 | DIR | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\benchmark_execution_freeze_v2.md | 是(1) |
| three_day_candidate_registry.md | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20261027_staged-order-strategy\PLAN.md | 是(2) |
| checkpoint_compat_delivery_20261026.md | FILE | 0.01 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20261026_checkpoint-numpy-compat\HARNESS_PROGRESS.md | 是(1) |
| price_lineage_probe.py | FILE | 0 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\price_lineage.md | 是(1) |
| checkpoint_compat_final_qa_v2_20261027 | DIR | 0 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20261026_checkpoint-numpy-compat\HARNESS_PROGRESS.md | 是(1) |
| universe_lineage_probe.py | FILE | 0 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\universe_lineage.md | 是(1) |
| three_day_universe_sample.json | FILE | 0 | 1 | KEEP_EVIDENCE | 被仓库文档引用：docs\research\20261026\universe_lineage.md | 是(1) |
| unified_recalc | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(1) |
| tree_rebuild | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(2) |
| opencode | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\full_train_todo.md | 是(38) |
| market_neutral | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(1) |
| m_research | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(2) |
| h10_roll_bt | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\combine_rolling_preds.py | 是(15) |
| h10_roll_B | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\combine_rolling_preds.py | 是(3) |
| h10_roll_A | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\combine_rolling_preds.py | 是(3) |
| h10_risk3 | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\ensemble_voting_27.py | 是(3) |
| h10_risk1 | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\halving_drawdown.py | 是(3) |
| h10_final_combo | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：scripts\frozen\final_combo_voting_halving.py | 是(3) |
| attr | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\agent\task\20260916_0010_turnover-industry-attribution\HARNESS_PROGRESS.md | 是(2) |
| tree_verify | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(2) |
| __pycache__ | DIR | 0 | 0 | KEEP_EVIDENCE | 被仓库文档引用：docs\ENGINE_MAP_2026.md | 是(1) |
| staged_mechanical_results_20261028_v1 | DIR | 7906.73 | 138 | KEEP_ARTIFACT | 八窗机械回测原始结果（80 jsonl + summary.sha256 48 hex），项目记忆/二次审计引用，不可再生 | 否 |
| w1_real_prefix_exploration_20261029_v2 | DIR | 4381.42 | 187 | KEEP_ARTIFACT | 真实前缀探索原始逐日 jsonl 4.3GB + 8 份哈希清单，唯一副本 | 否 |
| validation_2025_ab_real_20261029_v1 | DIR | 2731.83 | 64 | KEEP_ARTIFACT | AB 实盘模拟原始 full_opportunities.jsonl（1.28GB/账户）与中断证据 | 否 |
| validation_2025_ab_real_20261029_v2 | DIR | 2719.77 | 58 | KEEP_ARTIFACT | AB 实盘模拟原始 full_opportunities.jsonl（1.28GB/账户）与中断证据 | 是(1) |
| w3_2022H1_workers0_20261026_032347.stderr.log | FILE | 2.5 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| F4_OHLC_W1_stderr.log | FILE | 1.74 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| w3_2022H1_workers0_20261026_032347.stdout.log | FILE | 0.19 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| F4_OHLC_W1_stdout.log | FILE | 0.16 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| w3_2022H1_20261025_235808.stderr.log | FILE | 0.03 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| w3_2022H1_20261025_235808.stdout.log | FILE | 0.01 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| state_audit_main_v3_stdout.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| state_audit_main_v2_stdout.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| w2_f4_env_copy_20261026.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| cnn_bridge_env_copy_20261026.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| cnn_bridge_env_20261026_stderr.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| cnn_bridge_env_20261026_stdout.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| state_audit_main_v2_stderr.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| state_audit_main_v3_stderr.log | FILE | 0 | 1 | KEEP_ARTIFACT | 运行日志，可能为训练/执行证据；保留成本低 | 否 |
| checkpoint-compat-venv | DIR | 2779.51 | 12392 | DELETE_CACHE | uv 创建的临时 Python 环境：含 CACHEDIR.TAG + .gitignore=`*`；66 个 dist-info 与主 .venv 完全同名集合；backtest_core 39 个 .py 全部在 D:/code 有副本；uv 缓存 archive-v0 9GB 可离线再同步 | 否 |
| _scan_files.xml | FILE | 15.28 | 1 | DELETE_CACHE | 本代理本次扫描生成的中间文件 | 否 |
| _scan_agg.xml | FILE | 0.1 | 1 | DELETE_CACHE | 本代理本次扫描生成的中间文件 | 否 |
| _scan_refs.xml | FILE | 0.08 | 1 | DELETE_CACHE | 本代理本次扫描生成的中间文件 | 否 |
| _scan_refs2.xml | FILE | 0.07 | 1 | DELETE_CACHE | 本代理本次扫描生成的中间文件 | 否 |
| alpha_m | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_robust_C | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_robust_B | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_robust_A | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_risk2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_regime_study | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_redesign | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_robust_C2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_reconcile | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_opt1_verify | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_index_audit | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_freq_audit | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_freq_3M | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_freq_2M | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_freq_1M | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_opt2_verify | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_fix_B | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_roll_small | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_trade_review | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| smokeE | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| smoke3 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| smile | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| sdkdl | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| ruffbase | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| qa_t06 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_shot_2026 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| probe3 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| jkx_samples | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| jkx_compare | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| horizon_7_10 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| horizon_15_20 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| horizon_1_3 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_weighted_ic | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| mcpjar | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| state_acquisition_main_audit_20261027_v1 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_fix_A | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_F | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| clientjar | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E5 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E4 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E3 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E1 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| e0e5 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt40_E0 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_smoke_roll | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_naked_2025 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_J30_26_gate0 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_J30_26 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_B26_gate0 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_B26_base | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| bt_smoke_tgt | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_final_stack | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_2026_bakeoff | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_2026_V1 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_E | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_D | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_C | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_B | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_A2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_exit_A | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_2026_bakeoff2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_early_stack2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_bt_B | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_bt_A | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_bins | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_adapt_build | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_adapt_audit | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_2026_V2 | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| h10_early_stack | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| t6_bt_2026_target | DIR | 0 | 0 | DELETE_STALE | 空目录：0 文件 0 字节，未被文档引用，无 .git/reparse，属旧轮转留下的空跑目录 | 否 |
| staged_prepared_inputs_20261027_v12 | DIR | 1924.5 | 4694 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 是(2) |
| staged_prepared_inputs_20261027_v8 | DIR | 1104.96 | 4686 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v7 | DIR | 1104.9 | 4686 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v10 | DIR | 1062.4 | 261 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| validation_2025_restricted_delivery_20261029 | DIR | 335.95 | 1113 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_execution_input_snapshot_20261027_v1 | DIR | 327.66 | 49 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| F4_OHLC_W1_cache | DIR | 314.94 | 20 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v9 | DIR | 47.27 | 2301 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| three_day_models | DIR | 46.72 | 29 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_prepared_inputs_20261027_v6 | DIR | 35.3 | 1421 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v11 | DIR | 33.86 | 1315 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v2 | DIR | 30.67 | 1091 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v4 | DIR | 29.5 | 986 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v3 | DIR | 24.8 | 622 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v1 | DIR | 24.07 | 574 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| staged_prepared_inputs_20261027_v5 | DIR | 21.42 | 354 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| state_2025_toprank_coverage_20261029 | DIR | 13.07 | 15 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_restricted_fix2_20261029 | DIR | 7.95 | 286 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_gap_lifecycle_20261027_v1 | DIR | 7.64 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_restricted_fix1_20261029 | DIR | 7.56 | 552 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_dual_core_identity_fix3_sol_reverify_20261029 | DIR | 5.66 | 125 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_primary_audit_20261028 | DIR | 4.28 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| old_1435476987 | DIR | 3.93 | 800 | HOLD_REVIEW | 含 parquet/npy 原始或派生数据；除 v12/v8 外为已被取代的旧版本，重建需 2040s 且无法确认字节可复现 | 否 |
| pause_listing_official_sources_20261027 | DIR | 2.76 | 13 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_acquisition_main_audit_20261027_v2 | DIR | 2.74 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_real_prefix_exploration_20261029_v3 | DIR | 2.65 | 12 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_restricted_fix3_20261029 | DIR | 2.34 | 301 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| existing_source_recovery_20261026 | DIR | 1.37 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_evidence_W1_ds_v1 | DIR | 0.77 | 30 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_engineering_harness | DIR | 0.54 | 339 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w2_execution_audit | DIR | 0.54 | 11 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w2_tax_fifo_feasibility_20261029 | DIR | 0.52 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_runner_fix1_20261027 | DIR | 0.47 | 26 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_execution_audit | DIR | 0.39 | 11 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_official_independent_qa_20261028 | DIR | 0.32 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| mechanical_W1_000001_v1 | DIR | 0.23 | 10 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_sol_diagnostic_20261029 | DIR | 0.2 | 16 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_integration_snapshot_20261026_1606.index | FILE | 0.19 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_dual_core_identity_fix2_20261029 | DIR | 0.18 | 24 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_ca_exposure_availability_20261029 | DIR | 0.16 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_official_search3_20261028 | DIR | 0.16 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core-baseline-qa-20261026 | DIR | 0.16 | 9 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_document_search2_20261028 | DIR | 0.15 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_runner_v2_delivery_20261027 | DIR | 0.14 | 21 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_observer_final_20261026_v1 | DIR | 0.12 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_observer_preview_20261026_v1 | DIR | 0.12 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_baseline_40f9612_immutable | DIR | 0.12 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_audit_independent_ds_20261027 | DIR | 0.11 | 24 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| historical_order_rules_20261027_v1 | DIR | 0.1 | 5 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_ceil_precision_fix2_20261029 | DIR | 0.1 | 27 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| safe_feature_training_plan_probe | DIR | 0.07 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_local_inputs_independent_qa_20261029 | DIR | 0.06 | 5 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_worktree_tracked_20261026.patch | FILE | 0.06 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged-source-guard-fix-index-20261027 | FILE | 0.05 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| board_quantity_exposure_20261027_v1 | DIR | 0.05 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| corporate_action_context_delivery_20261027 | DIR | 0.04 | 23 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_production_integration_plan_20261027 | DIR | 0.04 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_uncertainty_bounds_20261028 | DIR | 0.02 | 6 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| audit_z_corporate_actions.json | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_snapshot_main_verification_20261027_v1.json | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_verified_state_source_contract.md | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_price_lineage.md | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_corporate_actions_contract.md | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_fractional_scenarios_fix1_20261028 | DIR | 0.02 | 11 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| evidence_closure_review_20261027 | DIR | 0.02 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_implementation_20261028 | DIR | 0.02 | 9 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_execution_plan_20261029 | DIR | 0.02 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_bridge_plan_20261029 | DIR | 0.02 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| board_quantity_rules_independent_qa_20261027 | DIR | 0.02 | 12 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_queue.md | FILE | 0.02 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_fractional_scenarios_plan_20261028 | DIR | 0.02 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_luna_review.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_candidate_runner_plan_20261027 | DIR | 0.01 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| session_runtime_diagnostic_20261027_v2.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_dual_core_identity_fix_20261029 | DIR | 0.01 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_dual_core_identity_plan_20261029 | DIR | 0.01 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| corporate_action_loader_plan_20261027 | DIR | 0.01 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_universe_lineage.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| session_runtime_diagnostic_20261027_v1.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_research_control.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_checkpoint_probe.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_approved_delta_20261026.patch | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_proof_plan_20261028 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| technical29_prefix_probe.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| clean_exam_coverage_recheck_20261029 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_ca_cutoff_availability_20261029 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_windows.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_conservative_execution_review.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_worktree_tests_20261026.patch | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| session_runtime_diagnostic_20261027_v5.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| validation_2025_ab_independent_audit_20261029 | DIR | 0.01 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| conservative_envelope_input_review_20261026.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_financial_pit_audit.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_fee_pit_analysis_20261028 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| eight_windows_independent_review_20261028 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| staged_candidate_prereg_20261027_v1 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_stop_after_close_20261030.patch | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_acquisition_audit_delivery_20261027_v1.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_2025_local_inventory_20261029 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_technical29_time_audit.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_margin_time_audit.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_asset_inventory.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_safe_feature_training_plan.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| raw_limit_provider_qa_20261026.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| worktree_retirement_review_20261028 | DIR | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_staged_state_review.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_fix4_20261028 | DIR | 0.01 | 4 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| session_runtime_diagnostic_20261027_v4.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| limit_order_implementation_plan_20261026.md | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| session_runtime_diagnostic_20261027_v3.json | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| strategy_goal_fast_path_20261029 | DIR | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| summary_report.py | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_worktree_actions_20261026.patch | FILE | 0.01 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_cross_index_20261028 | DIR | 0.01 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| board_quantity_rules_delivery_20261027 | DIR | 0.01 | 8 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_asset_inventory.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_fix2_20261028 | DIR | 0 | 3 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| checkpoint_compat_backup_review_20261027.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_engineering_plan.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| market_rules_2025_research_20261029 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| approve_core_reads_once_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_signal_plan.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| verify_state_snapshot_main_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| freeze_staged_run_prereg_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_staged_delivery.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_acceptance_evidence.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| core_baseline_handoff_20261026.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| corporate_action_tax_handoff.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| user_claims_db_probe.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| raw_limit_provider_delivery_20261026.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| diagnose_session_runtime_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_staged_policy | DIR | 0 | 2 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w3_2022H1_20261025_235817_manifest.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| quantity_rules_main_integration_20261027 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| raw_limit_provider_luna_qa_20261026.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| handoff-cnn-walkforward-audit.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| diagnose_board_order_sizes_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_checkpoint_probe.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| pause_primary_source_verification_20261027_v1.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| explain_state_gaps_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_windows.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ca_300502_pagination_20261028 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| verify_pause_primary_sources_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| verify_w2_ckpt.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| checkpoint_main_verification_results_20261027.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_2025_probe_20261029 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w2_f4_preflight_plan.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w2_output_independent_validation_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| poll_research_sessions_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_signal_precision_diagnosis.md | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| diagnose_dividend_field_relations_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ex_reference_semantics_samples_20261027_v2.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_prefix_fix3_20261028 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| checkpoint_main_verification_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| classify_boundary_anomalies_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_margin_artifact_probe_2021h1.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_user_data_claims_sample.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| observer_minimal_breakdown_20261026 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| dividend_field_relations_20261027_v1.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| check_ex_reference_semantics_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| archive_retired_runner_state_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| check_boundary_signal_exposure_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| freeze_state_audit_delivery_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_cpu_preflight.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| resolve_targeted_session_permissions_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| stop_retired_research_sessions_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| board_exposure_audit_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| ex_reference_semantics_samples_20261027_v1.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| download_sse_2020_order_rules_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w1_ceil_precision_fix_20261029 | DIR | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| query_pause_evidence_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| match_pause_gaps_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| download_sse_repeal_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_queue_facts.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| read_sdk_status_docstring_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| launch_state_audit_v3_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| download_sse_rule_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| inspect_remaining_state_gaps_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| retired_research_sessions_stop_20261027.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| w2_ckpt_verify.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| symtest.sh | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| extract_sse_rule_links_20261027.py | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| sdk_status_docstring_20261027_v1.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| three_day_training_cpu_preflight.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |
| state_audit_main_v3_process.json | FILE | 0 | 1 | HOLD_REVIEW | 含唯一数据/权重/报告，无文档引用但无法确认可再生 | 否 |

## 汇总

| 类别 | 条目数 | 字节 | MB |
|---|---:|---:|---:|
| KEEP_ACTIVE | 16 | 230592734 | 219.9 |
| KEEP_EVIDENCE | 75 | 246838878 | 235.4 |
| KEEP_ARTIFACT | 18 | 18606326357 | 17744.4 |
| DELETE_CACHE | 5 | 2930818767 | 2795 |
| DELETE_STALE | 71 | 0 | 0 |
| HOLD_REVIEW | 185 | 6855429350 | 6537.8 |
| **合计** | **370** | **28870006086** | **27532.6** |

### 计划

- **删除**：DELETE_CACHE 5 条 + DELETE_STALE 71 条 = 76 条；DELETE_CACHE 占 2930818767 字节（2795 MB），DELETE_STALE 均为 0 字节。
- **保留**：109 条，19083757969 字节（18199.7 MB）。
- **HOLD**：185 条，6855429350 字节（6537.8 MB），全部不删。


## DELETE_CACHE 的再生性论证（唯一有体积的删除项）

`checkpoint-compat-venv/` 2,779.5 MB：

- 是 `uv` 创建的一次性验证环境，根目录有 `CACHEDIR.TAG`（标准缓存标记）与 `.gitignore` 内容为 `*`。
- 66 个 `*.dist-info` 与 `D:/code/cnn_full_20260905/cnn/.venv` **完全同名同集合**，无独有包。
- 其中 `backtest_core` 39 个 `.py` 与 `D:/code/cnn_full_20260905/backtest-core/src/backtest_core` 逐文件比对，仅 `engine/account_runner.py` 不同；该文件与 `cnn/.venv` 内同名文件**哈希完全一致**（AA156EC2…），差异内容（`stop_after_close`）即 `w1_stop_after_close_20261030.patch` 的内容，已留存。`contracts/account_actions.py` 三处哈希一致，非孤立源码。
- `pyvenv.cfg` 指向 uv 管理的 CPython 3.12.13；`uv` 缓存 `archive-v0` 现存 9,143.7 MB 已解析包，`uv sync --offline` 可重建。
- 唯一提到它的两个文档（`checkpoint_compat_delivery_20261026.md`、`checkpoint_main_verification_results_20261027.md`）都只在**命令示例**里出现该路径，且同段落并列给出主环境 `.venv/Scripts/python.exe` 的等价命令；这两份文档位于**本临时目录**，不在仓库 `docs/`，不属于红线 5 的"仓库文档引用"。

> 代价说明：这两份文档记录的是 2026-10-26/27 的历史命令，环境删除后该命令行**无法原样重放**。这是本方案唯一的可复现性代价，已记录供人工复核。

## DELETE_STALE 明细（全部 0 文件 0 字节）

旧 h10/bt/e0e5 轮转目录的残留空壳，以及 `attr/`、`clientjar/`、`mcpjar/`、`sdkdl/` 这类只剩空子目录树的外壳。它们不含任何文件，删除不产生数据损失。`docs/ENGINE_MAP_2026.md` 对 `tree_rebuild`/`market_neutral`/`unified_recalc`/`m_research` 的引用指向**仓库内同名路径**（仓库里另有实体），不是本临时目录的空壳，因此这些已归入 KEEP_EVIDENCE 保留。

## HOLD_REVIEW 重点关注（交人工判断）

1. **`staged_prepared_inputs_20261027_v1..v12`（约 6.5 GB，12 版）**：v12 是文档引用的最终版；v1–v11 是同一准备流程的逐版中间产物，每版含 261–4,686 个 parquet。删除 v1–v11 约可释放 3.3 GB。**未删原因**：准备流程耗时 2040.9 秒且依赖外部数据库，无法确认重跑字节级一致；上一轮刚发生数据丢失事故，按"宁可少删"原则保留。
2. **`old_1435476987/`（3.93 MB）**：名为 `old_` 的 opencode 配置备份，含 `node_modules`（797 文件）与空 `MEMORY.md`。看着像测试残留，但无法确认是否有意留存。
3. **`F4_OHLC_W1_cache/`（314.94 MB）**：`v3_relative_groups` 训练缓存，16 个 `.npy` + 2 个 `.ok` 完成标记。重建需重跑特征管线，成本不低。
4. **`validation_2025_ab_real_20261029_v1/`（2,731.8 MB）**：v1 已被 v2 取代（v1 在 2025-01-06 因 `record_date_unknown` 中断），但含 2 个约 1.28 GB 的 `full_opportunities.jsonl` 原始产物。v1 未被仓库文档引用，v2 被引用。
5. **`three_day_models/W2_F4_v1/run_20261026_212052/best_model.pth`（42.24 MB）**：模型权重，SHA 与项目记忆一致（03625b7d…）。
6. **`state_2025_toprank_coverage_20261029/`、`validation_2025_restricted_delivery_20261029/`、`staged_execution_input_snapshot_20261027_v1/`**：均含 parquet 原始输入/交付快照，体积数百 MB，无文档引用但不可确认可再生。

## 已知不在本任务范围

- `C:/Users/yanwen/.local/share/opencode/`（含 `opencode.db`、worktree 存档）未触碰。
- `C:\Users\yanwen\AppData\Local\uv\cache`（14.8 GB，含 7 个 `.tmpXXXX` 残留约 5.6 GB）未触碰，仅作为重建可行性证据引用。