# 整理项目代码实施计划

> Generated: 2026-09-06
> Task Dir: `docs/agent/task/20260906_整理项目代码/`
> 范围：阶段 6 收口；基于阶段 1-5 的当前改动补测试、清理和验证，不提交

## Goal

按阶段 1 到阶段 6 整理当前 CNN 训练、数据、评估和回测工程，消除文档与实现漂移及重复构建逻辑，固定当前数据输入、标签、归一化和模型输入输出契约。

## 当前事实与主要风险

- 实际唯一训练入口是 `train.py`；`scripts/multi_seed_train.py` 复制了配置、数据集、模型、损失、优化器和 Trainer 构建逻辑。
- `data/dataset.py` 约 523 行，混合 parquet 读取、过滤、时间切分、特征推导、future return、离散标签、scaler、窗口索引和 DataLoader。
- `train.py` 和 README/历史文档存在 45/48/55 维、close-close/open-open、per-code/global z-score、scaler 文件名等冲突。
- `CNNTransformer.forward` 当前返回 `(logits, ret_pred)`；旧模型 checkpoint 兼容逻辑已按用户决定不保留，历史权重不可与当前模型直接混用。
- `scripts/eval_bins_mapping.py`、`scripts/run_backtest.py`、`scripts/build_ohlc_path.py` 共同消费 `preds.npz`/OHLC npz；旧缓存缺 `codes` 或使用旧标签口径时不可混用。

## 不可改变的契约

1. 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序，禁止恢复旧 NPZ 主链路。
2. 默认 per-code 特征口径以 `docs/per_code_normalization_spec.md` 为事实源：有效特征 39，加 6 个 G9 mask，模型默认输入 `F=45`；显式 `use_factor_only`/`feature_cols` 的行为需保留并在文档中区分，不能把 48 因子列数误写成模型 F。
3. `seq_len=60`；训练标签使用当前实现的 open-open：`open[t+1+horizon]/open[t+1]-1`，默认 `horizon=5`；`BINS=linspace(-0.25,0.25,51)`，类别数 52，窗口标签取末日。
4. scaler 只在训练集 fit，验证集复用训练集统计；持久化版本 `v2_per_code` 和 `logs/scaler_per_code.pkl` 需兼容读取，禁止验证集重新 fit。
5. 模型配置至少保留 `featurenum/seq_len/num_classes` 及 CNN/Transformer 字段；训练实际需校验 `F=dataset.num_features`、`T=60`、`C=52`。
6. EMDLoss 保持 `(logits[B,52], labels[B]) -> scalar`；Dual/PureReg 的四参路径需继续被 Trainer 正确识别。
7. 当前模型只验证双头输出 shape；旧模型 checkpoint 不在当前支持范围，历史权重须重新训练或显式转换后再使用。
8. 回测使用 T 日决策、T+1 open 买入、T+6 open 卖出及双边成本；preds 必须带 `exp_ret/true_ret/dates/codes`，OHLC npz 键契约不可静默改变。

## Architecture

先建立单一配置对象和可复用的训练构建入口，由 `train.py` 与多 seed 脚本共同调用；再把 `dataset.py` 拆成职责清晰的数据读取/特征契约/标签与窗口/归一化适配层，但保留外部 `ParquetDataConfig` 和 `ParquetDataset` 兼容 facade。Trainer 只负责批处理、验证、早停、调度和结果产物，评估/回测脚本复用模型构建、数据加载和预测缓存契约。

六个阶段按依赖串行执行：契约统一是所有代码重构前置；共享配置依赖契约；数据拆分依赖配置接口；Trainer 整理依赖数据和构建接口；评估回测依赖稳定 checkpoint/prediction schema；测试与清理最后执行。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|---|---|---|---|
| 配置事实源 | 新增共享配置/构建模块，保留 CLI 覆盖 | 继续复制两套 dict | 避免训练与多 seed 漂移 |
| 数据 facade | 保留 `ParquetDataConfig`、`ParquetDataset` 外部名称 | 一次性改所有调用方 | 降低 checkpoint/脚本迁移风险 |
| 模型输出 | 先固定双头 tuple 与单头兼容适配，再决定是否抽象统一输出对象 | 直接改成单 Tensor | 当前 Trainer、评估和损失已依赖双头 |
| 特征维度 | 以实际输出 F=45 为 per-code 默认；48 仅指原始因子列集合 | 继续混用 48/55 | 防止线性层输入和 scaler mask 错配 |
| scaler | 训练 fit、验证/推理 load；缺失正式评估直接失败 | 验证集自动 fit | 避免数据泄露和不可复现 |
| checkpoint | 仅维护当前双头模型的显式 schema/version | 保留旧键重映射 | 用户决定不保留旧模型兼容逻辑，历史权重不可与当前模型混用 |
| 评估/回测 | 预测缓存作为稳定边界，回测只消费 schema | 在脚本内重新推理/猜列 | 便于多模型、多 seed 和旧缓存隔离 |

## Impact

| 模块 | 文件 | 操作 | 风险 |
|---|---|---|---|
| 文档/契约 | `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、相关 `docs/*.md`、`scripts/README.md` | modify | high |
| 配置/构建 | `train.py`、`scripts/multi_seed_train.py`、拟新增共享配置/构建模块 | modify/create | high |
| data | `data/dataset.py`、`data/scaler.py`、拟新增 `data/*` 模块 | modify/create | high |
| models | `models/cnn_transformer/config.py`、`model.py`、`models/__init__.py` | modify | high |
| training | `training/trainer.py`、`training/metrics.py`、`training/early_stopping.py` | modify | high |
| criterion | `criterion/emd_loss.py`、`dual_loss.py`、`pure_reg_loss.py` | inspect/可能 modify | medium |
| 日志 | `log_manager/__init__.py` | modify/通常仅兼容 | medium |
| 评估回测 | `scripts/eval_bins_mapping.py`、`scripts/build_ohlc_path.py`、`scripts/run_backtest.py`、`scripts/plot_topn_curve.py`、`backtest/engine.py` | modify | high |
| 测试/清理 | `tests/unit/**`、过期文档/脚本引用 | create/modify/delete需逐项确认 | high |

## Task Decomposition

### T01：文档与契约统一（阶段 1）
- **文件**：`README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`scripts/README.md`、冲突的 `docs/*.md`（modify）
- **描述**：建立 45/48/55 术语表、open-open 标签公式、per-code scaler 和预测/OHLC npz schema；标注历史结果与当前口径，移除已删除模块的可执行指引。
- **依赖**：无；后续所有任务依赖 T01
- **预估行数**：+80/-80
- **验收标准**：全项目文档不再把默认模型 F 写成 55/48；命令均指向 `train.py`；契约明确 `F=45,T=60,C=52`、scaler 复用和 checkpoint 规则。
- **风险因子**：历史实验数字可能是旧 close-close 口径，不能未经标注改写成当前结果。

### T02：抽取共享配置和训练构建逻辑（阶段 2）
- **文件**：拟新增共享配置/工厂模块（create）；`train.py`、`scripts/multi_seed_train.py`、`models/__init__.py`、`models/cnn_transformer/config.py`（modify）
- **描述**：集中默认数据、模型、criterion、optimizer、scheduler、seed 与 CLI 覆盖；提供模型构建和损失构建，保留 `ModelConfig` 字段。
- **依赖**：T01
- **预估行数**：+180/-220
- **验收标准**：两入口共享同一配置来源；`CNNTransformer` 输入 `[B,45,60]` 输出当前 tuple（分类 logits `[B,52]`、回归 `[B]`）。
- **风险因子**：浅拷贝嵌套 dict、CLI 默认值、dual/pure-reg 分支和 `run_log_dir` 注入容易产生行为差异。

### T03：拆分数据模块（阶段 3）
- **文件**：`data/dataset.py`、`data/scaler.py`、拟新增 `data/reader.py`、`data/features.py`、`data/labels.py`、`data/window.py`（modify/create）
- **描述**：按读取过滤、特征选择、标签、per-code 变换、窗口索引和 DataLoader 拆责；保留 facade/API、时序切分及训练 scaler 到验证集的复用。
- **依赖**：T01、T02
- **预估行数**：+260/-300
- **验收标准**：真实 parquet 过滤合成行；默认输出 `x [45,60]`、`y∈[0,51]`、`y_ret`；open-open 与 horizon=5 对齐；`save/load` 后 transform 一致；验证集不 fit。
- **风险因子**：全表内存、code 未见回退、G9 mask 顺序、边界窗口和 DataLoader 多进程在 Windows 下的生命周期。

### T04：整理 Trainer（阶段 4）
- **文件**：`training/trainer.py`、`training/metrics.py`、`training/early_stopping.py`、`log_manager/__init__.py`（modify）
- **描述**：拆出 batch 解包、单/双头输出适配、loss 调用、epoch 统计、验证产物和 checkpoint 保存职责；统一空验证集、scheduler、异常和日志行为。
- **依赖**：T02、T03
- **预估行数**：+140/-180
- **验收标准**：EMD 两参、Dual/PureReg 四参均可训练；早停保存并加载最佳模型；`run_log_dir` 由 LoggerManager 预建；指标/混淆矩阵保持已有产物语义。
- **风险因子**：scheduler 类型判断、无验证集时访问 `val_losses`、异常吞掉和 checkpoint 加载设备。

### T05：整理实验评估回测脚本（阶段 5）
- **文件**：`scripts/eval_bins_mapping.py`、`scripts/multi_seed_train.py`、`scripts/build_ohlc_path.py`、`scripts/run_backtest.py`、`scripts/plot_topn_curve.py`、`backtest/engine.py`（modify）
- **描述**：统一预测缓存 schema、模型配置读取、scaler 必须 load、评估指标、OHLC 路径和回测参数；隔离旧缓存并修正文档中 close-close 旧脚本说明。
- **依赖**：T02、T03、T04
- **预估行数**：+180/-220
- **验收标准**：无 scaler 的正式评估明确失败；预测含 `exp_ret/true_ret/dates/codes`；回测按 T+1/T+6 open-open、成本和基准计算；多 seed 结果可被同一评估/回测消费。
- **风险因子**：checkpoint config 缺失、旧 npz 无 codes、`true_ret` 与交易收益混淆、截面日期对齐和空样本。

### T06：测试和工程清理（阶段 6）
- **文件**：`tests/unit/**`、`pyproject.toml`（必要时）、过期脚本/文档（逐项确认后 modify/delete）
- **描述**：补齐共享配置隔离、三种损失 factory、数据 schema/labels、模型 shape、评估缓存、Trainer 空数据和回测纯函数测试；清理死 import、过期引用与临时产物说明。
- **依赖**：T01-T05 全部通过
- **预估行数**：+300/-100
- **验收标准**：单测、ruff、pyright、数据探查和训练冒烟命令均有记录；不删除仍被真实 import 的文件；git diff 只包含计划范围。
- **风险因子**：当前已有测试覆盖有限，Windows worker 与 3.5G parquet 验证需分 smoke/full 层级。

## 验收命令

规划阶段不执行以下命令；编码阶段按阶段门禁执行：

```bash
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run pyright
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
uv run --project . python train.py --smoke --num_workers 0
```

高风险阶段已验证模型前向、评估缓存和回测 fixture；旧模型 checkpoint 不作兼容验证，全量 parquet 冒烟不得替代小型确定性单测。
