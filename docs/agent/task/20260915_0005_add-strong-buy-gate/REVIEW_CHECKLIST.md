# 审查清单 — add-strong-buy-gate

> 生成时间：2026-09-15 00:05
> 依据：需求「target 买入端新增交易规则 s5/s10/s50 —— 需模型给出较强上涨语义才能买」，
> 全部口径已确认（绝对阈值、买入带全部候选、留现金不补位、`--strong_buy_threshold` 默认 0.0、负数 raise）

## 需求理解

在 target 回测的**买入端**新增「强买门槛」：仅当买入带候选的绝对预测收益满足阈值才买入。
- 阈值定义 = 绝对预测收益：`exp_ret >= strong_buy_threshold` 才允许买入。
- 作用范围 = 买入带全部候选（`rank <= target_size`）；不满足阈值的候选被跳过、该槽位留现金、**不补位**。
- 默认 `strong_buy_threshold = 0.0` = 关闭该规则（向后兼容）；负数 raise。
- 与 target 两套退出规则交叉测试：`--sell_buffer 500` 与 `--exit-on-nonpositive`。
- 目标尺寸测试档位：size = 5 / 10 / 50；阈值档位 1% / 2% / 3%。

### 显式假设（实现时按此执行）

1. 阈值比较为 `>=`（恰好等于阈值允许买入）。
2. `strong_buy_threshold > 0.0` 才启用规则；`0.0` 恒为关闭哨兵；`< 0` 抛 `ValueError`。
3. 门槛与 `min_edge` 正交，执行顺序 **min_edge → strong_buy → limit_up**；同一候选先命中者计数。
4. 门槛在 OHLC 行查询 / 涨停检查**之前**评估（纯预测层过滤）。
5. 买入候选来自当日 `order_list`（有预测的样本），`exp_map[s]` 恒存在，买入端无缺预测分支。
6. 持仓端缺预测行为不变（`exit_on_nonpositive` 时缺预测不卖）。
7. skip 计数新增独立桶 `strong_buy`；`skipped[d]` 仅记非零桶。
8. metrics 只增 `strong_buy_threshold` / `n_skipped_strong_buy`，不改名/删除任何旧键。
9. 单槽预算、费用模型、T+1 open 买 / T+6 open 卖时序、退出规则一律不变。
10. 只改 target 模式；rolling 模式、`_simulate`、费用纯函数、`benchmark_index_nav` 不受影响。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|---|---|---|---|
| 回测引擎 | `backtest/engine.py` | 修改 | `run_backtest_target` 增 `strong_buy_threshold`；`skips` 增 `strong_buy`；买入循环新增门槛分支；docstring |
| 回测 CLI | `scripts/run_backtest.py` | 修改 | 新增 `--strong_buy_threshold`；透传；metrics 新键；打印/图题/NOTE |
| 回测引擎测试 | `tests/unit/backtest/test_engine.py` | 修改 | 门槛生效、默认等价、与 min_edge/limit_up 顺序、负数 raise |
| CLI 测试 | `tests/unit/scripts/test_run_backtest_cli.py` | 修改 | 新参数默认值/解析、metrics 旧键兼容 |
| 文档 | `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`scripts/README.md` | 修改 | §3.4 / §5.2 / 选项表补门槛语义与默认值 |
| 进度 | `docs/agent/task/20260915_0005_add-strong-buy-gate/HARNESS_PROGRESS.md` | 修改 | 3×2×3 交叉测试结果表 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 处置 |
|---|---|---|---|
| `strong_buy` | 否 | — | 全新，无重复实现 |
| `min_edge` | 是 | `engine.py:294,317,370-371` / `run_backtest.py:297` / `test_engine.py:351-374` | 保留不动，新门槛与之正交（tail 过滤 vs 全带门槛） |
| `edge_tail_pct` | 是 | `engine.py:294,319` | 保留不动 |
| `skips`/`skipped` | 是 | `engine.py:363,398-399` | 扩展 dict 增 `strong_buy` 桶 |
| `exit_on_nonpositive`/`exit_threshold` | 是 | `engine.py:295,348-349` | 保留不动，交叉测试对象 |
| `sell_buffer` | 是 | `engine.py:294,351` | 保留不动 |
| `n_skipped_min_edge` | 是 | `run_backtest.py:162,168` | 保留，新增 `n_skipped_strong_buy` |
| `strong` 前缀其它实现 | 否 | — | 无冲突 |
| 可复用工具 | 是 | `exp_map`/`order_list`/`rank_map`（`engine.py:417-419`） | 直接复用，无需新建数据结构 |

> 结论：无重复实现；买入带候选、预测映射、skip 结构均可直接复用。费用/基准/退出规则纯函数零改动。

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 参数命名 `strong_buy_threshold` 与 `snake_case` 一致；docstring/类型注解；line-length 120；中文注释 | HIGH |
| 2 | 模块边界 | 门槛逻辑仅在 `backtest/engine.py`；`scripts/*` 只透传不重实现；不侵入 data/models/training/criterion | HIGH |
| 3 | 默认等价 | `strong_buy_threshold=0.0` 时 nav/holdings/skipped 与改动前逐位一致（`> 0.0` 守卫短路） | HIGH |
| 4 | 计数确定性 | min_edge → strong_buy → limit_up 顺序写死；空槽不补位；`skipped[d]` 只记非零桶 | HIGH |
| 5 | 数据安全/校验 | `strong_buy_threshold < 0` raise；无硬编码凭证；不读 parquet | HIGH |
| 6 | 导入合规 | 无通配符/未使用 import；CLI 无新增冗余依赖 | MEDIUM |
| 7 | 错误处理 | 非法阈值显式 `ValueError`；缺预测路径不误触（买入端 `exp_map[s]` 恒存在） | MEDIUM |
| 8 | 性能风险 | 门槛为候选循环内常数次标量比较，无 O(N²)；不改变每槽预算与费用计算路径 | MEDIUM |
| 9 | metrics 兼容 | 只增字段；旧键（`min_edge`/`n_skipped_min_edge`/`target_size`/`sell_buffer` 等）保留；JSON 可解析 | HIGH |
| 10 | rolling 隔离 | `run_backtest`/`_simulate`/`benchmark_index_nav`/费用纯函数无 diff；rolling 单测不改动仍通过 | HIGH |

## 回归风险清单

| # | 风险点 | 验证方式 | 期望 |
|---|--------|----------|------|
| 1 | 默认值等价性 | 同 fixture `strong_buy_threshold=0.0` 与省略参数 / 改动前 NAV 逐位比较 | 完全相等 |
| 2 | rolling 不受影响 | 现有 `TestRunBacktest`/`TestRollingFeeModel`/`TestBenchmarkIndexNav` 不改动仍全绿 | 全绿 |
| 3 | metrics schema 兼容 | 断言 target metrics 含全部旧键 + 两个新键 | 旧键不丢 |
| 4 | 与 min_edge 顺序 | tail 且 `exp < min_edge` 且 `exp < threshold` 用例 | 计 `min_edge` 非 `strong_buy` |
| 5 | 与 limit_up 顺序 | 涨停且 `exp < threshold` 用例 | 计 `strong_buy`（门槛先于涨停） |
| 6 | 空槽留现金 | size=3、仅 1 个候选过阈 | nav ≈ 2/3 现金 + 1/3 买入，无补位 |
| 7 | 阈值档位单调性 | 交叉测试 0.0 < 0.01 < 0.02 < 0.03 | `avg_cash_ratio` / `n_skipped_strong_buy` 单调不降 |
| 8 | 端到端可复现 | 同 preds 同参数两次运行 | NAV 逐位一致 |
