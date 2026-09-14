# Project Memory

## 当前架构
- 唯一训练入口：`train.py`。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（`RelativeScaler` E0 + `PerCodeGroupedScaler` E1）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`；训练：`training/`；损失：`criterion/`；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`；`scripts/run_backtest.py`（TopN rolling 回测 + benchmark）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联（多臂同名 best_model.pth，脚本按目录派生唯一 `--preds_out`）。

## 不可变契约
- 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序。
- 默认序列 `T=60`，horizon=5，标签 `open[t+1+horizon]/open[t+1]-1`；`BINS` 51 边界 → `C=52`。
- scaler 只在训练集 fit；验证/评估复用训练 scaler，禁止重拟合（rolling 复用训练 rolling state）。
- 回测口径：T 日决策，T+1 open 买入，T+6 open 卖出。
- `train.py:48` `set_seed` 刻意设 `cudnn.deterministic=True` + `benchmark=False` 保可复现。
- **warmup 窗口语义**：`start_date` 之前的历史行（`_transform_context`）保留在 `groups` 作窗口 warmup 输入；`valid_starts` 用 `is_context[label_pos]` 过滤，context **绝不作标签日**。context 上限：rolling 且 `role!=training` 为 `max(seq_len-1,251)`，否则 `max(seq_len-1,1)`。评估/验证标签日覆盖 = 区间交易日数 − `(horizon+1)`。`CACHE_FORMAT_VERSION=v3_relative_groups`。
- **默认 parquet 路径**：`ParquetDataConfig.parquet_path` 与 `config/defaults.DEFAULT_PARQUET`（Linux 分支）均指向 `data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`（F60 schema）；win32 由 `train.py` 覆盖为 `Z:/...`。
- **注意**：`train.py --smoke` 会用 max_codes=20 重拟合并**覆盖 `logs/scaler_per_code.pkl`**；需按训练口径（2013-01-01~2025-06-30 全量）重拟合恢复。

## Redesign（P/R/N/G 分组 + E0–E5，2026-09-14 落地，commit 178f24e）
- **schema（T01）**：`FEATURE_GROUPS={P:18,R:16,N:12,G:6}`，`APPROVED_RAW_FEATURES`=**52**（`close` 解禁进 P）；`G9_OBSERVATION_SOURCE`=18，`G9_MASK_COLUMNS=("g9_observed_mask",)`（1 列）；`PROHIBITED_COLUMNS` 去 close；`column_group`/`default_feature_cols(normalize)`/`g9_observed_mask(frame)`。**F_out=52+1=53**。`EXPORT_FACTORS`/`BASE_COLUMNS` 未动。
- **ColumnRule/RelativeScaler（T02）**：`ASINH_CLIP=5.0`/`P_CLIP=(-5,5)`/`N_CLIP=(0,1)`/`AMIHUD_SCALE=1e12`/`RELATIVE_DENOMINATOR="close"`/`G9_RAW_CLIP`(6 列)；`COLUMN_RULES`(52, 由 FEATURE_GROUPS 生成)；`column_rule(col)` 未知 raise；模块级 `_relative_transform`（分母 `isfinite & !=0`）；`RelativeScaler(feature_cols, add_mask=True)` 无 `fit`，末尾 1 个 `g9_observed_mask`；digest payload=`COLUMN_RULES`+version+`G9_MASK_COLUMNS`。
- **PerCodeGroupedScaler E1（T03）**：按 `COLUMN_RULES` 路由；仅 P 组 fit 每股 median/IQR（在 `x/close[t-1]-1` 上），transform `(v-med)/(IQR/1.349)` clip±5；R/N/G 确定性；未见 code 回退 `global_stats`；未知列 raise；1 shared mask；`SCALER_VERSION="v4_per_code"`、`TRANSFORM_VERSION="per_code_transform_v4"`（旧 v3 payload load raise）。对外 API 全保留。
- **RollingNormalizer（T04）**：`ROLLING_SCOPE_FEATURES={e0:(),e1:P,e2:P,e3:P+vol(21),e4:+vol_ratio/amihud(24),e5:+G raw(30)}`；默认 `scope="e5"`。scope P→relative+rolling robust；scope VOL/VOLUME/G→rolling winsor；非 scope 按 `COLUMN_RULES`；末尾恰 1 列 shared mask（e5 G9 raw 入 scope 也**不短路**）；`_validate_feature_cols` 允许 close；`ROLLING_VERSION="v2_rolling_scope_e0_e5"`、`ROLLING_TRANSFORM_VERSION="rolling_transform_v2"`、`PAYLOAD_VERSION="v2_rolling_state"`；digest 含 scope 名。
- **dataset（T05）**：`normalize` 增 `relative`（无状态、无 fit、无落盘）；`_cache_key`/`_scaler_identity` mode-aware；`_resolve_scaler_on_cache_hit` 增 relative 重建分支；`rolling_scope` 默认 `e5`；`CACHE_FORMAT_VERSION="v3_relative_groups"`；`num_features=len(feature_cols_out)`。
- **train/CLI（T06）**：`ROLLING_SCOPES=("e0".."e5")`；`configure_preprocessing` 支持 `{per_code,rolling,relative}`（relative→`SCALER_PATH=None`+`./logs/relative`）；删 `featurenum==69` 断言，改 `resolve_featurenum`（None 实测/显式≠实测 raise）；CLI `--normalize relative`/`--rolling_scope e0..e5`/`--feature_cols`/`--featurenum`；metadata 含 `feature_cols`+`feature_cols_out`；rolling 维度不符改 warning。`config/defaults.py`：`ROLLING_SCOPE="e5"`、`featurenum=53`、**`LEARNING_RATE=3e-4`**。
- **eval/scripts（T07）**：mode 白名单增 relative、scope e0..e5、featurenum 实测派生（缺失 raise 不静默 45）、relative 无 state 重建、`run_eval_full.sh` 唯一 `--preds_out`、`multi_seed_train.py` 同步；`tests/unit/scripts/__init__.py` 使 discover 递归。
- **T08/T09**：旧契约测试增量同步完成（全量 `discover tests/unit` 275 OK）；5+1 份文档（AGENTS.md/README_TRAINING_CHAIN.md/docs/per_code_normalization_spec.md/data/AGENTS.md/models/AGENTS.md/docs/AGENTS.md）同步为 F=53 与新分组。
- **整体 review**：VERDICT=PASS；修 M1（dataset 默认 parquet→F60）、M4（relative digest 增 mask_columns）、L1（`_relative_transform` inf 分母统一）、LR 1e-4→3e-4。既有 64 项仓级 ruff 报错为未触碰文件存量（scope_outside）。

## E0–E5 redesign 训练/评估（2026-09-14，`--lr 3e-4 --batch_size 1024 --num_workers 4 --seed 42 --epochs 50 --patience 5`）
- 训练并发受 **RAM 限制（15.9GB，单臂占满）→ 必须串行**；单臂约 2h（rolling 另加缓存构建），六臂物理上无法短时全完成。后台：psmux `cnn_e0e5`（训练链）+ `cnn_ctrl`（控制器：E2 后暂停→评 E0–E2→续训 E3–E5→评）。
- 已完成（2026-09-14）：
| 臂 | mode/scope | Best Val Loss / Acc | run 目录 | 截面 RankIC mean | 回测 top5 annual(超额) | top100 annual(超额) |
|---|---|---|---|---|---|---|
| E0 | relative | 0.0562 / 0.1043 | `logs/relative/run_20260914_024253` | 0.0248 | -47.33% (-34.67%) | -12.88% (-0.22%) |
| E1 | per_code | 0.0562 / 0.1005 | `logs/run_20260914_045053` | 0.0302 | -48.40% (-35.74%) | -3.13% (+9.53%) |
| E2 | rolling e2 | 0.0562 / 0.1033 | `logs/rolling_e2/run_20260914_064942` | 0.0415 | -27.35% (-14.69%) | -4.15% (+8.50%) |
- 基准（全截面等权）annual -12.66%、sharpe -1.266；评估区间 2026-01-01~08-31（154 日，794,501 样本）。
- E2 截面 IC 最高；E1/E2 top50/top100 相对基准有正超额。
- E3–E5 训练进行中（E3 于 09:31 启动 ctrl 重启；预计 E3≈11:5x、E4≈14:2x、E5≈16:4x，评估随后）。产物：`logs/preds_<tag>_2026-08-31.npz`、`logs/backtest_<tag>_2026-01-01_2026-08-31/`、`logs/topn_curve_<tag>_*.png`、`logs/ohlc_path_2026-01-01_2026-08-31.npz`。
- 进程日志：`%TEMP%\opencode\e0e5\{progress,ctrl,E0..E5}.log`；脚本 `run_e0e5.ps1`/`ctrl_e0e5.ps1`。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows / 16 线程 15.9GB）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU）→ **batch=1024**；epoch≈14–16min。
- **内存是并发硬约束**：单臂（num_workers=4）即占满 ~16GB，禁止并行多臂。
- `torch.compile` 不可用；rolling `_rolling_column` 已向量化，rolling 缓存各 ~15-20min。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit   # 275 OK
uv run ruff check .                                         # 仓级仍有 64 项存量（未触碰文件）
uv run --project . python train.py --smoke --num_workers 0
```

## 历史结果（旧 F=69 schema / lr=1e-4，不可与新 F=53 结果混用）
- E1 per_code 0.0568/0.0947；E2 rolling e2 0.0565/0.1042；E3 rolling e3 0.0565/0.0961；E4 rolling e4 0.0563/0.0971；均 6 epoch 早停。
- 评估（154 日）：E1 RankIC -0.0058 / Top5 -43.0%；E2 0.0215 / -52.7%；E3 0.0039 / -52.1%；E4 0.0109 / -60.9%。

## 已知变更
- [2026-09-13 10:15] T05 修复 `_FeatureView` 重复全量 mmap（WinError 1455）：`_MMAP_REGISTRY`+`_open_shared_mmap`。commit 4bc7f26。
- [2026-09-13 13:40] T01 向量化 `rolling_scaler._rolling_column`；commit 0a22d1f。
- [2026-09-13 20:1x] context warmup 窗口；commit `42ffe0c`。
- [2026-09-14] redesign 全流程 T01–T09 落地 + 整体 review 修复；commit `178f24e`（feature/rolling-normalization-cnn，已 push）。文档三件套（MODULE_DESIGN/INTERVIEW_LOG/DESIGN_SPEC/PLAN/REVIEW_CHECKLIST/HARNESS_PROGRESS）在 `docs/agent/task/20260913_2331_rolling-normalization-redesign/`。
- [2026-09-14] E0–E2 训练+评估完成（见上表）；E3–E5 后台进行中。