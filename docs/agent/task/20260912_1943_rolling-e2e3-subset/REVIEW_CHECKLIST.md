# 审查清单 — 20260912_1943_rolling-e2e3-subset

> 生成时间：2026-09-12 19:43

## 需求理解

frozen-vs-rolling 对照 E1–E4 代码先行：E1 frozen 不动；E2 rolling 10列
（G1 9列 +macd）；E3 13列（E2+G3）；E4 16列全量（=现有 rolling 默认）。
现状缺口：ROLLING_FEATURES 写死16列、无子集开关、无 scope 参数、seed 未知。
显式假设：F=69/seq=60/C=52 不变；透传列不断言 frozen 值；预算默认
EPOCHS=50/PATIENCE=10/BATCH=256；GPU 为 GTX 970M 3GB。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| data | data/rolling_scaler.py:39-40 | modify | ROLLING_FEATURES 加 scope 预设，digest/manifest 纳入 scope |
| data | data/dataset.py:45,77,329 | modify | ParquetDataConfig.rolling_scope；_RollingDatasetState 隔离 |
| 入口 | train.py:37,99 | modify | --rolling_scope/--seed；LOG_DIR/scaler 按 scope 隔离 |
| config | config/defaults.py:24,31 | modify | 默认 NORMALIZE 不动，加 ROLLING_SCOPE 默认 e4 |
| eval | scripts/run_eval_pipeline.py, run_eval_full.sh | modify | scope 透传；config.json 读 rolling_audit |
| frozen | data/scaler.py | none | per_code 零改动 |
| 模型 | models/cnn_transformer/config.py | none | featurenum=69/seq=60/C=52，forward [B,F,T]->[B,C] 不变 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 复用结论 |
|------------|---------|------|----------|
| ROLLING_FEATURES | 是 | data/rolling_scaler.py:40 | 复用常量切子集，不另起新表 |
| passthrough 分支 | 是 | data/rolling_scaler.py:215 | 非子集列直接复用，不断言 frozen |
| PerCodeGroupedScaler | 是 | data/scaler.py:30 | 复用为 rolling fallback，不改实现 |
| transform_config_digest | 是 | rolling_scaler.py:93/dataset.py | 扩展纳入 scope，不另起 digest 体系 |
| _RollingDatasetState | 是 | data/dataset.py:77 | 扩展 save/load/validate，不另起 state |
| set_all_seeds | 是 | scripts/multi_seed_train.py:29 | 搬入 train.py，不重复实现 |
| rolling_audit | 是 | data/dataset.py:365 | 直接从 config.json 取数，不另起统计 |
| eval_bins_mapping | 是 | scripts/eval_bins_mapping.py | 缺 codes 用其重建（见 data/schema.py:64） |
| seed in train.py | 否 | train.py 全文无 seed | T03 新增 --seed（缺口确认） |
| rolling_scope | 否 | 全项目无 | T01–T03 新增（缺口确认） |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 默认回归 | 无 scope rolling = E4 全量；per_code 零改动 | HIGH |
| 2 | identity 隔离 | scope 进 digest/manifest/state/checkpoint，异 scope 互用报错 | HIGH |
| 3 | 前视 | rolling 窗口右端=t；context 不进 labels/windows/index；val 用 251 context | HIGH |
| 4 | seed | random/numpy/torch/cuda 全设；同 seed smoke loss 逐轮一致 | HIGH |
| 5 | scope 隔离 | scaler_path/LOG_DIR 按 scope 分目录；eval 拒异 scope | HIGH |
| 6 | forward shape | [B,69,60]->[B,52]；close 不入模型列；F=69 断言 | HIGH |
| 7 | 规范 | ruff line-length 120；无通配符 import；异常不静默吞 | MEDIUM |
| 8 | 性能/串行 | tmux 后台串行 + sleep 链式跟踪；禁止并行训练；smoke 用 --num_workers 0 | MEDIUM |
