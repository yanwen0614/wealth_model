# PLAN — 换手 + 行业暴露归因

## Goal

对已有回测产物（rolling / target-b500 / target-exitnp / 强买门槛 24 组）做**换手**与**申万一级行业暴露**归因，判定各规则/配置的收益来源是行业押注还是选股，并复盘此前"E0 最好"的结论。

## Mode

`analyze`（依据用户确认）——**不改动仓库源码/不加单测**，临时脚本置于 `C:/Users/yanwen/AppData/Local/Temp/opencode/attr/`，结论落本目录文档。

## Architecture

```
holdings_*.csv (33 目录 × 6 臂)
        │
        ├─► 换手：日单边成交额/NAV → 252×mean
        ├─► 行业暴露：建仓日 point-in-time 申万一级 → 逐日权重均值 → active weight
        │        （基准：沪深300 成分权重 / 全市场等权）
        └─► 收益归因：Σ(weight × ret_net) 按行业汇总
```

## Key Decisions

| # | 决策 | 理由 |
|---|---|---|
| D1 | 换手用 holdings 权重近似，不依赖 NAV 曲线 | 引擎未落 `nav` CSV（仅 png），权重即建仓 NAV 占比 |
| D2 | 行业映射自建二分查找（`IndustryLookup`） | `merge_asof` 报 "right keys must be sorted"，且需 point-in-time |
| D3 | 行业权重对未持有日**补 0** 再取均值 | 否则只对被持有日求均值，系统性高估主动暴露（初版 bug，已修） |
| D4 | 行业 P&L 用简单求和近似 | 无行业指数价格（`kline_index` 无 801xxx），直接法更直观；仅横向比较 |
| D5 | 基准同时给 沪深300 与 全市场等权 | 用户选定；两者差异本身反映指数行业分布偏离 |

## Tasks

| # | 任务 | 产物 | 状态 |
|---|---|---|---|
| T01 | 目录/配置/臂解析 + holdings 载入 | `analyze.py` | done |
| T02 | 换手率、持仓期、在持数 | `out/turnover.csv` | done |
| T03 | 申万一级映射 + 双基准行业权重 | `IndustryLookup`/`bench_weights` | done |
| T04 | 逐日行业暴露 + active weight | `out/industry_active_long.csv`、`industry_summary.csv` | done |
| T05 | 行业 P&L 归因 | `out/industry_pnl.csv` | done |
| T06 | 汇总 + 报告 | `ATTRIBUTION_REPORT.md` | done |

## Verification

- 复算校验：`Σ(weight×ret_net)` 与 `metrics.json` 的 `annual/final_nav` 同号同量级（简单求和近似，允许偏差）
- 恒等校验：`sbg_*_t0.02` 与 `t0.00` 的换手/超额应逐位一致（验证强买门槛 2% 无效）
- 暴露口径校验：修正 D3 后 `mean|active|` 从 0.07–0.09 降至 0.024–0.044（合理量级）
