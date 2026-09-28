# 实验状态索引

状态含义：`current` 表示当前入口或当前保留的研究参考；`experimental` 表示可继续研究但不能作为稳定结论；`historical` 表示已完成、用于历史比较；`invalid` 表示因口径或泄露问题不得使用；`negative` 表示该方案已被判负；`smoke` 只证明链路可运行。

| 产物 | 状态 | 可用事实 | 使用边界 |
|---|---|---|---|
| `artifacts/daily_continuous_runs/20260906_gpu_stride1_full` | **current / experimental** | daily stride=1 的完整 GPU TRAIN/VAL 与一次性 2026 TEST；TEST 155 个可用信号日、总收益 5.28%、Sharpe 0.439、8 个 locked/unpriced holdings | 2026 不是完整年度，样本短；8 个锁定/无价持仓必须保留，不作为稳定业绩结论 |
| `artifacts/joint_e2e_gate_off` | **current / experimental** | 41 日 stride 修正版；TRAIN 56、VAL 10、TEST 2 episodes；gate-off VAL 年化 23.3767%，2026 两期总收益 1.1132% | 2026 只有两期，非统计结论；joint 的 score 是投影权重，不是旧 HGB future-return score |
| `artifacts/opt_extend/top100` | **historical** | 2026 延长段的分散 Top100 账户实验，事实记录见 `REPORT.md` §5.8 | 用于延长段比较，不覆盖当前 daily/joint 链，也不扩展为充分样本验证 |
| `artifacts/opt_edge/B_extend` | **historical** | Top100、跌出前 300 卖、min-edge 0.01 的执行延长实验；事实记录见 `REPORT.md` §5.8 | 执行敏感性历史结果；不能与 daily continuous 结果混合比较 |
| `artifacts/opt_final` | **historical** | 200 万、Top100、T+1 open、20 日调仓、滞后 50 的完整可交易结果；年化 46.12%、Sharpe 1.4383、回撤 18.43% | 当前最完整的历史账户证据，仍受 2024~2025 样本和既有局限约束 |
| `artifacts/joint_e2e` | **invalid** | 40 日 stride 与 episode 持有期产生时序重叠；目录 README 已明确 INVALID | 不得作为 VAL、TEST、接受标准或性能结论 |
| `artifacts/opt_trigger` | **negative** | 每日触发式调仓触发率高、交易和成本显著增加；`STRATEGY.md` 记录为不采纳 | 仅保留作负面对照，不是推荐执行规则 |
| `artifacts/daily_continuous_runs/20260906_gpu_stride20_100x20` | **experimental** | 目录当前仅有 `checkpoint.pt` 和 `selection.json`，未在现有状态文档中形成可引用的账户结论 | 不自行补写指标；需要单独报告和口径审计后才能升级状态 |
| `artifacts/daily_continuous_runs/smoke` | **smoke** | synthetic daily smoke 用于验证连续状态和延迟奖励队列 | 不能与真实数据账户结果比较 |

## 结果阅读规则

- 当前链看 `daily_continuous_runs/20260906_gpu_stride1_full` 和 `joint_e2e_gate_off`，但两者都必须带短样本限制。
- 历史可交易证据看 `opt_final`，延长段看 `opt_extend/top100` 和 `opt_edge/B_extend`。
- 纸面 HGB 结果见根 [`REPORT.md`](../REPORT.md)；它是信号证据，不是账户验收。
- `joint_e2e` 的任何 `v6_raw` 曲线、Q5 或 benchmark 数字都不能被引用。
