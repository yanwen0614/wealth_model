# goal 研究快照归档说明（READ ONLY）

> 来源：`~/code/goal`，`master 88d851c`（2026-09-12，`cleanup: drop service layer`）。
> 归档方式：精简快照（源码 `.py` + 文档 `.md` + 小指标 `.json`），**不含** `data/*.parquet（7.5G）`
> 与 `artifacts/*` 二进制（6.9G，见 `artifacts/MANIFEST.md` 索引）。
> 本目录为只读历史存档，不参与 `cnn` 主链路构建；解释器沿用 `cnn/.venv`。

## goal 工程定位（三条代码链）

1. **旧 HGB 基线**（信号存在性证明）：`data/prep.py → models/baseline_hgb.py → backtest/engine.py`，
   5日收益标签 + 截面五分位 + HGB 回归。纸面 TEST（HGB）不能替代 T+1 可交易口径。
2. **可交易账户链**（执行后是否赚钱）：`models/train_realizable.py → backtest/account_engine_v2~v6.py`，
   可实现 `open[t+6]/open[t+1]-1` 标签（存盘 score 取负使用），T+1 open、先卖后买、100股整手、
   佣金万2.5（min5）+印花卖万5+过户双边万1、成交量滑点、涨跌停/停牌处理。主证据 `artifacts/opt_final/`。
3. **daily continuous / joint 链**（连续状态实验）：`models/daily_* + backtest/continuous_daily_executor.py`
   与 `models/joint_portfolio.py + backtest/account_engine_joint.py`。均为短样本实验观察，非稳定业绩结论。

## 结果优先级与引用禁令

1. daily stride=1（`artifacts/daily_stride1/`）：TEST 仅 155 信号日（源数据截止 2026-08-31），
   8 个 locked/unpriced 持仓必须随结果引用，不得描述为完整年度/已清算结果。
2. joint gate_off（`artifacts/joint_e2e_gate_off/`）：2026 仅 2 episode，非统计结论；score 为投影权重，
   非旧 HGB future-return score。
3. 历史可交易证据：`opt_final`（分散 Top100 年化+46.12%）> 延长段 `opt_extend/top100`、`opt_edge/B_extend`。
4. `joint_e2e/`（40日 stride 时序重叠）：**INVALID**，任何数字不得引用。
5. `opt_trigger`（每日触发式）：**判负**，仅作负对照。
6. 个人版 Top20+1亿护栏已被 2026 熊市证伪（-24.44%），推荐分散版。

## 与 cnn 主链路的口径差（禁直接对比数字）

| 项 | goal（本存档） | cnn 主链路（2026-09-28 起） |
|---|---|---|
| 特征 | 39 raw + 6逐列mask = 45（`vendor_scaler v2`，旧G1~G9） | 52 raw P18/R16/N12/G6 + 1共享mask = F53 |
| 标签 horizon | H5（close5d / realizable / daily5 / joint41） | 默认 H10，BINS ±0.38（`2391436` 起） |
| 回测 | v2~v6 账户引擎群 | 单套 `backtest-core` + `cnn_adapter/goal_adapter` |

cnn 侧同期 cousin 研究（`models/retail_friendly/`、`scripts/h10_rolling/`、`scripts/*retail*`、
`paper_jkx/`、`docs/archive/`）超出 goal 范围，H10 与 goal H5 数字禁止直接对比。
