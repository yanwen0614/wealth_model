# 20260912_1943_rolling-e2e3-subset Implementation Plan

> Generated: 2026-09-12 19:43
> Task Dir: docs/agent/task/20260912_1943_rolling-e2e3-subset/
> Branch: feature/rolling-normalization-cnn

## Goal

为 frozen-vs-rolling 对照 E1–E4 提供代码先行支持：新增 rolling
子集开关（E2=10列 / E3=13列 / E4=16列全量），E1 与 E4 默认行为冻结。

## Architecture

- `RollingNormalizationConfig` 新增 `scope: e2|e3|e4`（默认 e4），
  scope 进入 `transform_config_digest` / `schema_manifest` /
  `_RollingDatasetState` identity，异 scope 互用报错。
- `train.py` 新增 `--rolling_scope`（默认 e4）与 `--seed`；
  `SCALER_PATH` / `LOG_DIR` 按 scope 隔离；per_code 路径零改动。
- `ParquetDataConfig` 透传 scope；`RollingNormalizer.transform_code`
  按 scope 切分子集，其余列走既有 passthrough 分支（不断言 frozen 值）。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 子集表达 | config 字段 `scope` + 预设列组 | CLI 直接传列名 / 改 ROLLING_FEATURES | digest/identity 可哈希、CLI 简单、防拼写漂移 |
| 默认值 | scope 默认 e4 = 现有 16 列全量 | 默认 e2 | E4 回归零风险，`--normalize rolling` 行为冻结 |
| 非子集列 | 复用既有 passthrough 分支 | 抛错/填零 | 与 issue §3 口径一致，不断言 frozen 值 |
| seed | train.py 新增 `--seed` + `set_all_seeds` | 复用 multi_seed_train | E1–E4 必须同一种子，train.py 现无 seed（已核查） |
| 隔离 | LOG_DIR/scaler 按 scope 分目录 + 加载拒异 scope | 混用同一目录 | checkpoint/state/digest 互用报错（issue §5 约束1/3） |

## Impact

| 模块 | 文件 | 操作 | 风险 |
|------|------|------|------|
| data | data/rolling_scaler.py | modify | high（digest/identity 核心） |
| data | data/dataset.py | modify | high（state save/load/validate） |
| training入口 | train.py | modify | high（CLI/seed/隔离） |
| config | config/defaults.py | modify | low（默认 NORMALIZE 不动，加 ROLLING_SCOPE 可选） |
| eval | scripts/run_eval_pipeline.py, scripts/run_eval_full.sh | modify/docs | low（scope 透传+取数说明） |
| per_code | data/scaler.py | none | -（零改动，E1 冻结） |

## Task Decomposition

### T01: rolling scope 配置与 digest 隔离
- **文件**: `data/rolling_scaler.py` (modify)
- **描述**: `RollingNormalizationConfig` 加 `scope: str="e4"`（校验
  e2/e3/e4）；新增 `ROLLING_SCOPE_FEATURES` 预设（e2=9 G1+macd=10列；
  e3=e2+3 G3=13列；e4=全量16列）；`transform_config_digest` /
  `schema_manifest` 纳入 scope+子集列；`transform_code` 按 scope
  判定 rolling 列，其余走既有 passthrough/G9 分支。
- **依赖**: 无
- **预估行数**: +45 / ~8
- **need_test**: 是（TDD 先行：digest 互异、manifest 含 scope、非法 scope 报错）
- **验收标准**: e2/e3/e4 digest 两两不同；默认构造 = e4 digest 与现行为一致；
  `output_feature_cols` 仍 F=69（51 raw+18 mask）；forward `[B,69,60]->[B,52]` 不变。
- **风险因子**: 忘记把 scope 纳入任一 digest 即隔离失效；ROLLING_FEATURES 不得改默认值语义。

### T02: dataset scope 透传与 state 隔离
- **文件**: `data/dataset.py` (modify)
- **描述**: `ParquetDataConfig` 加 `rolling_scope: str="e4"`；
  rolling 分支用 scope 构造 `RollingNormalizer`；`_RollingDatasetState`
  save/load/validate 全量校验 scope+digest+identity，异 scope 抛错；
  validation 仍复用训练 state（含 251 context），不得重 fit。
- **依赖**: T01
- **预估行数**: +35 / ~10
- **need_test**: 是（TDD：异 scope state validate/load 报错；同 scope 复用通过）
- **验收标准**: e2 state 用于 e3/e4 数据集抛 `ValueError`；`num_features=69`；
  `--max_codes 10 --normalize rolling` 各 scope 出数且 audit 有 fallback_ratio。
- **风险因子**: 前视（context 进 labels/windows/index）；验证集误 fit；close 入模型列。

### T03: train.py CLI、seed 与产物隔离
- **文件**: `train.py` (modify), `config/defaults.py` (modify)
- **描述**: 新增 `--rolling_scope {e2,e3,e4}`（默认 e4）与 `--seed int`
  （默认如 42）；`set_all_seeds`（random/numpy/torch/cuda，参考
  scripts/multi_seed_train.py:29）；`configure_preprocessing` 按 scope 隔离
  `SCALER_PATH=logs/rolling_{scope}/scaler_rolling_{scope}.pkl`、
  `LOG_DIR=./logs/rolling_{scope}`；非 rolling 时忽略 scope；
  checkpoint/state 加载拒异 scope；`config.json` 记录 preprocessing+scope+seed。
- **依赖**: T01, T02
- **预估行数**: +55 / ~10
- **need_test**: 是（TDD：默认 e4 路径 = 现有行为；异 scope checkpoint 拒绝；seed 可复现）
- **验收标准**: 无 scope 的 `--normalize rolling` 路径/行为与现分支一致；
  `--seed` 两次 smoke 的 loss 逐轮一致；config.json 含 scope/seed/digest/identity。
- **风险因子**: 改动 LOG_DIR/SCALER_PATH 默认值破坏 E4 回归；seed 只设 torch 漏 random。

### T04: 评估取数与实验文档线
- **文件**: `scripts/run_eval_pipeline.py` (modify), `scripts/run_eval_full.sh` (docs/modify),
  `docs/per_code_normalization_spec.md` §5.1 (docs，可选)
- **描述**: eval 从 `run_log_dir/config.json: preprocessing` 读 scope/digest/
  identity/`rolling_audit`（fallback 比例、winsor/constant_iqr/missing 统计）；
  `run_eval_full.sh` 支持按 scope 传入 checkpoint；PLAN 附 E1–E4 四组命令。
- **依赖**: T03
- **预估行数**: +25 / ~5（不含文档）
- **need_test**: 是（eval_bins_mapping 用既有缓存 codes 重建，缺 codes 报错见 data/schema.py:64）
- **验收标准**: 给定 run_dir 能输出 IC/ICIR、top-bottom、换手成本后收益、
  fallback 比例、winsor 统计五项；口径 T 日决策→T+1 open 买→T+6 open 卖。
- **风险因子**: 评估误用异 scope scaler；preds 缓存缺 exp_ret/true_ret/dates/codes。

## 执行顺序与依赖

T01 → T02 → T03 → T04，串行；TDD 每任务先补单测再实现。
全文件每批写入 ≤100 行；ruff line-length 120；`--smoke --num_workers 0` 验证。

## E1–E4 训练命令（EPOCHS=50/PATIENCE=10/BATCH=256，GTX 970M 3GB）

> 必须 tmux 后台串行 + `sleep N && <观察命令>` 链式跟踪，禁止并行训练。
> 全量 4 组在该卡上预计耗时久（单组数小时～十余小时），先 smoke 再全量。

```bash
# E1 frozen 基线（不动）
uv run --project . python train.py --normalize per_code --seed 42 --epochs 50 --batch_size 256 --num_workers 0
# E2 rolling G1+macd=10列
uv run --project . python train.py --normalize rolling --rolling_scope e2 --seed 42 --epochs 50 --batch_size 256 --num_workers 0
# E3 = E2+G3=13列
uv run --project . python train.py --normalize rolling --rolling_scope e3 --seed 42 --epochs 50 --batch_size 256 --num_workers 0
# E4 全量16列（默认，与无 scope 一致）
uv run --project . python train.py --normalize rolling --rolling_scope e4 --seed 42 --epochs 50 --batch_size 256 --num_workers 0
# smoke 矩阵（每组先跑）
uv run --project . python train.py --smoke --num_workers 0 --normalize rolling --rolling_scope e2 --seed 42
```

## 评估命令

```bash
bash scripts/run_eval_full.sh logs/rolling_e2/<run>/best_model.pth 2026-01-01 2026-08-31
bash scripts/run_eval_full.sh logs/rolling_e3/<run>/best_model.pth 2026-01-01 2026-08-31
bash scripts/run_eval_full.sh logs/rolling_e4/<run>/best_model.pth 2026-01-01 2026-08-31
# rolling_audit 取数：<run_log_dir>/config.json -> preprocessing.rolling_audit
# preds 缓存须含 exp_ret/true_ret/dates/codes；缺 codes 用 eval_bins_mapping 重建
```
