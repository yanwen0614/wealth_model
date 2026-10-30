# 研究回顾包索引（2026-10-30）

本目录收 2026-10-30 工程整理与三天研究回顾的全部产物。新接手者从这里读起。

## 先读这两份

| 文件 | 作用 |
|---|---|
| **`00-必读/下一次实验必读.md`** | **下次动手前先看这个。** 四条真实事故 + 四条硬规范 + 开工/跑中/收尾检查清单 + 15 条具体教训 |
| `00-必读/五个问题白话回答.md` | 五个问题的完整人话版答案：①试了哪些路 ②当前有什么 ③能不能复现 ④卡在哪 ⑤下一步。已过三轮可读性评审（8.0/10） |

> 说明：这五个问题的**原始探索报告（q1~q5）已删除**，其全部结论已并入上面这份白话版（第 3/7/8/9/10 节逐一对应）。删除前已提交入库（`3d422bb`），需要原文可用 `git show 3d422bb:'docs/research/review_20261030/10-五问探索/q1_failed_research_report.md'` 取回。

## 专项审计（`20-专项审计/`）

| 文件 | 内容 |
|---|---|
| `fill_gap_analysis_20261030.md` | 八项不可复现能否补（3 不能 / 5 部分 / 1 推翻原判可补） |
| `quant_source_audit_20261030.md` | quant 源头历史缺口可解性：缺口不是取数漏，是源头本无行情 |
| `train_data_stock_audit_20261030.md` | 训练数据侧问题股票排查 |
| `RESEARCH_CONSOLIDATION_AUDIT_20261030.md` | 研究产物收口审计（P0 TODO 来源） |
| `DELETE_PLAN_abandoned_20261030.md` | 14 条放弃路线死代码删除计划与执行 |

## 清理与退役（`30-清理与退役/`）

| 项 | 内容 |
|---|---|
| `CLEANUP_PLAN_20261030.md` / `CLEANUP_RESULT_20261030.md` | Temp 目录清理方案与结果（含 uv 缓存回收 8.17 GiB） |
| `worktree_retirement_20261030/REPORT.md` | 四棵工作树退役记录 |
| `recovered_w1_20261030/` | 恢复过程的**身份与校验记录**（REPORT + MANIFEST + verification + scan_records + raw_patches_index + rebuild_v5） |
| **代码清理（2026-10-30）** | 三批删除，共约 19.5 GB 可再生/已证伪产物：①`research/goal/`（旧栈只读快照，93 个已跟踪文件，提交 `0d85715`，结论已由 `research/goal_repro/` 新栈重做）；②`logs/tree_verify/` + `logs/tree_rebuild/`（3.21 GB 可再生 npz，小文本证据 63 个另存 `D:/code/cnn_full_20260905/logs_tree_evidence_20261030/`，**⚠️ `REPORT.md`/`SUMMARY.md` 两个 md 被保全脚本漏掉 .md 扩展名而误删，恢复状态待确认**）；③`paper_jkx/logs/`（16.27 GB JKX 七路产物，48 个小文本证据另存 `D:/code/cnn_full_20260905/paper_jkx_logs_small_evidence/`，结论见 `docs/archive/paper_jkx_2024-2026_seven_routes.md`）。失败的实验清单与"为什么可以删"见 `00-必读/五个问题白话回答.md` 第 3.1 节 |

> `recovered_w1_20261030/` 只保留 6 个记录文件。18 个恢复出的源码已随 `8cd25a9` 进入主仓库（逐字节相同，无需在文档里留副本）；739 个恢复中间产物（`work/` 调试输出、`raw_patches/` 621 个补丁、`evidence2.json` 6.2 MB、`scripts_used/`）已移出仓库，完整副本在 `D:/code/cnn_full_20260905/evidence_tmp_20261030/recovered_w1_20261030/`（SHA256SUMS 覆盖）。

## 评审记录（`90-评审记录/`）

`review-round1.md`（7.5）、`review-round2.md`（7.5）、`review-round3.md`（8.0）——三轮可读性评审答卷，记录文档如何被逐轮挑错并修正，可作为"文档质量自查"的范例。

## 注意

1. 本目录内文件正文引用的绝对路径多为**写作时的原始位置**（整理前在 Temp）。保留原始记录未改写，阅读时映射到本目录即可。
2. 大体积证据数据不在此处，已复制保全至 `D:/code/cnn_full_20260905/evidence_tmp_20261030/`（7 个根、5,863 文件、~13.4 GB、逐文件哈希、4812/4812 校验通过）。
3. 本目录已入库（`3d422bb`）。
