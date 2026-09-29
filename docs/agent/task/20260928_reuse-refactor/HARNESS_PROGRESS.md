# 进度跟踪 — 20260928_reuse-refactor（已完成并归档，commit aa3e867）

> 生成时间：2026-09-28 14:00
> 需求：整体 review 优化重构（Phase0 立规矩 / Phase1 收敛重复 / Phase2 解 God Object / Phase3 工程 hygiene），零行为变更
> 执行顺序：T01 → T02 → T03 → T04 → T05 → T06 → T07 → T08 → T09 → T10 → T11 → T12 → T13 → T14 → T15 → T16 → T17 → T18 → T19

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | backtest __init__ 停导旧 engine | pending | - | P0 规矩 |
| T02 | engine 真守卫 | pending | - | 依赖 T01 |
| T03 | h10_rolling + wf_xgb 移 frozen | pending | - | P0 归档 |
| T04 | AGENTS/README 口径修正 | pending | - | 依赖 T03 |
| T05 | LoggerManager 防碰撞 + 原子写 | pending | - | P0 |
| T06 | data/identity.py 统一 hash | pending | - | 依赖 T04；P1 |
| T07 | transform_kernel 统一路由 | pending | - | 依赖 T06；P1 |
| T08 | preprocessing 统一装配 | pending | - | 依赖 T04；P1 |
| T09 | config 统一 BINS/CENTERS/fee | pending | - | 依赖 T08；CENTERS 漂移需声明 |
| T10 | preds 4 字段 + OHLC 统一 | pending | - | 依赖 T09；P1 |
| T11 | dataset 拆 reader/cs_mkt/cached | pending | - | 依赖 T06+T07；P2 最大风险 |
| T12 | Trainer 统一 RetailTrainer | pending | - | 依赖 T08；P2 |
| T13 | train_retail thin wrapper | pending | - | 依赖 T08+T12；P2 |
| T14 | checkpoint 续训字段 | pending | - | 依赖 T12；P2 |
| T15 | ruff 规则清零 | pending | - | 依赖 T13；P3 |
| T16 | pytest/coverage/CI 最小 | pending | - | 依赖 T06+T07+T08；P3 |
| T17 | pyproject dev 合并 | pending | - | P3 独立可并行 |
| T18 | logs 轮转 + scaler 入库 | pending | - | 依赖 T05；删前确认 |
| T19 | 各包 __init__ facade | pending | - | 依赖 T06+T07+T08+T11+T12；P3 收尾 |

## 执行详情

### T01: backtest __init__ 停导旧 engine
- **状态**：pending
- **依赖**：无
- **文件**：
  - `backtest/__init__.py` (modify, ~30)
- **预估行数**：~30
- **验收标准**：生产代码零旧 engine 引用；adapter 回测数值不变；`--smoke` 通过
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: engine 真守卫
- **状态**：pending
- **依赖**：T01
- **文件**：
  - `backtest/engine.py` (modify, ~20)
  - `backtest/legacy.py` (modify, ~10)
- **预估行数**：~30
- **验收标准**：默认 raise `LegacyBacktestDisabledError`；opt-in 逐 bit 一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: h10_rolling + wf_xgb 移 frozen
- **状态**：pending
- **依赖**：无
- **文件**：
  - `scripts/h10_rolling/*` + `scripts/wf_xgb_cs.py` → `scripts/frozen/*` (move)
  - `scripts/frozen/README.md` (create)
- **预估行数**：移动 + ~40
- **验收标准**：生产代码零 frozen 外引用；frozen 可手动复现
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: AGENTS/README 口径修正
- **状态**：pending
- **依赖**：T03
- **文件**：
  - `AGENTS.md` (modify)
  - `README.md` (modify)
  - `README_TRAINING_CHAIN.md` (modify)
- **预估行数**：~60
- **验收标准**：F53/BINS/H10/唯一入口与代码一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: LoggerManager 防碰撞 + 原子写
- **状态**：pending
- **依赖**：无
- **文件**：
  - `log_manager/__init__.py` (modify, ~40)
  - `train.py` (modify, ~20)
- **预估行数**：~60
- **验收标准**：同秒启动不碰撞；无半写 config.json
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06: data/identity.py 统一 hash
- **状态**：pending
- **依赖**：T04
- **文件**：
  - `data/identity.py` (create, ~80)
  - `data/feature_cache.py` / `data/dataset.py` / `data/scaler.py` / `data/rolling_scaler.py` (modify)
- **预估行数**：+80 / -60
- **验收标准**：旧 digest 向量单测全过；缓存语义不变
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T07: transform_kernel 统一路由
- **状态**：pending
- **依赖**：T06
- **文件**：
  - `data/transform_kernel.py` (create, ~120)
  - `data/scaler.py` / `data/rolling_scaler.py` (modify)
- **预估行数**：+120 / -80
- **验收标准**：column_rules + rolling nonscope 单测全过；`[B,53,60]->[B,52]` 断言
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T08: preprocessing 统一装配
- **状态**：pending
- **依赖**：T04
- **文件**：
  - `training/preprocessing.py` (create, ~130)
  - `train.py` / `train_retail.py` / `scripts/multi_seed_train.py` / eval 双脚本 (modify)
- **预估行数**：+130 / -90
- **验收标准**：三入口矩阵一致；`test_train_metadata` 全过
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T09: config 统一 BINS/CENTERS/fee
- **状态**：pending
- **依赖**：T08
- **文件**：
  - `config/defaults.py` / `config/__init__.py` (modify, ~50)
  - `scripts/eval_bins_mapping.py` / `scripts/run_eval_pipeline.py` (modify, ~10)
- **预估行数**：~60
- **验收标准**：`len(BINS)+1==num_classes==len(CENTERS)`；漂移可解释声明
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T10: preds 4 字段 + OHLC 统一
- **状态**：pending
- **依赖**：T09
- **文件**：
  - `backtest/cnn_adapter/predictions.py` / `market.py` / `cache.py` (modify, ~80)
  - `scripts/build_ohlc_path.py` / eval 双脚本 (modify, ~40)
- **预估行数**：~120
- **验收标准**：双脚本 preds 互读；缺字段拒绝；OHLC 与 parquet 一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T11: dataset 拆 reader/cs_mkt/cached
- **状态**：pending
- **依赖**：T06, T07
- **文件**：
  - `data/reader.py` / `data/cs_mkt.py` / `data/cached_dataset.py` (create)
  - `data/dataset.py` (modify, 缩至 <400 行兼容层)
- **预估行数**：迁移 ~300（零逻辑改动）
- **验收标准**：`python -m data.dataset --max_codes 10` 一致；warmup 语义不变
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T12: Trainer 统一 RetailTrainer
- **状态**：pending
- **依赖**：T08
- **文件**：
  - `training/trainer.py` (modify, ~100)
  - `training/retail_trainer.py` (modify, re-export)
  - `training/factory.py` (modify, ~30)
- **预估行数**：~130（净负）
- **验收标准**：双 smoke 通过；calibrate 数值一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T13: train_retail thin wrapper
- **状态**：pending
- **依赖**：T08, T12
- **文件**：
  - `train_retail.py` (modify, 322→<120)
  - `train.py` (modify, ~30)
- **预估行数**：-200
- **验收标准**：loss 逐 epoch 一致；CLI 兼容
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T14: checkpoint 续训字段
- **状态**：pending
- **依赖**：T12
- **文件**：
  - `training/trainer.py` / `train.py` / `train_retail.py` (modify, ~80)
- **预估行数**：~80
- **验收标准**：断点续训连续；旧 ckpt 可加载评估
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T15: ruff 规则清零
- **状态**：pending
- **依赖**：T13
- **文件**：
  - `pyproject.toml` (modify, ~20)
  - 全仓违规文件 (modify, ~80)
- **预估行数**：~100
- **验收标准**：`ruff check .` 零告警
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T16: pytest/coverage/CI 最小
- **状态**：pending
- **依赖**：T06, T07, T08
- **文件**：
  - `tests/*` (modify/add, ~80)
  - CI workflow (create, ~30)
- **预估行数**：~110
- **验收标准**：CI 绿；AGENTS 测试表述同步更新
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T17: pyproject dev 合并
- **状态**：pending
- **依赖**：无（可并行）
- **文件**：
  - `pyproject.toml` (modify, ~15)
- **预估行数**：~15
- **验收标准**：`uv sync --offline` 通过；torch 平台切分不变
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T18: logs 轮转 + scaler 入库
- **状态**：pending
- **依赖**：T05
- **文件**：
  - `log_manager/__init__.py` (modify, ~30)
  - `.gitignore` (modify, ~10)
- **预估行数**：~40
- **验收标准**：轮转 dry-run 正确；无大文件误入库
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T19: 各包 __init__ facade
- **状态**：pending
- **依赖**：T06, T07, T08, T11, T12
- **文件**：
  - `data/training/models/criterion/config/log_manager/backtest __init__` (modify, ~70)
- **预估行数**：~70
- **验收标准**：包导入全过；旧导入路径兼容；无循环 import
- **Quality Gate 结果**：-
- **修复轮次**：0/2
