# 进度跟踪 — 20260904_2359_emd-p0-bins-map

> 生成时间：2026-09-04 23:59
> 需求：P0修criterion/emd_loss.py bug（register_buffer+删to+注释）+ Step0全量bins分位重算 + Step1 52→11映射评估

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | EMDLoss P0 修复 | pending | - | register_buffer+删to |
| T02 | Step0 全量 bins 分位重算 | pending | - | 新脚本+外部bins注入 |
| T03 | Step1 52→11 映射评估 | pending | - | 依赖 T01,T02 |

## 执行详情

### T01: EMDLoss P0 修复
- **状态**：pending
- **依赖**：无
- **文件**：
  - `criterion/emd_loss.py` (modify)
- **预估行数**：+15/-20
- **验收标准**：weights 随 `.to()` 同 device；`[B,52]` forward 可反向；smoke 无 device 错
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: Step0 全量 bins 分位重算
- **状态**：pending
- **依赖**：无
- **文件**：
  - `scripts/recompute_bins.py` (create)
  - `data/dataset.py` (modify)
- **预估行数**：+90
- **验收标准**：51 边界单调；新 bins 尾类占比提升；验证集复用 scaler 不重 fit
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: Step1 52→11 映射评估
- **状态**：pending
- **依赖**：T01, T02
- **文件**：
  - `scripts/eval_bins_mapping.py` (create)
  - `train.py` (modify)
- **预估行数**：+110
- **验收标准**：52 vs 11 对照表；`[B,F,60]->[B,11]` 断言；不改默认 52 链路
- **Quality Gate 结果**：-
- **修复轮次**：0/2
