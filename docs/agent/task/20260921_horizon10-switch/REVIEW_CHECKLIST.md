# 审查清单 — 20260921_horizon10-switch

> 生成时间：2026-09-21 09:40
> 需求：生产默认标签窗口 horizon=5 → 10（含分桶边界适配，52类不变）

## 影响范围（已逐项核实）

| # | 文件 | 操作 | 核实结论 |
|---|------|------|----------|
| 1 | data/dataset.py:68-69 | modify | horizon默认5→10；bins ±0.25→待定（51边界/52类不变） |
| 2 | data/dataset.py:1134 | modify | `__main__`探查horizon=5→10（与默认一致） |
| 3 | config/defaults.py:15,20 | modify | HORIZON 5→10；DEFAULT_BINS同步；改此文件即够（train.py:141默认取HORIZON，:213/:278-279透传） |
| 4 | data/labels.py | 确认无改 | `_future_ret_open_open`已参数化，与horizon无关 |
| 5 | data/dataset.py:427-429, feature_cache.py:90-110 | 确认无改 | 缓存key已含horizon+bins_digest，旧缓存自动失效，无需bump版本 |
| 6 | backtest/engine.py:3,124,195 | 不改 | 持有期语义≠标签窗口；默认5保留，调用方显式传参 |
| 7 | 根AGENTS.md:50-51 | modify | Data Contract中horizon=5、BINS引用同步更新 |

## bins边界决策表（52类/51边界为硬约束，EMDLoss有序假设不变）

| 候选 | 边界 | 结论 |
|------|------|------|
| 保留±0.25 | linspace(-25,25,51)/100 | 淘汰：H10 std≈0.11，尾部溢出严重 |
| **推荐±0.35** | linspace(-35,35,51)/100 | q1≈-0.23/q99≈+0.35全覆盖，±3.2σ对称，num_classes不变 |
| 非均匀分位桶 | 按H10分位数定界 | 淘汰：破坏EMD均匀间距假设，复杂度高 |

## 单测影响（全显式传参，默认变化不破坏）

| 单测 | horizon写法 | 结论 |
|------|-------------|------|
| test_dataset_label_openopen.py UT5:93 | 显式horizon=5/2 | 不受影响 |
| test_data_feature_pipeline.py | 显式horizon=1 | 不受影响 |
| test_context_warmup_windows.py | 显式2/5/1 | 不受影响 |
| test_dataset_cache.py/test_feature_cache.py | 显式key | 不受影响 |
| test_config_defaults.py | 断言52类/51边界 | H10保持52类即过 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 52类不变 | len(BINS)==51，num_classes==52，EMDLoss有序假设不断 | HIGH |
| 2 | 全量H10分位数验证 | 全市场is_trading过滤+horizon=10口径求q1/q99/std，确认±0.35覆盖 | HIGH |
| 3 | 默认一致性 | dataset.py与defaults.py的horizon/bins双源一致 | HIGH |
| 4 | 缓存隔离 | 新旧key互异，旧缓存miss而非误命中 | MEDIUM |
| 5 | 回测隔离 | engine.py默认未动，标签/持有期概念未混淆 | MEDIUM |
| 6 | 文档同步 | AGENTS.md无残留horizon=5描述 | LOW |
