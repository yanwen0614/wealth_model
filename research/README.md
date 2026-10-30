# 研究注册表 research/（2026-10-09）

> 本目录是全部实验的唯一入口。规则：只读、不改生产链路；
> 复现脚本+小产物（json/csv）入库，大文件（npz/parquet/pth）留
> `%TEMP%/opencode/`与`logs/`（不入库）；生产代码禁import（ruff快照口径）。
> 红线：2026-01~08烧掉样本不验收，只认2026-09后干净样本。

## 总表（一行一个实验，结论只写这里，各目录README只留复跑方法）

| 实验 | 回答的问题 | 方法/口径 | 结论 | 状态 | 入口 | 代码状态 |
|---|---|---|---|---|---|---|
| goal_repro | goal三链在新数据还成立吗 | 现行栈F53/H10重做R1基线/R2可交易/R3连续性 | 信号存在且更强；rolling亏、target保收益；惯性>硬切 | ✅已完成 | `goal_repro/REPORT.md` | 保留 |
| m_research | m_t能预测吗 | 12方法×EXT37维×expanding WF×诚实滞后门+双塔 | 方向/幅度不可行；仅波动IC+0.18显著【未验证引擎】；双塔方向门证伪 | ✅完成，方向线❄️关闭 | `m_research/REPORT.md` | 保留 |
| precision | 涨精确能买到吗 | precision-coverage/交集/否决，只看VAL2025 | VAL 0.59→0.63~0.64（容量6~13%）；2026全塌，不跨regime | ✅完成，规则包⏳待验收 | `precision/` | 保留 |
| alpha_attribution | 钱从哪来 | r=m_t+α全模型分解 | 2025靠m；2026主/JKX α归零，唯树头部α守住 | ✅完成（归因证据） | `alpha_attribution/` | 保留 |
| unified_recalc | 横向对比口径齐吗 | 交集日期+同脚本+bootstrap | 树胜A显著、与B相当；spread/NAV是噪声 | ✅完成（纠偏） | `unified_recalc/` | 保留 |
| market_neutral | α对冲m后能变现吗 | 纸面topN-bottomN（引擎无空头，只能纸面） | LS存在性成立，但纸面≠可交易 | ✅完成（开口验证） | `market_neutral/` | 保留 |
| goal（快照） | — | 旧栈源码存档，复现不用旧栈 | 存档自述 READ ONLY；结论已由 goal_repro 在新栈重做 | ❌已删除（2026-10-30） | 已删除（代码已移除，结论见 `goal_repro/`） | 已删除 |

图例：✅已完成 / ❄️冻结关闭 / ⏳待干净样本验收 / 🧪候选。代码状态：`保留`（still on disk，可复跑）/ `已删除`（目录已移除，结论由保留目录承载）。

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
- logs侧报告（不入库，只读）：`logs/tree_verify/`（树同口径验证全量表）与 `logs/tree_rebuild/`（重建复现）
  **已于 2026-10-30 删除**（含约 3.21 GB 可再生 npz）。文本证据（json/txt/log 共 63 个文件）另存于
  `D:/code/cnn_full_20260905/logs_tree_evidence_20261030/`。
  - `logs/tree_verify/REPORT.md`（177 行 / 12,295 字节）：**已从会话数据库完整恢复**并回写原位
    （`logs/tree_verify/REPORT.md`，受 `.gitignore` 忽略，故不入库；恢复来源 opencode.db 的 read 快照，
    SHA256 四重校验一致）。
  - `logs/tree_rebuild/SUMMARY.md`（8,909 B / 2026-10-03 10:39:12）—— **不可恢复**。
    2026-10-30 两次独立深度复核（第二次含前一代理漏扫的 event 表 40.7 万行）：
    四表 59 万行、11 个磁盘位置、18 个 opencode 快照 git 库（13 万对象）全零命中；
    并以同批可恢复的 `tree_verify/REPORT.md` 作正向对照，证明扫描器有效。
    根因：写入会话 `ses_f00a30de6ffe0TuNPVHpDCnVkJ` 在 7 天保留期（cleanup prune=7.days）
    后被四表物理删除，2026-10-03 当天在四表中均为 0 行。
    **内容替代**：结论压缩版见 `docs/prediction_target_and_tree_2026.md` 第六节
    （含重建复现的 VAL RankIC 0.1187 / TEST 0.0803 等原始数字）。
  仍在盘上的 logs 侧报告：`logs/m_research/`（门控/双塔引擎指标）。
  结论性内容另见 `docs/research/review_20261030/`（含 `20-专项审计/` 与 `30-清理与退役/`）。
- TEMP是工作草稿区（`%TEMP%/opencode/`下h10/rv/t3/t4/t6等百余文件），只有被本表
  点名收录的脚本+小json才算交付，其余一律视为草稿、不得引用验收。
