# Research script and evidence index

These entries are explicit research tools. None is a default production backtest entry point.
Paths in the external-material sections are relative to `C:/Users/yanwen/AppData/Local/Temp/opencode/`.

## CA consolidation worktree

- Conditional 2025 entry, currently uncommitted in this tree: `scripts/run_2025_ab_execution.py`; imports `backtest.cnn_adapter.validation_2025_bridge` and `validation_2025_execution`. Invoke only by explicit research command (`python -m scripts.run_2025_ab_execution ...`); inspect `--help` first.
- Current status: source identity was FAIL in `validation_2025_bridge_independent_qa_20261029/REPORT.md`; `validation_2025_bridge_fix1_20261029/REPORT.md` records fixes and 199 targeted tests but does not supply independent final identity acceptance. No annual A/B NAV. Preserve `IDENTITY_LOCAL`, `PIT_UNPROVEN`, `INCOMPLETE` and `actual_after_tax_target_eligible=false`.
- Related evidence: `validation_2025_bridge_delivery_20261029/REPORT.md`, `validation_2025_data_preflight_20261029/REPORT.md`, `validation_2025_ca_two_event_audit_20261029/REPORT.md`, `validation_2025_ca_evidence_adapter_20261029/REPORT.md`, `validation_2025_ab_v2_abort_audit_20261029/REPORT.md`.

## W1 research worktrees (not transplanted)

- Fractional scenarios: original relative paths are under worktree `w1-fractional-scenarios-20261028/`; QA at `w1_fractional_scenarios_independent_qa_20261028/` and delivery at `w1_fractional_scenarios_delivery_20261028/EXECUTION_REPORT.md`. Floor/ceil outcomes and coverage are incomplete; official allocation/PIT proof is absent.
- Prefix/attestor tools: source and scripts remain under `w1-fractional-scenarios-20261028/` original relative paths; fixes/evidence in `w1_prefix_fix5_20261028/`, `w1_dual_core_identity_fix3_20261029/`, `w1_prefix_independent_qa_20261028/`, `w1_dual_core_identity_independent_qa_20261029/`. Trusted pins remain unset; real 12-path proof and performance are BLOCKED.
- Real prefix/ceil evidence: `w1_real_prefix_exploration_20261029/REPORT.md`, `w1_real_prefix_independent_audit_20261029/REPORT.md`, `w1_ceil_precision_independent_qa_20261029/REPORT.md`. Records are INCOMPLETE; no production proof.
- None of these scripts belongs in `backtest/cnn_adapter` defaults. Recover via the named original worktree and its relative paths; do not copy from a report or rename as production code.

## Shared production-candidate code (not a production acceptance)

- Raw market input preparation and provider are modules under `backtest/cnn_adapter/`, not CLI scripts. Their consuming research preparation entry in this tree is `python -m backtest.cnn_adapter.staged_production_inputs --prepare-only ...`; running it requires a complete explicit input config and writes to a new output directory.
- Single-window runner is `python -m backtest.cnn_adapter.staged_candidate_runner ...`; this is a candidate API/CLI with explicit incomplete gates, not a default strategy verdict.
- Module evidence: `corporate_action_context_independent_qa_20261027/reverify1/REPORT.md`, `staged_runner_independent_qa_20261027/reverify1/REVERIFY_REPORT.md`, `staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md`. Mechanical PASS is bounded; source lineage and real performance remain unaccepted.

## Frozen unrelated research reports

- Historical baseline: `corporate-action-fix-20261027/research/goal/REPORT.md` (legacy snapshot) and `research/goal_repro/REPORT.md` (2026-09-28 reproduction); neither is a CA/W1/2025 acceptance artifact.
- Integration status and CA scope: `corporate-action-fix-20261027/docs/research/20261026/ENGINEERING_STATUS.md`, `corporate_action_tax_tdd_plan.md`, `staged_order_strategy_delivery.md`.
- Consolidation decisions, excluded files and planned source ZIP path: [`docs/research/worktree_consolidation_20261030/README.md`](../../docs/research/worktree_consolidation_20261030/README.md). ZIP path is a convention only; no archive or cleanup was performed.
