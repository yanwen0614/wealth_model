# 研究产物收口审计（2026-10-30）

审计者：只读审计代理。审计时刻：2026-10-30 01:24~01:30（北京时间）。
未修改、未删除、未执行任何 Git 写操作。所有数字均来自实测命令输出。

**并发限制声明**：`docs/research/final_delivery_20261030.md`、`scripts/research/README.md`、`docs/research/worktree_consolidation_20261030/README.md`、`C:/Users/yanwen/AppData/Local/Temp/opencode/recovered_w1_20261030/`、`CLEANUP_*.md` 由其他代理并发修改，本报告**未读取其当前内容**，仅记录其 Git 状态与文件尺寸。

**注意**：审计期间主区 HEAD 从 `997bc71` 前移到 `2cdcb9f`（01:16，另一代理提交了钩子批次）。下表状态以 01:29 的实测为准。

---

## 1. 执行摘要

1. 三棵研究树删除后，**至少 9 个源码 + 5 个测试只在 Temp 或未跟踪文件中存活**，其中 `quantity_rules.py` 在主区工作区、且不在任何 Git 提交里 —— 这是当前最高风险项。
2. `quantity_rules.py` + 其测试 + `staged_order_strategy` 数量规则接线**已在工作区完成且与冻结哈希一致，却从未入库**；一旦工作区被清理即第二次丢失。
3. 任务文档 `20261030_2200_workspace-consolidation` 的计划核心条款（"先归档回读校验再删除"）已被实际执行推翻，且其中 T02/T04/T06 的部分验收项已不可能完成。
4. 仓库文档引用 35 个 Temp 证据目标，其中 **3 个目录已被删除**（引用即断链），其余仍全靠 Temp 存活。
5. 可入库的小体积文本证据约 **56 个文件 / 1.5 MB**（推荐口径），宽口径 76 个 / 3.4 MB；与 5 GB 级 logs、2 GB 级输入目录相比完全可承受。
6. `logs/` 已 5.02 GB（超 T18 的 2 GiB），但 T18 dry-run 计划为空 —— 因为顶层 `run_*` 目录数为 0，阈值实际未生效。
7. `feature/rolling-normalization-cnn` 是 main 的祖先（0 独有提交），属纯冗余分支。
8. core 有 4 个未推送提交，且 cnn 的 wheel 内容精确对应 `893fc96`，不含 `a176be9`。
9. `w1_stop_after_close` 补丁已被 `a176be9` 实际入库，Temp 保留说明"core main 尚无该实现"已过时。
10. `docs/agent/` 有 22 个任务目录、其中 17 个是 9 月旧任务，无索引、无 deprecated 标记。

---

## 2. 未提交/未跟踪项处置表

HEAD = `2cdcb9f`（`git status --short` 实测，2026-10-30 01:29）。

| # | 路径 | 状态 | 判定 | 理由 |
|---|---|---|---|---|
| 1 | `backtest/cnn_adapter/quantity_rules.py` (3958 B) | `??` 未跟踪 | **应提交（P0）** | `git log --all` 对该路径 0 提交；与 `validation_2025_bridge_fix1_20261029/worktree_files_fix1.zip` 内同名文件 SHA-256 完全一致（`d88ed93a…`）；生产 `staged_order_strategy.py` 已 import 它。这是删树后仅存的两份之一（另一份在 Temp 的 ZIP 里）。不提交=再丢一次。 |
| 2 | `tests/unit/backtest/test_quantity_rules.py` (3372 B) | `??` | **应提交（P0）** | 6 个用例，覆盖科创板 200/1/10万、余额全卖、未知代码不猜。与 ZIP 内哈希一致。 |
| 3 | `backtest/cnn_adapter/staged_order_strategy.py` (+28 行) | `M` | **应提交（P0）** | 新增 `quantity_rule_resolver` 注入与买卖两处 `rule.validate`，是 1、2 的使用方；与 ZIP 内 `4101d8af…` 一致。当前 HEAD 的版本（`493ff85`）不含此逻辑，二者必须同批入库，否则 HEAD 与工作区语义分叉。 |
| 4 | `tests/unit/backtest/test_staged_order_strategy.py` (+38 行) | `M` | **应提交（P0）** | 上述接线的用例；与 ZIP 内 `d391b88c…` 一致。 |
| 5 | `scripts/audit_walkforward_execution.py` (+66/-5) | `M` | **应提交（P1）** | 新增 `_verify_label_endpoints`（逐样本核验 `open[t+11]/open[t+1]-1`，误差门 3e-6）与 `bins_version` 真实哈希，替换 "unknown" 占位。属研究审计工具的可信度改进，不是用户 WIP（与 Temp 里冻结的 2025 链无关）。 |
| 6 | `_check_signals.py` (1176 B) | `??` | **应删除** | 仓库根目录的一次性探针，硬编码 `Temp/three_day_signals/W1_F4_full_CPU_v1` 路径，无测试无引用。放根目录会污染 `compileall`/ruff 范围。 |
| 7 | `.opencode/memory/HISTORY.md` (+31) / `MEMORY.md` (+53/-37) | `M` | **应提交（P1）** | 记忆子系统运行期写回，已被跟踪（`.gitignore` 有 `!.opencode/memory/`），不提交会持续显示脏。 |
| 8 | `docs/research/20261026/PARALLEL_WORKSPACES.md` (+13) | `M` | **应提交（P1）** | 更新为"core 树已退休、893fc96 收口"及新增"收尾与清理"立约；与 consolidation 工作直接对应。 |
| 9 | `docs/research/20261026/f4_signal_delivery.md` (+18) | `M` | **应提交（P1）** | 新增 W2 交付与独立复核段（538599 行/4424 码、signals SHA256、禁止当作可执行证明）。 |
| 10 | `docs/research/20261026/state_acquisition_request_v2.md` (+1/-1) | `M` | **应提交（P2）** | 仅改采集 owner 会话 ID（旧会话已交接）。 |
| 11 | `docs/research/three_day_strategy_report_20261029.md` (26298 B) | `??` | **应提交（P0）** | 三天工作的唯一自洽汇报，被 `final_delivery_20261030.md:155` 引用；不提交则总稿引用断链。 |
| 12 | `docs/agent/task/20261030_2200_workspace-consolidation/` (3 文件 6928 B) | `??` | **提交但须先改写（P1）** | 见第 3 节：计划已被执行推翻，直接提交会把错误计划固化。 |
| 13 | `docs/research/final_delivery_20261030.md` (29056 B) | `??` | **待定（由并发代理收口）** | 按约束未读取内容；仅记录未跟踪状态。 |
| 14 | `docs/research/worktree_consolidation_20261030/README.md` | `M` | **待定（由并发代理收口）** | 同上，未读取内容。 |
| 15 | `scripts/research/README.md` | `M` | **待定（由并发代理收口）** | 同上，未读取内容。 |
| 16 | `.gitignore` / `.gitattributes` / `scripts/githooks/post-checkout` | 已干净 | **已收口** | 实测已在 `2cdcb9f` 提交（`git show --stat HEAD`：3 files, +107）。审计开始时它们显示为未跟踪，现已被另一代理提交。`core.hooksPath` 已设为绝对路径。 |

**结论**：第 1~4 项是同一个功能切口，必须一次提交；这是"整棵 CA 树删除后残留在工作区"的唯一存活副本。

---

## 3. 失效任务文档清单（含行号）

目录 `docs/agent/task/20261030_2200_workspace-consolidation/`，共 3 文件 6928 B，全部未跟踪。

### 3.1 `PLAN.md`（31 行）

| 行号 | 现文要点 | 与实际执行的冲突 | 建议 |
|---|---|---|---|
| 16 | "每树退役前**归档**修改、未跟踪…建立 SHA-256 和恢复说明；**从归档回读逐项校验后才可删除**" | 实际按用户新指示"直接删除不存档"执行（`worktree_retirement_20261030/REPORT.md:16-21,42`），此条**从未执行**，且已不可能追溯执行 | 标注为"被 2026-10-30 用户指示取代" |
| 9 | "W1 fractional、attestor、ledger 和 2025 限制入口**保留在 research archive**" | 这些源码已永久丢失（`git log --all` 对 9 个路径均 0 提交）；不存在 archive | **标记不可完成** |
| 13 | "已确认主区及三棵研究树均为 ce7d1c6" | 不准确：CA 树 HEAD 实为 `79cc2b7`（早于合并），且主区已到 `997bc71`→`2cdcb9f` | 标注基线误判 |
| 28 | T03 验收"研究代码归档且隔离入口" | 研究代码未归档即被删，验收不成立 | **标记未通过** |
| 29 | T04 验收"引用可回溯，未删除受保护数据" | 引用已断链（3 个被引 Temp 目录消失，见第 4 节）；受保护数据虽保留，但源码未归档 | **标记部分失败** |
| 30 | T05 "独立质量门…问题关闭或明确阻塞" | 未对最终代码/文档做独立质量门即退役 | **标记未执行** |
| 31 | T06 验收"归档清单、校验记录及退役记录齐全，失败则保留原树" | 退役记录齐全，但**归档清单与校验记录不存在**；未按失败分支保留树 | **标记违反自设验收** |

### 3.2 `REVIEW_CHECKLIST.md`（22 行）

| 行号 | 失效条目 | 说明 |
|---|---|---|
| 4 | "整合后逐项核对 WIP 哈希" | 未产出核对记录 |
| 5 | "W1 fractional/attestor/ledger 与 2025 限制入口仅进 research archive" | 源码已丢失，无从归档 |
| 9 | "ignored 数据逐项审阅，**不删除**…用户证据" | 未做逐项审阅清单；数据确实未删，但审阅证据缺失 |
| 10 | "stop_after_close patch 完整归档并回读验 hash，**未默认并入生产**" | 部分失效：`a176be9` 已在 core main **正式提交**（2026-10-30 00:50），不再是"仅归档"状态 |
| 17 | 关卡 1"文件清单冻结" | 无冻结产物 |
| 20 | 关卡 4"每树归档含修改、未跟踪、重要 ignored，逐项回读 hash" | **全部未执行** |
| 21 | 关卡 5"独立审查最终代码…记录冻结版本" | 未执行 |
| 6 | 全项复选框均为 `[ ]` | 无任何勾选证据，文档状态与实际不符 |

### 3.3 `HARNESS_PROGRESS.md`（18 行）

| 行号 | 现文 | 问题 |
|---|---|---|
| 3 | "状态：计划已创建；**后续执行任务均未开始**" | 直接与事实矛盾：CA 候选已合入（`79cc2b7`）、4 棵树已退役、索引 README 已产出 |
| 7-12 | 6 个任务全部"未开始" | 同上；T01/T03/T06 实际已发生（尽管未按计划形态） |
| 16 | "独立 backtest-core 的具体工作树位置及 dirty patch 清单尚待 T01 核实" | 已核实并处置（patch 已保留，且已被 `a176be9` 覆盖） |
| 15 | "主区与三棵研究树基线均为 ce7d1c6" | 与 `PLAN.md:13` 同一误判 |

**总判定**：该任务文档应**改写为"事后事实记录 + 明确标注失效条款"**，而不是原样提交。它现在同时存在"计划写了但没做"和"做了但计划不允许"两类矛盾，是最容易误导后续阅读者的文档。

---

## 4. 证据孤本风险（量化）

### 4.1 仓库文档引用的 Temp 目标（`Grep "AppData/Local/Temp/opencode" docs/`）

共 35 个不同目标，全部位于 `C:/Users/yanwen/AppData/Local/Temp/opencode/`。实测存在性：

| 目标 | 被引文档 | Temp 现状 | 体积 |
|---|---|---|---|
| `corporate-action-fix-20261027` | final_delivery:20 | **已删除** | — |
| `w1-fractional-scenarios-20261028` | final_delivery:21 | **已删除** | — |
| `validation-2025-restricted-20261029` | final_delivery:22 | **已删除** | — |
| `staged_prepared_inputs_20261027_v12` | final_delivery:128、three_day:153 | 存在 | **2,017,982,250 B（1.88 GiB）** |
| `state_acquisition_20261027` | state_acquisition_request_v2:33 等 2 篇 | 存在 | 115,239,478 B / 9,216 文件 |
| `state_acquisition_main_audit_20261027_v3` | three_day:147 | 存在 | 5,048,543 B |
| `state_gap_lifecycle_20261027_v2` | three_day:147 | 存在 | 8,004,692 B |
| `signal_probe_W1_two_codes` | margin_time_audit:16 | 存在 | 1,609,261 B |
| `three_day_signals` | f4_signal_delivery:15 | 存在 | 20,845,841 B |
| `board_exposure_audit_20261027_v1` | state_collection_and_board_rules:30 | 存在 | 296,133 B |
| `worktree_retirement_20261028` | **5 处**（final_delivery 三处 + three_day:155 等） | 存在 | 37,976,517 B（含 3 个 ZIP） |
| `w2_goal_acceptance_review_20261029` | three_day:133、final_delivery:155 | 存在 | 7,507 B |
| `eight_windows_second_audit_20261028` | three_day:134 | 存在 | 9,504 B |
| `w2_mechanical_risk_review_20261028` | three_day:135 | 存在 | 99,234 B |
| `w2_exposure_evidence_20261028` | three_day:136 | 存在 | 62,543 B |
| `w2_tax_fifo_independent_qa_20261029` | three_day:137 | 存在 | 20,119 B |
| `validation_2025_ab_v2_abort_audit_20261029` | three_day:138 | 存在 | 5,990 B |
| `validation_2025_000601_official_20261029` | three_day:139 | 存在 | 3,586,394 B（含 3.3 MB PDF） |
| `validation_2025_000506_official_20261029` | three_day:140 | 存在 | 741,401 B |
| `w1_real_prefix_independent_audit_20261029` | three_day:144 | 存在 | 64,137 B |
| `w1_ceil_failure_root_cause_20261029` | three_day:145 | 存在 | 9,397 B |
| `w1_prefix_fix5_20261028` | three_day:146 | 存在 | 11,076 B |
| `existing_oos_evidence_inventory_20261028` | three_day:148 | 存在 | 14,323 B |
| `clean_exam_data_inventory_20261028` | three_day:152 | 存在 | 12,657 B |
| `prospective_exam_feasibility_20261028` | three_day:152 | 存在 | 15,373 B |
| 根级单文件 8 个（`price_lineage_probe.py`、`universe_lineage_probe.py`、`technical29_prefix_probe.py`、`three_day_*aggregate/sample/claims*.json/md`、`state_acquisition_audit_delivery_20261027_v2.json`、`checkpoint_compat_delivery_20261026.md`） | 5 篇 20261026 文档 | 全部存在 | 约 200 KB |
| `attr` | 20260916 任务文档 ×2 | 存在但**空目录**（0 文件） | 0 |

**断链数：3**（`final_delivery_20261030.md` 第 20/21/22 行指向的三个已删目录）。

### 4.2 小体积文本证据 vs 大体积数据

对 22 个仍存在的引用目录做实测分档：

| 口径 | 文件数 | 字节 | 说明 |
|---|---|---|---|
| 全部文件 | 14,034 | 2,211,662,370（2.06 GiB） | 含 1.88 GiB 输入快照 |
| `< 5 MB` 且 md/json/sha256/txt | 343 | 17,662,438 | **宽口径**，含 state 逐码原始响应 JSON 265 个 |
| 同上但排除 `state_acquisition_20261027/` 原始响应 | 76 | 3,406,046 | 中等口径 |
| `< 1 MB` 且 md/sha256/txt，或"具名结论类 JSON"（manifest/summary/QA/REPORT/identity/SOURCE） | **56** | **1,495,637** | **推荐入库口径** |
| 仅 `.md` | 25 | 140,817 | 极端最小口径 |

其中推荐口径 56 个文件的构成：`.json` 25 个 / 1,346,044 B、`.md` 25 个 / 140,817 B、`.sha256` 2 个 / 2,680 B、`.txt` 4 个 / 6,096 B。

**估算结论**：把推荐口径归档进 `docs/research/`，约 **56 文件 / 1.46 MB**，其中真正承载结论的 `.md`+`.sha256`+`.txt` 只有 31 个 / 150 KB。对比仓库现有 `docs/research/` 27 个文件、`research/` 约 3.9 MB，这个体量完全可入库。

**不可入库项（保持不变）**：`staged_prepared_inputs_20261027_v12`（1.88 GiB 输入快照）、`state_acquisition_20261027`（115 MB 原始响应，可考虑只留 manifest）、`three_day_signals`（20 MB parquet/npz）、`worktree_retirement_20261028` 的 3 个 ZIP（约 38 MB）、`validation_2025_000601` 的 3.3 MB PDF（是否入库属政策选择，建议入库，因其是唯一官方原件）。

### 4.3 已删源码的"第二份"现状（关键发现）

5 个被认为"已永久丢失"的源码，实际在 Temp 中仍有两处副本，但均有硬缺陷：

| 源码 | 位置 | 状态 |
|---|---|---|
| `fractional_scenarios.py` (11368 B) / `fractional_prefix_gate.py` (3939 B) / `fractional_scenario_cli.py` (6666 B) / `prefix_attestor.py` (12819 B) / `validation_2025_bridge.py` (14785 B) / `validation_2025_execution.py` (24603 B) / `scripts/run_2025_restricted.py` (53360 B) | `Temp/opencode/recovered_w1_20261030/replay/` | **属并发代理产出，按约束未读取内容**；仅记录存在与尺寸 |
| 同名（更小版本） | `recovered_w1_20261030/replay2/`（如 `fractional_scenarios.py` 仅 3121 B） | 同上；`replay` 与 `replay2` 尺寸差异巨大，**不能判断哪个是原始版本** |
| `validation_2025_bridge.py` / `validation_2025_execution.py` / `run_2025_ab_execution.py` + 2 测试 | `Temp/opencode/validation_2025_bridge_fix1_20261029/worktree_files_fix1.zip` | **可验证**：5 个文件 SHA-256 与同目录 `SOURCE_HASHES.json` 的 `fix1_delivered_files` **逐一 MATCH**；`REPORT.md` 记录 199 项 unittest / ruff / Pyright 通过（2026-10-29） |
| `prefix_ledger_verifier.py`、`scripts/run_2025_restricted.py`（ZIP 外） | 无命中 | 遍历 Temp 全部 9 个 ZIP，`fractional/attestor/ledger` 关键字命中 **0** |

**结论**：`validation_2025_bridge.py`、`validation_2025_execution.py`、`scripts/run_2025_ab_execution.py` 及其 2 个测试**并非永久丢失**——`worktree_files_fix1.zip`（110,179 B）+ `SOURCE_HASHES.json`（4,597 B）+ `complete_diff_fix1.patch`（331,372 B）构成一套自校验、可恢复的交付包。当前 `final_delivery_20261030.md` 第 97 行称其"永久丢失"**与实测不符**（该文件由并发代理维护，此处仅记录事实分歧，不要求其修改）。

---

## 5. `research/` 目录现状

全部 7 个子目录共 150 个跟踪文件，无未跟踪源码（`git ls-files --others --exclude-standard -- research/` 返回 0）；另有 96 个 `__pycache__/*.pyc` 被忽略。最后修改时间统一为 2026-10-10，符合"冻结快照"特征。

| 子目录 | 已跟踪 | 总文件 | 跟踪字节 | 总字节 | 性质 |
|---|---|---|---|---|---|
| `alpha_attribution` | 6 | 8 | 61,018 | 75,491 | **冻结点快照**（报告+JSON产物+2脚本） |
| `goal` | 93 | 161 | 1,620,983 | 3,070,555 | **冻结只读**（`README_ARCHIVE.md` 明示 READ ONLY，源自 `~/code/goal` master `88d851c`） |
| `goal_repro` | 6 | 10 | 15,047 | 35,580 | **活代码（但为一次性复现链）**：`r2/r3` 有 `from research.goal_repro.common import …`，`runs/` 被 `.gitignore:33` 忽略 |
| `m_research` | 28 | 46 | 426,664 | 575,412 | **冻结点快照**（README 明示"研究+预注册，不得转产"） |
| `market_neutral` | 4 | 5 | 9,091 | 14,989 | **冻结点快照**（纸面验证，明示不得写成回测收益） |
| `precision` | 5 | 6 | 69,055 | 83,421 | **冻结点快照**（大 npz 不入库） |
| `unified_recalc` | 7 | 9 | 24,343 | 40,007 | **冻结点快照**（深审纠偏产物） |
| 根 `research/README.md` | 1 | 1 | — | 3,251 | 索引 |

**`research/goal` 冻结验证**：`grep "from research\.|import research|research\.goal"` 全仓（排除 `.venv`）**仅 2 处命中**，均在 `research/goal_repro/` 内部（`r2_account_backtest.py:15`、`r3_daily_continuous.py:14`），且导入的是 `research.goal_repro.common`，**不是 `research.goal`**。`backtest/`、`training/`、`data/`、`models/`、`config/`、`scripts/`、`tests/` 下 **0 处** 引用 `research.*`。生产代码未 import goal，冻结声明成立。

**ruff 边界**：`pyproject.toml:114-121` exclude 了 `research/goal`、`research/precision`、`research/alpha_attribution`、`research/unified_recalc`、`research/market_neutral`、`scripts/frozen`。**注意 `research/m_research` 与 `research/goal_repro` 未 exclude** —— 它们仍在 ruff 检查范围内，与其"研究/预注册不得转产"的定位不一致（`m_research` 有 17 个 py 文件，其中大量 sklearn/xgboost 试验脚本）。

**结论**：7 个目录中 6 个是冻结点快照，`goal_repro` 是可重跑的复现链。无需迁移或清理，但建议补 `m_research`/`goal_repro` 的 ruff 边界决议。

---

## 6. 分支与 worktree 残留

### 6.1 cnn 仓库

`git worktree list`（实测）：**仅 1 项** —— `D:/code/cnn_full_20260905/cnn 2cdcb9f [main]`。与 `worktree_retirement_20261030/REPORT.md:46` 一致（该处记 `997bc71`，因审计期间前移）。

`git branch -a`（实测）：

| 分支 | 远端 | 状态 | 判定 |
|---|---|---|---|
| `main` | `origin/main` = `116cb31` | 本地领先 **33 个提交**、落后 0 | 见下 |
| `feature/rolling-normalization-cnn` | `origin/feature/rolling-normalization-cnn` = `250225e` | **是 main 的祖先**（`git merge-base --is-ancestor` 返回 0）；`main..feature` 独有提交 **0** 个；`feature..main` 有 **55** 个 | **可删（P2）**：纯冗余，内容已全部进入 main |

- 无额外 worktree、无 detached HEAD、无 stash 依赖。

### 6.2 main 与 origin 的 33 个未推送提交

`git log --oneline origin/main..main` 显示本地 `main` 从 `95e3443`（2026-09-xx）到 `2cdcb9f`（2026-10-30）共 33 个提交未推送，`origin/main` 停在 `116cb31`（2026-10-25 23:04）。这是**整个十月下旬的工作全部只在本地**，不是本次审计引入的问题，但风险等级很高（唯一副本=本地磁盘）。

### 6.3 backtest-core 仓库

`git worktree list`：仅 1 项 —— `D:/code/cnn_full_20260905/backtest-core a176be9 [main]`。
`git branch -a`：仅 `main`，无远端分支残留。
`git status --short`：**干净**（0 项）。

### 6.4 同级其他仓库

`D:/code/cnn_full_20260905/` 下有 `cnn`（git）、`backtest-core`（git）、`quant`（git）、`.config`（非 git）。`quant` 未在本任务范围内，未审计。

---

## 7. core 未推送提交表

`git -C backtest-core log --oneline origin/main..main`：**4 个本地提交**，`git rev-list --left-right --count origin/main...main` = `0 4`（落后 0、领先 4），`origin/main` = `8aa82f2`。

| 提交 | 时间 | 内容 | 依赖关系 | 建议 |
|---|---|---|---|---|
| `40f9612` | 2026-10-26 16:13 | 集成公司行动与执行基线、净值/终端契约（15+ 文件，含 `contracts/account_actions.py` 136 行、`engine/account_runner.py` +250） | 基座，被后续 3 个提交依赖 | **应推送（P1）** |
| `987ee0f` | 2026-10-26 20:42 | 权威成交观察器、稳定订单身份、`execution_feedback.py` 98 行 | 依赖 40f9612 | **应推送（P1）** |
| `893fc96` | 2026-10-26 22:12 | 固定股数限价订单、法定价格界裁决、schema 1.3 | 依赖 987ee0f | **应推送（P1）** |
| `a176be9` | 2026-10-30 00:50 | `stop_after_close` 收盘后停止并留存待执行挂单（`account_runner.py` +30、`test_account_orders.py` +44） | 依赖 893fc96；**cnn 的 wheel 尚不包含它** | **应推送（P1）**，但须先决定 cnn wheel 是否重建 |

**关键事实（实测，非推测）**：

1. cnn 的 `wheels/backtest_core-0.1.0-py3-none-any.whl`（125,130 B，mtime 2026-10-26 22:14）内 `backtest_core/engine/account_runner.py` 为 87,970 B，SHA-256 `AA156EC2…`；`.venv` 内安装副本**完全相同**（`direct_url.json` 指向该 wheel，`RECORD` 记录 `qhVuwu5_…` 即 base64url 的 `AA156EC2…`）。
2. `893fc96` 的 `account_runner.py` 为 86,136 B，**归一化 EOL 后 SHA-256 与 wheel 完全一致**（`f77462f4…`）。
3. `a176be9` 的 `account_runner.py` 为 87,677 B，哈希 `0bb5c30c…`，**与 wheel 不同**。即 **cnn 生产运行时用的是 893fc96 语义，不含 `stop_after_close`**。
4. `w1_stop_after_close_20261030.patch`（8,143 B，SHA `D13E06BB…`）内容等价于 `git diff --binary 893fc96 a176be9`（归一化 EOL 后逐字节相等），**其改动已被 `a176be9` 正式提交**。因此该补丁的保留理由（`REPORT.md:30` "主 core 的 main 尚无 `stop_after_close` 实现"）**已过时**，`a176be9` 在补丁保留前一天就已提交。

**建议**：4 个提交应一起推送（它们构成连续依赖链，单独推送任一会破坏 main 可编译性）。推送前须决定：cnn 是否重建 wheel 以纳入 `a176be9`；若暂不重建，须在 cnn 侧显式记录"wheel 身份 = 893fc96，core 远端 = a176be9"的身份差。

---

## 8. 仓储卫生

### 8.1 `docs/agent/` 旧任务堆积

- `docs/agent/task/` 下 **22 个任务目录**、跟踪 **64 个文件**、66 个跟踪文件合计 465,783 B。
- 其中 **17 个是 9 月任务**（`20260904`~`20260928`），最新代码提交停在 2026-09-29。
- **无 `deprecated`/`closed` 标记机制**：17 个目录中的 `HARNESS_PROGRESS.md` 里，15 个含"完成/PASS/收口"字样，但仍有 5 个（`20260904_2359_emd-p0-bins-map`、`20260905_dual-head`、`20260905_1000_cross-section-topk-metrics`（无 progress 文件）、`20260921_horizon10-switch`、`20261030_2200_workspace-consolidation`）无完成标记。
- `docs/agent/issue/` 仅 1 项（`20260908_rolling-normalization-export`），已 2026-09-29 停止更新。
- **风险**：`docs/agent/task/20260921_horizon10-switch` 描述 H10 切换，而 `20260904_2359_emd-p0-bins-map` 描述旧 bins；二者在同一目录并列且都无状态标记，新读者无法判断哪个是现行口径。同类问题还有 `20260905_dual-head`（双头实验）后来被放弃但目录无痕迹。

### 8.2 `scripts/` 可被误用的废弃脚本

| 脚本 | 问题 | 风险 |
|---|---|---|
| `scripts/h10_rolling/` | 目录**只剩 `__pycache__/*.pyc`**（7 个 pyc，61,038 B），源码已 `git mv` 到 `scripts/frozen/`。目录本身未被跟踪、也**未被 `.gitignore` 明确忽略**（仅靠 `*.pyc` 规则间接忽略）。 | 中：残留的 pyc 可被 `python -m` 意外导入，且 `h10_rolling` 名字暗示"活跃目录" |
| `scripts/run_backtest.py` | `from backtest.engine import …`（第 34 行）—— 直连**已被 legacy guard 默认 raise** 的旧引擎（`tests/unit/backtest/test_engine_legacy_guard.py:31` 断言 `run_backtest()` 默认抛错）。文件头 docstring 称"adapter 唯一路径骨架"，与实际 import 矛盾。 | **高**：这是"看起来是官方 CLI 但默认会抛错"的组合，最容易被误用 |
| `scripts/README.md` | 第 3-7 行自述"部分口径（F45/horizon=5）已过时，仅作历史记录"，但正文仍以"当前共同契约"口吻描述 F=45/horizon=5，与现行 F=80（或 `--no-cs_rank --no-mkt-factors` 时 F=53）/H10 不符 | 中：与 `docs/archive/data_contract_F53_H10_adapter.md` 冲突，且未指向它 |
| `scripts/frozen/*`（9 文件 + README） | 冻结声明清楚（生产禁 import），实测 `backtest/`、`training/`、`data/`、`models/`、`config/`、`scripts/`（除 frozen 自身）**0 处引用** | 低：边界守住了 |
| `scripts/run_eval_full.sh` | 被 `scripts/README.md` 引用 16 次，但内容仍是旧的 `h10_rolling` 链路 | 低-中：脚本本身不属主链路 |

**关键发现**：`scripts/run_backtest.py` 的 "CLI 入口" 与 `backtest.engine` 的 "默认 raise" 是结构性矛盾。生产入口应为 `backtest/cnn_adapter/*`，该脚本应显式标注 deprecated 或删除。

### 8.3 `logs/` 体积与 T18 轮转

实测（`logs/` 递归）：**697 文件 / 5,386,845,683 B ≈ 5.02 GiB**，远超 T18 的 2 GiB 阈值。

| 顶层目录 | 文件数 | 体积 | 最后修改 |
|---|---|---|---|
| `tree_verify` | 58 | **2,333,651,149 B（2.17 GiB）** | 2026-10-03 |
| `tree_rebuild` | 44 | **1,117,337,589 B（1.04 GiB）** | 2026-10-03 |
| `relative` | 261 | 907,861,887 B（866 MB） | 2026-10-26 |
| `KEEP` | 279 | 413,420,028 B（394 MB） | 2026-09-29 |
| `m_research` | 14 | 216,508,129 B（206 MB） | 2026-10-08 |
| `retail_relative` | 7 | 44,676,724 B（43 MB） | 2026-09-29 |
| 17 个 `bt_*` | 17 | 约 30 KB | 2026-09-29~10-10 |
| 根级散落文件 | 10 | 约 355 MB（`preds_*.npz` 6 个 + json） | — |

**T18 阈值实际未生效（关键发现）**：

- `log_manager.collect_rotation_plan('logs', keep_last_n=10, max_total_bytes=2*1024**3)` **实测返回 `{'keep': [], 'delete': [], 'total_bytes': 0}`**。
- 原因：`log_manager/__init__.py:164` 只遍历**顶层**且 `name.startswith("run_")` 的目录。当前 `logs/` 顶层 `run_*` 目录数 = **0**（`run_*` 全部在 `logs/KEEP/` 下有 34 个、`logs/relative/` 下 23 个、`logs/retail_relative/` 下 1 个，均为二级）。
- 因此 **5.02 GiB 的占用完全逃过 T18 监管**，且 `docs/archive/logs_manifest.csv` 只覆盖到 2026-09-29（340 行），`tree_verify`、`tree_rebuild`、`m_research` 三个最大目录**均不在编目内**（实测 `UNCATALOGED_TOPDIRS` 列出 17 项）。
- 这不违反 T18 字面约定（它只管 `run_*`），但意味着**"2 GiB 上限"是虚假安全感**。

### 8.4 其他卫生项

- `.gitignore` 未忽略 `scripts/h10_rolling/`：实测 `git check-ignore scripts/h10_rolling` 返回 exit=1（未忽略），仅其中的 `.pyc` 因 `*.pyc` 被忽略。目录本身是空壳（仅 `__pycache__`），但会在 `git status` 中"隐身"。
- `research/` 下 96 个 `__pycache__/*.pyc` 被忽略但占据目录空间（`goal` 161 文件中 68 个是 pyc）。
- `logs/KEEP/` 内有 8 个未跟踪的 `.py`/`.log`（`analyze_trades.py`、`check_cash_leverage.py`、`dl_csrank_output.log` 等），`KEEP` 语义上"永不自动删"，但这些脚本未编目。
- 33 个 dangling git 对象中，**无任何 commit 含 `fractional/attestor/ledger_verifier/validation_2025/run_2025` 路径**（已逐一 `git ls-tree -r` 校验）。即**无法从 git 对象库恢复丢失源码**，这排除了最后一条技术恢复路径。

---

## 9. 优先级 TODO

### P0 — 必须做（不做会造成不可逆损失或事实错误）

| # | 事项 | 理由 | 不做的风险 |
|---|---|---|---|
| P0-1 | **立即提交 `quantity_rules.py` + `test_quantity_rules.py` + `staged_order_strategy.py` + `test_staged_order_strategy.py` 四件套**（一次提交） | 四者构成同一功能切口；`git log --all` 对这些路径 0 提交；生产代码已 import `quantity_rules`。这是三树删除后的**唯一存活副本**（另一份在 Temp ZIP 里，Temp 可被清） | 工作区一旦被 clean/切分支/误删，第二次永久丢失，且生产 import 立刻断裂 |
| P0-2 | **把 `docs/research/three_day_strategy_report_20261029.md` 提交** | 它是三天工作的唯一自洽汇报，被 `final_delivery_20261030.md:155` 直接引用 | 总稿引用断链；三天工作结论只剩一份由并发代理维护的单点文档 |
| P0-3 | **备份 `validation_2025_bridge_fix1_20261029/` 整套交付包到仓库内（或第二物理位置）** | 实测 5 个源码 SHA-256 与 `SOURCE_HASHES.json` 全部 MATCH，且 199 项测试通过，是可自校验、可恢复的完整交付。当前**仅存在于 Temp 一个位置** | Temp 被清则 2025 受限链真正永久丢失；`final_delivery` 现称其"永久丢失"是错误结论，会误导放弃恢复 |
| P0-4 | **修正 `final_delivery_20261030.md:30-33、91、97、172-173` 的"永久丢失"表述**（交由文档 owner 执行） | 第 97 行称 `validation_2025_bridge.py`/`validation_2025_execution.py`/`run_2025_ab_execution.py` 及 2 测试"永久丢失"，但实测 ZIP 内 5 文件哈希全 MATCH | 读者据此放弃恢复，造成实际损失；且与事实不符的文档会削弱整套证据可信度 |
| P0-5 | **改写 `docs/agent/task/20261030_2200_workspace-consolidation/` 三份文档后再提交** | 见第 3 节：`PLAN.md:16` 的归档要求从未执行、`PLAN.md:9` 已不可完成、`HARNESS_PROGRESS.md:3` "均未开始"与事实矛盾 | 原样提交会把"计划未执行"固化为历史记录，且 T06 验收条款（`PLAN.md:31`）被自身违反却无标注 |

### P1 — 应该做（影响可信度、可维护性或存在显著单点风险）

| # | 事项 | 理由 | 风险 |
|---|---|---|---|
| P1-1 | 把约 **56 文件 / 1.46 MB** 的推荐口径文本证据归档进 `docs/research/evidence_20261030/`（附 manifest + SHA256） | 35 个被引 Temp 目标中 3 个已断链，其余全靠 Temp 单点存活；推荐口径体量仅 1.46 MB | 继续依赖 Temp，随时可能二次断链；已被删除的 3 个目录证明这不是假设风险 |
| P1-2 | **推送 main 的 33 个未推送提交** | 整个十月下旬工作仅存于本地磁盘，`origin/main` 停在 2026-10-25 | 本地磁盘故障 = 整月工作丢失；与 P0-1 同类风险但量级更大 |
| P1-3 | **推送 core 的 4 个提交**（`40f9612`/`987ee0f`/`893fc96`/`a176be9`，一条依赖链，须一起推） | 同上；且 `w1_stop_after_close` 的唯一性论断已依赖 core main 是否含该实现 | core 侧同样只剩本地副本 |
| P1-4 | 在 cnn 侧显式记录 wheel 身份差：wheel = `893fc96` 语义，core 远端 = `a176be9`；并决定是否重建 wheel | 实测 wheel 内 `account_runner.py` 哈希与 `893fc96` 完全一致、与 `a176be9` 不同。AGENTS.md 要求"升级需 bump+build+lock" | 生产运行的核心语义与仓库声明不一致，属静默身份漂移 |
| P1-5 | 修正 T18 轮转失效：`log_manager/__init__.py:164` 只扫顶层 `run_*`，而当前顶层 `run_*` 数为 0，5.02 GiB 完全逃过监管 | 实测 `collect_rotation_plan` 返回空计划，与"2 GiB 上限"严重不符 | 磁盘持续增长；`tree_verify` 2.17 GiB + `tree_rebuild` 1.04 GiB 均为 2026-10-03 旧产物，无编目 |
| P1-6 | 更新 `docs/archive/logs_manifest.csv`：补录 `tree_verify`/`tree_rebuild`/`m_research`/17 个 `bt_*` | 340 行编目只到 2026-09-29，实测 17 个顶层目录未编目 | 无法判断哪些 logs 可删；T18 立约的"逐项编目"形同虚设 |
| P1-7 | 标注 `scripts/run_backtest.py` 为 deprecated 或删除 | 该文件 `from backtest.engine import …`，而该引擎由 legacy guard 默认 raise；docstring 却称"adapter 唯一路径骨架" | 使用者运行即报错，且会误以为旧引擎仍可用 |
| P1-8 | 清理 `scripts/h10_rolling/` 空壳（仅剩 7 个 pyc） | 源码已全迁移到 `scripts/frozen/`；该目录未被 `.gitignore` 显式忽略 | 残留 pyc 可被意外导入，目录名误导为活跃 |
| P1-9 | 给 `docs/agent/task/` 22 个目录加状态索引（现行/已完结/已废弃），至少处理 5 个无完成标记的 | 17 个 9 月目录与 10 月目录并列、无状态区分；H10 vs 旧 bins、dual-head 等已废弃实验无痕迹 | 新读者无法判断现行口径，容易引用废弃结论 |
| P1-10 | 提交 `.opencode/memory/*` 及 3 个已修改的 20261026 研究文档 | 均为本工作直接产出的记录更新，长期显脏会掩盖真实改动 | 持续脏工作区，后续无法用 `git status` 判断新增变化 |

### P2 — 可选（清理与优化，无紧迫风险）

| # | 事项 | 理由 |
|---|---|---|
| P2-1 | 删除 `_check_signals.py`（仓库根一次性探针，硬编码 Temp 路径） | 污染 ruff/compileall 范围；无测试无引用 |
| P2-2 | 删除 `feature/rolling-normalization-cnn`（本地 + 远端） | 实测是 main 的祖先，独有提交 0 个，纯冗余 |
| P2-3 | 删除或归档 `w1_stop_after_close_20261030.patch` | 其内容已被 `a176be9` 完整提交；`REPORT.md:30` 的保留理由已过时 |
| P2-4 | 为 `research/m_research`、`research/goal_repro` 补 ruff exclude 决议 | 二者定位为研究/复现，但未在 `pyproject.toml:114-121` 的 exclude 名单中 |
| P2-5 | 修正 `scripts/README.md` 的 F45/horizon=5 表述或加显式跳转 | 正文与现行 F=80/H10 冲突，且未指向 `docs/archive/data_contract_F53_H10_adapter.md` |
| P2-6 | 清理 `logs/` 无编目大目录前先做 dry-run 清单 | `tree_verify`（2.17 GiB）/`tree_rebuild`（1.04 GiB）为 2026-10-03 旧产物，但需先确认是否仍被引用 |
| P2-7 | 让 `docs/research/20261026/README.md:22` 的"本归档未提交/推送"与现状对齐 | 该文件已被 `d46655d` 提交，表述过时 |

---

## 附录 A：本次审计的关键实测证据

| 断言 | 实测方式 | 结果 |
|---|---|---|
| `quantity_rules.py` 无任何提交 | `git log --all --oneline -- <path>` | 0 行（对 9 个丢失源码路径同样为 0） |
| 工作区四件套 = Temp ZIP 内四件套 | SHA-256 对比 | 4/4 一致（`d88ed93a`/`414855dd`/`4101d8af`/`d391b88c`） |
| 2025 受限链 5 文件可恢复 | `SOURCE_HASHES.json` vs ZIP | 5/5 MATCH |
| Temp 所有 ZIP 无 fractional/attestor/ledger | 遍历 9 个 ZIP 的 namelist | 命中 0 |
| git 对象库无法恢复丢失源码 | `git fsck --dangling` 33 对象逐一 `ls-tree -r` | 命中 0 |
| wheel = `893fc96` 语义 | 归一化 EOL 后 SHA-256 三方对比 | `f77462f4` 三方一致；`a176be9` 为 `0bb5c30c` |
| T18 轮转计划为空 | `collect_rotation_plan('logs', 10, 2GiB)` | `{'keep': [], 'delete': [], 'total_bytes': 0}` |
| `feature/rolling-normalization-cnn` 无独有提交 | `git rev-list --count main..feature` | 0（反向 55） |
| `research/goal` 未被生产 import | 全仓 grep `research\.` | 仅 2 处，均在 `goal_repro` 内部导入 `goal_repro.common` |
| 主区未推送提交数 | `git rev-list --count origin/main..main` | 33 |
| core 未推送提交数 | `git rev-list --left-right --count origin/main...main` | `0 4` |



