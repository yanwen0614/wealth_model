# 当前架构

## 边界

项目分为数据、模型、执行和展示四层。数据层只读 parquet 并负责时段切分、特征窗口和标签；模型层只生成分数或连续策略输出；执行层负责把信号变成可交易订单与账户 NAV；展示层只读取产物，不重新解释或修改指标。

所有实验都应保持 TRAIN/VAL/TEST 的时间边界。旧基线使用 2013~2021 / 2022~2023 / 2024~2025；新数据 daily/joint 链使用 TRAIN 2013~2023、VAL 2024~2025、TEST 2026~，具体实验 README 以自身记录为准。scaler 只在对应 TRAIN 段拟合。

## 主要入口

| 层 | 入口 | 责任 |
|---|---|---|
| 旧数据准备 | `data/prep.py` | 读取列投影、窗口、scaler、q5 标签和 split 检查 |
| HGB 预测 | `models/baseline_hgb.py` | 训练 HGB 回归并输出标准预测文件 |
| 纸面回测 | `backtest/engine.py` | Q1/Q5/基准、费用和 IC/IR 指标 |
| 可实现模型 | `models/train_realizable.py` | 训练可实现开盘到开盘收益方向 |
| 可交易账户 | `backtest/account_engine_v2.py` 至 `v6.py` | T+1 open、整手、费用、滑点、限制和持仓状态 |
| daily 数据与策略 | `models/daily_dataset.py`、`models/daily_portfolio_data.py`、`models/daily_continuous_policy.py` | 每日记录、候选 1000、当前权重输入和 per-name 输出 |
| daily 执行 | `backtest/continuous_daily_executor.py` | 目标权重到整手订单，处理卖先买、现金、费用、滑点和不可交易状态 |
| daily 编排 | `models/run_daily_train_val.py`、`models/run_daily_test_once.py` | TRAIN/VAL 选择和一次性 TEST rollout |
| joint 编排 | `models/joint_portfolio.py`、`models/run_joint_e2e.py` | episode 构造、joint policy、离散账户投影 |
| joint 执行 | `backtest/account_engine_joint.py` | joint 产物的账户结算与最终标记 |

## 调用关系

```text
parquet
  -> data/prep.py -> baseline_hgb.py -> pred parquet -> backtest/engine.py
  -> daily_dataset.py/daily_portfolio_data.py
       -> daily_continuous_policy.py
       -> continuous_daily_executor.py
       -> run_daily_train_val.py / run_daily_test_once.py -> daily artifacts
  -> joint_portfolio.py
       -> run_joint_e2e.py -> account_engine_joint.py -> joint artifacts
```

`REPORT.md`、`STRATEGY.md` 和本目录只读这些产物。服务层仅保留 `service/api.py`，负责展示已有指标和提供基线预测接口，不是新的回测执行器。

## 当前推荐执行器

需要评估可交易策略时，优先使用与 `opt_final` 同口径的 v2 系列账户链：T+1 open、Top100、20 日调仓、滞后 50、100 股整手、卖先买、逐笔费用、成交量滑点、涨跌停和无行情处理。`backtest/AUDIT.md` 是该链的审计依据。

需要研究每日连续动作时，使用 `backtest/continuous_daily_executor.py`；它是当前 daily 链的推荐执行器，输入目标权重和市场快照，不应改写已审计的 V6/v2 执行器。需要研究 joint 时，使用 `account_engine_joint.py` 的修正版投影链，并把结果标作短样本实验。

`artifacts/joint_e2e/` 不在推荐执行路径中：它的 40 日 signal stride 与 40 日 episode 持有期重叠，整个 acceptance run 已失效。
