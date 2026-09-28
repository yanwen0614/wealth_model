# goal 三链复现报告（cnn 现行栈 + F60 最新数据，2026-09-28）

> goal 目录已删；旧源码见 `research/goal/` 快照。本复现不用 goal 旧栈，
> 以 cnn 现行（F53/H10/backtest-core/统一实盘费率）+ F60 全集（70列/1196万有效行）重做三链。
> 运行：`r1_baseline_hgb.py → r2_account_backtest.py → r3_daily_continuous.py`，产物 `runs/`（已忽略）。

## R1 基线（信号存在性）

HGB 回归（16 rank特征，CPU），标签 close[t+5]/close[t]-1（沿 goal 基线口径保可比）：

| fold（预测段） | 日数 | RankIC | Q5-Q1年化 | Q5年化 |
|---|---|---|---|---|
| fold1（2024-07~2025-06） | 242 | **0.1011** | +259.7% | +353.7% |
| fold2（2025-07~2026-08） | 281 | **0.0727** | +147.5% | +164.0% |

goal 锚点 TEST IC 0.0616 / 利差 49.85%：同量级偏强（周期与特征代差，不逐值对标）。
结论：信号存在性在最新数据上成立，且强于 goal 时期。

## R2 可交易（R1 preds → cnn_adapter，统一费用，本金200万）

| fold | rolling top10 | rolling top50 | target s100/buf500 |
|---|---|---|---|
| fold1 | 年化 -43.3% | -0.9% | **+59.5% / Sharpe 1.72 / MDD 18.3%** |
| fold2 | 年化 -15.3% | -15.9% | **+8.3% / Sharpe 0.39 / MDD 25.7%** |

与 goal `AUDIT §7` 同一教训：close 口径纸面 edge 经 T+1 open 执行后，
高换手 rolling Bale 亏光，低换手 target 保住收益。复现确认该结论在新数据上依然成立。

## R3 连续性消融（target buffer=0 vs 500）

| fold | daily_hard(0) | inertia500 |
|---|---|---|
| fold1 | +18.3% / Sharpe 0.74 | **+59.5% / 1.72** |
| fold2 | -12.0% / -0.75 | **+8.3% / 0.39** |

惯性持有两折均胜，回答 goal chain-3 问题：连续性（低换手）优于每日硬切。

## 附带发现（已修）

F60 新 vintage 有 73 行 `is_trading=True` 但 OHLC=0 的脏行（2026-08 停牌误标，
如 000016.SZ 2026-08-24~27）：R1 已过滤；`market.py` 新增 `_optional_price`
（非正报价转 None，禁入引擎，防 core 除零），单测已加。建议上游 quant 修正
`is_trading` 标记。
