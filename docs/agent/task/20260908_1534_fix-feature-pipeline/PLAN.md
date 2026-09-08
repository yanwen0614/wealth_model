# fix-feature-pipeline Implementation Plan

> Generated: 2026-09-08 15:34
> Task Dir: docs/agent/task/20260908_1534_fix-feature-pipeline

## Goal

Make the per-code parquet feature pipeline reproducible and leakage-safe: reuse a scaler only for the exact fitting identity, produce finite neutral-zero values for missing signals, and preserve the approved F=45 feature contract.

## Architecture

`data/schema.py` will own an ordered, explicit 39-column raw-feature allowlist; the scaler appends the six G9 masks to retain F=45. `data/scaler.py` will persist a versioned identity manifest and a complete, validated transformation schema, while `data/dataset.py` will distinguish a training cache lookup/refit from validated external reuse for validation and evaluation. Validation loading will prepend one eligible prior row per code only for relative transformation context, then discard it before labels, windows, and samples are built.

## Key Decisions

| Decision | Choice | Rejected | Reason |
|---|---|---|---|
| Raw feature selection | Ordered explicit 39-column allowlist | Parquet-derived denylist | Extra parquet columns cannot silently enter training; the order is hashable and F=45 is deterministic. |
| `use_factor_only` | Remove it from `ParquetDataConfig` and `_default_feature_cols`; callers use explicit `feature_cols` for deliberate experiments | Retaining a flag that selects all 48 exported factors | Its true branch violates the approved G2/G6/G7 exclusions and F=45 contract. |
| Cache identity | SHA-256 of canonical JSON manifest | Path-only or pickle-version-only reuse | Binds data snapshot, fitting period, feature order, normalization/mask semantics, and scaler implementation version. |
| Parquet fingerprint | Resolved path, `st_size`, `st_mtime_ns`, plus parquet metadata row count/schema fingerprint when available | Filename only | Meets the minimum path/stat requirement and detects schema/snapshot drift without reading the 3.5G file. |
| Mismatch policy | Training cache mismatch refits and overwrites; externally supplied validation/evaluation scaler must match its declared training identity and schema or fail | Fallback pickle loading or validation refit | Prevents stale-cache leakage and prevents validation statistics from becoming training data. |
| Missing values | Apply transforms to valid observations, then replace all non-finite outputs with the final neutral zero | Filling raw values with zero before relative/robust transform | A raw zero can become a non-neutral robust score. |
| Unseen codes | Store global stats produced through the same transform and winsor pipeline as per-code stats | Global median/IQR on raw values | Ensures fallback applies valid relative, winsor, robust, and clip semantics. |
| Validation context | Prepend only each code's last eligible pre-start row for transformations, then trim it before window/index creation | Dropping history or allowing context rows into samples | Preserves first-day `prev_close` without changing validation membership. |

## Impact

| Module | File | Operation | Risk |
|---|---|---|---|
| data | `data/schema.py` | modify | high |
| data | `data/scaler.py` | modify | high |
| data | `data/dataset.py` | modify | high |
| scripts | `scripts/eval_bins_mapping.py` | modify | medium |
| docs | `docs/per_code_normalization_spec.md` | modify | medium |
| tests | `tests/unit/data/test_data_schema_labels.py` | modify | medium |
| tests | `tests/unit/data/test_data_feature_pipeline.py` | create | high |

## Hash Contract

The persisted payload gains `identity_manifest`, `identity_hash`, `schema_manifest`, and `version="v3_per_code"`. `identity_manifest` is canonical JSON (`sort_keys=True`, compact separators, UTF-8) containing: resolved parquet path; size; nanosecond mtime; parquet row count and schema digest when readable; normalized training `start_date`/`end_date`; ordered raw feature names; `normalize`; `per_code_add_mask`; `filter_is_trading`; `max_codes`; transform/mask configuration digest; and scaler version. `identity_hash` is its SHA-256 digest.

`schema_manifest` records ordered input/output/mask columns, add-mask state, and transform-spec version/digest. Load validates required keys, version, column uniqueness/order, output construction, G9 masks, per-code/global stat coverage and required statistic fields. Reuse compares both the expected identity hash and the requested schema before any transform.

## Task Decomposition

### T01: Define the Approved Feature Contract
- **Files**: `data/schema.py` (modify), `data/dataset.py` (modify), `tests/unit/data/test_data_schema_labels.py` (modify)
- **Description**: Add the ordered 39-column approved raw-feature allowlist from the normalization specification; make default selection require all listed parquet columns in that exact order. Remove `use_factor_only` and its invalid 48-factor branch; retain explicit `feature_cols` as the sole override and reject unavailable columns.
- **Dependencies**: None
- **Estimated lines**: +55/-28, each source edit under 100 lines
- **Acceptance criteria**: Default selection is exactly the approved 39 raw names; G2/G6/G7 and base `close`/absolute-volume fields are absent; per-code output remains 39+6=45; custom feature order is preserved.
- **Risk factors**: Existing callers using the removed field must fail clearly during migration rather than silently changing model input.

### T02: Add Versioned Scaler Identity and Schema Validation
- **Files**: `data/scaler.py` (modify), `tests/unit/data/test_data_feature_pipeline.py` (create)
- **Description**: Implement canonical manifest/hash helpers, attach the fitting identity in `fit`, persist it in a v3 payload, and add strict load/reuse validation for payload shape, required metadata, input/output/mask columns, groups, and stats. Remove the raw-pickle fallback path from the dataset integration in T04.
- **Dependencies**: T01
- **Estimated lines**: +95/-18, split into helper and persistence edits under 100 lines each
- **Acceptance criteria**: Identical manifests hash identically; changing parquet stat/path, training range, raw feature order, mask configuration, transform version, or scaler version changes the hash; malformed/legacy payloads and schema mismatches raise actionable `ValueError`.
- **Risk factors**: Pickle is untrusted input; only project-created v3 payloads are supported after this change.

### T03: Correct Per-Code Transform and Unseen-Code Semantics
- **Files**: `data/scaler.py` (modify), `tests/unit/data/test_data_feature_pipeline.py` (create)
- **Description**: Refactor shared per-column transform/stat helpers so per-code and global fallback calculate relative values with prior closes, winsor bounds, robust values, and clips identically. Keep missing values outside statistics and map NaN/inf to zero only after the group transformation; retain G9 observed masks before filling.
- **Dependencies**: T01, T02
- **Estimated lines**: +90/-70, split into focused edits under 100 lines each
- **Acceptance criteria**: Every transformed output is finite; a missing G1/G3/G4/G5/G8/G9 signal is final zero (with G9 mask=0); unseen-code G1 relative robust and G3/G4 winsor results match global training semantics; known-code behavior still follows the G1/G3/G4/G8/G9 specification.
- **Risk factors**: Relative transformation needs a valid prior close and must not manufacture a signal at the first usable row.

### T04: Enforce Training Cache Policy and Validation Context Boundaries
- **Files**: `data/dataset.py` (modify), `tests/unit/data/test_data_feature_pipeline.py` (create)
- **Description**: Build the expected fit identity from the training config before loading `scaler_path`. A matching training cache may load; a mismatch refits on the filtered training frame and overwrites the cache. Validate externally supplied scaler objects against the declared training identity/schema. For a date-bounded dataset, retain one preceding eligible row per code only as transformation context and remove it before labels, group storage, and window index construction.
- **Dependencies**: T01, T02, T03
- **Estimated lines**: +95/-45, split into cache-policy and context-window edits under 100 lines each
- **Acceptance criteria**: Matching training cache is reused; each identity mismatch causes exactly a train-only refit; validation never fits; the first validation observation uses the prior close; no validation window/date/index contains a context row; F=45 and `[B,45,60]` stay unchanged.
- **Risk factors**: Current date filtering precedes grouping, so context must be marked and trimmed without contaminating labels or sample counts.

### T05: Propagate Verified Reuse to Training and Evaluation Entrypoints
- **Files**: `scripts/eval_bins_mapping.py` (modify), `tests/unit/data/test_data_feature_pipeline.py` (modify)
- **Description**: Make evaluation construct and require the scaler's training identity (including explicit training dates) before external reuse. Keep `create_dataloaders` passing the verified training scaler to validation, rather than attempting to match validation dates. Preserve the explicit evaluation debug path that may fit only when opted in.
- **Dependencies**: T04
- **Estimated lines**: +45/-12, each source edit under 100 lines
- **Acceptance criteria**: Evaluation rejects missing, legacy, hash-mismatched, and schema-incompatible scalers; normal training/validation reuses the train scaler; no call path silently loads arbitrary pickle statistics.
- **Risk factors**: The evaluator currently exposes validation dates but not fitting dates, requiring an explicit CLI/config contract.

### T06: Update Specification and Execute Focused Regression Tests
- **Files**: `docs/per_code_normalization_spec.md` (modify), `tests/unit/data/test_data_schema_labels.py` (modify), `tests/unit/data/test_data_feature_pipeline.py` (create)
- **Description**: Update the source-of-truth persistence and validation-context sections to v3 identity/schema semantics. Add compact parquet fixtures and unit cases for allowlist/F=45, identity mutation, load validation, neutral missing values, unseen-code fallback, first-validation-day context exclusion, and cache mismatch/refit policy.
- **Dependencies**: T01, T02, T03, T04, T05
- **Estimated lines**: +95, each source/test edit under 100 lines
- **Acceptance criteria**: `uv run --project . python -m unittest discover tests/unit/data` passes; focused fixture checks assert `[B,45,60]`, finite outputs, six masks, and unchanged 52-class label contract; `uv run ruff check data tests/unit/data scripts/eval_bins_mapping.py` passes.
- **Risk factors**: Tests must remain synthetic and never read the ignored multi-gigabyte parquet file.
