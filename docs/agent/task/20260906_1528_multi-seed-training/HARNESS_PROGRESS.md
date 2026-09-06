# 进度跟踪 — multi-seed-training

> 生成时间：2026-09-06 15:28
> 需求：创建多 seed 训练脚本 scripts/multi_seed_train.py，支持多 seed 独立训练 + λ 随机波动 + 结果汇总

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | 创建 `scripts/multi_seed_train.py` | pending | - | 单一任务，无依赖 |

## 执行详情

### T01: 创建 `scripts/multi_seed_train.py`
- **状态**: pending
- **依赖**: 无
- **文件**:
  - `scripts/multi_seed_train.py` (create)
- **预估行数**: +250 行
- **验收标准**:
  1. `uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42,123` 能以 20 股×1epoch 完成 2 个 seed 的冒烟训练
  2. 每个 seed 的日志目录为 `logs/run_seed42_*` 和 `logs/run_seed123_*`
  3. 生成的汇总 CSV 包含两行数据（seed=42, λ≈0.2±0.005；seed=123, λ≈0.2±0.005）
  4. 两个 seed 的 λ 值不完全相同（因 jitter 波动）
  5. 训练完成后 CUDA 缓存已清理
  6. 不修改 `train.py`、`training/trainer.py`、`data/dataset.py`、`criterion/*`、`models/*` 中任何文件
- **Quality Gate 结果**: -
- **修复轮次**: 0/2

## 验证命令

```bash
# 冒烟验证（20 股，2 seed，1 epoch）
uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42,123

# 完整验证（3 seed，全量数据，推荐后台运行，预计数小时）
uv run --project . python scripts/multi_seed_train.py --seeds 42,123,2024 --epochs 50 --batch_size 256

# 自定义 λ 和 jitter 验证
uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42,123 --lambda_reg 0.6 --lambda_jitter 0.01

# 查看汇总结果
cat logs/multi_seed_summary_*.csv
```
