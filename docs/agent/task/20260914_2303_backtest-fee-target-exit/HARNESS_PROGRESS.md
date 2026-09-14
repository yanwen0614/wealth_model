# 进度跟踪 — backtest-fee-target-exit

> 生成时间：2026-09-14 23:03
> 需求：回测口径升级 —— rolling/target 统一 A 股真实费用模型（佣金最低 5 元 + 卖出印花税）+
> target 退出规则（sell_buffer 200→500、可选 exit-on-nonpositive）
> 分支：`feature/rolling-normalization-cnn`
> 计划：`PLAN.md`；审查：`REVIEW_CHECKLIST.md`

## 执行顺序

```
T01 费用纯函数与命名常量
 ├─ T02 rolling 逐笔费用模型
 ├─ T03 target 逐笔费用模型
 │   └─ T04 target 退出规则
 └────────────┐
T02,T03,T04 ──┴─ T05 CLI/脚本/文档适配
                    └─ T06 全量单测 + ruff 收尾
                        └─ T07 端到端重跑与新旧对比
```

> T02 与 T03 均只依赖 T01，可并行；T04 依赖 T03；T05 依赖 T02+T03+T04；T06 收尾 T01–T05。

## 任务列表

| Task | 名称 | 依赖 | 预估行数 | need_test | 状态 |
|------|------|------|----------|-----------|------|
| T01 | 费用纯函数与命名常量 | 无 | +80 | 是 | pending |
| T02 | rolling 逐笔费用模型 | T01 | +120 | 是 | pending |
| T03 | target 逐笔费用模型 | T01 | +150 | 是 | pending |
| T04 | target 退出规则 | T03 | +70 | 是 | pending |
| T05 | CLI/脚本/文档适配 | T02,T03,T04 | +130 | 是 | pending |
| T06 | 全量单测 + ruff 收尾 | T01–T05 | +60 | 否 | pending |
| T07 | 端到端重跑与新旧对比 | T01–T06 | +40 | 是 | pending |

## 既有基线（供 T07 对比）

- rolling 旧基线（cost_rate=0.0015）：`logs/backtest_relative_run_20260914_024253_2026-01-01_2026-08-31/`、
  `logs/backtest_run_20260914_045053_2026-01-01_2026-08-31/`、`logs/backtest_rolling_e{2,3,4,5}_run_*_2026-01-01_2026-08-31/`。
- target 旧基线（sell_buffer=200, cost_rate=0.0015, target_size=100）：`logs/backtest_target_e0e5_ts100/metrics.json`。
- 数据：`logs/ohlc_path_2026-01-01_2026-08-31.npz`（rolling）、`logs/ohlc_full_2026-01-01_2026-08-31.npz`（target）。
- 6 臂 preds：`preds_relative_run_*`(E0)、`preds_run_20260914_045053_*`(E1)、`preds_rolling_e2/e3/e4/e5_*`(E2–E5)。

## 执行详情

### T01 费用纯函数与命名常量
- **状态**：pending
- **依赖**：无
- **文件**：`backtest/engine.py` (modify)、`tests/unit/backtest/test_engine.py` (modify)
- **预估行数**：+80
- **验收标准**：常量 `0.00025/0.00025/0.00025/5.0/1_000_000.0`；买 10000→5.0、买 100000→25.0；
  卖 110000→佣 27.5+印花税 27.5；`net_return_after_fees` 两情形与手算一致。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02 rolling 逐笔费用模型
- **状态**：pending
- **依赖**：T01
- **文件**：`backtest/engine.py` (modify)、`tests/unit/backtest/test_engine.py` (modify)
- **预估行数**：+120
- **验收标准**：`nav[6]=1+0.2×((220000−110−200050)/200050)`（capital=1e6）；benchmark 同模型；capital 敏感性生效。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03 target 逐笔费用模型
- **状态**：pending
- **依赖**：T01
- **文件**：`backtest/engine.py` (modify)、`tests/unit/backtest/test_engine.py` (modify)
- **预估行数**：+150
- **验收标准**：shares 两情形求解（阈值 20005）；`nav[1]=0.99975`；平仓 `ret_net` 符合通式；cash/nav 用 NAV 单位。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04 target 退出规则
- **状态**：pending
- **依赖**：T03
- **文件**：`backtest/engine.py` (modify)、`tests/unit/backtest/test_engine.py` (modify)
- **预估行数**：+70
- **验收标准**：默认 `sell_buffer==500`；`exit_on_nonpositive` 时 `exp_ret≤exit_threshold` 即卖；关闭时 rank 决定；两规则互斥。
- **Quality Gate 结果**：-
- **修复轮次**：0/2
### T05 CLI/脚本/文档适配
- **状态**：pending
- **依赖**：T02, T03, T04
- **文件**：`scripts/run_backtest.py`、`scripts/run_eval_full.sh`、`scripts/run_eval_pipeline.py`、`scripts/README.md`、`backtest/__init__.py` (modify)、`tests/unit/scripts/test_run_backtest_cli.py` (create)
- **预估行数**：+130
- **验收标准**：`parse_args([]).capital==1_000_000.0`、`sell_buffer==500`、`exit_on_nonpositive is False`；
  `--cost_rate 0.0015` 触发 warning 且被忽略；`run_eval_full.sh` 无 `--cost_rate`。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06 全量单测 + ruff 收尾
- **状态**：pending
- **依赖**：T01–T05
- **文件**：`tests/unit/backtest/test_engine.py` (modify)、`tests/unit/**` 按需 (modify)
- **预估行数**：+60
- **验收标准**：`uv run --project . python -m unittest discover tests/unit` 全绿；`ruff check` 对改动文件无错。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T07 端到端重跑与新旧对比
- **状态**：pending
- **依赖**：T01–T06
- **文件**：`docs/agent/task/20260914_2303_backtest-fee-target-exit/HARNESS_PROGRESS.md` (modify)
- **预估行数**：+40
- **验收标准**：6 臂 rolling（top5/10/20/50/100）与 target（size=100）新旧 annual/sharpe/超额对照表落本文件；
  新产物落 `logs/backtest_*_fee_*`；结论区分「费用模型升级」与「buffer/exit 规则」各自影响。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 风险与假设（摘要）

- 旧结果不可比：费用模型 + target 默认 buffer 双变量变化，禁止与历史数字直接混用。
- `--cost_rate` 兼容：保留 warning 后忽略，避免历史命令静默改变结果。
- 默认 `capital=1e6,size=100` → target 单槽预算 10000<20005 → 最低佣金默认生效（预期）。
- 单位换算（target `÷capital`）与 benchmark 同模型为易错点。
- E2E 全市场 target 无并发、耗时；`full_ohlc` 已存在。
