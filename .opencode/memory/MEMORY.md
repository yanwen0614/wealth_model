# Project Memory

## 当前架构
- 唯一训练入口：`train.py`。
- **默认归一化 = E0 (relative)**（`config/defaults.py` `NORMALIZE="relative"`，`SCALER_PATH=None`；`data/dataset.py` `ParquetDataConfig.normalize="relative"`）。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（`RelativeScaler` E0 + `PerCodeGroupedScaler` E1）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`；训练：`training/`；损失：`criterion/`；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`（`--full` 出全期日频矩阵）；`scripts/run_backtest.py`（rolling/target 回测 + 指数基准 + 强买门槛）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联。

## 不可变契约
- 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序。
- 默认序列 `T=60`，horizon=5，标签 `open[t+1+horizon]/open[t+1]-1`；`BINS` 51 边界 → `C=52`。
- scaler 只在训练集 fit；验证/评估复用训练 scaler，禁止重拟合（rolling 复用训练 rolling state）。
- 回测时序：T 日决策，T+1 open 买入，T+6 open 卖出。
- `train.py:48` `set_seed` 刻意设 `cudnn.deterministic=True` + `benchmark=False` 保可复现。
- **warmup 窗口语义**：`start_date` 之前的历史行（`_transform_context`）保留在 `groups` 作窗口 warmup 输入；`valid_starts` 用 `is_context[label_pos]` 过滤，context **绝不作标签日**。context 上限：rolling 且 `role!=training` 为 `max(seq_len-1,251)`，否则 `max(seq_len-1,1)`。评估/验证标签日覆盖 = 区间交易日数 − `(horizon+1)`。`CACHE_FORMAT_VERSION=v3_relative_groups`。
- **默认 parquet 路径**：`ParquetDataConfig.parquet_path` 与 `config/defaults.DEFAULT_PARQUET`（Linux 分支）均指向 `data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`（F60 schema）；win32 由 `train.py` 覆盖为 `Z:/...`。指数数据在 `Z:/test/kline_index/day/<code>.parquet`（列 `code,kline_time,open,high,low,close,volume,amount`）。
- **注意**：`train.py --smoke` 会用 max_codes=20 重拟合并**覆盖 `logs/scaler_per_code.pkl`**；需按训练口径（2013-01-01~2025-06-30 全量）重拟合恢复。

## Redesign（P/R/N/G 分组 + E0–E5，2026-09-14 落地，commit 178f24e）
- **schema（T01）**：`FEATURE_GROUPS={P:18,R:16,N:12,G:6}`，`APPROVED_RAW_FEATURES`=**52**（`close` 解禁进 P）；`G9_OBSERVATION_SOURCE`=18，`G9_MASK_COLUMNS=("g9_observed_mask",)`（1 列）；`PROHIBITED_COLUMNS` 去 close；`column_group`/`default_feature_cols(normalize)`/`g9_observed_mask(frame)`。**F_out=52+1=53**。`EXPORT_FACTORS`/`BASE_COLUMNS` 未动。
- **ColumnRule/RelativeScaler（T02）**：`ASINH_CLIP=5.0`/`P_CLIP=(-5,5)`/`N_CLIP=(0,1)`/`AMIHUD_SCALE=1e12`/`RELATIVE_DENOMINATOR="close"`/`G9_RAW_CLIP`(6 列)；`COLUMN_RULES`(52, 由 FEATURE_GROUPS 生成)；`column_rule(col)` 未知 raise；模块级 `_relative_transform`（分母 `isfinite & !=0`）；`RelativeScaler(feature_cols, add_mask=True)` 无 `fit`，末尾 1 个 `g9_observed_mask`；digest payload=`COLUMN_RULES`+version+`G9_MASK_COLUMNS`。
- **PerCodeGroupedScaler E1（T03）**：按 `COLUMN_RULES` 路由；仅 P 组 fit 每股 median/IQR（在 `x/close[t-1]-1` 上），transform `(v-med)/(IQR/1.349)` clip±5；R/N/G 确定性；未见 code 回退 `global_stats`；未知列 raise；1 shared mask；`SCALER_VERSION="v4_per_code"`、`TRANSFORM_VERSION="per_code_transform_v4"`（旧 v3 payload load raise）。对外 API 全保留。
- **RollingNormalizer（T04）**：`ROLLING_SCOPE_FEATURES={e0:(),e1:P,e2:P,e3:P+vol(21),e4:+vol_ratio/amihud(24),e5:+G raw(30)}`；默认 `scope="e5"`。scope P→relative+rolling robust；scope VOL/VOLUME/G→rolling winsor；非 scope 按 `COLUMN_RULES`；末尾恰 1 列 shared mask（e5 G9 raw 入 scope 也**不短路**）；`_validate_feature_cols` 允许 close；`ROLLING_VERSION="v2_rolling_scope_e0_e5"`、`ROLLING_TRANSFORM_VERSION="rolling_transform_v2"`、`PAYLOAD_VERSION="v2_rolling_state"`；digest 含 scope 名。
- **dataset（T05）**：`normalize` 增 `relative`（无状态、无 fit、无落盘）；`_cache_key`/`_scaler_identity` mode-aware；`_resolve_scaler_on_cache_hit` 增 relative 重建分支；`rolling_scope` 默认 `e5`；`CACHE_FORMAT_VERSION="v3_relative_groups"`；`num_features=len(feature_cols_out)`。
- **train/CLI（T06）**：`ROLLING_SCOPES=("e0".."e5")`；`configure_preprocessing` 支持 `{per_code,rolling,relative}`（relative→`SCALER_PATH=None`+`./logs/relative`）；删 `featurenum==69` 断言，改 `resolve_featurenum`；CLI `--normalize relative`/`--rolling_scope e0..e5`/`--feature_cols`/`--featurenum`；metadata 含 `feature_cols`+`feature_cols_out`；rolling 维度不符改 warning。`config/defaults.py`：`ROLLING_SCOPE="e5"`、`featurenum=53`、**`LEARNING_RATE=3e-4`**。
- **eval/scripts（T07）**：mode 白名单增 relative、scope e0..e5、featurenum 实测派生（缺失 raise 不静默 45）、relative 无 state 重建、`run_eval_full.sh` 唯一 `--preds_out`、`multi_seed_train.py` 同步；`tests/unit/scripts/__init__.py` 使 discover 递归。
- **T08/T09**：旧契约测试增量同步完成；6 份文档同步为 F=53 与新分组。
- **整体 review**：VERDICT=PASS；修 M1（dataset 默认 parquet→F60）、M4（relative digest 增 mask_columns）、L1（inf 分母统一）、LR 1e-4→3e-4。既有 64 项仓级 ruff 报错为未触碰文件存量。

## 默认归一化 = E0 relative（2026-09-16 baseline 迁移）

**修改**：
- `config/defaults.py`：`NORMALIZE="relative"`, `SCALER_PATH=None`
- `data/dataset.py`：`ParquetDataConfig.normalize="relative"`, CLI `--normalize default="relative"`
- `scripts/run_eval_full.sh`：默认演示命令指向 E0

**理由**：跨期消融实验验证 E0 是唯一在验证期（2025-07~12，基准+38.3%）和评估期（2026-01~08，基准-3.4%）都贡献稳定正超额的配置，且零拟合/无状态。

**运行**：`uv run --project . python train.py` 现在默认 E0 relative。

## 强买门槛 + s50 + E0–E5 综合结论（2026-09-15，task 20260915_0005_add-strong-buy-gate）
- **新特性**：target 模式 `--strong_buy_threshold F`（默认 0.0=关闭、负值 raise）——买入带（`rank<=target_size`）候选 `exp_ret >= F` 才买，否则跳过留现金**不补位**；执行顺序 `strong_buy → 涨停检查`；`min_edge` 已删除（排序池下与 strong_buy_threshold 等价）。metrics 只增 `strong_buy_threshold`/`n_skipped_strong_buy`。`backtest/engine.py` `run_backtest_target` + `scripts/run_backtest.py`。默认 0.0 与改动前逐位一致。
- 详见 `docs/per_code_normalization_spec.md` §7。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows / 16 线程 15.9GB）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU）→ **batch=1024**；epoch≈14–16min。
- **内存是并发硬约束**：单臂（num_workers=4）即占满 ~16GB，禁止并行多臂。
- `torch.compile` 不可用；rolling `_rolling_column` 已向量化，rolling 缓存各 ~15-20min。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit   # 312 OK（删3个min_edge测试）
uv run ruff check .                                         # 仓级仍有存量（未触碰文件）
uv run --project . python train.py --smoke --num_workers 0
```

## 已知变更
- [2026-09-15] add-strong-buy-gate：target `--strong_buy_threshold`（T01–T05 全 PASS，discover 312 OK）+ 24 组扫描；删除 `min_edge`（等价参数）。commit `c7e8f72`。
- [2026-09-16] **E0 (relative) 设为默认 baseline**：`config/defaults.py` + `data/dataset.py` 默认归一化改为 relative。commit `<pending>`。