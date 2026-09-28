# Daily Continuous Status

Date: 2026-09-06

## Delivered

- Leakage-safe daily records: 45 rolling features plus 4 close-only features, fixed 1,000-name pool, T+1 buy, five-session sell, and reward validity masks.
- Deeper per-name policy: `(batch, 1000, 50)` input, per-name alpha logits, per-name trade gates, and differentiable long-only target-weight projection.
- Lot-sized executor: sell-before-buy, 100-share lots, cash reallocation, V6 fees, participation slippage, limit-up guard, missing-price and halted-name handling.
- Streaming parquet dataset builder: only the date window and required columns are read; records are yielded one at a time.
- Synthetic daily smoke: 12 consecutive signal days, delayed five-session reward queue, carried portfolio state, and 207 synthetic trades.
- GPU training: CUDA path verified on `NVIDIA GeForce GTX 970M` with `torch 2.13.0+cu126`.
- Real lot-account rollout: execution sidecars include the full buy-date universe so holdings falling out of the 1,000-name signal pool can be sold instead of becoming zombies.

## Verification

- Full suite: `70 passed, 38 subtests passed`.
- Current full suite after the training, rollout, and TEST guard work: `109 passed, 38 subtests passed`.
- Real-data probe: 3,317 trading dates found; 2026-08-24 window produced `(1000, 49)` and 999 valid reward rows, with sell date 2026-08-31.
- Full GPU TRAIN/VAL: stride 1, 2,607 TRAIN records, 480 VAL records; VAL account final `3363618.32`, total `68.18%`, max drawdown `11.86%`, 827 trades, fee `5559.19`, 27 locked/unpriced holdings.
- Full single-use TEST: stride 1 yielded 155 TEST records; final `2105560.41`, total `5.28%`, max drawdown `9.70%`, Sharpe `0.439`, 493 trades, fee `4487.33`, slippage `4399.42`, 8 locked/unpriced holdings.
- Git milestones include: `c5490d2`, `100a3f4`, `c2f0360`, `894097f`, `a2f6cdb`, `666662b`, `98ff42f`, `b745f80`, `3563c1a`, `bd6a0dd`, `c83f637`.
- Worktree is clean after the status commit.

## Not Yet Claimed

- The reported TRAIN/VAL and TEST numbers now use full `stride=1`; TEST has 155 available signal days through the source data cutoff of 2026-08-31, not a complete calendar year.
- `model_5d.pkl` was not used as a teacher because it was retrained on TRAIN+VAL.
- The 2026 TEST was opened exactly once through `run_daily_test_once.py`; all run outputs are in `artifacts/daily_continuous_runs/20260906_gpu_stride1_full/`.
- The account result has eight locked/unpriced holdings and must retain that limitation in any report.
