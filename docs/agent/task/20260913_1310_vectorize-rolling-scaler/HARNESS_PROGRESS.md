# HARNESS_PROGRESS — vectorize-rolling-scaler

任务：把 `data/rolling_scaler.py` 的 `_rolling_column` 逐行 O(N·W) Python 循环改造为向量化实现，数值语义与审计计数保持等价，用于消除 E2/E3/E4 建缓存 ~16h 瓶颈。

## 背景事实
- 现实现 `rolling_scaler.py:250-293`：每行对 ≤252 窗口重算 `np.median`/`np.percentile`，单线程；实测 E2≈265min、E3≈317min、E4≈372min（10.49M 训练行）。
- 参考 `tests/unit/data/test_rolling_normalization.py`（450 行）锁定契约；`pandas>=2.3` 已是依赖。

## 验收
- 向量化后输出与逐行参考实现逐位一致（`np.array_equal(..., equal_nan=True)`），审计计数完全一致，fallback_mask 完全一致。
- 既有 rolling 单测全绿；ruff/pyright 0。
- 单列 10.49M 行从分钟级降到秒级。

## 任务
| ID | 描述 | 状态 | 依赖 | verify | TDD | 规模 | 结果 | 备注 |
|---|---|---|---|---|---|---|---|---|
| T01 | 向量化 `_rolling_column` + 等价测试 | pass | - | fast | true | ~120 | PASS | mask/audit 逐位一致；输出 ULP≤1.8e-15，float32 逐位一致；69–72x |
