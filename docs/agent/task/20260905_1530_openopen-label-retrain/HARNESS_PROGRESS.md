# 进度跟踪 — openopen-label-retrain

> 生成时间：2026-09-05 15:30
> 需求：训练标签 close-close → open-open（与回测实盘口径对齐），三 loss 全串行重训（patience 10→2）
> 2026-09-12 状态同步：本任务未执行即被后续工作取代 —— train.py 现状已是 open-open 标签口径（future_ret=open[t+6]/open[t+1]-1）且含 --patience；全表 pending → superseded，不再恢复。
> 环境：非 git 仓库（git 环节跳过）；GPU RTX 3070 8GB；RAM 15.9GB（强制 num_workers=0 + 串行）

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | 单测先行（TDD RED） | superseded | - | 5 组用例，旧实现下须全 FAIL |
| T02 | dataset.py 标签 open-open（TDD GREEN） | superseded | 待审 | 纯函数抽取 + max_s 收 1 + 注释同步 |
| T03 | train.py --patience CLI | superseded | 待审 | +3 行，skip TDD（纯配置转发） |
| T04 | 链路一致性验证 + 旧缓存归档 | superseded | -（运行任务） | dataset 探查 sanity + preds npz 归档 |
| T05 | 三连串行训练（pure_reg→base→dual） | superseded | -（运行任务） | 不进 quality gate，监控 patience=2 生效 |

执行顺序：T01 → T02 →（T02/T03 完成后）T04 → T05；T03 可与 T01/T02 并行。

## 执行详情

### T01: 单测先行（TDD RED）
- **状态**：superseded
- **依赖**：无
- **文件**：
  - `tests/unit/data/test_dataset_label_openopen.py` (create)
- **预估行数**：+90
- **验收标准**：UT1-UT5（见 PLAN 单测清单）在旧实现下全 FAIL（RED 确认）；
  用例覆盖公式逐点/端点 NaN/非正防护/尾部截断/临时 parquet 集成
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: dataset.py 标签 open-open（TDD GREEN）
- **状态**：superseded
- **依赖**：T01
- **文件**：
  - `data/dataset.py` (modify)
  - `scripts/build_ohlc_path.py` (modify, 仅注释)
  - `scripts/recompute_bins.py` (modify, 仅 docstring)
- **预估行数**：+25 / -10
- **验收标准**：T01 全 GREEN；`py_compile` + `ruff check .` 通过；
  test_scope=full（data 链路触发规则 #1）：`train.py --smoke --num_workers 0` 通过
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: train.py --patience CLI
- **状态**：superseded
- **依赖**：无（可并行）
- **文件**：
  - `train.py` (modify)
- **预估行数**：+4 / -1
- **验收标准**：`--patience 2` 后 EarlyStopping counter 分母=2（smoke 观察）；
  skip TDD 理由：argparse 纯配置转发，早停行为由 trainer 既有逻辑覆盖
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 链路一致性验证 + 旧缓存归档（运行任务）
- **状态**：superseded
- **依赖**：T02, T03
- **文件**：无代码；`logs/preds_base_ep4.npz`、`logs/preds_dual_ep7.npz` → mv 至 `logs/archive_closeclose/`
- **预估行数**：0
- **验收标准**：`uv run --project . python -m data.dataset --max_codes 10 --normalize per_code`
  输出新口径标签分布无异常；三方对齐推论（eval/回测零改动）确认；旧 npz 已归档
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: 三连串行训练（运行任务，不进 quality gate）
- **状态**：superseded
- **依赖**：T04
- **文件**：`logs/run_*/` ×3（运行产出）
- **预估行数**：0
- **验收标准**：3 个 run 各含 best_model.pth + config.json + training_curve.png；
  串行执行（前一条完成后才启动下一条）；启动前 nvidia-smi 确认 GPU 空闲
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 已知风险（执行时对照 PLAN 风险表）

- R1 旧 preds npz 口径混用（T04 归档缓解）
- R3 9 月妖股隔夜跳空 → 标签尾部更肥（T04 分布 sanity 监控）
- R5 patience=2 对 dual 偏激进（用户已决策，留档）
