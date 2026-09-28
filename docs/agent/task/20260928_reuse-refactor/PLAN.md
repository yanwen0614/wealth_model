# 20260928_reuse-refactor Implementation Plan

> Generated: 2026-09-28 14:00
> Task Dir: docs/agent/task/20260928_reuse-refactor/

## Goal

整体 review 优化重构：在零行为变更前提下消除重复实现、拆解 God Object、冻结旧回测世界，使后续模型/特征/回测开发可复用、入口可发现、回归可拦截。

## Architecture

三层收敛策略：P0 用“守卫 + 归档 + 口径冻结”先把 5 个回测世界收成 1 个生产路径（adapter）并锁死旧引擎默认不可达；P1 把 4 处 hash / 3 处 transform_code / 3+2 处 preprocessing 装配收敛为 `data/identity.py`、`data/transform_kernel.py`、`training/preprocessing.py` 三个单事实源，config 侧统一 BINS→CENTERS 派生与 fee 常量；P2 把 1179 行 `dataset.py` 与双 Trainer（441+464 行）拆分为 reader/cs_mkt/cached_dataset 与统一 Trainer，`train_retail.py` 缩为 thin wrapper，checkpoint 补全续训字段。P3 以 ruff/pytest/CI、dev 合并、logs 轮转、各包 facade 收尾，全程保留兼容 re-export，验收靠 `--smoke` + 数值一致性断言。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 旧 engine 处置 | 保留文件 + 真守卫 + `__init__` 停导（opt-in 经 `CNN_ALLOW_LEGACY=1`） | 直接删除 `engine.py` | 历史结果/文档可追溯；删除会导致旧报告链断裂，守卫模式已有 `legacy.py` 先例 |
| h10_rolling + wf_xgb 去向 | 移 `scripts/frozen/` 归档，生产代码禁 import | 删除或留在原地加 README 警告 | 冻结可复现但默认不可达；删则丢复现证据，留原地则持续被误复用 |
| hash 收敛点 | 新建 `data/identity.py`（canonical JSON + sha256） | 以 `feature_cache.py` 或 `scaler.py` 任一现实现为准 | 四处语义微差（scaler identity vs cache key vs rolling state），新建中立模块避免偏向某调用方 |
| transform 收敛点 | 新建 `data/transform_kernel.py` 纯函数内核，三 scaler 只做统计量装配 | 在 `scaler.py` 内统一 | rolling 侧已 import scaler（`rolling_scaler.py:12`），反向合入会成循环依赖；纯函数内核无依赖最稳 |
| preprocessing 收敛点 | 新建 `training/preprocessing.py`（含 eval scaler 解析） | 只合 train/train_retail，不管 eval | eval 侧 `EvalPreprocessing` + 双 resolve 函数是同类重复的主要复发源，必须一次收完 |
| CENTERS 口径 | 以 `config/defaults.py` BINS 派生 CENTERS，删 eval 硬编码 ±0.255 | 以 eval 侧 ±0.255 为准 | BINS ±0.38 是训练标签事实源；CENTERS 必须与其一致，否则 exp_ret 谱系断裂 |
| Trainer 统一方向 | 以 `training/trainer.py` 为基统一，RetailTrainer 能力并入（calibrate/metrics_csv 可选分支） | 以 RetailTrainer 为基 | 主链路（52 类 + EMD + factory）调用面最广，动它风险最大；零售为派生需求 |
| checkpoint 格式 | `best_model.pth` 改存 dict `{model, optimizer, scheduler, epoch, config}` + 兼容裸 state_dict 加载 | 另存 `resume.pth` 双文件 | 单文件最不易漂移；加载侧 `map_location` + 缺键兼容即可覆盖旧 ckpt |
| dev 依赖 | 保留 `dependency-groups dev`，删除 `optional-dependencies dev` | 反向保留 | `uv` 原生走 dependency-groups；optional-dev 是历史残留 |

## Impact

| 模块 | 文件 | 操作(create/modify) | 风险等级 |
|------|------|--------------------|----------|
| backtest | `backtest/__init__.py` | modify | medium |
| backtest | `backtest/engine.py` | modify | medium |
| backtest | `scripts/frozen/*`（自 h10_rolling + wf_xgb_cs 移入） | move | low |
| config | `config/defaults.py`, `config/__init__.py` | modify | medium |
| data | `data/identity.py` | create | low |
| data | `data/transform_kernel.py` | create | medium |
| data | `data/scaler.py`, `data/rolling_scaler.py`, `data/feature_cache.py`, `data/dataset.py`, `data/schema.py` | modify/split | high |
| training | `training/preprocessing.py` | create | medium |
| training | `training/trainer.py`, `training/retail_trainer.py`, `training/factory.py` | modify | high |
| root | `train.py`, `train_retail.py` | modify | high |
| log | `log_manager/__init__.py` | modify | low |
| docs | `AGENTS.md`, `README.md`, `README_TRAINING_CHAIN.md` | modify | low |
| 工程 | `pyproject.toml`, `tests/*`, 各包 `__init__.py` | modify | low |

## Task Decomposition

### T01: backtest __init__ 停导旧 engine
- **文件**: `backtest/__init__.py` (modify, ~30行)
- **描述**: 只重导出 `cnn_adapter` + backtest-core 门面；旧 engine 符号全部下掉，内部引用改直引 `backtest.engine`（需 opt-in）。
- **依赖**: 无
- **预估行数**: ~30
- **验收标准**: `rg "from backtest import (run_backtest|commission)"` 生产代码零命中；`--smoke` 通过；adapter 回测数值不变
- **风险因子**: 通配导入方漏改；需全仓 grep 调用点

### T02: engine 加 guard 真守卫
- **文件**: `backtest/engine.py` (modify, ~20行), `backtest/legacy.py` (modify, ~10行)
- **描述**: `run_backtest/run_backtest_target` 入口首行调 `guard_legacy_disabled(caller)`；`OLD_LOGIC=True` 保留；deprecated docstring 补 opt-in 说明。
- **依赖**: T01
- **预估行数**: ~30
- **验收标准**: 默认 env 下调旧 engine raise `LegacyBacktestDisabledError`；`CNN_ALLOW_LEGACY=1` 时旧行为逐 bit 一致
- **风险因子**: 有调用方吞异常；守卫必须放参数校验之前

### T03: h10_rolling + wf_xgb_cs 移 frozen
- **文件**: `scripts/h10_rolling/*` + `scripts/wf_xgb_cs.py` → `scripts/frozen/*` (move), 引用点 (modify, ~20行)
- **描述**: `git mv` 迁移 8 文件；加 `scripts/frozen/README.md`（冻结声明+复现命令）；修正残留引用与文档链接。
- **依赖**: 无
- **预估行数**: 移动 + ~40
- **验收标准**: `rg "h10_rolling|wf_xgb" --glob '!frozen' --glob '!docs/archive'` 生产代码零命中；frozen 内脚本仍可手动执行
- **风险因子**: 外部文档/脚本硬编码路径；用 grep 全仓扫

### T04: AGENTS/README 口径修正
- **文件**: `AGENTS.md`, `README.md`, `README_TRAINING_CHAIN.md` (modify, ~60行)
- **描述**: README 的 F69 默认描述改为 F53（F69 仅 cs_rank 开启时）；NORMALIZE 默认值对齐 `config/defaults.py`（relative）；补 frozen 归档与 adapter 唯一入口声明。
- **依赖**: T03
- **预估行数**: ~60
- **验收标准**: 文档 F/BINS/H10/入口描述与代码实现逐项一致；无新 F69 默认表述残留
- **风险因子**: 纯文档，低风险；注意 archive 历史文档不改（只改现行三件）

### T05: LoggerManager 防碰撞 + config.json 原子写
- **文件**: `log_manager/__init__.py` (modify, ~40行), `train.py:358,377` 双写收敛 (modify, ~20行)
- **描述**: 同秒 `run_*` 目录碰撞时递增后缀（`run_xxx_01`）；config.json 经 tmp + `os.replace` 原子发布；train 侧单次写（含 featurenum 回填）。
- **依赖**: 无
- **预估行数**: ~60
- **验收标准**: 同秒启动两次得不同目录；kill -9 压测无半写 config.json；`Trainer` 仍由 `run_log_dir` 注入
- **风险因子**: Windows `os.replace` 语义；`_configure_logging` 清 root handler 副作用保留不变

### T06: data/identity.py 统一 hash
- **文件**: `data/identity.py` (create, ~80行)；`data/feature_cache.py`, `data/dataset.py`, `data/scaler.py`, `data/rolling_scaler.py` (modify, 各~15行)
- **描述**: 唯一 `canonical_hash(payload)`（json sort_keys + sha256 hex）；四处调用点替换，digest 逐位一致（单测锁定）。
- **依赖**: T04（口径冻结后收敛，避免 digest 语义漂移）
- **预估行数**: +80 / -60
- **验收标准**: 旧 digest 向量单测全过（scaler identity / cache key / rolling state）；`CACHE_FORMAT_VERSION` 语义不变
- **风险因子**: 某处 canonical 化细节（float/None 编码）不一致 → 先加对照单测再替换

### T07: transform_kernel 统一 COLUMN_RULES 路由 + clip + mask
- **文件**: `data/transform_kernel.py` (create, ~120行)；`data/scaler.py`, `data/rolling_scaler.py` (modify, 各~40行删减)
- **描述**: 纯函数 `apply_column_rule(raw, finite, rule)` + `append_shared_mask(out, observed)`；三处 `transform_code` 只保留统计量装配（relative/P-robust/rolling），逐元素语义委托 kernel。
- **依赖**: T06
- **预估行数**: +120 / -80
- **验收标准**: `test_scaler_column_rules` + rolling nonscope 单测全过；asinh scale（amihud 1e12）/ clip（P ±5 / N [0,1] / G fixed）/ mask OR 语义数值一致
- **风险因子**: kernel 不得 import scaler/rolling（防循环依赖）；缺失先填 0 顺序保留

### T08: training/preprocessing.py 统一装配 + eval 解析
- **文件**: `training/preprocessing.py` (create, ~130行)；`train.py:52`, `train_retail.py:88`, `scripts/multi_seed_train.py:31` (modify)；`scripts/eval_bins_mapping.py`, `scripts/run_eval_pipeline.py` scaler 解析 (modify)
- **描述**: 唯一 `configure_preprocessing(config, normalize, scope)` + `resolve_eval_scaler_path/run_cfg`；eval 侧 `EvalPreprocessing` 收敛到同一解析；rolling 产物路径隔离规则集中。
- **依赖**: T04
- **预估行数**: +130 / -90
- **验收标准**: 三入口 `--normalize/--rolling_scope` 矩阵行为一致；eval 两脚本同 ckpt 得同 scaler；`test_train_metadata` 全过
- **风险因子**: multi_seed 默认 scope 语义（历史 e4 残留）需显式对齐，禁静默默认

### T09: config 统一键名 / parquet / BINS / CENTERS / fee
- **文件**: `config/defaults.py`, `config/__init__.py` (modify, ~50行)；`scripts/eval_bins_mapping.py:38`, `scripts/run_eval_pipeline.py:87` (modify, ~10行)
- **描述**: `CENTERS = bins_to_centers(BINS)` 派生函数，删 eval 硬编码 ±0.255；fee 常量集中（生产口径），旧 engine 冻结值不动；键名大小写混用（`model` vs `CNNTransformerConfig`）立约不改值。
- **依赖**: T08
- **预估行数**: ~60
- **验收标准**: `len(BINS)+1 == num_classes == len(CENTERS)` 断言；同 ckpt 的 eval exp_ret 与历史逐 bit 一致（CENTERS 修正后允许一次可解释漂移，需报告）
- **风险因子**: CENTERS ±0.255→±0.38 派生会改变历史 eval 数值 → 属口径修复，必须在报告中显式声明漂移

### T10: preds 4 字段 + OHLC parquet 直读统一
- **文件**: `backtest/cnn_adapter/predictions.py`, `market.py`, `cache.py` (modify, ~80行)；`scripts/build_ohlc_path.py`, `run_eval_pipeline.py:312`, `eval_bins_mapping.py` (modify, ~40行)
- **描述**: preds 缓存契约锁 4 字段 `{exp_ret,true_ret,dates,codes}`，读写两侧走 `data/schema.py:129 validate_prediction_cache_*`；OHLC 统一经 adapter market 直读 parquet，`build_ohlc_path` 转调或删除。
- **依赖**: T09
- **预估行数**: ~120
- **验收标准**: 双脚本产出 preds 互相可读；adapter 回测输入校验拒绝缺字段；ohlc 行数/日期与 parquet 一致
- **风险因子**: 历史 npz 缺 true_ret 需兼容读（缺键默认 None + warning，不静默补零）

### T11: dataset.py 拆 reader / cs_mkt / cached_dataset
- **文件**: `data/reader.py`, `data/cs_mkt.py`, `data/cached_dataset.py` (create, ~300行迁移)；`data/dataset.py` (modify, 缩至 <400 行兼容层)
- **描述**: `_load_and_prepare` → reader；`_compute_cross_sectional_rank/_compute_market_factors` → cs_mkt；cache key/hit/save → cached_dataset；`dataset.py` 只留 `ParquetDataConfig/_RollingDatasetState/ParquetDataset` 门面 re-export。
- **依赖**: T06, T07（identity + kernel 先稳）
- **预估行数**: 迁移 ~300 / 本体 -700（净负，单任务改动面 <150 行有效增量，迁移行不计新逻辑）
- **验收标准**: `python -m data.dataset --max_codes 10` 标签分布一致；cache 命中/未命中双路径单测过；warmup 不作标签日语义不变
- **风险因子**: God Object 拆分最大风险点；必须零逻辑改动（纯移动），每步 `--smoke` 验证

### T12: Trainer 统一 RetailTrainer
- **文件**: `training/trainer.py` (modify, ~100行)；`training/retail_trainer.py` (modify, 删至 re-export 或删除)；`training/factory.py` (modify, ~30行)
- **描述**: 以 Trainer 为基，吸入零售能力（二分类 calibrate_threshold / metrics_csv / binarize_labels 可选分支）；工厂 `_build_retail_*` 分支收敛为 `mode` 参数。
- **依赖**: T08（preprocessing 先统一，Trainer 只关心 loader/criterion 接口）
- **预估行数**: ~130（净负）
- **验收标准**: 主链路 52 类 + 零售二分类双 smoke 通过；calibrate 阈值报告数值一致；`forward [B,F,T]->[B,num_classes]` 断言
- **风险因子**: validate_epoch 返回类型分歧（tuple vs dict）→ 统一为 dict + 兼容解包，调用方同步改

### T13: train_retail 缩成 thin wrapper
- **文件**: `train_retail.py` (modify, 322→<120行)；`train.py` (modify, ~30行，导出可复用 parse/build/main 片段)
- **描述**: retail 只保留模型/损失装配差异，其余 parse_args/configure/cache/dataloader/checkpoint 全调 `train.py` 或 preprocessing 公共函数。
- **依赖**: T08, T12
- **预估行数**: -200（删减为主）
- **验收标准**: `train_retail.py --smoke` 与重构前逐 epoch loss 一致；`--help` CLI 兼容（参数不消失）
- **风险因子**: 零售 history/final_metrics/inference_config.json 落盘差异需保留，不可吞

### T14: checkpoint 存 optimizer / scheduler / epoch / config
- **文件**: `training/trainer.py:56`, `retail_trainer.py:83`, `train.py:446`, `train_retail.py` (modify, ~80行)
- **描述**: best ckpt 存 dict `{model, optimizer, scheduler, epoch, config}`；加载兼容裸 state_dict 旧 ckpt（`map_location` + 缺键分支）；early_stopping.path 语义对齐。
- **依赖**: T12
- **预估行数**: ~80
- **验收标准**: 中断后续训 epoch 计数/ scheduler 状态连续；旧 ckpt 仍可加载评估
- **风险因子**: `torch.load(weights_only=?)` 版本语义；config 需可 json 序列化（沿 train.py:266 约束）

### T15: ruff 规则 + 全仓告警清零
- **文件**: `pyproject.toml [tool.ruff]` (modify, ~20行)；全仓违规文件 (modify, ~80行)
- **描述**: 锁定 select/ignore（含既有 `DTZ005/TRY004` noqa 约定）；`ruff check .` 清零；AGENTS 补静态检查命令。
- **依赖**: T13（代码定型后再锁规则，避免反复）
- **预估行数**: ~100
- **验收标准**: `ruff check .` 零告警；`py_compile` 全过
- **风险因子**: 规则收紧误伤历史 noqa；只加不删 noqa

### T16: pytest / coverage / CI 最小闭环
- **文件**: `tests/*` (modify/add, ~80行)；`.github/workflows/*` 或等效 CI (create, ~30行)
- **描述**: 最小门：identity/kernel/preprocessing/dataset-cache 单测 + `--smoke`；coverage 下限（建议 50% 起步）；CI 跑 ruff + pytest。
- **依赖**: T06, T07, T08（单测对象先收敛）
- **预估行数**: ~110
- **验收标准**: CI 绿；无测试套件→有最小套件（AGENTS “无测试套件”表述同步更新）
- **风险因子**: 受限环境 num_workers/ CUDA；CI 用 `--num_workers 0` + cpu

### T17: pyproject dev 合并
- **文件**: `pyproject.toml` (modify, ~15行)
- **描述**: 删除 `optional-dependencies dev`，唯一保留 `dependency-groups dev`；校验 `uv sync --offline` 可用。
- **依赖**: 无
- **预估行数**: ~15
- **验收标准**: `uv sync --offline` 通过；torch cu130/cu126 平台切分与 `amazingdata/tgw` 路径不变
- **风险因子**: 有文档引用 `pip install .[dev]` → 同步改为 `uv sync --group dev`

### T18: logs 轮转 + scaler 入库策略
- **文件**: `log_manager/__init__.py` (modify, ~30行)；`.gitignore` (modify, ~10行)；相关文档 (modify)
- **描述**: run 目录保留数/体积上限 + 最老删除（运行期不删当次）；`logs/scaler_per_code.pkl` 与 `logs/KEEP/baseline` 入库边界立约（沿 2026-09-27 冻结结论）。
- **依赖**: T05
- **预估行数**: ~40
- **验收标准**: 轮转 dry-run 正确；`git status` 不出现大文件误入库；冒烟产物归位 KEEP
- **风险因子**: 误删有效 KEEP；删除前列清单 + 用户确认（blocked 点，见下）

### T19: 各包 __init__ facade
- **文件**: `data/__init__.py`, `training/__init__.py`, `models/__init__.py`, `criterion/__init__.py`, `config/__init__.py`, `log_manager/__init__.py`, `backtest/__init__.py` (modify, 各~10行)
- **描述**: 只做重导出（新模块 + 兼容符号）；禁在 `__init__` 放逻辑；循环 import 检查。
- **依赖**: T06, T07, T08, T11, T12（被导出符号先稳定）
- **预估行数**: ~70
- **验收标准**: `python -c "import data, training, config, backtest"` 全过；无循环 import；旧 `from data.dataset import X` 仍可用
- **风险因子**: facade 层遮蔽真实定义位置；文档注明 canonical 位置

## 需主编排器裁决的 blocked 点（本规划不擅自决定）

1. CENTERS 修正漂移（T09）：eval 历史数值允许一次可解释漂移？默认允许，需在报告声明。
2. logs 轮转删除（T18）：264 项量级历史产物删除前是否再打包？默认只删超限 run 目录，KEEP 永不自动删。
3. `retail_trainer.py` 最终形态（T12）：删文件 vs 留 re-export 兼容层？默认留 re-export（零外部断裂）。
