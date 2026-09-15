# HARNESS_PROGRESS — turnover-industry-attribution

- 任务：`docs/agent/task/20260916_0010_turnover-industry-attribution/`
- 模式：`analyze`（用户确认）——仅分析，不改源码
- 区间：2026-01-05 ~ 2026-08-31（160 交易日），基准沪深300

## 任务状态

| # | 任务 | 状态 |
|---|---|---|
| T01 | 目录/配置/臂解析 + holdings 载入 | ✅ done |
| T02 | 换手率 / 持仓期 / 在持数 | ✅ done |
| T03 | 申万一级映射 + 双基准行业权重 | ✅ done |
| T04 | 逐日行业暴露 + active weight | ✅ done |
| T05 | 行业 P&L 归因 | ✅ done |
| T06 | 汇总报告 | ✅ done |

## 关键结论

1. **出口规则主导换手**：exitnp 17.9×NAV vs b500 48.6×NAV（2.7×），持仓期 21.6 vs 7.9 天。
2. **强买门槛 t=2% 完全无效**（与 t=0 逐位一致）；t=5% 换手降至 12.9–25.3×NAV，但现金比 30–61%。
3. **归一化模式（E0–E5）对行业暴露几乎无影响**（臂间 `mean|active|` 差 <0.01）。
4. **决定性发现**：全部配置总 P&L = -11.77，其中 `801080 电子` = +22.74 → **剔除电子后所有配置整体亏损 34.5**；E0 exitnp_s5 的"最好"来自电子 4 笔交易（平均 +40.4%）。
5. 因此**"E0 最好"的结论需修正**：领先主要来自电子行情的运气，而非稳定选股 α。

## 验证

- `sbg_*_t0.02` vs `t0.00` 恒等校验：PASS
- 复算 `Σ(weight×ret_net)` vs `metrics.annual`：同号同量级（简单求和近似）
- 暴露口径修正（未持有日补 0）后 `mean|active|` 落在 0.024–0.044 合理区间

## 提交

- 本任务为 analyze 模式：**仅提交文档**（PLAN / REVIEW_CHECKLIST / HARNESS_PROGRESS / ATTRIBUTION_REPORT），无源码变更。
- 分析脚本与中间 CSV 位于临时目录 `C:/Users/yanwen/AppData/Local/Temp/opencode/attr/` 与 `logs/attribution_20260916/`（后者被 gitignore）。
