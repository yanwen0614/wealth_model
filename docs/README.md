# docs/ 文档地图（2026-10-30 整理）

**本文件是文档导航的唯一入口。** 找东西先看这里，不要凭印象在目录里翻。

## 根级文档

| 文件 | 作用 | 维护状态 |
|---|---|---|
| `AGENTS.md` | 给 AI 代理的项目约定（命令、架构、数据契约、坑） | 活文档，改动前先读 |
| `README.md` | 项目对外介绍 | 活文档 |
| `README_TRAINING_CHAIN.md` | 训练链路新人上手指南 | 稳定 |
| `docs/AGENTS.md` | 归一化决策留档约定 | 稳定 |

## `docs/research/` — 研究结论

### 最新总稿（先读这两个）

| 文件 | 内容 |
|---|---|
| `final_delivery_20261030.md` | 策略探索最终交付说明：三年研究全部结论、有效性矩阵、数据边界、联合目标验收状态 |
| `three_day_strategy_report_20261029.md` | 三天工程汇报：W1/W2 八窗、成本、税务、执行假设 |

### `review_20261030/` — 本轮工程整理的完整记录

**入口 = `review_20261030/README.md`**

| 文件 | 回答 |
|---|---|
| `下一次实验必读.md` | **下次动手前必看**：四条真实事故 + 四条硬规范 + 检查清单 + 15 条教训 |
| `五个问题白话回答.md` | 五问的人话版（已过三轮评审 8.0/10） |
| `q1~q5_*.md` | 五个问题的原始探索报告（失败路线/当前进度/可复现性/阻塞/下一步） |
| `fill_gap_analysis_20261030.md` | 八项不可复现能否补（3 不能 / 5 部分 / 1 推翻原判） |
| `quant_source_audit_20261030.md` | quant 源头历史缺口可解性（停牌/上市前/unknown/限价/公司行动/退市） |
| `train_data_stock_audit_20261030.md` | 训练数据侧问题股票排查 |
| `DELETE_PLAN_abandoned_20261030.md` | 14 条放弃路线死代码删除计划与执行 |
| `RESEARCH_CONSOLIDATION_AUDIT_20261030.md` | 研究产物收口审计 |
| `CLEANUP_*_20261030.md` | Temp 清理方案与结果 |
| `worktree_retirement_20261030/` | 工作树退役记录 |
| `recovered_w1_20261030/` | 从会话数据库恢复的 18 个源文件 + 清单 + 原始补丁 |
| `理解测试回答{,2,3}.md` | 三轮可读性评审答卷 |

### `20261026/` — 三天工程的过程文档

正式结论 26 个文件：`price_lineage.md`（价格血缘）、`universe_lineage.md`（股票池血缘）、`verified_state_source_contract.md`（状态源契约）、`ENGINEERING_STATUS.md`（工程状态）、`INDEPENDENT_AUDIT_REPORT_20261027.md`（独立审计）等。**以这些为准。**

`20261026/source_drafts/` 收 33 份原存于 Temp 的 `three_day_*.md` / `*_handoff*.md` / `*_qa_*.md` 过程草稿（2026-10-30 迁入，防证据孤本）。草稿不具权威性，正式版见上级目录；仅对无正式版的主题（candidate_registry、asset_inventory、training_queue 等）作为执行细节参考。

### `worktree_consolidation_20261030/` — 工作树整合索引

含"已提交可复用 / 已永久丢失"两分清册（后者在 18 文件恢复后部分已过时，见 `review_20261030/` 的订正）。

## `docs/` 顶层专题文档

| 文件 | 内容 | 状态 |
|---|---|---|
| `per_code_normalization_spec.md` | **归一化决策唯一事实源**（P/R/N/G 分组 + relative/asinh/clip/robust/winsor/mask），与 `data/schema.py`、`data/scaler.py` 一一对应 | 活文档，改分组先改此表 |
| `prediction_target_and_tree_2026.md` | 预测目标与树模型收口结论（2026-10） | 稳定结论 |
| `ENGINE_MAP_2026.md` | 引擎模块地图 | 稳定 |
| `lambda_ablation_20260906.md` | λ 消融实验（**已证伪**，见 review_20261030/q1） | 历史 |
| `loss_ablation_20260905.md` | 损失函数消融（**旧口径已作废**） | 历史 |
| `retail_winrate_research_summary_20260920.md` | 单票胜率研究（**已证伪，数学不可达**） | 历史 |
| `full_train_todo.md` | 全量训练待办（**未启动**） | 待定 |

## `docs/archive/` — 冻结归档

`paper_jkx_2024-2026_seven_routes.md`（JKX 七路，全灭）、`main_2015-2026_prereg_A.md`（冻结 A，预注册 REJECT）、`logs_manifest.csv`（logs 编目）。**只读，不修改。**

## `docs/agent/` — 任务执行记录

按 `task/YYYYMMDD_HHMM_<名称>/` 组织，每个含 `PLAN.md` / `REVIEW_CHECKLIST.md` / `HARNESS_PROGRESS.md`。
**注意**：2026-09 的旧任务目录多数无状态标记，不代表仍在进行。

## 阅读顺序建议

**新人第一次接触** → `README_TRAINING_CHAIN.md` → `docs/research/final_delivery_20261030.md`

**准备做新实验** → `docs/research/review_20261030/下一次实验必读.md`（强制）

**查某条研究为什么失败** → `review_20261030/q1_failed_research_report.md`

**查某个结论能不能复现** → `review_20261030/q3_reproducibility_report.md` + `fill_gap_analysis_20261030.md`

**要知道下一步做什么** → `review_20261030/q5_next_plan_report.md`

## 已知的文档债务

1. `review_20261030/` 与 `20261026/source_drafts/` 内文件正文引用的绝对路径多为搬迁前的 Temp 位置，未改写（保留原始记录，映射到本目录即可）。
2. `worktree_consolidation_20261030/README.md` 的"已永久丢失"一节写于 18 文件恢复之前，需与 `review_20261030/` 交叉阅读。
3. `docs/` 顶层 `lambda_ablation_20260906.md`、`loss_ablation_20260905.md`、`retail_winrate_research_summary_20260920.md` 均属已证伪研究，保留仅为结论留档，不要据此重启实验。
