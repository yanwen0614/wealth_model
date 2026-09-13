# Project Memory

## 当前架构
- 唯一训练入口：`train.py`。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（frozen）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`；训练：`training/`；损失：`criterion/`；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`；`scripts/run_backtest.py`（TopN rolling 回测 + benchmark）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联（四臂同名 best_model.pth 会互相覆盖 preds，须手动传 `--preds_out`）。

## 不可变契约
- 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序。
- 默认 per-code 输入 `F=69` = 51 raw feature + 18 G9 mask；`close` 仅辅助列。
- 默认序列 `T=60`，horizon=5，标签 `open[t+1+horizon]/open[t+1]-1`；`BINS` 51 边界 → `C=52`。
- scaler 只在训练集 fit；验证/评估复用训练 scaler，禁止重拟合（rolling 复用训练 rolling state）。
- 回测口径：T 日决策，T+1 open 买入，T+6 open 卖出。
- `train.py:48` `set_seed` 刻意设 `cudnn.deterministic=True` + `benchmark=False` 保可复现。
- **warmup 窗口语义（新）**：`start_date` 之前的历史行（`_transform_context`）保留在 `groups` 作窗口 warmup 输入；`valid_starts` 用 `is_context[label_pos]` 过滤，context **绝不作标签日**。context 上限：rolling 且 `role!=training` 为 `max(seq_len-1,251)`，否则 `max(seq_len-1,1)`。评估/验证标签日覆盖 = 区间交易日数 − `(horizon+1)`。`CACHE_FORMAT_VERSION=v2_context_warmup`。
- **注意**：`train.py --smoke` 会用 max_codes=20 重拟合并**覆盖 `logs/scaler_per_code.pkl`**，导致评估 identity 不匹配；需按训练口径（2013-01-01~2025-06-30 全量）重拟合恢复（identity_hash `9d590b…`）。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU），与 batch 无关 → **batch=1024**（吞吐 ×4；GPU 91%、epoch≈12:40）。
- `torch.compile` 不可用（缺 functorch/triton）；`channels_last_1d` 不存在；`batch_first` 无收益。
- rolling `_rolling_column` 已向量化（pandas，69–72x），rolling 缓存各 ~15-20min。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run --project . python train.py --smoke --num_workers 0
```

## E1-E4 训练结果（batch=1024 / patience=5 / seed=42 / lr=1e-4）
| 臂 | 归一化 | Best Val Loss | Best Val Acc | run 目录 |
|---|---|---|---|---|
| E1 | per_code | 0.0568 | 0.0947 | `logs/run_20260913_103612` |
| E2 | rolling e2 | 0.0565 | 0.1042 | `logs/rolling_e2/run_20260913_134654` |
| E3 | rolling e3 | 0.0565 | 0.0961 | `logs/rolling_e3/run_20260913_152257` |
| E4 | rolling e4 | 0.0563 | 0.0971 | `logs/rolling_e4/run_20260913_170018` |
- 四臂均 epoch 1 达最优、6 epoch 早停（欠训练，勿强下结论）。

## E1-E4 评估（2026-01-01~08-31，**warmup 后 154 交易日**，490,571→约 79 万样本）
| 臂 | 整体 RankIC | 日截面 RankIC mean | xs_spread mean | 回测 Top5 annual(超额) |
|---|---|---|---|---|
| E1 | -0.0060 | -0.0058 | 0.0007 | -43.0% (-30.4%) |
| E2 | 0.0333 | **0.0215** | 0.0032 | -52.7% (-40.1%) |
| E3 | 0.0049 | 0.0039 | -0.0006 | -52.1% (-39.5%) |
| E4 | 0.0226 | 0.0109 | 0.0036 | -60.9% (-48.2%) |
- 基准（全截面等权）annual -12.66%、sharpe -1.27。
- **warmup 修复前（95 天）E1 Top5 为 +17.98%；修复后（154 天）翻转为 -43.0%** → 之前的正超额是样本窗口偏置造成的假象。修复后四臂 TopN 回测**全部跑输基准**，仅 E2/E4 截面 IC 弱正（E2 最强）。
- 产物：`logs/preds_E{1..4}_2026-08-31.npz`、`logs/eval_E{1..4}_2026-08-31.json`、`logs/backtest_e1e4_2026-01-01_2026-08-31/`、`logs/topn_curve_e1e4_2026.png`、`logs/ohlc_path_2026-01-01_2026-08-31.npz`。

## 已知变更
- [2026-09-08 14:57] 精简 dependencies 从 30 到 7 个核心包，其余移入 optional-dependencies 分组
- [2026-09-13 10:15] T05 修复 `_FeatureView` 重复全量 mmap（WinError 1455）：`_MMAP_REGISTRY`+`_open_shared_mmap`。commit 4bc7f26。
- [2026-09-13 13:40] T01 向量化 `rolling_scaler._rolling_column`；commit 0a22d1f，QA PASS。
- [2026-09-13 20:1x] context warmup 窗口（`data/dataset.py` 保留 context 作 warmup、`is_context` 过滤标签日；`feature_cache.py` bump `v2_context_warmup`；文档同步）；commit `42ffe0c`，QA PASS。
