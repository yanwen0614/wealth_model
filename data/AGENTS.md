# data/ — Parquet 入口与 Per-Code 归一化

- `dataset.py:57` 默认 `ParquetDataConfig(normalize="per_code")`，`scaler.py:30` `PerCodeGroupedScaler` 是 frozen 归一化事实源；rolling 仅通过 `--normalize rolling` 显式启用。
- 当前默认输出为 51 个 raw feature + 18 个 G9 mask = `F=69`；`F=45`（39+6 mask）是历史 schema。`close` 只作辅助列，不进入模型；改特征时传 `feature_cols` 显式列表，别改 `EXPORT_FACTORS`。
- 归一化必须时序防泄露：`ParquetDataset.create_dataloaders:525` 训练集 `fit` 并 `save scaler_per_code.pkl`，验证集传 `scaler_stats` 复用。`is_trading=False` 必须 `160` 过滤。
- 调试：`uv run --project . python -m data.dataset --max_codes 10 --normalize per_code` 会打标签分布并校验 `save/load` 一致性。
