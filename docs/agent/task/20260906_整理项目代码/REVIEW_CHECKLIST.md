# 审查清单 — 整理项目代码

> 生成时间：2026-09-06
> 阶段 6 实际收口记录；仅测试、清理和验证，不提交

## 需求理解

用户要求按六阶段逐步整理当前 CNN 项目：

1. 文档与契约统一；
2. 抽取共享配置和训练构建逻辑；
3. 拆分数据模块；
4. 整理 Trainer；
5. 整理实验、评估、回测脚本；
6. 测试和工程清理。

显式决定：当前 per-code 主链路优先于旧 NPZ 链路；历史实验文档保留但仅作不可混用的历史口径；用户决定不保留旧模型 checkpoint 兼容逻辑。

## 影响范围与真实 import

| 模块 | 实际入口/调用 | 观察 |
|---|---|---|
| data | `train.py`、`scripts/eval_bins_mapping.py`、测试导入 `data.dataset` | `dataset.py` 同时负责读取、标签、scaler、窗口和 loader；`scaler.py` 是唯一 per-code 实现 |
| models | `train.py`、评估脚本导入 `models.cnn_transformer.*` | `models/__init__.py` 仅 package marker；不存在旧 `attention.py`/`cnn_lstm_attention.py` |
| training | `train.py`、`scripts/multi_seed_train.py` 导入 `training.Trainer` | `training/__init__.py` 暴露 EarlyStopping，需确认实际 re-export 与 import 是否一致 |
| criterion | 训练入口直接导入 EMD/Dual/PureReg；Dual 内部导入 EMD | EMD 两参是基础契约，双头损失通过 `is_dual_head` 分支 |
| log_manager | 两个训练入口导入 `LoggerManager` | 创建 `run_*`、写 `config.json`、配置 root logger；Trainer 依赖 `run_log_dir` |
| eval/backtest | eval 直接构造 Dataset/Model；run_backtest 消费 npz 并调用 `backtest.engine` | 预测 schema 与 OHLC schema 是脚本边界 |

## 重复与过期检测

| 项目 | 结果 | 位置/结论 |
|---|---|---|
| 共享配置 | 存在重复 | `train.py:39-86` 与 `scripts/multi_seed_train.py:32-75` 两套 dict |
| 模型构建 | 存在重复 | 两入口均校正 `featurenum`、实例化 `ModelConfig/CNNTransformer` |
| 损失构建 | 存在重复 | 两入口均有 EMD/Dual/PureReg 分支；应共享但保留语义差异 |
| 数据构建 | 存在重复 | 训练入口走 `create_dataloaders`；评估脚本自行构造验证 Dataset 并加载 scaler |
| EMDLoss | 单一实现 | `criterion/emd_loss.py`；未发现第二个 EMD 类，但 Dual/PureReg 是相关包装 |
| scaler | 单一实现 | `data/scaler.py:62`；旧 grouped scaler 已删除 |
| 旧模型 | 未发现实际文件 | 文档/历史任务仍提到旧模型，不能按当前 import 设计 |
| 旧 NPZ | 主链路未使用 | 根 AGENTS 明确已删除；脚本仍消费预测/OHLC npz，二者不能等同旧训练 NPZ |
| 过期文档 | 存在 | README 仍写 global z-score、55 维、`scaler.pkl`、close-close 等旧内容；`scripts/README.md:128` 明确提示 bins 脚本仍旧口径 |

## 不可改变契约检查

- [ ] parquet schema：10 个基础列 + 48 因子；`is_trading=False` 必须过滤。
- [ ] 默认 per-code 输出：39 有效特征 + 6 mask = `F=45`；原始因子集合“48”不可直接当模型输入维度。
- [ ] 可选显式特征与 `use_factor_only` 行为有清晰文档，不改 `EXPORT_FACTORS` 事实复刻。
- [ ] `seq_len=60`、`horizon=5`、open-open `open[t+1+5]/open[t+1]-1`、51 bins/52 类保持。
- [ ] 窗口输入 `[B,F,T]`，默认 `[B,45,60]`；标签位为窗口末日。
- [ ] scaler 训练集 fit，验证/推理 load；版本 `v2_per_code` 和 `logs/scaler_per_code.pkl` 保持读取兼容。
- [ ] `EMDLoss(logits[B,52], labels[B])` 签名不变；Dual/PureReg 四参路径有测试。
- [ ] 模型当前双头输出 `(logits[B,52], ret_pred[B])` 的事实与通用单 Tensor 文档差异被明确处理，不可静默改返回类型。
- [x] 当前 CNNTransformer 双头输出 shape 已覆盖；旧模型 checkpoint 兼容不属于当前契约。
- [ ] preds npz 必须含 `exp_ret,true_ret,dates,codes`；OHLC 路径键和 open-open 回测口径保持。

## 阶段门禁

| 阶段 | 进入条件 | 必须审查 | 验收命令/证据 |
|---|---|---|---|
| 1 文档 | 现有事实已盘点 | 45/48/55、标签、scaler、旧文档 | `rg "z-score|scaler\\.pkl|55维|close-close" README_TRAINING_CHAIN.md docs scripts` 结果已分类 |
| 2 构建 | T01 通过 | 配置覆盖、ModelConfig、模型注册 | 单测 + 模型 forward shape |
| 3 数据 | T02 通过 | 过滤、时序切分、G1-G9、mask、未见 code | `uv run --project . python -m data.dataset --max_codes 10 --normalize per_code` |
| 4 Trainer | T02/T03 通过 | 单/双头 loss、早停、scheduler、日志目录 | `uv run --project . python train.py --smoke --num_workers 0` |
| 5 评估回测 | T04 通过 | cache schema、日期/code 对齐、交易成本、防前视 | fixture 单测 + eval/backtest CLI 小样本 |
| 6 清理 | T01-T05 通过 | import、未使用文件、文档、测试覆盖 | `uv run ruff check .`、`uv run pyright`、unit tests |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|---|---|---|
| 1 | 契约一致性 | 45/48/55、open-open、52 类、60 长度、per-code 语义一致 | HIGH |
| 2 | 模块边界 | data 不依赖 training/models；models 不侵入 data；criterion 只提供损失；Trainer 不读取 parquet 细节 | HIGH |
| 3 | 防泄露 | scaler 仅训练 fit；评估缺 scaler 不自动拟合；回测只使用 T 及之后允许的路径 | HIGH |
| 4 | checkpoint | 当前双头 schema 记录；旧模型兼容逻辑明确不保留 | HIGH |
| 5 | 数值 | EMD 平滑行和为 1、有限值、梯度；标签边界和 NaN 过滤 | HIGH |
| 6 | import/依赖 | 真实 import 无死模块；不恢复已删除旧模型/NPZ 训练入口；无通配符和未使用 import | MEDIUM |
| 7 | 性能 | 不新增全量重复 parquet 读取、O(N²) 日期/code 扫描或 Windows worker 内存复制 | MEDIUM |
| 8 | 工程卫生 | 不提交 parquet、logs、pth、npz 产物；保留可追溯历史实验说明 | MEDIUM |
