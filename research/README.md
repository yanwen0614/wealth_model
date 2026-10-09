# 研究注册表 research/（2026-10-09）

> 本目录是全部实验的唯一入口。规则：只读、不改生产链路；
> 复现脚本+小产物（json/csv）入库，大文件（npz/parquet/pth）留
> `%TEMP%/opencode/`与`logs/`（不入库）；生产代码禁import（ruff快照口径）。
> 红线：2026-01~08烧掉样本不验收，只认2026-09后干净样本。

## 总表（一行一个实验，结论只写这里，各目录README只留复跑方法）

| 实验 | 回答的问题 | 方法/口径 | 结论 | 状态 | 入口 |
|---|---|---|---|---|---|
| goal_repro | goal三链在新数据还成立吗 | 现行栈F53/H10重做R1基线/R2可交易/R3连续性 | 信号存在且更强；rolling亏、target保收益；惯性>硬切 | ✅已完成 | `goal_repro/REPORT.md` |
| m_research | m_t能预测吗 | 12方法×EXT37维×expanding WF×诚实滞后门+双塔 | 方向/幅度不可行；仅波动IC+0.18显著【未验证引擎】；双塔方向门证伪 | ✅完成，方向线❄️关闭 | `m_research/REPORT.md` |
| precision | 涨精确能买到吗 | precision-coverage/交集/否决，只看VAL2025 | VAL 0.59→0.63~0.64（容量6~13%）；2026全塌，不跨regime | ✅完成，规则包⏳待验收 | `precision/` |
| alpha_attribution | 钱从哪来 | r=m_t+α全模型分解 | 2025靠m；2026主/JKX α归零，唯树头部α守住 | ✅完成（归因证据） | `alpha_attribution/` |
| unified_recalc | 横向对比口径齐吗 | 交集日期+同脚本+bootstrap | 树胜A显著、与B相当；spread/NAV是噪声 | ✅完成（纠偏） | `unified_recalc/` |
| market_neutral | α对冲m后能变现吗 | 纸面topN-bottomN（引擎无空头，只能纸面） | LS存在性成立，但纸面≠可交易 | ✅完成（开口验证） | `market_neutral/` |
| goal（快照） | — | 旧栈源码存档，复现不用旧栈 | READ ONLY | ❄️冻结 | `goal/` |

图例：✅已完成 / ❄️冻结关闭 / ⏳待干净样本验收 / 🧪候选。

## 待验收队列（预注册冻结后、2026-09后新数据一次性考试）

1. 波动风控缩放（草案见`m_research/REPORT.md §5`，方向门禁止加入）。
2. B×HGB N200交集 / 输家否决规则包（见`precision/README.md`）。
3. 树辅助集成（归因+统一重算支撑，先离线融合，权重亦须预注册）。

## 与 docs/、logs/ 的关系（防迷路）

- 总收口：`docs/prediction_target_and_tree_2026.md`；总图：`docs/ENGINE_MAP_2026.md`。
- 历史（自带历史声明、不混入口径）：`docs/loss_ablation_20260905.md`、
  `docs/lambda_ablation_20260906.md`（F45/close-close时代）、
  `docs/retail_winrate_research_summary_20260920.md`（75%不可达四路验证）、
  `docs/full_train_todo.md`（换卡后执行，未执行）、`docs/archive/`（冻结A/七路关闭/大扫除编目）。
- logs侧报告（不入库，只读）：`logs/tree_verify/REPORT.md`（树同口径验证全量表）、
  `logs/tree_rebuild/SUMMARY.md`（重建复现）、`logs/m_research/`（门控/双塔引擎指标）。
- TEMP是工作草稿区（`%TEMP%/opencode/`下h10/rv/t3/t4/t6等百余文件），只有被本表
  点名收录的脚本+小json才算交付，其余一律视为草稿、不得引用验收。
