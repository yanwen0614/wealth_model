# multi-seed-training Implementation Plan

> Generated: 2026-09-06 15:28
> Task Dir: docs/agent/task/20260906_1528_multi-seed-training/

## Goal

创建一个多 seed 训练脚本 `scripts/multi_seed_train.py`，在现有 DualLoss（λ=0.2）配置下，使用多个随机种子独立训练并汇总结果。脚本不得修改现有 `train.py` 或 `Trainer`，仅通过导入现有组件实现多 seed 编排。

## Architecture

- 新建 `scripts/multi_seed_train.py`，导入 `train.py` 中已有的组件（`ParquetDataConfig`、`ParquetDataset`、`CNNTransformer`、`ModelConfig`、`Trainer`、`LoggerManager`、`DualLoss` 等），并在新脚本中编排多 seed 循环
- 每个 seed 独立创建 `LoggerManager` 实例，自动生成 `logs/run_seed{seed}_{timestamp}/` 目录；λ 在 [0.195, 0.205] 内随机波动
- 全部 seed 训练完毕后，解析各 seed 日志目录下的 `best_model.pth` 对应训练记录，汇总为 CSV 报告
- 严格遵循现有模块边界：不修改 `train.py`、`training/trainer.py`、`data/dataset.py`、`criterion/*`、`models/*`

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 脚本位置 | `scripts/multi_seed_train.py` | 在 `train.py` 内加 `--multi_seed` 参数 | 关键约束要求不修改现有 train.py |
| seed 传播方式 | 在循环中调用 `torch.manual_seed(seed)` + `np.random.seed(seed)` + `random.seed(seed)` 后重建模型/DataLoader | 仅设置全局 seed | DataLoader shuffle 也依赖 seed 可复现；重建 DataLoader 使不同 seed 下数据加载顺序不同 |
| λ 波动方式 | 每个 seed 的 λ = 0.2 + uniform(-0.005, +0.005)，在 `DualLoss` 初始化时传入固定 λ | 在训练循环中动态改变 λ | DualLoss 的 λ 是实例化参数，固定值保证训练过程自洽；每个 seed 独立初始化 loss |
| run_log_dir 命名 | `logs/run_seed{seed}_{timestamp}/` 其中 timestamp 为 seed 统一时间戳 | 每个 seed 独立时间戳 | 统一时间戳便于关联同一批次实验；每个 seed 仍独立 LoggerManager |
| 结果汇总 | 解析各 seed 日志目录下的训练历史 + 早停记录的 best_val_loss/acc，写入 CSV | 在 Trainer 中增加回调 | 不修改 Trainer 的约束，只能从已有日志/模型文件中提取 |
| CUDA 清理 | 每 seed 训练循环后调用 `torch.cuda.empty_cache()` | 依赖 Python GC | 显式清理避免显存碎片累积，确保后续 seed 有足够显存 |

## Impact

| 模块 | 文件 | 操作(create/modify) | 风险等级 |
|------|------|--------------------|----------|
| scripts | `scripts/multi_seed_train.py` | create | high |
| logs | `logs/multi_seed_summary_{timestamp}.csv`（运行时自动生成） | create | low |

> 风险等级说明：新脚本不修改现有代码，风险集中于新脚本本身的逻辑正确性（seed 设置、λ 波动、CUDA 清理、结果汇总），以及导入链路的兼容性。

## Task Decomposition

### T01: 创建 `scripts/multi_seed_train.py`
- **文件**: `scripts/multi_seed_train.py` (create)
- **描述**:
  1. 导入 `train.py` 中使用的所有现有组件（`ParquetDataConfig`, `ParquetDataset`, `CNNTransformer`, `ModelConfig`, `Trainer`, `LoggerManager`, `DualLoss`, `EMDLoss`, `PureRegLoss`, `Visualizer` 等）
  2. 复制 `train.py` 中 `config` 字典定义作为基准配置，但命令行参数独立设计
  3. 支持 `--seeds` 参数（如 `--seeds 42,123,2024` 或 `--seed_count 5` + `--seed_start 42`）
  4. 支持 `--lambda_reg` 参数（默认 0.2），可调基准 λ
  5. 支持 `--lambda_jitter` 参数（默认 0.005），控制 λ 随机波动的 ± 范围
  6. 支持 `--smoke` 模式（同 `train.py` 语义：max_codes=20, epochs=1）
  7. 支持现有 `train.py` 的其他参数（`--epochs`, `--batch_size`, `--lr`, `--max_codes`, `--no_val` 等）
  8. 主循环逻辑：遍历 seeds，对每个 seed 执行一次完整训练
     - 设置所有随机种子的 seed（torch/numpy/random）
     - 计算当前 seed 的 λ = 基准 λ + uniform(-jitter, +jitter)
     - 创建独立的 `LoggerManager`（run_log_dir 含 seed 标识）
     - 初始化 DataLoader、模型、损失（DualLoss 或 EMDLoss 取决于 `--dual_head`）、优化器、调度器、Trainer
     - 调用 `trainer.train()` 完整训练
     - 提取训练历史 `trainer.get_training_history()` 获取最佳 val_loss 和 val_acc
     - 清理 CUDA 缓存
  9. 汇总阶段：从各 seed 的训练历史中提取 best_val_loss 和 best_val_acc，生成对比表 CSV
  10. CSV 包含列：seed, lambda, best_val_loss, best_val_acc, total_epochs, run_log_dir, early_stopped_epoch
  11. 按 best_val_loss 升序排序，打印到终端
- **依赖**: 无
- **预估行数**: +250 行
- **验收标准**:
  1. `uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42,123` 能以 20 股×1epoch 完成 2 个 seed 的冒烟训练
  2. 每个 seed 的日志目录为 `logs/run_seed42_*` 和 `logs/run_seed123_*`
  3. 生成的汇总 CSV 包含两行数据（seed=42, λ≈0.2±0.005；seed=123, λ≈0.2±0.005）
  4. 两个 seed 的 λ 值不完全相同（因 jitter 波动）
  5. 训练完成后 CUDA 缓存已清理（`torch.cuda.empty_cache()` 可安全重复调用）
  6. 不修改 `train.py`、`training/trainer.py`、`data/dataset.py`、`criterion/*`、`models/*` 中任何文件
- **风险因子**: 导入 `train.py` 中 config 字典常量的方式需谨慎；`train.py:300` 末尾 `os._exit(0)` 调用会直接退出进程，multi_seed 脚本需避免触发该调用——应导入组件而非直接调用 `main()`
