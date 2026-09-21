# AGENTS.md

> Per-code 分组归一化为主链路（`train.py` 唯一入口）。旧 NPZ/inference/grouped 已在 `e69a47b` 删除。

## Commands

```bash
# 环境（离线可用，依赖复刻 quant，要求 3.12）
uv sync --offline
uv run --project . python -c "import torch, pyarrow; print(torch.cuda.is_available())"

# 冒烟（20股1epoch，num_workers 0 在受限环境更稳）
uv run --project . python train.py --smoke --num_workers 0
# 数据集探查（不训练）
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
uv run --project . python -m data.dataset --max_codes 20

# 数据缓存（train.py 默认开启）：关闭 / 重建新 generation / 指定根
uv run --project . python train.py --smoke --num_workers 0 --no_cache
uv run --project . python train.py --smoke --num_workers 0 --rebuild_cache
uv run --project . python train.py --smoke --num_workers 0 --cache_dir D:/tmp/cnn_cache

# 归一化模式 / 列子集 / featurenum（relative E0 / per_code E1 / rolling E2–E5）
uv run --project . python train.py --normalize relative --rolling_scope e0 --num_workers 0
uv run --project . python train.py --normalize rolling --rolling_scope e5 --num_workers 0
uv run --project . python train.py --feature_cols open high low close ma_5 --featurenum 5 --num_workers 0
# 缓存单测（feature_cache + dataset 接入 + 配置默认）
uv run --project . python -m unittest tests.unit.data.test_feature_cache tests.unit.data.test_dataset_cache tests.unit.config.test_config_defaults

# 全量/分段
uv run --project . python train.py --epochs 50 --batch_size 256 --num_workers 4
uv run --project . python train.py --train_start 2013-01-01 --train_end 2025-06-30 --val_start 2025-07-01 --val_end 2025-12-31

# 静态检查
uv run --project . python -m py_compile data/dataset.py data/scaler.py train.py
uv run ruff check .   # line-length 120, pyproject.toml
```

## Architecture

- `train.py:23` 唯一训练入口。`data/dataset.py:57` + `data/scaler.py:30` 数据；`models/cnn_transformer/model.py:66` 模型；`training/trainer.py:24` 训练；`criterion/emd_loss.py` 损失。
- 无测试套件、无 CI，验证靠 `--smoke` + `python -m data.dataset`。
- `pyproject.toml:55` 定义 `torch` 按平台切 `cu130(win)/cu126(linux)`，`amazingdata/tgw` 指向 `../quant/wheels/*.whl` — 删除或改路径会使 `uv sync` 失败。
- `data/test/train_data/*.parquet` 与 `logs/` 被 `.gitignore:5,7` 忽略（3.5G 大文件不入库）。

## Data Contract

- 单 parquet `data/test/train_data/train_data_v1_*.parquet` 11.4M行×58列 5166股，10基础+48因子。`is_trading=False` 的行 OHLC/因子=NaN 必须 `dataset.py:160` 过滤。
- 当前默认特征为 **52 个 raw feature（`P18+R16+N12+G6`）+ 1 个共享 `g9_observed_mask`，输出 `F=53`**，列序 `[P→R→N→G→mask]`（`data/schema.py` `FEATURE_GROUPS`/`APPROVED_RAW_FEATURES`）。`close` 已解禁进 P 组（relative 分母 `close[t-1]`）。`F=69`（旧 51 raw + 18 逐列 mask）、`F=45`（39+6 mask）、`F=55` 均为**历史** schema，不代表当前默认输入。
- 标签 `dataset.py:309` `future_ret[t]=open[t+1+horizon]/open[t+1]-1`（horizon=10），`np.digitize(BINS)` 52类，`BINS=linspace(-0.38,0.38,51)` `config/defaults.py:15`。窗口 `[s,s+60)` 取末日 `y`。
- 窗口 warmup（评估/验证）：`start_date` 之前最多 `seq_len-1`（rolling 非训练 251）条历史行以 `_transform_context=True` 保留，**可进入窗口作 warmup 输入，但绝不作为标签日**（`valid_starts` 过滤 `is_context[s+seq_len-1]`）；评估区间标签日覆盖 = 交易日数 − `(horizon+1)`（2026-01-01~08-31 由 95 → ≈154）。`data/feature_cache.py` `CACHE_FORMAT_VERSION=v3_relative_groups`（旧 `v2_context_warmup` 为历史）使旧语义缓存失效；训练集 start≈数据起点，窗口不变。勿与归一化统计预热混淆。

## Normalization — 三策略（relative/per_code/rolling）+ 列语义分组 P/R/N/G

- 列分组 `data/schema.py` `FEATURE_GROUPS{P:18,R:16,N:12,G:6}`，`APPROVED_RAW_FEATURES`=**52**（`close` 解禁进 P）；输出恒追加 1 个共享 `g9_observed_mask`（OR 18 个 G9 列 finite）→ `F=53`。
- 变换规则由 `data/scaler.py` `COLUMN_RULES` 集中注册：P `x/close[t-1]-1`(+robust)+`clip±5`；R `clip(asinh(x·scale),±5)`（`amihud` `scale=1e12`）；N `clip[0,1]`；G `fixed_clip`（E0–E4）/ rolling winsor（E5）。`column_rule`/`column_group` 对未知列 raise。
- 三模式：`relative`（E0，`RelativeScaler` 无状态/无 fit，P 仅 relative+clip）；`per_code`（E1，`PerCodeGroupedScaler` P 组静态 per-code robust，`fit` 仅训练集，`save/load` `logs/scaler_per_code.pkl`）；`rolling`（E2–E5，`RollingNormalizer` 252 滚动 robust/winsor）。`none` 仅供明确实验；验证/评估复用训练 scaler/state，未见 code 回退 `global_stats`，切勿重 fit。
- rolling scope `e0..e5`（滚动列数 0/18/18/21/24/30，默认 `e5`）；`e1`/`e2` 列集同但语义异（per_code 静态 vs rolling 动态）。
- 版本：`SCALER_VERSION=v4_per_code`、`TRANSFORM_VERSION=per_code_transform_v4`、`CACHE_FORMAT_VERSION=v3_relative_groups`、`_RollingDatasetState.PAYLOAD_VERSION=v2_rolling_state` → 旧缓存/scaler 自动失效需重建。

## Model & Training

- `ModelConfig` `models/cnn_transformer/config.py:1` 默认值仅占位；`featurenum` 以 `ParquetDataset.num_features=len(feature_cols_out)` 实测派生为权威（当前默认 `featurenum=53,seq=60,num_classes=52,d_model=256,nhead=8,layers=4,kernels[1,3,5,7,10]`）；`train.py --featurenum` 缺省 None，显式≠实测 raise，rolling 维度不符仅 warning 自动校正。
- `Trainer` `training/trainer.py:284` 依赖 `config["run_log_dir"]`（由 `LoggerManager` 创建），早停 `early_stopping.py` 要求预先 `os.makedirs`。
- 训练默认超参：`AdamW(lr=3e-4, wd=1e-5)` + `EMDLoss` + `ReduceLROnPlateau`（`config/defaults.py:31`；E0–E5 矩阵统一 `--lr 3e-4`）。
- `.python-version:1` 锁定 3.12；`training/early_stopping.py:27` 用 `np.inf`（`np.Inf` 在 numpy2 已移除）；`ReduceLROnPlateau` 无 `verbose` 参数。

## Gotchas

- `data/dataset.py:82` `bins` 用 `field(default_factory=...)` — 直接写 `list` 会在 3.12 报 mutable default。
- `logs/`、`*.parquet`、`*.pth` 不入库，`history` 在 `.opencode/memory/`（被 `.gitignore:15` 忽略）。
- 详规见 `docs/per_code_normalization_spec.md`（P/R/N/G 分组与 `ColumnRule` 决策表，正文含历史 G1~G9 说明）与项目记忆 `.opencode/memory/MEMORY.md`。
