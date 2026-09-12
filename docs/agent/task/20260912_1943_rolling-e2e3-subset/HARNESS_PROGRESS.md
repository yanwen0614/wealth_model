# 进度跟踪 — 20260912_1943_rolling-e2e3-subset

> 生成时间：2026-09-12 19:43
> 需求：rolling E2/E3 子集开关 + E1–E4 对照实验代码支持

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | rolling scope 配置与 digest 隔离 | done | PASS | data/rolling_scaler.py，26/26 全绿，默认 digest 1983dd5c…e0d |
| T02 | dataset scope 透传与 state 隔离 | done | PASS | data/dataset.py +9/-3，31/31 全绿；LOW：validate scope 可选参数旁路靠 identity 兜底（后续可改为必填，不阻塞） |
| T03 | train.py CLI、seed 与产物隔离 | done | PASS | train.py+62/-12，10/10；e4→logs/rolling_e4/ 有意迁移；遗留：eval回退旧路径/ workers未播种（T04/后续跟进） |
| T04 | 评估取数与实验文档线 | done | PASS | scripts eval双文件+sh注释，9/9；旧logs/rolling/零残留；残留均为改前既有（I001/BLE001等，不归因T04） |

## 执行详情

### T01: rolling scope 配置与 digest 隔离
- **状态**：done
- **依赖**：无
- **文件**：`data/rolling_scaler.py` (modify)
- **预估行数**：+45/-8
- **验收标准**：e2/e3/e4 digest 互异；默认=e4 现行；F=69；[B,69,60]->[B,52]
- **Quality Gate 结果**：PASS（6 关卡全过，ruff/pyright/26单测全绿）
- **修复轮次**：0/2

### T02: dataset scope 透传与 state 隔离
- **状态**：done
- **依赖**：T01
- **文件**：`data/dataset.py` (modify)
- **预估行数**：+35/-10
- **验收标准**：异 scope state 报错；num_features=69；各 scope 有 fallback_ratio
- **Quality Gate 结果**：PASS（ruff/pyright/31单测全绿，1 LOW 非阻塞）
- **修复轮次**：0/2

### T03: train.py CLI、seed 与产物隔离
- **状态**：done
- **依赖**：T01, T02
- **文件**：`train.py` (modify)；`config/defaults.py` (modify)
- **预估行数**：+55/-10
- **验收标准**：默认 rolling=E4；同 seed smoke 可复现；config.json 含 scope/seed/digest
- **Quality Gate 结果**：PASS（10/10；2 MEDIUM：eval回退旧路径→T04修 / workers未播种→对照统一num_workers）
- **修复轮次**：0/2

### T04: 评估取数与实验文档线
- **状态**：done
- **依赖**：T03
- **文件**：`scripts/run_eval_pipeline.py` (modify)；`scripts/run_eval_full.sh` (docs)
- **预估行数**：+25/-5
- **验收标准**：IC/ICIR、top-bottom、成本后收益、fallback、winsor 五项可取数
- **Quality Gate 结果**：PASS（9/9；2 FAIL 关卡均为改前既有、T04 零新增）
- **修复轮次**：0/2

## execution_order

T01 → T02 → T03 → T04（串行，TDD 先单测后实现；全量训练 tmux 串行禁并行）。
