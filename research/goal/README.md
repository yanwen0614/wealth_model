# goal 项目入口

这是一个独立的端到端盈利验证项目，目标是把预测信号、可交易回测和后续服务验证放在同一套可审计的工程中。项目不作为 `cnn`/`quant` 插件，也不反向修改上游源码。

## 三条代码链

### 1. 旧 HGB 基线：证明信号存在

入口主要是 `data/prep.py`、`models/baseline_hgb.py` 和 `backtest/engine.py`。它使用 5 日收益标签、截面五分位和 HGB 回归，输出 IC、Q1~Q5 和纸面等权组合结果。对应完整方法和结果见 [`REPORT.md`](REPORT.md)，产物集中在 `artifacts/baseline/` 及根 `artifacts/` 下的基线文件。

这条链的定位是信号存在性证明，不等价于真实账户收益。纸面 TEST 的 HGB 结果不能替代 T+1 开盘、整手、费用和滑点口径。

### 2. 可交易账户链：检验执行后是否还能赚钱

入口是 `models/train_realizable.py` 与 `backtest/account_engine_v2.py`/`account_engine_v3.py`/`account_engine_v5.py`/`account_engine_v6.py`。它使用可实现的开盘到开盘标签，并模拟 T+1 开盘、先卖后买、100 股整手、费用、成交量滑点、涨跌停和无行情处理。当前可交易策略口径与限制见 [`STRATEGY.md`](STRATEGY.md)，引擎审计见 [`backtest/AUDIT.md`](backtest/AUDIT.md)。

`artifacts/opt_final/` 是已经完成审计的历史可交易主证据；`opt_extend/top100` 和 `opt_edge/B_extend` 是延长到 2026 的历史实验。它们不能被解读为 2026 充分样本验证。

### 3. 当前 daily continuous / joint 链：连续状态实验

daily 链由 `models/daily_dataset.py`、`models/daily_portfolio_data.py`、`models/daily_continuous_policy.py`、`backtest/continuous_daily_executor.py` 和 `models/run_daily_test_once.py` 组成：每日信号、固定候选池、跨日持仓状态、延迟 5 日奖励和整手账户执行。

joint 链由 `models/joint_portfolio.py`、`models/run_joint_e2e.py` 与 `backtest/account_engine_joint.py` 组成，研究选择 logits 和 replacement gate，再投影到现有账户执行器。`artifacts/joint_e2e_gate_off/` 是当前保留的修正版产物，但 2026 只有 2 个 episode，属于实验观察，不是稳定业绩结论。

当前 daily stride=1 结果在 [`docs/DAILY_CONTINUOUS_STATUS.md`](docs/DAILY_CONTINUOUS_STATUS.md)：TEST 只有 155 个可用信号日，源数据截止 2026-08-31，且账户末端有 **8 个 locked/unpriced holdings**。这两个限制必须随结果一起引用；不能把它描述成完整年度或已清算账户结果。

## 推荐阅读顺序

1. [`docs/experiments.md`](docs/experiments.md)：先看每个产物的状态，决定哪些数字可以使用。
2. [`docs/DAILY_CONTINUOUS_STATUS.md`](docs/DAILY_CONTINUOUS_STATUS.md)：了解当前 daily 链的已验证范围和限制。
3. [`REPORT.md`](REPORT.md)：阅读旧 HGB 基线和可交易账户链的完整方法、口径与历史结果。
4. [`STRATEGY.md`](STRATEGY.md)：阅读当前推荐的分散 Top100 策略口径及实盘缺口。
5. [`docs/architecture.md`](docs/architecture.md)：需要复现或修改代码时，查看模块边界和调用关系。
6. [`artifacts/README.md`](artifacts/README.md)：最后按状态进入具体产物目录。

## 结果优先级

1. **当前研究状态优先**：daily stride=1 和修正版 joint 只用于观察当前链路是否工作；短样本、锁定持仓和 2026 观测不足时，不得外推稳定收益。
2. **可交易历史证据其次**：`opt_final` 的完整账户结果是历史上最完整的可交易验证；`opt_extend/top100`、`opt_edge/B_extend` 用于延长段和执行敏感性判断。
3. **旧 HGB 纸面结果最后**：用于证明排序信号存在，不能覆盖账户链的现实摩擦。
4. **负面和失效结果同等重要**：`opt_trigger` 的触发式方案判负；`artifacts/joint_e2e/` 因 40 日 stride 时序重叠而 **INVALID**，不可作为 VAL、TEST 或性能结论。

## 常用入口与验证边界

以下命令对应仓库中已存在的脚本或文档中已记录的验证入口。这里不把未在当前工作区重跑的全量训练命令标成“已验证”。解释器沿用 `/home/starcyan/code/cnn/.venv/bin/python`。

```bash
# 文档改动的静态检查
git diff --check

# daily synthetic smoke；状态文档记录该 smoke 已通过
/home/starcyan/code/cnn/.venv/bin/python models/run_daily_continuous_smoke.py \
  --outdir artifacts/daily_continuous_runs/smoke

# 已存在的聚焦测试入口；本次文档整理未重跑
/home/starcyan/code/cnn/.venv/bin/python -m unittest \
  tests.test_daily_continuous_smoke -v
/home/starcyan/code/cnn/.venv/bin/python -m unittest \
  tests.test_joint_portfolio -v
```

`models/run_daily_test_once.py` 和 `models/run_joint_e2e.py` 会触及单次 TEST 或完整训练流程，不能作为普通 smoke 反复执行。daily TEST 已按单次 guard 打开；joint 的有效产物路径是 `artifacts/joint_e2e_gate_off/`，不要照抄其 README 中已经过期的 `artifacts/joint_e2e_corrected` 路径。
