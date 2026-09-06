# 审查清单 — multi-seed-training

> 生成时间：2026-09-06 15:28

## 需求理解

创建多 seed 训练脚本 `scripts/multi_seed_train.py`，支持：
1. 基准 λ=0.2（DualLoss 回归权重），可通过 `--lambda_reg` 调整
2. 多个 seed（如 [42, 123, 2024]）独立训练
3. 每个 seed 的 λ 随机波动 ±0.005（即 λ = 0.2 + uniform(-0.005, +0.005)）
4. 每个 seed 独立日志目录（`logs/run_seed42_{timestamp}/`）
5. 训练完成后汇总各 seed 的 best_val_loss / best_val_acc 对比表（CSV + 终端打印）

**显式假设**：
- 所有 seed 共用同一组 DataLoader（训练/验证集时间范围、特征列、归一化 scaler 一致），仅 seed 不同
- 归一化 scaler 在训练集上仅拟合一次（第一个 seed），后续 seed 复用——但需确保每个 seed 的 DataLoader 使用相同的 scaler_stats 对象
- λ 波动在 seed 内固定（每个 seed 初始化时确定 λ，训练过程中不变）
- `train.py:300` 的 `os._exit(0)` 调用不会在 multi_seed 脚本中被触发，因为不直接调用 `train.main()`
- 环境假设 GPU 单卡可用，多 seed 串行运行（非并行）
- 已有的 λ 消融文档 `docs/lambda_ablation_20260906.md` 建议做 5 个 seed 稳定性验证——本脚本即实现该需求

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| scripts | `scripts/multi_seed_train.py` | 新增 | 多 seed 编排主脚本，导入现有组件 |
| logs | `logs/multi_seed_summary_{timestamp}.csv`（运行时生成） | 新增 | 结果汇总报告 |

> 不修改任何现有源码文件。

## 重复检测

| 搜索关键词 | 是否存在 | 位置 |
|------------|---------|------|
| multi_seed / multi-seed / multiseed | 否 | — |
| seed | 是 | `train.py` 未显式设置 seed |
| DualLoss | 是 | `criterion/dual_loss.py` |
| LoggerManager | 是 | `log_manager/__init__.py` |
| lambda_jitter / lambda fluctuation | 否 | — |
| run_seed | 否 | — |
| summary CSV / multi_seed_summary | 否 | — |
| 并行训练 / parallel train | 否 | — |
| torch.manual_seed | 是（许多 `__main__` 块中） | 无标准种子设置 |
| np.random.seed | 是（仅 `dataset.py:363` `rng`） | 非全局 seed |

**结论**：全项目范围无任何多 seed 训练或类似功能实现，本次为全新功能。

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名（`multi_seed_train.py`）与现有 `scripts/` 文件风格一致；导入顺序（标准库→第三方→本地）；日志用 `logging.getLogger` 而非 `print` | HIGH |
| 2 | 模块边界 | 不修改 `train.py`、`training/trainer.py`、`data/dataset.py`、`criterion/*`、`models/*` 中任何代码 | HIGH |
| 3 | Seed 设置完整性 | `torch.manual_seed()`、`torch.cuda.manual_seed_all()`、`np.random.seed()`、`random.seed()` 四件套齐全 | HIGH |
| 4 | 导入合规 | 从 `train.py` 正确导入 config 字典/组件，而非重新定义 | MEDIUM |
| 5 | 错误处理 | 单个 seed 训练失败不中断整个流程（捕获异常并记录），最后在汇总表中标 FAIL | MEDIUM |
| 6 | 性能风险 | 每 seed 后 `torch.cuda.empty_cache()` 确保显存不累积；串行训练可接受 | MEDIUM |
| 7 | 代码安全 | 无 `os._exit(0)` 调用（multi_seed 脚本退出时自然结束，不强行终止进程） | HIGH |
| 8 | λ jitter 正确性 | `np.random.uniform(-0.005, 0.005)` 在每个 seed 循环内调用，且使用已设置的 seed（保证可复现） | MEDIUM |
| 9 | 结果汇总准确性 | CSV 中的 best_val_loss/acc 与 `trainer.get_training_history()` 提取的最佳值一致 | MEDIUM |
| 10 | 种子可复现性 | 相同 `--seeds` 两次运行应产生完全相同的 λ 序列（λ jitter 使用 seed 化 np.random） | MEDIUM |
