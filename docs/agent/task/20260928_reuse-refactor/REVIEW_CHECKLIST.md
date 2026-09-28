# 审查清单 — 20260928_reuse-refactor

> 生成时间：2026-09-28 14:00
> 需求：整体 review 优化重构，核心为后续开发可复用和方便（Phase0 立规矩 / Phase1 收敛重复 / Phase2 解 God Object / Phase3 工程 hygiene）
> 任务目录：`docs/agent/task/20260928_reuse-refactor/`

## 需求理解

- 本次为纯重构：零行为变更，所有验收以“数值逐 bit/容差一致 + `--smoke` 通过”为红线。
- 四个 Phase 按序执行：P0 先冻结口径与守卫（防回归），P1 收敛重复实现（单事实源），P2 拆 God Object（可测性），P3 工程 hygiene（CI/规范/轮转）。
- 显式假设（无需用户确认，按约束文件裁定）：
  - A1：`train.py` 唯一入口地位不变；`train_retail.py` 收缩为 thin wrapper，不删除文件（保留 CLI 兼容）。
  - A2：F53（52 raw P18/R16/N12/G6 + 1 shared mask）+ H10 + BINS `linspace(-0.38,0.38,51)` 为当前唯一默认口径；F69/F45 与 CENTERS `±0.255` 为历史/评估侧残留，收敛时以 defaults.py 为准。
  - A3：`backtest/cnn_adapter` 为唯一生产回测路径；`backtest/engine.py` 为 OLD_LOGIC 冻结逻辑，只加守卫不修口径。
  - A4：2026-01~08 为烧掉样本，不得用于新规则验收；冒烟验收用 `--smoke --num_workers 0`。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| backtest | `backtest/__init__.py` | modify | 停导旧 engine，只导出 adapter + core 门面 |
| backtest | `backtest/engine.py` (434行) | modify | 入口加 `guard_legacy_disabled` 真守卫（现有仅注释+`OLD_LOGIC=True` 标记） |
| backtest | `backtest/legacy.py` (46行) | modify | 守卫唯一事实源，保持 `CNN_ALLOW_LEGACY` opt-in |
| backtest | `backtest/cnn_adapter/*.py` | modify(轻) | predictions/market/cache 口径收敛对象 |
| scripts | `scripts/h10_rolling/*` (7文件) + `scripts/wf_xgb_cs.py` | move | 迁入 `scripts/frozen/`，更新引用与文档 |
| config | `config/defaults.py`, `config/__init__.py` | modify | 统一键名/parquet/BINS/CENTERS/fee 常量 |
| data | `data/dataset.py` (1179行) | split | 拆 reader/cs_mkt/cached_dataset，保留兼容层 |
| data | `data/identity.py` | create | 统一 hash（现有 4 处 sha256 各自实现） |
| data | `data/transform_kernel.py` | create | 统一 COLUMN_RULES 路由+clip+mask（transform_code x3） |
| data | `data/scaler.py`, `data/rolling_scaler.py`, `data/feature_cache.py`, `data/schema.py`, `data/labels.py` | modify | 收敛到新内核 |
| training | `training/preprocessing.py` | create | 统一 `configure_preprocessing` + eval scaler 解析 |
| training | `training/trainer.py` (441行), `training/retail_trainer.py` (464行), `training/factory.py` | modify | Trainer 统一 RetailTrainer，工厂去零售分支 |
| root | `train.py` (457行), `train_retail.py` (322行) | modify | retail 缩成 thin wrapper（~70% 重复） |
| log | `log_manager/__init__.py` (80行) | modify | 防碰撞（同秒 `run_*`）+ config.json 原子写 |
| checkpoint | `training/*` + `train*.py` | modify | 存 optimizer/scheduler/epoch/config（现仅 state_dict） |
| docs | `AGENTS.md`, `README.md`, `README_TRAINING_CHAIN.md` | modify | 口径修正（README 仍写 F69，AGENTS defaults 已 E0/relative） |
| 工程 | `pyproject.toml`, `tests/*`, 各包 `__init__.py` | modify | ruff/pytest/coverage/CI、dev 合并、facade |

## 重复检测（静态 grep 实测）

| 搜索关键词 | 是否存在 | 位置 | 收敛目标 |
|------------|---------|------|----------|
| hash/identity sha256 x4 | 是 | `data/feature_cache.py:17,59` / `data/dataset.py:27,161` / `data/scaler.py:17,57` / `data/rolling_scaler.py:4,88` | `data/identity.py` canonical-json + sha256 唯一实现 |
| transform_code x3 | 是 | `data/scaler.py:174,400` (PerCode+Relative) / `data/rolling_scaler.py:236` (+ `research/goal/data/vendor_scaler.py:228` 历史) | `data/transform_kernel.py` 统一路由/clip/mask |
| configure_preprocessing x3+2 | 是 | `train.py:52` / `train_retail.py:88` / `scripts/multi_seed_train.py:31` (+ eval 侧 `eval_bins_mapping.py:52 EvalPreprocessing` / `run_eval_pipeline.py:93,112`) | `training/preprocessing.py` 唯一装配 + eval 解析 |
| COLUMN_RULES 路由 | 是（已收敛半程） | `data/scaler.py:346` 定义；`rolling_scaler.py:12,200` 复用；`dataset.py:252,415` 摘要引用 | transform_kernel 承接非 scope 列变换 |
| 5 个回测世界 | 是 | `backtest/engine.py` OLD_LOGIC / `cnn_adapter/*` 生产 / `scripts/h10_rolling/engine_replica_core.py` 复制品 / `scripts/run_backtest.py` / `scripts/run_retail_backtest.py` | P0 守卫 + frozen 归档，adapter 唯一生产 |
| 双 preds schema | 是 | `run_eval_pipeline.py:312` 4 字段 `{exp_ret,true_ret,dates,codes}` vs `eval_bins_mapping.py:351` 多列表 + 各自 CENTERS | preds 4 字段契约 + `validate_prediction_cache_*` (schema.py:129 已有校验器，推广使用) |
| 双 OHLC 路径 | 是 | `scripts/build_ohlc_path.py` vs `cnn_adapter/market.py+cache.py` | OHLC parquet 直读统一到 adapter |
| CENTERS 漂移 | 是 | `config/defaults.py:15` BINS ±0.38 vs `run_eval_pipeline.py:87`/`eval_bins_mapping.py:38` CENTERS52 ±0.255 | 以 BINS 派生 CENTERS，删除硬编码 |
| fee 双口径 | 是 | engine 万2.5/万2.5(冻结) vs 实盘万2min5/万5/过户万1（见 engine docstring deprecated 声明） | 常量集中 `config`，旧值冻结不改 |
| config 双写 | 是 | `train.py:358` (LoggerManager 内) + `train.py:377` 重写 featurenum | 原子写 + 单次写 |
| dev 依赖双份 | 是 | `pyproject.toml:73` optional-dev vs `:107` dependency-groups dev 完全重复 | 合并为单一事实源 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | ruff（line-length 120）零告警；命名/日志/注释风格统一；无中文乱码路径 | HIGH |
| 2 | 模块边界 | data↔models↔training↔criterion↔backtest 无越层 import（scaler 不 import rolling/dataset；trainer 不建目录；engine 不读 parquet）；新增共享代码只进 `data/identity.py` / `transform_kernel.py` / `training/preprocessing.py` / `config` | HIGH |
| 3 | 数据安全 | 无硬编码凭证；parquet 路径经 config；`is_trading=False` 过滤与 `_transform_context` 不作标签日语义零变更 | HIGH |
| 4 | 导入合规 | 无通配符/未使用 import；`scripts/frozen/*` 不得被生产代码 import（仅文档/手动复现引用）；各包 `__init__` 只做 facade 重导出 | MEDIUM |
| 5 | 错误处理 | 守卫异常不静默吞掉（legacy 守卫 raise 可追踪 caller）；未知列 raise（column_rule 语义保留）；原子写失败不留半文件 | MEDIUM |
| 6 | 性能风险 | 无 O(N²) 全量扫描；parquet 全量加载路径不变；feature memmap 缓存 key 语义不变（默认关 cs/mkt 时逐字节不变）；模型参数量/显存无突增；`seq_len/featurenum` 维度错配只 warning→raise 收敛需显式说明 | MEDIUM |

## ModelConfig / forward 接口校验（每任务必跑）

- [ ] `featurenum` 以 `ParquetDataset.num_features == len(feature_cols_out)` 实测派生为权威（默认 53）；`--featurenum` 显式≠实测 raise；rolling 维度不符 warning 自动校正语义保留。
- [ ] 任意模型 `forward([B,F,T]) -> [B,num_classes]`（默认 `[B,53,60] -> [B,52]`）；dual/retail 双头返回 `(logits[, ret_pred])` 签名经 `training/factory.py` 兼容。
- [ ] `EMDLoss(num_classes=52, p=2, label_smoothing, smooth_eps=0.1)` 签名不变；`(logits[batch,52], labels[batch])` 与 Trainer 兼容。
- [ ] BINS 51 边界 → `np.digitize` 52 类 → CENTERS 52 中心链路一致（`len(BINS)+1 == num_classes == len(CENTERS)` 断言）。
- [ ] F53 列序 `[P→R→N→G→mask]` + `g9_observed_mask` OR 语义不变；scaler identity/scaler 版本变更必须 bump 并使旧缓存失效（可验证）。

## Phase 验收门（跨任务）

- P0：`CNN_ALLOW_LEGACY` 未置时旧 engine 路径全部 raise；`rg "from backtest.engine|from backtest import" --glob '!frozen' ` 零生产引用；`--smoke` 通过。
- P1：`rg "hashlib.sha256\(json.dumps.*sort_keys" ` 仅 `data/identity.py` 一处；`transform_code` 定义仅 kernel 一处；`configure_preprocessing` 定义仅 preprocessing 一处；eval 两脚本 scaler 解析走同一函数。
- P2：`data/dataset.py` 主文件 <400 行（兼容层 re-export）；`train_retail.py` <120 行；`torch.load(best_model.pth)` 恢复 optimizer/scheduler/epoch 可断点续训。
- P3：`ruff check .` 零告警；`pytest` 最小集通过；`pyproject` 单一 dev 源；`logs/` 新 run 不碰撞（同秒两次启动得不同目录），config.json 无半写文件。
