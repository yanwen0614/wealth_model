# 进度跟踪 — add-strong-buy-gate

> 生成时间：2026-09-15 00:05
> 需求：target 回测买入端新增「绝对预测收益强买门槛」`--strong_buy_threshold`
> （默认 0.0=关闭、负数 raise），作用于买入带全部候选、不满足留现金不补位；
> 与 `--sell_buffer 500` / `--exit-on-nonpositive` 两套退出规则及 size 5/10/50 交叉测试。
> 计划：`PLAN.md`；审查：`REVIEW_CHECKLIST.md`

## 执行顺序

```
T01 引擎强买门槛 + skip 计数
  └─ T02 CLI 参数 / metrics / 打印
       ├─ T03 回归 / 等价性测试 + 全量单测收尾
       ├─ T04 文档同步
       └─ T05 交叉测试（3 阈值 × 2 退出 × 3 尺寸）
```

> T01 为根；T02 依赖 T01；T03/T04 依赖 T01+T02；T05 依赖 T01–T04（端到端）。

## 任务列表

| Task | 名称 | 依赖 | 预估行数 | need_test | 状态 |
|------|------|------|----------|-----------|------|
| T01 | 引擎强买门槛 + skip 计数 | 无 | +45 | 是 | pending |
| T02 | CLI 参数 / metrics / 打印 | T01 | +35 | 是 | pending |
| T03 | 回归 / 等价性测试 + 全量单测收尾 | T01,T02 | +40 | 否 | pending |
| T04 | 文档同步 | T01,T02 | +15 | 否 | pending |
| T05 | 交叉测试（3 阈值 × 2 退出 × 3 尺寸） | T01–T04 | +30 | 是 | pending |

## 契约要点（实现红线）

- `strong_buy_threshold=0.0` 与改动前行为**逐位一致**（`> 0.0` 守卫短路）；`< 0` raise。
- 门槛顺序：`min_edge` → `strong_buy` → `limit_up`；同候选先命中者计数。
- 只改 target 模式；rolling / `_simulate` / 费用纯函数 / `benchmark_index_nav` / 退出规则零改动。
- metrics 只增 `strong_buy_threshold` / `n_skipped_strong_buy`，旧键全保留。
- 回测时序不变：T 日决策 → T+1 open 买入 → T+6 open 卖出。

## 执行详情

### T01 引擎强买门槛 + skip 计数
- **状态**：pending
- **依赖**：无
- **文件**：`backtest/engine.py` (modify)、`tests/unit/backtest/test_engine.py` (modify)
- **预估行数**：+45
- **验收标准**：`strong_buy_threshold=-0.01` → `ValueError`；threshold=0.05 且候选
  `exp=[0.30,0.03,0.001]`、size=3 → 仅 rank1 买入、`skipped[d]=={"strong_buy":2}`、nav 为
  「2/3 现金 + 1/3 买入」；threshold=0.0 时 nav 与既有断言逐位一致；与 min_edge 同命中计 min_edge。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02 CLI 参数 / metrics / 打印
- **状态**：pending
- **依赖**：T01
- **文件**：`scripts/run_backtest.py` (modify)、`tests/unit/scripts/test_run_backtest_cli.py` (modify)
- **预估行数**：+35
- **验收标准**：`parse_args(["--preds","x.npz","--mode","target"]).strong_buy_threshold == 0.0`；
  `--strong_buy_threshold 0.02` → 0.02；target metrics 含 `strong_buy_threshold` /
  `n_skipped_strong_buy` 且旧键全保留；打印含 strong_buy 跳过计数。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03 回归 / 等价性测试 + 全量单测收尾
- **状态**：pending
- **依赖**：T01, T02
- **文件**：`tests/unit/backtest/test_engine.py`、`tests/unit/scripts/test_run_backtest_cli.py` (modify)
- **预估行数**：+40
- **验收标准**：`python -m unittest discover tests/unit` 全绿；改动文件 `ruff check` 无新增报错；
  默认等价性断言通过；rolling 用例不改动仍通过。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04 文档同步
- **状态**：pending
- **依赖**：T01, T02
- **文件**：`README_TRAINING_CHAIN.md` (§3.4)、`docs/per_code_normalization_spec.md` (§5.2)、
  `scripts/README.md` (modify)
- **预估行数**：+15
- **验收标准**：三处口径一致：绝对阈值、默认 0.0=关闭、负数 raise、作用于买入带全部候选、
  不满足留现金不补位、与 `min_edge` 顺序（先 min_edge 后 strong_buy）。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05 交叉测试（3 阈值 × 2 退出 × 3 尺寸）
- **状态**：pending
- **依赖**：T01–T04
- **文件**：`docs/agent/task/20260915_0005_add-strong-buy-gate/HARNESS_PROGRESS.md` (modify)
- **预估行数**：+30
- **验收标准**：size ∈ {5,10,50} × 退出 ∈ {buffer500, exitnp} × 阈值 ∈ {0.0, 0.01, 0.02, 0.03}
  的 annual / excess_annual / `avg_cash_ratio` / `n_skipped_strong_buy` 汇总表落本文件；
  阈值越大现金仓位与跳过数单调不降；阈值 0.0 可复现既有基线；结论区分「强买门槛」单变量影响。
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 交叉测试结果（待 T05 填写）

数据：6 臂 preds（E0–E5）+ `logs/ohlc_full_2026-01-01_2026-08-31.npz`；
评估区间 2026-01-01~2026-08-31（154 交易日）。

| 臂 | size | 退出 | 阈值 | annual | excess | avg_cash | n_skipped_strong_buy |
|---|---|---|---|---|---|---|---|
| - | - | - | - | - | - | - | - |