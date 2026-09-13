# data/ — Parquet 入口与 Per-Code 归一化

- `dataset.py:57` 默认 `ParquetDataConfig(normalize="per_code")`，`scaler.py:30` `PerCodeGroupedScaler` 是 frozen 归一化事实源；rolling 仅通过 `--normalize rolling` 显式启用。
- 当前默认输出为 51 个 raw feature + 18 个 G9 mask = `F=69`；`F=45`（39+6 mask）是历史 schema。`close` 只作辅助列，不进入模型；改特征时传 `feature_cols` 显式列表，别改 `EXPORT_FACTORS`。
- 归一化必须时序防泄露：`ParquetDataset.create_dataloaders:525` 训练集 `fit` 并 `save scaler_per_code.pkl`，验证集传 `scaler_stats` 复用。`is_trading=False` 必须 `160` 过滤。
- 调试：`uv run --project . python -m data.dataset --max_codes 10 --normalize per_code` 会打标签分布并校验 `save/load` 一致性。
- **feature memmap 缓存**：`data/feature_cache.py` 只缓存归一化后的 `features`（float32）+ 小数组，`ParquetDataConfig.cache_enabled=False` 保冻结（单测/评估零改动），`train.py` 默认开启，`--no_cache`/`--rebuild_cache`/`--cache_dir` 控制；根解析 `--cache_dir` > `CNN_DATA_CACHE` > 平台默认（Linux `~/.cache/cnn`、Windows `%LOCALAPPDATA%\cnn\cache`）。key 含 role/scope/scaler identity/seq_len/horizon/max_windows/bins/cache_format_version；写侧新 generation + `.ok` 原子发布，运行期不自动删除。缓存不削弱验证集红线：命中仍校验并复用训练 scaler，绝不重 fit。
- **warmup 窗口语义**：`start_date` 之前的历史行（`_transform_context=True`）保留在 `groups` 中作滑动窗口 warmup 输入；`valid_starts` 用 `is_context[label_pos]`（`label_pos=s+seq_len-1`）过滤，保证 context **绝不作为标签日、不产生样本标签**。context 上限：rolling 且 `role!=training` 为 `max(seq_len-1,251)`，否则 `max(seq_len-1,1)`。评估/验证标签日覆盖 = 区间交易日数 − `(horizon+1)`（2026-01-01~08-31 由 95 → ≈154）。勿与 rolling `min_periods=120`/frozen fallback 的**归一化统计预热**混淆（两套机制）。`CACHE_FORMAT_VERSION=v2_context_warmup` 使携带旧「丢弃 context」语义的缓存失效。
