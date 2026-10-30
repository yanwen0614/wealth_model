# 临时目录清理结果报告（2026-10-30）

## 结论摘要

| 项目 | 数值 |
|---|---|
| 清理前一级条目 | 365 条（242 目录 + 123 文件） |
| 已删除条目 | 76 条（DELETE_CACHE 5 + DELETE_STALE 71） |
| 保留条目 | 289 条（KEEP_ACTIVE 16 + KEEP_EVIDENCE 75 + KEEP_ARTIFACT 18 + HOLD_REVIEW 185）；清理后一级条目 297 条（289 保留 + 本报告 + 计划 + 期间其他代理新增 2 件） |
| 名义删除体积 | 2,930,818,767 字节 ≈ 2,795.0 MB |
| 实际释放物理空间 | 约 25 MB（原因见下） |
| 清理前 C: 可用 | 172.27 GB |
| 清理后 C: 可用 | 172.26 GB |

> **重要发现：名义 2.78 GB 只释放了约 25 MB 物理空间。** 原因经实验证实：`uv` 把包文件从 `C:\Users\yanwen\AppData\Local\uv\cache\archive-v0` **硬链接**进虚拟环境。删除 venv 只减少链接数、不回收数据块，因为缓存副本仍持有同一 inode。实测 `fsutil hardlink list` 显示同一文件有两个链接（缓存 + venv）；删除 venv 后缓存文件完好、链接数回落为 1。所以这次删除**真正回收的空间很小，但没有任何数据损失，且缓存仍可秒级重建环境**。

## 已删除条目清单

### DELETE_STALE（71 条，均为 0 文件 0 字节，释放 0 字节）

这些是旧 h10/bt/e0e5 实验轮转留下的空目录，以及只剩空子目录树的外壳（`attr/`、`clientjar/`、`mcpjar/`、`sdkdl/` 内部实际 0 文件）：

```
alpha_m, bt_B26_base, bt_B26_gate0, bt_J30_26, bt_J30_26_gate0, bt_naked_2025,
bt_smoke_roll, bt_smoke_tgt, bt40_E0, bt40_E1, bt40_E2, bt40_E3, bt40_E4, bt40_E5,
clientjar, e0e5, h10_2026_bakeoff, h10_2026_bakeoff2, h10_2026_V1, h10_2026_V2,
h10_adapt_audit, h10_adapt_build, h10_bins, h10_bt_A, h10_bt_B, h10_early_stack,
h10_early_stack2, h10_exit_A, h10_exit_A2, h10_exit_B, h10_exit_C, h10_exit_D,
h10_exit_E, h10_exit_F, h10_final_stack, h10_fix_A, h10_fix_B, h10_freq_1M,
h10_freq_2M, h10_freq_3M, h10_freq_audit, h10_index_audit, h10_opt1_verify,
h10_opt2_verify, h10_reconcile, h10_redesign, h10_regime_study, h10_risk2,
h10_robust_A, h10_robust_B, h10_robust_C, h10_robust_C2, h10_roll_small,
h10_shot_2026, h10_trade_review, h10_weighted_ic, horizon_1_3, horizon_15_20,
horizon_7_10, jkx_compare, jkx_samples, mcpjar, probe3, qa_t06, ruffbase, sdkdl,
smile, smoke3, smokeE, state_acquisition_main_audit_20261027_v1, t6_bt_2026_target
```

删除前逐条二次校验：`HASFILES=0`、`HASGIT=0`、`REPARSE=0`，全部安全。

### DELETE_CACHE（5 条，释放名义 2,795 MB）

| 条目 | 字节 | 理由 |
|---|---:|---|
| `checkpoint-compat-venv/` | 2,914,332,672（12,392 文件） | uv 一次性验证环境，见再生性论证 |
| `_scan_files.xml` | 16,023,373 | 本代理本次扫描中间文件 |
| `_scan_agg.xml` | 107,610 | 同上 |
| `_scan_refs.xml` | 82,504 | 同上 |
| `_scan_refs2.xml` | 77,988 | 同上 |

`checkpoint-compat-venv/` 可重建性证据（删除前已核）：

1. 根目录含 `CACHEDIR.TAG`（标准缓存签名 `8a477f597d28d172789f06886806bc55`）与 `.gitignore` 内容为 `*`。
2. 66 个 `*.dist-info` 与 `D:/code/cnn_full_20260905/cnn/.venv` **完全同名同集合**，`onlyInTemp` 与 `onlyInMain` 均为空。
3. 内含 `backtest_core` 39 个 `.py`，与 `D:/code/cnn_full_20260905/backtest-core/src/backtest_core` 逐文件比对**仅 1 处不同**：`engine/account_runner.py`。该文件与 `cnn/.venv` 内同名文件**哈希完全一致**（`AA156EC2EE7FE8EE82EA3C27A2359DC4954BD6CF3D28D00A7ECE6868FC8DAA00`），左差异内容（`stop_after_close`）正是 `w1_stop_after_close_20261030.patch`（已保留）的内容。`contracts/account_actions.py` 三处（临时venv / backtest-core 源码 / 主 .venv）哈希均为 `623C1CA1…`，非孤立源码。
4. `pyvenv.cfg` 指向 uv 管理的 CPython 3.12.13。
5. 实测证明 uv 缓存仍完好（见下方实验记录）。

### 实测复现记录（证明缓存可重建）

```
uv venv opencode_del_test_20261030 --python 3.12 --offline    -> exit 0
uv pip install --offline wcwidth                              -> Installed 1 package
fsutil hardlink list .../wcwidth/__init__.py
  -> uv\cache\archive-v0\-zYca1bF1lo8gX_r\wcwidth\__init__.py
  -> Temp\opencode_del_test_20261030\Lib\site-packages\wcwidth\__init__.py
```

即：离线安装正常、文件为硬链接。测试环境已删除，缓存条目链接数回落为 1，缓存未受损。
## 保留条目清单及理由

### KEEP_ACTIVE（16 条）——红线保护 / 正在被使用

| 条目 | 理由 |
|---|---|
| `recovered_w1_20261030/` | **红线2**：另一代理正在写入，回收丢失源码（清理期间体积从 0.41MB 增到 16.7MB，确认活跃） |
| `worktree_retirement_20261030/` | **红线3**：退役报告 |
| `worktree_retirement_20261028/` | **红线3**：含 3 个已校验归档 ZIP（12.0 / 12.2 / 12.0 MB）+ REPORT.md，SHA 被文档引用 |
| `worktree_retirement_20261027/` | 被 `docs/research/20261026/PARALLEL_WORKSPACES.md` 引用，且含 4 个 zip / 3 个 bundle |
| `rmtest_1409618984/`、`rm2_1737917526/`、`rm3_888891012/`、`rm4_1314648040/` | **红线4**：含 `.git` |
| `fin_513914240/`、`fin2_1057940297/`、`ex_900259024/`、`ign_1555585458/` | **红线4**：含 `.git` 或 `.git` 文件 |
| `sym_245847389/`、`cmp_1896710164/`、`sy_1850558909/` | 当日 00:53–01:07 创建的 symlink/junction 测试沙箱（`l1`/`l3`/`link` 指向 `src`），疑为上一轮误删事故的根本原因排查现场，保留 |
| `_ro_probe4_33380.py` | 其他会话进程（PID 2392/3928）此刻正在执行的只读探针脚本 |

### KEEP_EVIDENCE（75 条）——被仓库 `docs/` 或 `scripts/` 引用

逐条命中记录见 `CLEANUP_PLAN_20261030.md` 总表"被文档引用"列。建议人工复核的完整清单（含命中文件）：

| 条目 | 命中位置 |
|---|---|
| `staged_mechanical_results_20261028_v1` | 未命中，但升级为 KEEP_ARTIFACT（见下） |
| `eight_windows_second_audit_20261028` | `docs/research/final_delivery_20261030.md`、`three_day_strategy_report_20261029.md` |
| `w2_goal_acceptance_review_20261029` | 同上两处 |
| `w2_mechanical_risk_review_20261028` | 同上两处 |
| `w2_exposure_evidence_20261028` | 同上两处 |
| `w2_tax_fifo_independent_qa_20261029` | 同上两处 |
| `staged_prepared_inputs_20261027_v12` | 同上两处 |
| `staged_integration_independent_qa_20261028` | 3 处（含 `worktree_consolidation_20261030/README.md`） |
| `validation_2025_000506_official_20261029` / `_000601_official_` | `final_delivery_20261030.md` 等 2 处 |
| `validation_2025_restricted_independent_qa_20261029` | `final_delivery_20261030.md` |
| `validation_2025_local_inputs_20261029` | `final_delivery_20261030.md`（**注：14 个 tmux 会话的 cwd 也在此**） |
| `w1_*` 系列（12 个） | `final_delivery_20261030.md` / `three_day_strategy_report_20261029.md` / `worktree_consolidation_20261030/README.md` / `scripts/research/README.md` |
| `corporate_action_context_*`、`validation_2025_bridge_*`、`validation_2025_ca_*` | `worktree_consolidation_20261030/README.md`、`scripts/research/README.md` |
| `state_acquisition_20261027`（109.9 MB） | `docs/research/20261026/state_acquisition_request_v2.md` 等 2 处 |
| `state_evidence_W1_luna_qa_v1`、`state_gap_lifecycle_20261027_v2`、`state_acquisition_main_audit_20261027_v3` | `state_semantics_followup.md` / `state_collection_and_board_rules_20261027.md` |
| `tree_rebuild`、`tree_verify`、`m_research`、`market_neutral`、`unified_recalc`、`opencode`、`__pycache__`、`attr` | `docs/ENGINE_MAP_2026.md`（指向仓库内同名路径；本目录对应条目为**空目录**，保留以免路径语义断裂） |
| `h10_final_combo`、`h10_risk1`、`h10_risk3`、`h10_roll_A`、`h10_roll_B`、`h10_roll_bt` | `scripts/frozen/*.py`（同上，均为空目录） |
| 其余 ~40 条 | 见计划总表 |

### KEEP_ARTIFACT（18 条）——唯一副本且不可再生

| 条目 | 大小 | 理由 |
|---|---:|---|
| `staged_mechanical_results_20261028_v1/` | 7,906.7 MB | 八窗机械回测原始结果：80 个 `.jsonl` 逐日账本 + `summary.sha256` + 项目记忆引用的精确收益数值（W2 B1 +23.6794% 等）。**未命中文档但绝不可删** |
| `w1_real_prefix_exploration_20261029_v2/` | 4,381.4 MB | 真实前缀探索原始 110 个 `.jsonl` + 8 份哈希清单，唯一副本 |
| `validation_2025_ab_real_20261029_v1/` | 2,731.8 MB | AB 实盘模拟原始 `full_opportunities.jsonl`（1.28 GB/账户）+ 中断证据（v1 亦归 KEEP_ARTIFACT 而非 HOLD，因含唯一原始产物） |
| `validation_2025_ab_real_20261029_v2/` | 2,719.8 MB | 同上，v2（被 `final_delivery_20261030.md` 引用） |
| `three_day_models/` | 46.7 MB | 含 `W2_F4_v1/run_20261026_212052/best_model.pth`（42.24 MB，SHA `03625b7d…` 与项目记忆一致）+ `manifest.json` |
| `three_day_signals/` | 19.9 MB | `signals.parquet` / `signals.npz` 原始信号 + metadata/manifest |
| 顶层 `*.log`（6 个） | 4.6 MB | 运行日志（`w3_2022H1_*`、`F4_OHLC_W1_*`），成本低且可能为训练证据 |

## HOLD_REVIEW 清单及待确认问题（185 条，全部未删）

### 需要决策的大体积项（前 6 项占 HOLD 总量 98%）

| 条目 | 大小 | 待确认问题 |
|---|---:|---|
| `staged_prepared_inputs_20261027_v12/` | 1,924.5 MB | 文档引用的最终版，建议**长期保留** |
| `staged_prepared_inputs_20261027_v8/` | 1,105.0 MB | 已被 v12 取代（v12 有一处 `raw` symlink 指向 v8，删除 v8 会破坏 v12 的链接——须先确认该链接用途） |
| `staged_prepared_inputs_20261027_v7/` | 1,104.9 MB | 已被取代的旧版本，可删？ |
| `staged_prepared_inputs_20261027_v10/` | 1,062.4 MB | 同上（含 255 parquet + `raw` symlink→v8） |
| `validation_2025_restricted_delivery_20261029/` | 336.0 MB | 交付快照，含 41 parquet + 47 份哈希；无文档引用 |
| `staged_execution_input_snapshot_20261027_v1/` | 327.7 MB | 原始输入快照（26 parquet + 4 份 delivery_manifest），项目记忆明确引用其 canonical SHA |

### 其余需要判断的项

| 条目 | 大小 | 待确认问题 |
|---|---:|---|
| `F4_OHLC_W1_cache/` | 314.9 MB | v3 训练缓存，16 个 `.npy` + 2 个 `.ok`；重跑特征管线成本较高 |
| `old_1435476987/` | 3.9 MB | 名为 `old_` 的 opencode 配置备份（`node_modules` 797 文件 + 空 `MEMORY.md`），是否有意留存？ |
| `staged_prepared_inputs_20261027_v1–v6, v9, v11` | 约 210 MB | 更旧的中间版本，可删？ |
| 其余 ~170 个小型 QA/审计/计划目录 | 合计约 50 MB | 多为一次性交付物，无文档引用；体积小、删除收益低，建议保留 |

**HOLD 原则**：上一轮刚发生数据丢失事故，凡无法 100% 确认可再生者一律不删。
## 清理后一级列表（共 297 条，证明没删错）

```
D __pycache__
F _ro_probe4_33380.py
F approve_core_reads_once_20261027.py
F archive_retired_runner_state_20261027.py
D attr
F audit_full_state_main_20261027.py
F audit_z_corporate_actions.json
F audit_z_corporate_actions.py
D board_exposure_audit_20261027_v1
F board_exposure_audit_20261027.py
D board_quantity_exposure_20261027_v1
D board_quantity_rules_delivery_20261027
D board_quantity_rules_independent_qa_20261027
D ca_300502_cross_index_20261028
D ca_300502_document_search2_20261028
D ca_300502_official_independent_qa_20261028
D ca_300502_official_search3_20261028
D ca_300502_pagination_20261028
D ca_300502_primary_audit_20261028
D ca_uncertainty_bounds_20261028
F check_boundary_signal_exposure_20261027.py
F check_ex_reference_semantics_20261027.py
F checkpoint_compat_backup_review_20261027.md
F checkpoint_compat_delivery_20261026.md
D checkpoint_compat_final_qa_v2_20261027
F checkpoint_main_verification_20261027.py
F checkpoint_main_verification_results_20261027.md
F classify_boundary_anomalies_20261027.py
D clean_exam_coverage_recheck_20261029
D clean_exam_data_inventory_20261028
F CLEANUP_PLAN_20261030.md
F CLEANUP_RESULT_20261030.md
D cmp_1896710164
F cnn_bridge_env_20261026_stderr.log
F cnn_bridge_env_20261026_stdout.log
F cnn_bridge_env_copy_20261026.log
F conservative_envelope_input_review_20261026.md
F core_approved_delta_20261026.patch
D core_baseline_40f9612_immutable
F core_baseline_handoff_20261026.md
F core_integration_snapshot_20261026_1606.index
D core_limit_final_893fc96
D core_observer_final_20261026_v1
D core_observer_preview_20261026_v1
F core_worktree_actions_20261026.patch
F core_worktree_tests_20261026.patch
F core_worktree_tracked_20261026.patch
D core-baseline-qa-20261026
D corporate_action_context_delivery_20261027
D corporate_action_context_independent_qa_20261027
D corporate_action_loader_plan_20261027
F corporate_action_tax_handoff.md
F diagnose_board_order_sizes_20261027.py
F diagnose_dividend_field_relations_20261027.py
F diagnose_session_runtime_20261027.py
F dividend_field_relations_20261027_v1.json
F download_sse_2020_order_rules_20261027.py
F download_sse_repeal_20261027.py
F download_sse_rule_20261027.py
D eight_windows_independent_review_20261028
D eight_windows_second_audit_20261028
D evidence_closure_review_20261027
D ex_900259024
F ex_reference_semantics_samples_20261027_v1.json
F ex_reference_semantics_samples_20261027_v2.json
D execution_opportunity_coverage_20261026
D existing_oos_evidence_inventory_20261028
D existing_source_recovery_20261026
F explain_state_gaps_20261027.py
F extract_sse_rule_links_20261027.py
D F4_OHLC_W1_cache
F F4_OHLC_W1_stderr.log
F F4_OHLC_W1_stdout.log
D fin_513914240
D fin2_1057940297
F freeze_staged_run_prereg_20261027.py
F freeze_state_audit_delivery_20261027.py
D h10_final_combo
D h10_risk1
D h10_risk3
D h10_roll_A
D h10_roll_B
D h10_roll_bt
F handoff-cnn-walkforward-audit.md
D historical_order_rules_20261027_v1
D ign_1555585458
F inspect_remaining_state_gaps_20261027.py
F launch_state_audit_v3_20261027.py
F limit_order_implementation_plan_20261026.md
D m_research
D market_neutral
D market_rules_2025_research_20261029
F match_pause_gaps_20261027.py
D mechanical_W1_000001_v1
D observer_minimal_breakdown_20261026
D old_1435476987
D opencode
D pause_listing_official_sources_20261027
F pause_primary_source_verification_20261027_v1.json
F poll_research_sessions_20261027.py
D precision
F price_lineage_aggregate.py
F price_lineage_probe.py
D prospective_exam_feasibility_20261028
D quantity_rules_main_integration_20261027
F query_pause_evidence_20261027.py
F raw_limit_provider_delivery_20261026.md
F raw_limit_provider_luna_qa_20261026.md
F raw_limit_provider_qa_20261026.md
F read_sdk_status_docstring_20261027.py
D recovered_w1_20261030
F RESEARCH_CONSOLIDATION_AUDIT_20261030.md
F resolve_targeted_session_permissions_20261027.py
F retired_research_sessions_stop_20261027.json
D rm2_1737917526
D rm3_888891012
D rm4_1314648040
D rmtest_1409618984
D safe_feature_training_plan_probe
F sdk_status_docstring_20261027_v1.json
F session_runtime_diagnostic_20261027_v1.json
F session_runtime_diagnostic_20261027_v2.json
F session_runtime_diagnostic_20261027_v3.json
F session_runtime_diagnostic_20261027_v4.json
F session_runtime_diagnostic_20261027_v5.json
D signal_probe_W1_two_codes
D staged_candidate_prereg_20261027_v1
D staged_candidate_runner_plan_20261027
D staged_execution_input_snapshot_20261027_v1
D staged_integration_independent_qa_20261028
D staged_mechanical_results_20261028_v1
D staged_policy_final_qa_20261027
D staged_policy_final_qa_round1_20261027
D staged_policy_independent_oracle_20261026
D staged_policy_strategy_plan_20261026
D staged_prepared_inputs_20261027_v1
D staged_prepared_inputs_20261027_v10
D staged_prepared_inputs_20261027_v11
D staged_prepared_inputs_20261027_v12
D staged_prepared_inputs_20261027_v2
D staged_prepared_inputs_20261027_v3
D staged_prepared_inputs_20261027_v4
D staged_prepared_inputs_20261027_v5
D staged_prepared_inputs_20261027_v6
D staged_prepared_inputs_20261027_v7
D staged_prepared_inputs_20261027_v8
D staged_prepared_inputs_20261027_v9
D staged_production_integration_delivery_20261027
D staged_production_integration_plan_20261027
D staged_runner_fix1_20261027
D staged_runner_independent_qa_20261027
D staged_runner_v2_delivery_20261027
F staged-source-guard-fix-index-20261027
D state_2025_local_inventory_20261029
D state_2025_probe_20261029
D state_2025_toprank_coverage_20261029
D state_acquisition_20261027
F state_acquisition_audit_delivery_20261027_v1.json
F state_acquisition_audit_delivery_20261027_v2.json
D state_acquisition_main_audit_20261027_v2
D state_acquisition_main_audit_20261027_v3
D state_audit_independent_ds_20261027
F state_audit_main_v2_stderr.log
F state_audit_main_v2_stdout.log
F state_audit_main_v3_process.json
F state_audit_main_v3_stderr.log
F state_audit_main_v3_stdout.log
D state_evidence_W1_ds_v1
D state_evidence_W1_luna_qa_v1
D state_gap_lifecycle_20261027_v1
D state_gap_lifecycle_20261027_v2
F state_snapshot_main_verification_20261027_v1.json
F stop_retired_research_sessions_20261027.py
D strategy_goal_fast_path_20261029
F summary_report.py
D sy_1850558909
D sym_245847389
F symtest.sh
F technical29_prefix_probe.json
F technical29_prefix_probe.py
F three_day_acceptance_evidence.md
F three_day_asset_inventory.json
F three_day_asset_inventory.md
F three_day_candidate_registry.md
F three_day_checkpoint_probe.json
F three_day_checkpoint_probe.py
F three_day_conservative_execution_review.md
F three_day_corporate_actions_contract.md
D three_day_engineering_harness
F three_day_engineering_plan.md
D three_day_execution_freeze_v2
F three_day_financial_pit_audit.md
F three_day_luna_review.md
F three_day_margin_artifact_probe_2021h1.json
F three_day_margin_time_audit.md
D three_day_models
F three_day_price_lineage_aggregate.json
F three_day_price_lineage.md
F three_day_research_control.md
F three_day_safe_feature_training_plan.md
F three_day_signal_plan.md
F three_day_signal_precision_diagnosis.md
D three_day_signals
F three_day_staged_delivery.md
D three_day_staged_policy
F three_day_staged_state_review.md
F three_day_technical29_time_audit.md
F three_day_training_cpu_preflight.json
F three_day_training_cpu_preflight.py
F three_day_training_queue_facts.json
F three_day_training_queue.md
F three_day_training_windows.json
F three_day_training_windows.py
F three_day_universe_lineage.md
F three_day_universe_sample.json
F three_day_user_data_claims_check.md
F three_day_user_data_claims_sample.json
F three_day_verified_state_source_contract.md
D tree_rebuild
D tree_verify
D unified_recalc
F universe_lineage_probe.py
F user_claims_db_probe.py
D validation_2025_000506_official_20261029
D validation_2025_000601_official_20261029
D validation_2025_ab_independent_audit_20261029
D validation_2025_ab_real_20261029_v1
D validation_2025_ab_real_20261029_v2
D validation_2025_ab_v2_abort_audit_20261029
D validation_2025_bridge_delivery_20261029
D validation_2025_bridge_fix1_20261029
D validation_2025_bridge_independent_qa_20261029
D validation_2025_bridge_plan_20261029
D validation_2025_ca_evidence_adapter_20261029
D validation_2025_ca_two_event_audit_20261029
D validation_2025_data_preflight_20261029
D validation_2025_execution_plan_20261029
D validation_2025_local_inputs_20261029
D validation_2025_local_inputs_independent_qa_20261029
D validation_2025_restricted_delivery_20261029
D validation_2025_restricted_fix1_20261029
D validation_2025_restricted_fix2_20261029
D validation_2025_restricted_fix3_20261029
D validation_2025_restricted_independent_qa_20261029
D validation_2025_sol_diagnostic_20261029
F verify_pause_primary_sources_20261027.py
F verify_state_snapshot_main_20261027.py
F verify_w2_ckpt.py
D w1_ca_cutoff_availability_20261029
D w1_ca_exposure_availability_20261029
D w1_ceil_failure_root_cause_20261029
D w1_ceil_precision_fix_20261029
D w1_ceil_precision_fix2_20261029
D w1_ceil_precision_independent_qa_20261029
D w1_dual_core_identity_fix_20261029
D w1_dual_core_identity_fix2_20261029
D w1_dual_core_identity_fix3_20261029
D w1_dual_core_identity_fix3_sol_reverify_20261029
D w1_dual_core_identity_independent_qa_20261029
D w1_dual_core_identity_plan_20261029
D w1_execution_audit
D w1_fractional_scenarios_delivery_20261028
D w1_fractional_scenarios_fix1_20261028
D w1_fractional_scenarios_independent_qa_20261028
D w1_fractional_scenarios_plan_20261028
D w1_prefix_fee_pit_analysis_20261028
D w1_prefix_fix2_20261028
D w1_prefix_fix3_20261028
D w1_prefix_fix4_20261028
D w1_prefix_fix5_20261028
D w1_prefix_implementation_20261028
D w1_prefix_independent_qa_20261028
D w1_prefix_proof_plan_20261028
D w1_real_prefix_exploration_20261029
D w1_real_prefix_exploration_20261029_v2
D w1_real_prefix_exploration_20261029_v3
D w1_real_prefix_independent_audit_20261029
F w1_stop_after_close_20261030.patch
F w2_ckpt_verify.json
D w2_execution_audit
D w2_exposure_evidence_20261028
F w2_f4_env_copy_20261026.log
F w2_f4_preflight_plan.md
D w2_goal_acceptance_review_20261029
D w2_mechanical_risk_review_20261028
F w2_output_independent_validation_20261027.py
D w2_tax_fifo_feasibility_20261029
D w2_tax_fifo_independent_qa_20261029
F w3_2022H1_20261025_235808.stderr.log
F w3_2022H1_20261025_235808.stdout.log
F w3_2022H1_20261025_235817_manifest.json
F w3_2022H1_workers0_20261026_032347.stderr.log
F w3_2022H1_workers0_20261026_032347.stdout.log
D worktree_retirement_20261027
D worktree_retirement_20261028
D worktree_retirement_20261030
D worktree_retirement_review_20261028
```

## 完整性与红线复核

清理后逐项确认存在：

| 检查项 | 结果 |
|---|---|
| `recovered_w1_20261030/` 存在且仍在增长 | 是（0.41 MB → 16.7 MB） |
| `worktree_retirement_20261030/` 存在 | 是 |
| `worktree_retirement_20261028/` 3 个 ZIP 完好 | 是（12.0 / 12.2 / 12.0 MB） |
| `w1_stop_after_close_20261030.patch` 存在 | 是（8,143 字节） |
| 8 个含 `.git` 沙箱全部存在 | 是 |
| `three_day_models/.../best_model.pth` 存在 | 是 |
| `staged_mechanical_results_20261028_v1/` 存在 | 是 |
| `staged_prepared_inputs_20261027_v12/` 存在 | 是 |
| 原始 365 条逐条比对，除计划内 72 条外全部存在 | 是（MISSING_UNEXPECTED=0） |
| 计划外误删 | 0 |

## 未触碰的目录（明确不在范围）

- `C:/Users/yanwen/.local/share/opencode/`（含 opencode.db 3,658.8 MB + WAL）
- `C:/Users/yanwen/.local/share/opencode/worktree/`（worktree 存档）
- `C:/Users/yanwen/AppData/Local/uv/cache`（14.8 GB，含 7 个 .tmpXXXX 残留约 5.6 GB）
- `D:/code/` 全部（只读用于引用判定与哈希比对）

## 建议后续动作

1. 优先清理 uv 缓存残留：uv cache prune 可回收 .tmpXXXX 残留约 5.6 GB，且不影响离线重建能力。这比继续删临时目录的收益高得多。
2. staged_prepared_inputs_20261027_v7/v8/v10（3.27 GB）：确认 v12 的 raw symlink 依赖后，v7/v10 可删；v8 是 v12/v10 的链接目标，须一并处理。
3. validation_2025_ab_real_20261029_v1（2.73 GB）：v2 已取代 v1 且无文档引用，可考虑删 v1；但它记录了 2025-01-06 的 record_date_unknown 中断证据，建议先归档其 run_status.json 再删大 jsonl。
4. old_1435476987/：确认是否为有意留存。

## 方法论备注

- 引用判定先做过纯子串匹配，发现 attr（命中 attribute）、precision（命中普通英文词）、opencode（命中大量无关路径）等假阳性，改用词边界正则后假阳性归零。
- 体积统计跳过 reparse point 子树，避免 junction/symlink 导致重复计数（本目录共 9 个 reparse point）。
- 空目录判定标准为"递归后 0 个文件"，实测 85 个空目录全部为真空。
- 删除前核对了 17 个 tmux 会话的 pane_current_path，无交集。