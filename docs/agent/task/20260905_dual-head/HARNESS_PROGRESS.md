# 进度跟踪 — 20260905_dual-head

> 生成时间：2026-09-05 00:10
> 需求：EMD+0.2*Huber双头52+1改造+冒烟对比baseline

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | Dataset返y_ret | pending | - | data/dataset.py +15 |
| T02 | 模型双头 | pending | - | model.py +30 |
| T03 | DualLoss | pending | - | dual_loss.py +80新建 |
| T04 | Trainer兼容 | pending | - | trainer.py +40 |
| T05 | train开关+冒烟 | pending | - | train.py +40，对比表 |

## 执行详情

### T01: Dataset返y_ret
- **状态**：pending
- **依赖**：无
- **文件**：
  - `data/dataset.py` (modify)
- **预估行数**：+15
- **验收标准**：`y_cls==digitize(raw)`；`|y_ret|<=0.5`；3张量collate
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: 模型双头
- **状态**：pending
- **依赖**：无（可与T01并行）
- **文件**：
  - `models/cnn_transformer/model.py` (modify)
- **预估行数**：+30
- **验收标准**：`(logits[B,52], ret_pred[B])`；`out[0]`守pluggable契约
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: DualLoss
- **状态**：pending
- **依赖**：T02
- **文件**：
  - `criterion/dual_loss.py` (create)
- **预估行数**：+80
- **验收标准**：λ=0退化EMD；`L=EMD+0.2*Huber`手算一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: Trainer兼容
- **状态**：pending
- **依赖**：T01, T03
- **文件**：
  - `training/trainer.py` (modify)
- **预估行数**：+40
- **验收标准**：旧2元batch回归可训；双头backward正常
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: train开关+冒烟
- **状态**：pending
- **依赖**：T04
- **文件**：
  - `train.py` (modify)
- **预估行数**：+40
- **验收标准**：默认smoke=baseline；`--dual_head --smoke`输出对比表
- **Quality Gate 结果**：-
- **修复轮次**：0/2
