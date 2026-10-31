# Staged source guard — round 1 read-only QA

## Verdict

**PASS for scope A (single-window module source guard). BLOCKED for scope B (production runner source/hash/full-rank binding).** This review covers only the round-1 source guard in the frozen owner tree. It does not certify production source identity binding or the production maximum-three-buffer profile.

## Scope A — verified

- The prior FAIL report identified `source_id="unknown"` with a complete ranking, `AAA` rank 1, `buy_eligible=True`, and a valid close as a path that produced a BUY. Round-1 now rejects the ID in `RankingSnapshot.__post_init__`, before the snapshot reaches `orders_for`.
- The target regression test `test_placeholder_source_ids_fail_at_snapshot_creation_without_registry_pollution` covers 13 placeholder inputs, including empty/whitespace, `unknown` casing and outer whitespace, `None` through constructor rejection, and asserts no orders, episodes, tranches or registry snapshot changes.
- A direct read-only runtime probe independently confirmed rejection for `unknown`, ` UNKNOWN `, and `None`; it accepted `fixture-ranks-v1`. The target suite's B1 fixture test confirms an ordinary source produces its expected BUY.
- Normalization is `strip().casefold()` and rejection is limited to the explicit placeholder set. BUY ranking and eligibility, including `buy_eligible=False` for existing tranches, and SELL behavior remain unchanged in the reviewed diff. The existing `buy_eligible=False` behavior remains expected.
- Prior independent oracle report's 14 PASS conclusions are carried evidence; the 15th item is the source guard repaired here, while its production-binding portion remains blocked. The four-buffer-day synthetic fixture is module stress evidence only.

## Scope B — remains blocked

- Production runner binding of source identity, source file hash and full ranking provenance to the final manifest remains unverified. The source guard only rejects placeholder labels; an opaque ID is not proof of identity.
- The maximum-three-buffer boundary of the production runner window remains unverified. No claim is made from the four-buffer-day synthetic fixture.

## Evidence

- Exact target unittest command: `.venv/Scripts/python.exe -m unittest tests.unit.backtest.test_staged_allocation tests.unit.backtest.test_staged_execution_bridge tests.unit.backtest.test_staged_order_strategy` — **54 tests PASS**.
- Exact Ruff command: `.venv/Scripts/ruff.exe check backtest/cnn_adapter/staged_allocation.py backtest/cnn_adapter/staged_execution_bridge.py backtest/cnn_adapter/staged_order_strategy.py tests/unit/backtest/test_staged_allocation.py tests/unit/backtest/test_staged_execution_bridge.py tests/unit/backtest/test_staged_order_strategy.py` — **PASS**.
- Exact Pyright command: `.venv/Scripts/python.exe -m pyright --pythonpath .venv/Scripts/python.exe --project . backtest/cnn_adapter/staged_allocation.py backtest/cnn_adapter/staged_execution_bridge.py backtest/cnn_adapter/staged_order_strategy.py tests/unit/backtest/test_staged_allocation.py tests/unit/backtest/test_staged_execution_bridge.py tests/unit/backtest/test_staged_order_strategy.py` — **0 errors, 0 warnings, 0 informations**.
- No source, owner environment, Git state, lock, wheel, real-return run or large-data run was changed or executed.
- The original FAIL report and manifest were preserved; their SHA256 values and the six frozen file hashes are in `ROUND1_QA_MANIFEST.json`.
