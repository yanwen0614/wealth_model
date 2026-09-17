# docs/ — 归一化决策留档

- `per_code_normalization_spec.md` 为归一化决策唯一事实源（P/R/N/G 分组 + relative/asinh/clip/robust/winsor/mask，正文含**历史** G1~G9 说明），与 `data/schema.py` `FEATURE_GROUPS`、`data/scaler.py` `COLUMN_RULES`/`data/rolling_scaler.py` 实现一一对应；改分组先改此表。
- `img/` 产物图不入库；`README_TRAINING_CHAIN.md` 根级仍为新人链路说明，与本 spec 互补。
