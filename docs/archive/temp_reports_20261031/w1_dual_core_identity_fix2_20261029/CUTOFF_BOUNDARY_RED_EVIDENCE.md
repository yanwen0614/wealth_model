# Cutoff boundary RED evidence

These failures were observed before their corresponding fixes in the mini test process.

## Raw market execution bound

`test_provider_requests_21_history_and_does_not_swallow_schema` failed because the loader passed `execution_end=2021-06-15` while the fixed cutoff was `2021-06-07`.

## State lookup bound

The same test failed with `KeyError: 'execution_end'` when asserting that `_load_prepared_window` propagated the cutoff to `StateLookup`.

## Full-window coverage read

The same test failed with `KeyError: 'cutoff'` when asserting that `_load_prepared_window` propagated the cutoff to `_complete_prepared_window`; the cutoff branch therefore could not skip full-window coverage metadata.

After the fixes, the combined provider/state/coverage test passed. The final 165-test run and static checks are recorded separately.
