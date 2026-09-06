# 进度跟踪 — 整理项目代码

> 生成时间：2026-09-06
> 需求：按阶段 1 到阶段 6 整理 CNN 项目；当前为阶段 6 收口，不提交

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|---|---|---|---|---|
| T01 | 文档与契约统一 | complete | 已验证 | 当前口径已统一，历史文档保留并标注不可混用 |
| T02 | 共享配置与训练构建 | complete | 已验证 | 默认配置隔离、factory 三种损失、当前双头 shape |
| T03 | 数据模块拆分 | complete | 已验证 | schema、labels、缓存键和长度校验 |
| T04 | Trainer 整理 | complete | 已验证 | 空训练集/验证集保护和 batch 解包 |
| T05 | 实验评估回测整理 | complete | 已验证 | backtest、criterion、data、training 测试保留 |
| T06 | 测试与工程清理 | complete | PASS（ruff/unit；pyright 有既有类型错误） | 用户决定不保留旧模型 checkpoint 兼容逻辑 |

## 执行详情

### T01：文档与契约统一
- **状态**：complete
- **依赖**：无
- **文件**：`README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`docs/*.md`、`scripts/README.md`（modify）
- **预估行数**：+80/-80
- **验收标准**：文档统一默认 `F=45,T=60,C=52`、open-open、per-code、scaler 复用、preds/OHLC schema；历史旧口径有标记。
- **Quality Gate 结果**：PASS（文档静态检查）
- **修复轮次**：0/2

### T02：共享配置与训练构建
- **状态**：complete
- **依赖**：T01
- **文件**：共享配置/构建模块（create）；`train.py`、`scripts/multi_seed_train.py`、`models/cnn_transformer/config.py`、`models/__init__.py`（modify）
- **预估行数**：+180/-220
- **验收标准**：两个训练入口共享构建逻辑；ModelConfig 对齐；模型输出和 loss 分支稳定；旧模型 checkpoint 不在支持范围。
- **Quality Gate 结果**：PASS（单测、factory、模型 shape）
- **修复轮次**：0/2

### T03：数据模块拆分
- **状态**：complete
- **依赖**：T01、T02
- **文件**：`data/dataset.py`、`data/scaler.py`、拟新增 data 子模块（modify/create）
- **预估行数**：+260/-300
- **验收标准**：过滤 `is_trading=False`；默认 `x [45,60]`；标签 open-open/52 类正确；训练 scaler 复用且 save/load 一致。
- **Quality Gate 结果**：PASS（数据单测、真实 parquet 探查）
- **修复轮次**：0/2

### T04：Trainer 整理
- **状态**：complete
- **依赖**：T02、T03
- **文件**：`training/trainer.py`、`training/metrics.py`、`training/early_stopping.py`、`log_manager/__init__.py`（modify）
- **预估行数**：+140/-180
- **验收标准**：单头/双头 loss、早停、scheduler、日志和混淆矩阵行为保持；`run_log_dir` 契约不变。
- **Quality Gate 结果**：PASS（训练单测、smoke）
- **修复轮次**：0/2

### T05：实验评估回测整理
- **状态**：complete
- **依赖**：T02、T03、T04
- **文件**：`scripts/eval_bins_mapping.py`、`scripts/build_ohlc_path.py`、`scripts/run_backtest.py`、`scripts/plot_topn_curve.py`、`backtest/engine.py`（modify）
- **预估行数**：+180/-220
- **验收标准**：预测缓存键完整、scaler 缺失不自动 fit、日期/code 对齐；回测保持 T+1/T+6 open-open、成本和基准语义。
- **Quality Gate 结果**：PASS（回测单测、脚本编译）
- **修复轮次**：0/2

### T06：测试和工程清理
- **状态**：complete
- **依赖**：T01-T05
- **文件**：`tests/unit/**`、必要时 `pyproject.toml`、过期引用（modify/create/delete 需审查）
- **预估行数**：+300/-100
- **验收标准**：单元测试覆盖配置隔离、factory 三种损失、data schema/labels、预测缓存、模型双头 shape、Trainer 空数据和既有 backtest/criterion/data/training 测试；无业务产物入库。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 计划验收命令

以下命令用于阶段 6 验证：

```bash
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run pyright
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
uv run --project . python train.py --smoke --num_workers 0
```

## 当前静态结论

- 未找到 `CLAUDE.md`；已读取根 `AGENTS.md`、`data/AGENTS.md`、`models/AGENTS.md`、`models/cnn_transformer/AGENTS.md`、`training/AGENTS.md`、`criterion/AGENTS.md`、`log_manager/AGENTS.md`、`README_TRAINING_CHAIN.md` 和 per-code spec。
- 已补充确定性单测；旧模型 checkpoint 兼容逻辑按用户决定不保留。
- 历史实验文档未删除，仅标注历史口径不可与当前链路混用。
- 本任务不提交；最终命令结果由本次执行记录补齐。

## 阶段 6 验证结果

- `uv run --project . python -m unittest discover tests/unit`：PASS，69 项。
- `uv run ruff check .`：PASS；pyproject 仅启用 E4/E7/E9/F 最小检查集。
- 相关模块 `py_compile`：PASS。
- `uv run pyright`：FAIL，34 个既有类型标注错误；未引入新依赖或关闭类型检查。
- `uv run --project . python -m data.dataset --max_codes 10 --normalize per_code`：PASS；真实 parquet 输出 F=45、T=60、C=52，scaler save/load 复用一致。
