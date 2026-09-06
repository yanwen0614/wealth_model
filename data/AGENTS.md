# data/ — Parquet 入口与 Per-Code 归一化

- `dataset.py:57` `ParquetDataConfig(normalize="per_code")` 唯一可信值；`scaler.py:30` `PerCodeGroupedScaler` 为归一化单一事实源（旧 `grouped` 已删）。
- 默认特征 `dataset.py:91` 自动剔除 G2/G6/G7/`TOT_SHARE`/`volume/amount`/`close` → 45维；改特征时传 `feature_cols`显式列表，别改 `EXPORT_FACTORS`。
- 归一化必须时序防泄露：`ParquetDataset.create_dataloaders:525` 训练集 `fit` 并 `save scaler_per_code.pkl`，验证集传 `scaler_stats` 复用。`is_trading=False` 必须 `160` 过滤。
- 调试：`uv run --project . python -m data.dataset --max_codes 10 --normalize per_code` 会打标签分布并校验 `save/load` 一致性。
