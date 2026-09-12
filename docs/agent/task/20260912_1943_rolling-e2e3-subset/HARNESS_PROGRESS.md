# 进度跟踪 — 20260912_1943_rolling-e2e3-subset

> 生成时间：2026-09-12 19:43
> 需求：rolling E2/E3 子集开关 + E1–E4 对照实验代码支持

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | rolling scope 配置与 digest 隔离 | pending | - | data/rolling_scaler.py |
| T02 | dataset scope 透传与 state 隔离 | pending | - | data/dataset.py，依赖 T01 |
| T03 | train.py CLI、seed 与产物隔离 | pending | - | train.py，依赖 T01+T02 |
| T04 | 评估取数与实验文档线 | pending | - | scripts，依赖 T03 |

## 执行详情

### T01: rolling scope 配置与 digest 隔离
- **状态**：pending
- **依赖**：无
- **文件**：`data/rolling_scaler.py` (modify)
- **预估行数**：+45/-8
- **验收标准**：e2/e3/e4 digest 互异；默认=e4 现行；F=69；[B,69,60]->[B,52]
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: dataset scope 透传与 state 隔离
- **状态**：pending
- **依赖**：T01
- **文件**：`data/dataset.py` (modify)
- **预估行数**：+35/-10
- **验收标准**：异 scope state 报错；num_features=69；各 scope 有 fallback_ratio
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: train.py CLI、seed 与产物隔离
- **状态**：pending
- **依赖**：T01, T02
- **文件**：`train.py` (modify)；`config/defaults.py` (modify)
- **预估行数**：+55/-10
- **验收标准**：默认 rolling=E4；同 seed smoke 可复现；config.json 含 scope/seed/digest
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 评估取数与实验文档线
- **状态**：pending
- **依赖**：T03
- **文件**：`scripts/run_eval_pipeline.py` (modify)；`scripts/run_eval_full.sh` (docs)
- **预估行数**：+25/-5
- **验收标准**：IC/ICIR、top-bottom、成本后收益、fallback、winsor 五项可取数
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## execution_order

T01 → T02 → T03 → T04（串行，TDD 先单测后实现；全量训练 tmux 串行禁并行）。
