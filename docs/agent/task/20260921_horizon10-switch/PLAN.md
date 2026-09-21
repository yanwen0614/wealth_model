# 20260921_horizon10-switch Implementation Plan

> Generated: 2026-09-21 09:40
> Task Dir: docs/agent/task/20260921_horizon10-switch

## Goal

生产默认标签窗口从horizon=5切换到horizon=10，分桶边界按H10收益分布重定（52类不变），旧缓存自动失效。

## Architecture

仅改两处默认值源（data/dataset.py + config/defaults.py），train.py透传链无需改动；labels.py已参数化、缓存key已含horizon/bins_digest，均确认无改；backtest持有期语义独立，明确不改。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| bins边界 | 推荐±0.35（51等距边界，52类） | 保留±0.25 / 非均匀分位桶 | 覆盖q1≈-0.23/q99≈+0.35（±3.2σ对称）；均匀间距保EMDLoss有序假设；类别数不变则模型/criterion零改动 |
| bins最终值 | **blocked待全量分位数确认** | — | 推荐值基于需求方给出的分布摘要，需全量parquet实测锁定 |
| backtest默认 | 不改（保持horizon=5） | 同步改为10 | 持有期≠标签窗口概念；策略持有期变更另行决策 |
| 缓存版本 | 不bump | bump版本 | key已含horizon+bins_digest，旧缓存自动miss |

## Task Decomposition

### T01: 全量H10分位数验证并锁定bins边界（blocked前置）
- **文件**: `logs/bins_h10_quantile.json` (create)
- **描述**: 全量parquet经is_trading过滤、horizon=10口径求future_ret的std/q1/q99/尾溢出率，确认±0.35
- **依赖**: 无
- **预估行数**: +60（脚本，可放scripts/或一次性命令）
- **验收标准**: q1/q99落在±0.35内且两端尾溢出率<1%；输出json锚定最终边界
- **风险因子**: 分布摘要若与全量实测偏离，边界需重议

### T02: 切换双源默认值（dataset.py + defaults.py）
- **文件**: `data/dataset.py:68-69` (modify, +2), `config/defaults.py:15,20` (modify, +2), `data/dataset.py:1134` (modify, +1)
- **描述**: horizon 5→10；DEFAULT_BINS/dataset默认bins→T01锁定值（推荐±0.35）；探查入口同步
- **依赖**: T01
- **预估行数**: +5
- **验收标准**: `ParquetDataConfig().horizon==10`；`make_default_config()["HORIZON"]==10`；len(BINS)==51且num_classes==52；`--help`显示horizon默认10

### T03: 文档同步（AGENTS.md Data Contract）
- **文件**: `AGENTS.md:50-51` (modify)
- **描述**: horizon=5→10，BINS描述更新（顺带修正train.py:34过期引用→config/defaults.py）
- **依赖**: T02
- **预估行数**: +3
- **验收标准**: 无残留horizon=5标签描述；行号引用可定位
