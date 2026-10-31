# AGENTS.md

> relative 分组归一化为默认链路（`train.py` 唯一入口，`NORMALIZE=relative` 见 `config/defaults.py:24`）。旧 NPZ/inference/grouped 已在 `e69a47b` 删除。

## Commands

```bash
# 环境（离线可用，依赖复刻 quant，要求 3.12）
uv sync --offline
uv run --project . python -c "import torch, pyarrow; print(torch.cuda.is_available())"

# 冒烟（20股1epoch，num_workers 0 在受限环境更稳）
uv run --project . python train.py --smoke --num_workers 0
# 数据集探查（不训练，默认 relative；per_code/rolling 需显式 opt-in）
uv run --project . python -m data.dataset --max_codes 10 --normalize relative
uv run --project . python -m data.dataset --max_codes 20

# 数据缓存（train.py 默认开启）：关闭 / 重建新 generation / 指定根
uv run --project . python train.py --smoke --num_workers 0 --no_cache
uv run --project . python train.py --smoke --num_workers 0 --rebuild_cache
uv run --project . python train.py --smoke --num_workers 0 --cache_dir D:/tmp/cnn_cache

# 归一化模式 / 列子集 / featurenum（默认 relative E0；per_code E1 / rolling E2–E5 需显式 opt-in）
uv run --project . python train.py --normalize relative --rolling_scope e0 --num_workers 0
uv run --project . python train.py --normalize rolling --rolling_scope e5 --num_workers 0
uv run --project . python train.py --feature_cols open high low close ma_5 --featurenum 5 --num_workers 0
# 缓存单测（feature_cache + dataset 接入 + 配置默认）
uv run --project . python -m unittest tests.unit.data.test_feature_cache tests.unit.data.test_dataset_cache tests.unit.config.test_config_defaults
# 最小门（T16，CI 同款选择；本地无 pytest 时用 unittest 同路径替代，需 --num_workers 0 + CPU）
uv run --project . python -m unittest tests.unit.test_ci_gate tests.unit.data.test_identity tests.unit.data.test_transform_kernel tests.unit.training.test_training_preprocessing tests.unit.data.test_dataset_cache
# 全量单测（无需任何环境变量；当前 1013 项 = 2F/10E/40S，均为已知非引擎缺陷，见「Gotchas」）
uv run --project . python -m unittest discover -s tests -t . -q

# 全量/分段
uv run --project . python train.py --epochs 50 --batch_size 256 --num_workers 4
uv run --project . python train.py --train_start 2013-01-01 --train_end 2025-06-30 --val_start 2025-07-01 --val_end 2025-12-31

# 静态检查（T15 锁定：ruff 窄名单 select，research/goal 与 scripts/frozen 为只读快照已 exclude，零告警口径）
uv run --project . python -m compileall -q data training backtest config scripts models criterion log_manager tests train.py train_retail.py
uv run ruff check .   # 零告警；规则见 pyproject.toml [tool.ruff.lint] select/ignore（DTZ005/TRY004/BLE001 系既有 noqa 约定，只加不删）
```

## Architecture

- `train.py:23` 唯一训练入口。`data/dataset.py:57` + `data/scaler.py:30` 数据；`models/cnn_transformer/model.py:66` 模型；`training/trainer.py:24` 训练；`criterion/emd_loss.py` 损失。
- 最小测试套件 + CI（T16）：`tests/unit/test_ci_gate.py` + identity/kernel/preprocessing/dataset-cache 四套件（全 Mock/mini parquet，不读大文件），`.github/workflows/ci.yml` 跑 ruff + pytest + coverage（下限 50%，收敛三模块），CPU + `--num_workers 0`；`--smoke`（需本地 parquet）仍为训练链路验收。
- `pyproject.toml:55` 定义 `torch` 按平台切 `cu130(win)/cu126(linux)`，`amazingdata/tgw` 指向 `../quant/wheels/*.whl` — 删除或改路径会使 `uv sync` 失败。
- `data/test/train_data/*.parquet` 与 `logs/` 被 `.gitignore:5,7` 忽略（3.5G 大文件不入库）。

## Data Contract

- 单 parquet `data/test/train_data/train_data_v1_*.parquet` 11.4M行×58列 5166股，10基础+48因子。`is_trading=False` 的行 OHLC/因子=NaN 必须 `dataset.py:160` 过滤。
- 当前默认特征为 **52 个 raw feature（`P18+R16+N12+G6`）+ 1 个共享 `g9_observed_mask` + 16 个 `cs_*` 截面 rank 列 + 11 个 `mkt_*` 市场因子列 = `F=80`**，列序 `[P→R→N→G→mask→cs→mkt]`（`data/schema.py` `FEATURE_GROUPS`/`APPROVED_RAW_FEATURES`/`DEFAULT_CS_RANK_FEATURES`/`DEFAULT_MKT_FACTOR_FEATURES`）。`F=53`（旧默认无 cs/mkt）、`F=69`（51+18 mask）、`F=45`（39+6 mask）均为**历史** schema。`--no-cs_rank --no-mkt-factors` 回到 `F=53`。
- 标签 `dataset.py:309` `future_ret[t]=open[t+1+horizon]/open[t+1]-1`（horizon=10），`np.digitize(BINS)` 52类，`BINS=linspace(-0.38,0.38,51)` `config/defaults.py:15`。窗口 `[s,s+60)` 取末日 `y`。
- 窗口 warmup（评估/验证）：`start_date` 之前最多 `seq_len-1`（rolling 非训练 251）条历史行以 `_transform_context=True` 保留，**可进入窗口作 warmup 输入，但绝不作为标签日**（`valid_starts` 过滤 `is_context[s+seq_len-1]`）；评估区间标签日覆盖 = 交易日数 − `(horizon+1)`（2026-01-01~08-31 由 95 → ≈154）。`data/feature_cache.py` `CACHE_FORMAT_VERSION=v3_relative_groups`（旧 `v2_context_warmup` 为历史）使旧语义缓存失效；训练集 start≈数据起点，窗口不变。勿与归一化统计预热混淆。

## Normalization — 三策略（relative/per_code/rolling）+ 列语义分组 P/R/N/G

- 列分组 `data/schema.py` `FEATURE_GROUPS{P:18,R:16,N:12,G:6}`，`APPROVED_RAW_FEATURES`=**52**（`close` 解禁进 P）；输出恒追加 1 个共享 `g9_observed_mask`（OR 18 个 G9 列 finite）+ 16 `cs_*` + 11 `mkt_*` → **`F=80`**（新默认 2026-10-24）。默认 `NORMALIZE=relative`（`config/defaults.py:24`），`per_code`/`rolling` 需显式 `--normalize` opt-in。旧 `F=53` 默认对应 `--no-cs_rank --no-mkt-factors`。
- 变换规则由 `data/scaler.py` `COLUMN_RULES` 集中注册：P `x/close[t-1]-1`(+robust)+`clip±5`；R `clip(asinh(x·scale),±5)`（`amihud` `scale=1e12`）；N `clip[0,1]`；G `fixed_clip`（E0–E4）/ rolling winsor（E5）。`column_rule`/`column_group` 对未知列 raise。
- 三模式：`relative`（E0，默认，`RelativeScaler` 无状态/无 fit，P 仅 relative+clip）；`per_code`（E1，`PerCodeGroupedScaler` P 组静态 per-code robust，`fit` 仅训练集，`save/load` `logs/scaler_per_code.pkl`）；`rolling`（E2–E5，`RollingNormalizer` 252 滚动 robust/winsor）。`none` 仅供明确实验；验证/评估复用训练 scaler/state，未见 code 回退 `global_stats`，切勿重 fit。
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
- 全量单测无需任何环境变量即达真基线 2F/10E/40S：2F 为 `test_prefix_attestor`/`test_prefix_ledger_verifier` 的 pin 不符（**故意保留，禁止修绿**），10E 归因 plotly 缺失 / Windows 文件锁 / `train.py` KeyError 'CNNTransformerConfig' / `RelativeScaler.identity_hash` / trainer / retail-config 滞后。legacy 守卫（`backtest.legacy.guard_legacy_disabled`）由 `test_engine_legacy_guard.py` 独立断言，跑全量即覆盖。
- 回测测试分层：`test_engine.py` 已退役为索引文件（无测试）；实际覆盖在 `test_metrics_and_benchmark.py`（费率算术/指标 parity/指数基准）、`test_cnn_adapter_rolling_semantics.py`（rolling top_n 等权）、`test_cnn_adapter_target_semantics.py`（target 滞后带/门槛/现金比）、`test_cnn_adapter_regression.py`（新引擎单侧基线）。
- 详规见 `docs/per_code_normalization_spec.md`（P/R/N/G 分组与 `ColumnRule` 决策表，正文含历史 G1~G9 说明）与项目记忆 `.opencode/memory/MEMORY.md`。
- 预测目标与树模型收口（2026-10）见 `docs/prediction_target_and_tree_2026.md`：信号是 α（截面相对）、截面目标只提 IC 不提 top-N 绝对收益、早停应用 RankIC、择时样本外无效、树模型排序领先主模型但不直接转产。

## Archive（2026-09-27 冻结，与 origin/main 合流 a8866a7 后整理）

- `logs/` 下仅 `logs/KEEP/` 有效（scaler/bins/baseline/训练证据），其余 264 项已打包 `D:/tmp/cnn_trash_20260927.tar.gz` 并清空，编目见 `docs/archive/logs_manifest.csv`。T18 轮转立约：仅超限顶层 `run_*` 可删（保留数默认 10/体积默认 2GiB，`collect_rotation_plan` dry-run 先列清单，`prune_old_runs(dry_run=False)` 才删；`KEEP/` 与当次运行目录永不自动删）；`logs/scaler*.pkl` 运行期产物一律忽略不入库，仅 `logs/KEEP/baseline/` 入库，冒烟 `run_*` 默认忽略、需留存手动归位 `KEEP/baseline/`。
- 回测唯一入口 `backtest/cnn_adapter/*`（`585a533` 确立），`backtest/legacy.py` 为历史；`../backtest-core` 为本地 editable 依赖。
- `scripts/frozen/*` 为冻结归档（自 `scripts/h10_rolling/*` + `scripts/wf_xgb_cs.py` 经 `git mv` 迁入，READ ONLY）：生产代码禁 import，复现命令见 `scripts/frozen/README.md`。
- `paper_jkx/` 2026-09-28 起源码入库（`logs/` 产物仍忽略），结论见 `docs/archive/paper_jkx_2024-2026_seven_routes.md`；主链路冻结A见 `docs/archive/main_2015-2026_prereg_A.md`。
- 2026-01~08 属烧掉样本，新规则不得用其验收；干净考试只认 2026-09 后新数据。
