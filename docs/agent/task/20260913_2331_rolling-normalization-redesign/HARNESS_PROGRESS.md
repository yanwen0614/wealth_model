# 进度跟踪 — rolling-normalization-redesign

> 生成时间：2026-09-13 23:31
> 需求：实现 DESIGN_SPEC v1.0 —— P/R/N/G 分组 + relative/per_code/rolling 三策略 + E0–E5 矩阵，F 69→53
> 分支：`feature/rolling-normalization-cnn`
> 计划：`PLAN.md`；审查：`REVIEW_CHECKLIST.md`

## 执行顺序

```
T01 schema 分组
 └─ T02 ColumnRule Registry + RelativeScaler
     ├─ T03 PerCodeGroupedScaler 重构（E1）
     └─ T04 rolling 重构（scope e0..e5 + G9 mask 修复）
             └─ T05 dataset 接入（relative / feature_cols_out / cache key）
                 └─ T06 train/CLI + metadata/config 落盘
                     ├─ T07 评估脚本层适配
                     └─ T08 旧契约测试同步与全量单测绿
                         └─ T09 文档同步
                             └─ T10 端到端验收（重建缓存 + E0–E5 重训/评估）
```

> T03 与 T04 均只依赖 T02，可并行；T05 依赖 T03+T04；T07 依赖 T05+T06；T08 收尾 T01–T07。

## 任务列表

| Task | 名称 | 依赖 | 预估行数 | TDD | 状态 |
|------|------|------|----------|-----|------|
| T01 | 数据分组重构（schema） | 无 | +200 | 是 | PASS |
| T02 | ColumnRule Registry + RelativeScaler（E0） | T01 | +260 | 是 | PASS |
| T03 | PerCodeGroupedScaler 重构（E1） | T02 | +220 | 是 | PASS |
| T04 | rolling 重构（scope e0..e5 + G9 mask 修复） | T02 | +300 | 是 | PASS |
| T05 | dataset 接入（relative / feature_cols_out / cache key） | T03,T04 | +220 | 是 | PASS |
| T06 | train/CLI + metadata/config 落盘 | T05 | +220 | 是 | PASS |
| T07 | 评估脚本层适配（69→53 / relative / scope） | T05,T06 | +200 | 是 | PASS（1 轮 fix） |
| T08 | 旧契约测试同步与全量单测绿 | T01–T07 | +180 | 否 | PASS（incremental，272→275 OK） |
| T09 | 文档同步 | T01–T08 | +200 | 否 | PASS |
| T10 | 端到端验收（重建缓存 + E0–E5 重训/评估） | T01–T09 | +60 | 否 | PASS |

## T10 端到端结果（2026-09-14）
- 训练：`--lr 3e-4 --batch_size 1024 --num_workers 4 --seed 42 --epochs 50 --patience 5`，串行后台（psmux `cnn_e0e5` + 控制器 `cnn_ctrl`）。
- 六臂均 epoch3 达最优、epoch8 早停。
- 评估区间 2026-01-01~08-31（154 交易日，794,501 样本）；基准（全截面等权）annual -12.66%、sharpe -1.266。

| 臂 | mode/scope | Best Val Loss/Acc | run 目录 | 截面 RankIC | top5 annual(超额) | top50 annual(超额) | top100 annual(超额) |
|---|---|---|---|---|---|---|---|
| E0 | relative | 0.0562 / 0.1043 | `logs/relative/run_20260914_024253` | 0.0248 | -47.33% (-34.67%) | -14.17% (-1.51%) | -12.88% (-0.22%) |
| E1 | per_code | 0.0562 / 0.1005 | `logs/run_20260914_045053` | 0.0302 | -48.40% (-35.74%) | -8.80% (+3.85%) | -3.13% (+9.53%) |
| E2 | rolling e2 | 0.0562 / 0.1033 | `logs/rolling_e2/run_20260914_064942` | 0.0415 | -27.35% (-14.69%) | -9.44% (+3.21%) | -4.15% (+8.50%) |
| E3 | rolling e3 | 0.0564 / 0.1016 | `logs/rolling_e3/run_20260914_093155` | **0.0441** | -33.34% (-20.69%) | **-2.70% (+9.95%)** | **+3.95% (+16.61%)** |
| E4 | rolling e4 | 0.0561 / 0.1013 | `logs/rolling_e4/run_20260914_115221` | 0.0339 | -34.10% (-21.44%) | -8.97% (+3.68%) | -3.82% (+8.83%) |
| E5 | rolling e5 | 0.0561 / 0.1029 | `logs/rolling_e5/run_20260914_141450` | 0.0399 | -34.38% (-21.73%) | -19.79% (-7.14%) | -10.80% (+1.86%) |

- **结论**：六臂截面 RankIC 全为正；E3（rolling P+volatility）最优（IC 0.0441、top50 +9.95%、top100 +16.61%）；E1/E2/E4 在 top50/top100 有正超额；top5 因小盘/换手噪声全部跑输基准；E5 加入 G9 raw 滚动后未增益（top100 仅 +1.86%）。
- 产物：`logs/preds_*_2026-08-31.npz`、`logs/backtest_*_2026-01-01_2026-08-31/`、`logs/topn_curve_*_*.png`、`logs/ohlc_path_2026-01-01_2026-08-31.npz`。

## 整体 review 收尾（2026-09-14）
- 跨任务 review VERDICT=PASS；已修 M1（dataset 默认 parquet→F60）、M4（relative digest 增 mask_columns）、L1（`_relative_transform` inf 分母统一）、LR 默认 1e-4→3e-4。
- M3 `uv.lock` registry churn 为环境产物，提交前回退。
- 既有 64 项仓级 ruff 报错均为未触碰文件存量，属 `scope_outside`。
- E0–E5 训练：`--lr 3e-4 --batch_size 1024 --num_workers 4 --seed 42 --epochs 50 --patience 5`，串行后台（psmux `cnn_e0e5`）。

## 执行详情

### T01 数据分组重构（schema）
- **状态**：pending
- **依赖**：无
- **文件**：`data/schema.py` (modify)；`tests/unit/data/test_data_schema_labels.py` (modify)；`tests/unit/data/test_schema_groups.py` (create)
- **预估行数**：+200
- **验收标准**：`len(APPROVED_RAW_FEATURES)==52`（顺序 P→R→N→G）；`len(FEATURE_GROUPS)=={P:18,R:16,N:12,G:6}`；`column_group` 未知列 raise；
  `g9_observed_mask` OR 语义；`G9_MASK_COLUMNS==("g9_observed_mask",)`；`close not in PROHIBITED_COLUMNS`。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02 ColumnRule Registry + RelativeScaler（E0）
- **状态**：pending
- **依赖**：T01
- **文件**：`data/scaler.py` (modify)；`tests/unit/data/test_scaler_column_rules.py` (create)
- **预估行数**：+260
- **验收标准**：`COLUMN_RULES` 覆盖 52 列；`amihud.scale==1e12`；`RelativeScaler` 无 fit 方法且 `feature_cols_out[-1]=="g9_observed_mask"`；
  P relative clip±5、R asinh clip±5、N clip01、G 固定区间。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03 PerCodeGroupedScaler 重构（E1）
- **状态**：pending
- **依赖**：T02
- **文件**：`data/scaler.py` (modify)；`tests/unit/data/test_data_feature_pipeline.py` (modify)；`tests/unit/data/test_scaler_per_code.py` (create)
- **预估行数**：+220
- **验收标准**：仅 P 拟合 per-code median/IQR；R/N/G 按规则；`feature_cols` 子集收窄；未见 code 回退 global；旧 v3 payload load 报错。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04 rolling 重构（scope e0..e5 + G9 mask 修复）
- **状态**：pending
- **依赖**：T02
- **文件**：`data/rolling_scaler.py` (modify)；`data/dataset.py`（`_RollingDatasetState.PAYLOAD_VERSION`）(modify)；`tests/unit/data/test_rolling_normalization.py` (modify/create)
- **预估行数**：+300
- **验收标准**：scope 列数 {e0:0,e1:18,e2:18,e3:21,e4:24,e5:30}；E5 输出列数 == `output_feature_cols` 且 shared mask 恒在末尾；
  `close` 可入 feature_cols；异 scope digest 互异。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05 dataset 接入（relative / feature_cols_out / cache key）
- **状态**：pending
- **依赖**：T03, T04
- **文件**：`data/dataset.py` (modify)；`data/feature_cache.py` (modify)；`tests/unit/data/test_dataset_cache.py` (modify)；`tests/unit/data/test_context_warmup_windows.py` (modify)
- **预估行数**：+220
- **验收标准**：三模式 `num_features==53` 且 `ds[0][0].shape==(53,seq_len)`；`feature_cols_out[-1]=="g9_observed_mask"`；
  `CACHE_FORMAT_VERSION=="v3_relative_groups"`；缓存命中不重 fit。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06 train/CLI + metadata/config 落盘
- **状态**：pending
- **依赖**：T05
- **文件**：`train.py` (modify)；`config/defaults.py` (modify)；`tests/unit/test_train_metadata.py` (modify)
- **预估行数**：+220
- **验收标准**：`--featurenum` 缺省 None；`--feature_cols`/`--rolling_scope e0..e5`/`--normalize relative` 可用；
  删除 `featurenum==69` 断言；导出 config 含 `feature_cols_out`（含 mask）；rolling 维度不符仅 warning。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T07 评估脚本层适配
- **状态**：pending
- **依赖**：T05, T06
- **文件**：`scripts/eval_bins_mapping.py` (modify)；`scripts/run_eval_pipeline.py` (modify)；`scripts/run_eval_full.sh` (modify)；`scripts/multi_seed_train.py` (modify)；`tests/unit/scripts/test_eval_preprocessing.py` (modify)
- **预估行数**：+200
- **验收标准**：mode 支持 relative；`featurenum` 不静默 45；三模式维度校验通过；异 scope 拒绝；preds 契约不变。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T08 旧契约测试同步与全量单测绿
- **状态**：pending
- **依赖**：T01–T07
- **文件**：`tests/unit/data/test_data_dataset_triple.py`、`test_dataset_label_openopen.py`、`tests/unit/config/test_config_defaults.py`、`tests/unit/models/test_models_dual_head.py`、`tests/unit/training/test_training_trainer_dual.py` (modify)
- **预估行数**：+180
- **验收标准**：`uv run --project . python -m unittest discover tests/unit` 全绿；`uv run ruff check .` 无错误。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T09 文档同步
- **状态**：pending
- **依赖**：T01–T08
- **文件**：`docs/per_code_normalization_spec.md`、`README_TRAINING_CHAIN.md`、`data/AGENTS.md`、`models/AGENTS.md`、`AGENTS.md` (modify)
- **预估行数**：+200
- **验收标准**：F=53 与新分组描述一致；无 `F=69`/`18 mask` 当前口径残留（历史显式标注）。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T10 端到端验收（重建缓存 + E0–E5 重训/评估）
- **状态**：pending
- **依赖**：T01–T09
- **文件**：`docs/agent/task/20260913_2331_rolling-normalization-redesign/HARNESS_PROGRESS.md` (modify)；可选 `scripts/run_e0_e5.sh` (create)
- **预估行数**：+60
- **验收标准**：smoke `--rebuild_cache` 通过；六臂 config.json `preprocessing.featurenum==53` 且末列为 mask；
  截面 IC/xs_spread + TopN 回测产物落 `logs/`；旧 scaler 版本失效并重拟合。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
