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
- 默认特征 `dataset.py:91` 自动剔除：`return_1d/5d/10d/20d`(G2)、`TOT_SHARE`、`volume/amount`、`close`、`pe/pb/pcf/ps`(G6)、`revenue_growth*4`(G7) → 45维（39+6 mask）。
- 标签 `dataset.py:309` `future_ret[t]=close[t+5]/close[t]-1` horizon=5，`np.digitize(BINS)` 52类，`BINS=linspace(-0.25,0.25,51)` `train.py:34`。窗口 `[s,s+60)` 取末日 `y`。

## Normalization — Per-Code Only

- `ParquetDataConfig.normalize` 仅 `per_code|none` `dataset.py:75`（`grouped/minmax_window/zscore` 已删除）。
- `PerCodeGroupedScaler` `data/scaler.py` 按 code 独立算：G1/`macd` 用 `feature/prev_close-1` + robust `(x-median)/ (IQR/1.349)` + `clip±5`；G3/G4 `winsor 1/99`+clip；G8 透传；G9 截面 rank后 `fill0+mask+clip[0,1]` 不做 per-code。
- `fit` 仅训练集，`save/load` `logs/scaler_per_code.pkl`；验证集 `dataset.py:525` 传入 `scaler_stats` 复用，未见 code 回退全局统计。切勿在验证集重 `fit`。

## Model & Training

- `ModelConfig` `models/cnn_transformer/config.py:1` 默认 `featurenum=10,seq=20` 仅占位，`train.py:58` 覆盖为 `featurenum=45,seq=60,num_classes=52,d_model=256,nhead=8,layers=4,kernels[1,3,5,7,10]`，并 `206` 按实际特征数自动校正。
- `Trainer` `training/trainer.py:284` 依赖 `config["run_log_dir"]`（由 `LoggerManager` 创建），早停 `early_stopping.py` 要求预先 `os.makedirs`。
- `.python-version:1` 锁定 3.12；`training/early_stopping.py:27` 用 `np.inf`（`np.Inf` 在 numpy2 已移除）；`ReduceLROnPlateau` 无 `verbose` 参数。

## Gotchas

- `data/dataset.py:82` `bins` 用 `field(default_factory=...)` — 直接写 `list` 会在 3.12 报 mutable default。
- `logs/`、`*.parquet`、`*.pth` 不入库，`history` 在 `.opencode/memory/`（被 `.gitignore:15` 忽略）。
- 详规见 `docs/per_code_normalization_spec.md`（G1~G9 决策表）与项目记忆 `.opencode/memory/MEMORY.md`。
