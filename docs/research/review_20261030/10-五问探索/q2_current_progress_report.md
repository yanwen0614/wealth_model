# Q2 当前研究进度盘点（只读探索报告）

**日期：2026-10-30（实测窗口 12:03–12:17 本地时间）**
**角色：五个串行探索中的第二个。回答"现在手里到底有什么"，不重复 Q1 的失败路线罗列。**
**性质：只读。未修改/删除任何仓库文件，未执行任何 git 写操作。唯一新增文件是本报告。**
**前置输入：`q1_failed_research_report.md`（26 条路线：14 放弃 / 5 条件保留 / 4 待重做 / 3 未启动）。**

> 环境实测：Python 3.12.13、torch 2.12.0+cu130（CUDA 可用）、numpy 2.5.2、pandas 3.0.5、pyarrow 25.0.1、ruff 0.16.5、backtest_core 0.1.0。
> **本机 venv 无 pytest、无 coverage、无 plotly**（`python -m pytest` → ModuleNotFoundError），因此本文所有"测试"均用 `python -m unittest` 实跑，与 AGENTS.md 的 CI 同路径口径一致。

---

## 1. 一页纸摘要

### 1.1 HEAD 状态（`git log --oneline -3` / `git rev-parse` 实测）

| 仓库 | 分支 | HEAD | 与 origin/main | 提交总数 | 工作区 |
|---|---|---|---|---|---|
| `D:/code/cnn_full_20260905/cnn` | main | `05047f4` docs(task): 订正工作区整合任务文档中已失实的现状表述 | **完全同步**（HEAD == origin/main，`HEAD..origin/main` = 0） | 173 | 5 个 tracked-modified，0 个 untracked |
| `D:/code/cnn_full_20260905/backtest-core` | main | `df38c2e` merge: 合入远端 AGENTS.md wheel 发布与 v0.1.0 基线文档 | **完全同步**（0 差异） | 19 | **完全干净**（`git status --porcelain` 0 行） |

两仓库均只剩单工作树（`git worktree list` 仅主区），CNN 本地分支仅 `main` + `feature/rolling-normalization-cnn`（remote-only）。

### 1.2 测试状态（全部实测，红绿分明）

| 门 | 结果 | 结论 |
|---|---|---|
| CNN `ruff check .` | **All checks passed**（exit 0） | 绿。CI 零告警门成立 |
| core `ruff check .` | **All checks passed**（exit 0） | 绿 |
| core `unittest discover -s tests` | **Ran 718 tests / OK**（0.71s） | **全绿**，与预期 718 完全一致 |
| CNN T16 最小门（5 文件 58 项） | **Ran 58 / OK** | 绿，与 CI 选择同路径 |
| CNN 全量 `discover -s tests`（带 `CNN_ALLOW_LEGACY=1`） | **Ran 982 / FAILED（failures=2, errors=10, skipped=40）** | **红：12 项**（详见 §3.3） |
| CNN 全量（不带 env） | Ran 982 / FAILED（failures=2, **errors=50**, skipped=40） | 其中 40 项为 legacy 守卫环境性报错，非真缺陷 |

**关键结论：CI 门（ruff + 58 项）全绿且可复现；仓库级全量 982 项有 12 项真红，全部是"测试与现行 API 漂移 / 可选依赖缺失 / pytest-only 夹具"三类，无一是 backtest 引擎或数据契约的失败。**

### 1.3 资产状态

| 资产 | 状态 |
|---|---|
| 外置证据根 `Temp/opencode/` | **完好**：171 个目录、41,020 文件、**24.3 GB**；抽查 25 个关键目录 25/25 存在 |
| 八窗机械结果 | 完好：8 策略目录、138 文件、7.72 GB；`summary.json` 可读，W2 四策略数值完整 |
| W1 前缀真实运行证据 | 完好：v2（187 文件 / 4.28 GB）+ 独立审计 + fix5 + reverify4 均存在 |
| 2025 A/B 真实回放 | 完好：v2 目录 58 文件 / 2.66 GB，`run_summary.json`/`account_status.json` 可读 |
| 恢复证据 `recovered_w1_20261030` | 完好：745 文件（含 MANIFEST/raw_patches/recovered） |
| `logs/KEEP/` | **完好**：33 个顶层目录、279 文件、0.39 GB；`baseline/{best_model.pth 15,014,178 B, config.json}` 均在 |
| 训练 parquet（3.4 GB） | **可读**：11,413,377 行 × 58 列、11 rowgroups（只读 footer，未加载数据） |
| F60 parquet（4.28 GB，至 2026-08-31） | 存在且可读 |
| 行情/指数 | kline 5,215 文件均至 2026-09-30；`000300.SH` 3,338 行至 2026-09-30、**2026-10-01 后 0 行** |

### 1.4 三个本次新发现（旧报告没有写死的）

1. **CNN 侧安装的 core wheel 落后 core main 一个提交**：`.venv` 里的 `backtest_core/engine/account_runner.py` 内容等于 core `893fc96`（LF 归一 SHA `f77462f4…`），**不含 `a176be9` 的 `stop_after_close`**；core HEAD `df38c2e` 该文件为 `0bb5c30c…`。且 CNN 仓库 `backtest/` 全树 **0 处引用 `stop_after_close`**——W1 cutoff 能力在 CNN 侧根本不可调用（需 bump wheel + lock）。
2. **`prefix_attestor.fixed_source_sha256()` 的 15 项 pin 实测 4 通过 / 10 不一致 / 1 路径不存在**（不是旧报告的"11 项不符"）。这就是 `test_prefix_attestor` 与 `test_prefix_ledger_verifier` 各 1 error 的直接原因。
3. **`fractional_scenarios.py`、`prefix_attestor.py` 与 `run_2025_restricted.py` 的当前字节已不等于恢复基线**（分别被 `436cb73`、`d5c0dc3`、`bb4ddd8+9c15347+ff7e606` 改过），`recovered_w1_20261030/verification.json` 的 18 项里现有 **10 项一致 / 8 项不一致**。也就是说"恢复态"已被后续修复覆盖，证据链需要按提交重新对账。

### 1.5 离目标还差几件事

**一句话：缺 5 件具体的事——① core wheel 与 CNN 对齐（含 stop_after_close）；② 8 个 W1 版接口重建 + pin 重签；③ 2026-09 后基准/信号/账本链补齐；④ 一次事前冻结的 ≤10 持仓连续考试；⑤ 把 12 项测试红清成绿以恢复全量可信度。**（拆分见 §5.3）

---

## 2. A 节：代码资产（全部以 git 实查为准）

### 2.1 2026-10-27~30 入库提交清单与作用（`git log --oneline --since=2026-10-27`，共 21 条）

| 提交 | 日期 | 作用（一句话） | 规模 |
|---|---|---|---|
| `ab1138b` | 10-30 | 新增 `quantity_rules.py`（板别数量规则）并接线到 `staged_order_strategy` 买入前校验 | 4 文件 +218 |
| `8cd25a9` | 10-30 | **从 opencode.db 快照恢复 18 个 W1/2025 研究源文件与测试**（fractional_scenarios/prefix_attestor/prefix_ledger_verifier/validation_2025_bridge/execution/run_2025_*） | 18 文件 +6382 |
| `ff7e606` | 10-30 | 给 `run_2025_restricted.py` 导入块挂 `# noqa: I001` 守 CI 零告警（不改语义） | 1 文件 +3/-1 |
| `436cb73` | 10-30 | 修 `fractional_scenarios` 十处缺陷 + 补 `announcement_visibility` 键，7 个依赖未回收接口的用例改显式 skip | 2 文件 +32/-2 |
| `9c15347` | 10-30 | 2025 受限入口"既审身份校验"延迟化，修 4 个套件 import 期即崩 | 5 文件 +160/-25 |
| `d5c0dc3` | 10-30 | `prefix_attestor` 源码 pin 改按内容身份比对，消除 CRLF 行尾误伤 | 1 文件 +32/-1 |
| `bb4ddd8` | 10-30 | `run_2025_restricted` 的"干净解释器守卫"延迟化，整包同进程收集不再崩 | 1 文件 +18/-5 |
| `2cdcb9f` | 10-30 | 新增 `scripts/githooks/post-checkout`：worktree 自动链接主区 `.venv` | 钩子 |
| `997bc71` | 10-29 | merge `79cc2b7`（CA 候选运行收口树合入主区） | merge |
| `79cc2b7` | 10-29 | **CA 六模块收口**：`corporate_action_context`、`corporate_action_snapshot_loader`、`raw_market_inputs`、`raw_market_provider`、`staged_candidate_runner`、`staged_production_inputs` + 6 测试 + 研究索引 | 14 文件 +3761/-7 |
| `ce7d1c6` | 10-27 | 记录全量状态补采审计与科创板数量规则（文档） | docs |
| 其余 10 条 | 10-30 | 均为 docs / memory / task 文档订正（`84ca4fe` 入库三天总稿、`05047f4` 现状订正、`d2d0810` W1 接口缺失描述、`db6e1b2` 测试失败形态表述等） | 仅文档 |

**core 侧同期入库**（`git log` 19 条）：`893fc96`（固定股数限价 + 法定价格界）、`a176be9`（cutoff 收盘后停止 + 留存待执行挂单）、`df38c2e`（merge AGENTS.md + v0.1.0 基线文档）。

### 2.2 关键模块清单（`git ls-files` 确认已跟踪，非 WIP）

| 模块 | 首次入库 | 当前存在 |
|---|---|---|
| `corporate_action_context.py`、`corporate_action_snapshot_loader.py`、`raw_market_inputs.py`、`raw_market_provider.py`、`staged_candidate_runner.py`、`staged_production_inputs.py` | `79cc2b7` | 是 |
| `historical_costs.py` | `7f0fb2a`（10-26） | 是 |
| `staged_order_strategy.py`（含 `quantity_rule_resolver` 接线） | `ab1138b` | 是 |
| `quantity_rules.py` | `ab1138b` | 是 |
| `fractional_scenarios.py` / `_prefix_gate.py` / `_scenario_cli.py`、`prefix_attestor.py`、`prefix_ledger_verifier.py` | `8cd25a9` | 是（字节已被后续提交改过，见 §3.3） |
| `validation_2025_bridge.py`、`validation_2025_execution.py`、`scripts/run_2025_restricted.py`、`scripts/run_2025_ab_execution.py` | `8cd25a9` | 是 |

`backtest/cnn_adapter/` 现有 29 个 py 文件，全部被 git 跟踪。

### 2.3 未提交 WIP 清单（`git status --short` 实测，5 项，全部 tracked-modified，**0 untracked**）

| 文件 | 改动量 | 性质 | 处置建议 |
|---|---|---|---|
| `.opencode/memory/HISTORY.md` | +32/-0 | memory 子系统运行期写入 | **用户自有，不得动**；属记忆演化，随下次 memory 提交收敛 |
| `docs/research/20261026/PARALLEL_WORKSPACES.md` | +11/-2 | 追加"收尾与清理"章节、把"当前编码工作树"改为历史记录 | **用户/他人研究改动，不得动** |
| `docs/research/20261026/f4_signal_delivery.md` | +17/-1 | 追加 W2 交付与独立复核段（2026-10-27） | **用户/他人研究改动，不得动** |
| `docs/research/20261026/state_acquisition_request_v2.md` | +1/-1 | 更新采集 owner 会话 ID | **用户/他人改动，不得动** |
| `scripts/audit_walkforward_execution.py` | +66/-5 | 新增 `--label-cutoff`/`--evaluation-label-mode`、`_verify_label_endpoints()` 用 parquet 逐样本复核 open[t+1]→open[t+11] 标签端点、identity 增加 `bins_version` 与 checkpoint 身份 | **待处理**：功能完整、`ruff` 与 `py_compile` 均通过，但**无任何测试引用**（全仓 0 处，含 docs），也未入库 |

另有 `git stash list` **3 条历史 stash**（`ad7c7c9` 两条重复的 turnover-attribution 文档、`014f190` baseline+截面二分类指标）——按用户全局规则，stash 跨 worktree 共享，**不应用于隔离任务，本报告未触碰**。

### 2.4 环境与工具链实测

- `.venv` 为**主区真实目录**（非 symlink/junction），`core.hooksPath = D:\...\cnn\scripts\githooks`（绝对路径，符合记忆约定），`scripts/githooks/post-checkout` 存在，`.git/info/exclude` 已含 `.venv`。
- `_check_signals.py` **不存在**（旧记忆提到的脏文件已不在工作区）。
- CNN `wheels/` 下有 `backtest_core-0.1.0-py3-none-any.whl`（125,130 B，mtime 2026-10-26 22:14），其 `account_runner.py` 内容 == core `893fc96`，**不含 `stop_after_close`**；`pyproject.toml` 以 `path` 方式引用该 committed wheel。

---

## 3. B 节：测试与质量门现状（全部本轮实跑）

### 3.1 门禁总表

| # | 命令 | 工作目录 | 结果 | 退出码 |
|---|---|---|---|---|
| 1 | `uv run --project . python -m ruff check .` | cnn | `All checks passed!` | 0 |
| 2 | `uv run --project . python -m unittest tests.unit.test_ci_gate` | cnn | `Ran 6 tests / OK`（6.1s） | 0 |
| 3 | `uv run --project . python -m unittest <T16 五文件>` | cnn | `Ran 58 tests / OK`（3.1–3.3s） | 0 |
| 4 | `uv run --project . python -m unittest discover -s tests -t .`（无 env） | cnn | `Ran 982 / FAILED (failures=2, errors=50, skipped=40)` | ≠0 |
| 5 | 同上 + `CNN_ALLOW_LEGACY=1` | cnn | `Ran 982 / FAILED (failures=2, **errors=10**, skipped=40)`（55.3s） | ≠0 |
| 6 | `uv run python -m unittest discover -s tests` | backtest-core | `Ran 718 tests / OK`（0.713s） | 0 |
| 7 | `uv run ruff check .` | backtest-core | `All checks passed!` | 0 |

> 说明：命令 4/5 的差异（errors 50 → 10）纯由 `backtest/legacy.py` 的 `LegacyBacktestDisabled` 守卫造成——不带 env 时 40 个 `test_engine.py` / `test_cnn_adapter_regression.py` 用例在 `run_backtest` 入口即抛。**这不是缺陷，是设计上的 fail-closed**；不带 env 的 40 项应记为"环境未开启"而非"红"。

### 3.2 命令 5 的 12 项真红（`CNN_ALLOW_LEGACY=1` 下），逐项归因

| # | 用例 | 形态 | 实测根因 | 归属 |
|---|---|---|---|---|
| 1 | `test_prefix_attestor.test_fixed_source_inventory_accepts_exact_files_and_rejects_tampering` | 1 error | `ValueError: source fixed SHA mismatch: …\staged_candidate_runner.py`（pin 与现行文件不符 + core 路径指向已退役树） | W1 遗留 |
| 2 | `test_prefix_ledger_verifier.test_machine_proof_recomputes_all_12_branches_and_stays_unpinned` | 1 error | `ValueError: external attestation source SHA mismatch` | W1 遗留 |
| 3 | `test_data_feature_pipeline.test_training_refits_mismatch_but_validation_requires_scaler` | error | `AttributeError: 'RelativeScaler' object has no attribute 'identity_hash'` | 测试 vs API 漂移（测试写于 `178f24e`，仍按 `PerCodeGroupedScaler` 假设调用） |
| 4 | `test_log_manager_collision.test_failed_save_leaves_no_half_written_config` | error | `PermissionError: [WinError 32] training.log 被占用` | Windows 文件锁，非逻辑缺陷 |
| 5 | `test_log_manager_collision.test_same_second_two_managers_get_different_dirs` | error | 同上（清理阶段同样 WinError 32） | Windows 文件锁 |
| 6–7 | `test_decile_diagnosis.test_hump_e2e` / `test_monotonic_e2e` | 2 errors | `ModuleNotFoundError: No module named 'plotly'` | **可选依赖缺失**（`plotly` 在 `pyproject` 的 `viz` extra，venv 未装） |
| 8 | `test_trainer_unified.test_validate_epoch_dict_with_tuple_unpack` | error | `TypeError: CrossEntropyLoss.forward() got an unexpected keyword argument 'sample_weight'` | 测试针对旧 torch 签名；实测 torch 2.12 的 `CrossEntropyLoss.forward` **无** `sample_weight` |
| 9 | `test_training_retail_wrapper.test_main_config_stays_cnn_by_default` | error | `KeyError: 'CNNTransformerConfig'`（`train.py:247` 写 `cfg['CNNTransformerConfig']['gate_head']`，而测试传最小 cfg） | 测试夹具与 `train.py` 现状不匹配 |
| 10 | `test_training_retail_wrapper.test_retail_config_uses_isolated_dirs_and_model` | error | 同上 `KeyError` | 同上 |
| 11 | `test_config_defaults.test_featurenum_placeholder_matches_new_schema` | 1 failure | `AssertionError: 80 != 53`（测试写死 53，`config/defaults.py:92` 已是 `featurenum: 80`） | **文档/测试滞后于 F=80 新 schema**（AGENTS.md 也仍写 53） |
| 12 | `test_training_retail_wrapper.test_parquet_helper_passthrough` | 1 failure | `AssertionError: True is not false`（断言 `pc.cs_rank` 为 False，默认已开 cs_rank） | 测试滞后于 F=80 默认 |

**分类统计：W1 遗留 2 项、测试-API 漂移 3 项（#3/#8/#9-10 中的 cfg 类）、默认值漂移 2 项（#11/#12）、可选依赖 2 项、Windows 文件锁 2 项。**

### 3.3 恢复/修复过的套件逐个实测（不下"全绿"结论，如实记录）

| 套件 | 实测结果 | 说明 |
|---|---|---|
| `test_fractional_scenarios` | `Ran 29 / OK (skipped=7)`（12.0s） | **7 项是 skip 不是 pass**；skip 原因=依赖未回收的 W1 版接口 |
| `test_prefix_attestor` | `Ran 4 / FAILED (errors=1)` | pin 15 项中 **4 通过 / 10 不符 / 1 路径不存在**（本轮逐项算过） |
| `test_prefix_ledger_verifier` | `Ran 16 / FAILED (errors=1)` | external attestation source SHA mismatch |
| `test_2025_restricted` | `Ran 24 / OK (skipped=18)`（0.06s） | 18 项 skip，原因文案："依赖已于 2026-10-30 退役的 corporate-action-fix-20261027 既审树" |
| `test_2025_restricted_fix2` | `Ran 7 / OK (skipped=7)` | 全 skip |
| `test_2025_restricted_fix3` | `Ran 7 / OK (skipped=7)` | 全 skip |
| `test_ca_evidence_adapter` | `Ran 2 / OK (skipped=1)` | 1 项 skip（退役树） |
| `test_validation_2025_bridge` | `Ran 17 / OK` | **真全绿** |
| `test_validation_2025_execution` | `Ran 4 / OK` | **真全绿** |
| CA 六模块测试（quantity_rules 6 / corporate_action_context 19 / runner_e2e 4 / corporate_actions 9 / staged_candidate_runner 33 / staged_production_inputs 12 / staged_order_strategy 12 / historical_costs 4 / raw_market_provider 14 / raw_market_inputs 8 / snapshot_loader 5） | **全部 OK**（合计 126 项） | 主区版 CA 链路测试**完整可用** |

> 与旧报告对照：`final_delivery_20261030.md:37` 写 `test_fractional_scenarios` 为 `OK(skipped=7)`（本轮实测一致）、`test_prefix_attestor` 1 error（一致）、`test_prefix_ledger_verifier` 1 error（一致）、`test_2025_restricted*`/`test_ca_evidence_adapter` **"全部报错 FileNotFoundError"**——**这一条已过时**：`9c15347` 与 `bb4ddd8` 之后它们已从"报错"变为"OK(skipped)"，文件缺失被降级为 skip。旧报告 `final_delivery_20261030.md:37` 与 `worktree_consolidation_20261030/README.md` 的这两处描述需要更新。

### 3.4 恢复态与当前字节的漂移（`recovered_w1_20261030/verification.json` 逐文件复算）

计 18 项，按 verification.json 的 sha256 与本轮现算对照：**10 一致 / 8 不一致 / 0 缺失**。

| 文件 | verification 基线 | 当前实测 | 改动提交 |
|---|---|---|---|
| `fractional_scenarios.py` | `abf5e9fd3a19…` | `473ec43e226f…` | `436cb73` |
| `prefix_attestor.py` | `9c879639d455…` | `49f2a54bb19f…` | `d5c0dc3` |
| `scripts/run_2025_restricted.py` | `b1a5e69539cf…` | `f240885207f7…` | `ff7e606`→`9c15347`→`bb4ddd8` |
| `test_fractional_scenarios.py` | `9268a0672320…` | `7549231b5c38…` | `436cb73` |
| `test_2025_restricted.py` | `8d2aeb12fe44…` | `70a3ee676c83…` | `9c15347` |
| `test_2025_restricted_fix2.py` | `219eb5868ab1…` | `5b2e42486c22…` | `9c15347` |
| `test_2025_restricted_fix3.py` | `ad543b9156d2…` | `fbdf13861da1…` | `9c15347` |
| `test_ca_evidence_adapter.py` | `13efea05b77d…` | `a8f9f2a578ab…` | `9c15347` |

> 含义：**"恢复"已不是等价于"复原"**。若要复核 W1/2025 的原始语义，必须用 `git show 8cd25a9:<path>` 或 `recovered_w1_20261030/recovered/`，不能直接读工作区。

---

## 4. C 节：数据与证据资产

### 4.1 外置证据根（`C:/Users/yanwen/AppData/Local/Temp/opencode/`）

总量实测：**171 个目录 / 41,020 个文件 / 24.3 GB**。抽查 25 个关键目录，**25/25 存在**：

| 目录 | 文件数 | 体积 | 内容可读性核验 |
|---|---|---|---|
| `eight_windows_second_audit_20261028` | 1 | — | `audit.md` 9,504 B |
| `staged_mechanical_results_20261028_v1` | 138 | 7.72 GB | 8 个策略目录齐全；`summary.json` 含 W2 四策略完整 `main_return`/`benchmark_return`/`validation_failures` |
| `w1_real_prefix_independent_audit_20261029` | 3 | — | `REPORT.md` 4,118 B + `audit.json` 58,971 B；8 分支 5×exit0/INCOMPLETE + 3×exit1/FAILED 已核 |
| `w1_real_prefix_exploration_20261029` / `_v2` / `_v3` | 15 / 187 / 12 | 4.28 GB(v2) | v3 `v12_hash_audit.json`：**status PASS，4812/4812，读入 2,221,465,003 B == 声明字节** |
| `validation_2025_ab_real_20261029_v1` / `_v2` | 64 / 58 | 2.66 GB(v2) | v2 `run_summary.json` + `account_status.json` 可读；A/B 均 `NOT_EVALUABLE`、`main_end_nav=null` |
| `validation_2025_ab_v2_abort_audit_20261029` | 2 | — | 中断审计 |
| `validation_2025_local_inputs_20261029` | 285 | 0.01 GB | 本地输入快照 |
| `recovered_w1_20261030` | 745 | 0.02 GB | `MANIFEST.json`/`verification.json`/`raw_patches/`/`recovered/` |
| `w1_prefix_fix5_20261028` | 3 | — | `REPORT.md` 3,559 B + `HASHES.sha256` + `RUN_LOG.md` |
| `w1_prefix_independent_qa_20261028` | 23 | — | 含 `reverify4/REPORT.md`（mini PASS / 真实 BLOCKED） |
| `w1_ca_cutoff_availability_20261029` | 2 | — | `ANALYSIS.md` 统计 8740 行 dividend |
| `w1_ceil_failure_root_cause_20261029` | 2 | — | `ROOT_CAUSE.md` |
| `w1_dual_core_identity_independent_qa_20261029` | 375 | 0.01 GB | 早期 FAIL 裁决 |
| `staged_prepared_inputs_20261027_v12` | 4,694 | 1.88 GB | `manifest.json`（1.03 MB）+ `manifest.sha256`；`fees_W2.json` 可读 |
| `staged_production_integration_delivery_20261027` | 53 | — | 含 `SOURCE_HASHES_FINAL.json` |
| `staged_integration_independent_qa_20261028` | 4 | — | `reverify1/QA_REPORT.md` |
| `three_day_models` | 29 | 0.05 GB | `W2_F4_v1/run_20261026_212052/best_model.pth` 44,289,489 B，SHA256 `03625B7D…EF4A4` **与文档一致** |
| `three_day_signals` | 34 | 0.02 GB | W1/W2 `signals.parquet` + NPZ + metadata + manifest 齐全 |
| `prospective_exam_feasibility_20261028` / `clean_exam_data_inventory_20261028` | 1 / 2 | — | NO-GO 结论 |
| `clean_exam_coverage_recheck_20261029` | 2 | — | 覆盖矛盾复核 |
| `strategy_goal_fast_path_20261029` | 1 | — | `FAST_PATH.md`（最短可执行路径建议） |
| `w2_goal_acceptance_review_20261029` / `w2_mechanical_risk_review_20261028` / `w2_tax_fifo_*` | 2 / 6 / 多 | — | W2 账本/风险/税务独立复核 |
| `validation_2025_000601_official_20261029` / `_000506_official_20261029` / `_ca_evidence_adapter_20261029` | 3 / 多 / 7 | — | 官方 PDF 取证 + adapter closeout |
| `ca_300502_official_independent_qa_20261028` | 3 | — | 两个 163,160 B PDF（原下载 + 重下载，字节相同） |
| `worktree_retirement_20261028` / `_20261030` | 4 / 1 | — | 退役报告 |

**结论：全部证据目录完好，无缺失。** 唯一"疑似缺失"的 `scripts_frozen` 目录在 Temp 下本来就不存在（`scripts/frozen/` 在仓库内，17 个文件，正常）。

### 4.2 仓库内数据资产

| 资产 | 路径 | 实测 | 状态 |
|---|---|---|---|
| 训练 parquet（默认） | `data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet` | **3,682,488,555 B（3.43 GB）**、11,413,377 行 × 58 列、11 rowgroups、mtime 2026-09-01 | **可读**（只读 footer + schema，未加载数据） |
| F60 parquet | `C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet` | 4,279,965,200 B，12,254,385 行，业务日 2013-01-04 → **2026-08-31** | 存在可读 |
| `Z:/dev/train_data/` | 同上文件副本 | 1 个文件 | 存在 |
| `logs/KEEP/` | — | **33 个顶层目录 / 279 文件 / 0.39 GB** | 完好 |
| `logs/KEEP/baseline/best_model.pth` | — | **15,014,178 B**，SHA256 `0BA0E89E6C0A3DA16A4687E6AF75AFBA52ACC7BA1EF449DB1829DA632DCED3C7`，mtime UTC 2026-09-29 00:52:18 | 完好，可 `torch.load`（`OrderedDict`，401 键，`multi_window_cnn.stem.0.weight` 形状 `[128,45,7]` → **F=45 旧 schema**） |
| `logs/KEEP/baseline/config.json` | — | 1,819 B；TRAIN 2013-01-01~2025-06-30 / VAL 2025-07-01~12-31 / `NORMALIZE=per_code` / `SEQ_LEN=60` / `HORIZON=5` / `featurenum=45` / `d_model=256` / `EMDLoss` / `BINS` 为 ±0.25 步长 0.01 的 51 边界旧版 | 完好。**注意：这是 per_code + H5 + F45 的旧基线，不是现行 relative + H10 + F80** |
| 其它 KEEP run | `logs/KEEP/run_*` 32 个 | 均含 best_model.pth 或 training.log | 完好 |
| `logs/` 全量 | — | 697 文件 / 5.02 GB / 23 个顶层目录 | 远低于 T18 轮转阈值（10 目录 / 2 GiB 是针对顶层 run_* 的规则，此处为历史目录） |
| 预测 NPZ（可复核第三层） | `logs/preds_full{A,B}_{2025,2026}.npz` | 4 个 × 70.8/46.1 MB；A/B 2025 各 1,180,872 行（2025-01-02~12-16）；2026 各 768,549 行（2026-01-05~**08-14**） | **可读**，只含 `exp_ret`/`true_ret`/`dates`/`codes` 四键 |
| 树/JKX 预测 | `logs/preds_jkx*.npz`、`logs/tree_rebuild/preds_main_hgb_test_openopen.npz` | 存在 | 可读 |
| 训练权重（相对模式） | `logs/relative/run_*` 23 个目录 | 含 best_model.pth（~44.8 MB） | 完好 |
| `research/` | `goal`/`goal_repro`/`m_research`/`precision`/`alpha_attribution`/`unified_recalc`/`market_neutral` | `research/README.md` 注册表 7 行全在 | 完好 |
| `docs/research/` | `three_day_strategy_report_20261029.md`、`final_delivery_20261030.md`、`20261026/*` | 全部 `Test-Path` True | 完好 |
| `scripts/frozen/` | 17 文件 | READ ONLY 快照 | 完好 |

### 4.3 2026-09 后数据边界（本轮亲测，非引用）

| 源 | 实测覆盖 | 边界 |
|---|---|---|
| `Z:/dev/kline/day/*.parquet`（5,215 文件） | 抽查 6 个随机股票 + 000001.SZ：**全部 max = 2026-09-30**；000001.SZ 2026-09 有 21 行、**2026-10-01 后 0 行** | 9 月有原始行情，无 10 月 |
| `Z:/dev/kline_index/day/000300.SH.parquet` | **3,338 行，2013-01-04 → 2026-09-30；2026-10-01 后 0 行**；文件 mtime 2026-09-30 17:56 | 基准止于 9-30，**10 月起无同期基准** |
| `Z:/dev/alpha_factor/*.parquet` | 采样至 2026-09-30 | 同左 |
| `Z:/dev/model_features/996515042bf2/*.parquet` | 仅至 2026-08-11（旧报告已核） | 特征未覆盖 9 月 |
| `C:/train_data/…F60…20260831…parquet` | 业务日至 **2026-08-31** | 正式训练输入不含 9 月 |
| `Z:/dev/snapshot/`（**本轮新发现**） | 逐笔快照，schema 含 `bid_price1..5`/`offer_price1..5`/`orig_time`/`pre_close_price`/`trading_phase_code`；`000001.SZ` **100,745 行，`orig_time` 2026-01-05 09:00:51 → 2026-01-30 16:59:33**；目录 mtime 2026-10-24 | **只有 2026-01 一个月的 L2 逐笔**，属烧样本区间，不能用于 9 月后考试 |

**裁定：2026-09 后"有原始日线与指数，但无 10 月数据、无 9 月后事前冻结信号、无连续执行账本"的结论在本轮仍成立**（与 `clean_exam_inventory.md`、`coverage_recheck.md` 一致，本轮为独立复核）。

---

## 5. D 节：进度定位

### 5.1 四条"待重做"的具体卡点（Q1 #18–#21）

| Q1 编号 | 路线 | 现在卡在什么**具体**状态 | 本轮新增实测/证据 |
|---|---|---|---|
| #18 | W1 四策略（B1/S1/S2/C70，2021H1） | **卡在"碎股分配证据"与"W1 版接口"两处**。工程上已从"完全跑不起来"进展到"conda 可跑但 3 个 ceil 分支仍 FAILED"：v2 八分支 5×exit0/INCOMPLETE + 3×exit1/FAILED（S1/S2/C70 的 ceil）。`staged_mechanical_results_20261028_v1/summary.json` 仍写 `W1_*` 四策略 `INCOMPLETE`、`dividend:27726 … noninteger_or_unrepresentable_share_quantity`。**没有 E 日 NAV，没有全窗收益**。真实中登获配数仍未知（仅官方 PDF 证明"按账户排序、同尾随机"规则，SHA `c09dfd55…`，两 PDF 163,160 B 字节相同） | 四策略目录、`batch_error.json` 仍在；`prefix_attestor` pin 10/15 不符使 attestor 无法产出可信见证 |
| #19 | 2025 A/B 受限年度回放 | **卡在"公司行动登记日未知"的守卫 + 数据宇宙不足**。v2 实测：A 于 2025-08-22 `000601.SZ dividend:17916` 中断（持 33,600 股、成本 ¥3,376.20732、现金 ¥802,419.79）；B 于 2025-06-06 `000506.SZ dividend:63844` 中断（持 23,600 股、成本 ¥4,575.65435）。两者 `main_end_nav=null` / `target_verdict=NOT_EVALUABLE`。数据侧：信号宇宙 5,135 码，但本地状态仅 174 码、raw 行情 172 码 | `000506` 官方年报摘要 PDF SHA `455ba0e0…` 已核、董事会决议镜像 SHA `c6228f78…`；但**股东大会决议官方 PDF 仍 UNKNOWN**（仅证券日报转载）。`000601` 半年报 PDF SHA `A90B9633…` 已核，但 id 17917 年度项目决议原件未闭合 |
| #20 | W1 prefix/ceil 修复链（fix2/3/5） | **卡在"三个 TRUSTED pin 全为 None"**：`fractional_prefix_gate.py` 实测 `TRUSTED_PREFIX_PROOF_SHA256=None`、`TRUSTED_PREFIX_ATTESTATOR_SHA256=None`，`prefix_ledger_verifier.py` 的 `TRUSTED_PREFIX_ATTESTATION_SHA256=None`。真实八分支未启动（第二次），12 路径 proof BLOCKED，绩效 LOCKED。reverify4 裁决：mini PASS（94 CNN + 46 core + Ruff/Pyright）仅限合成范围 | **新增关键卡点**：core 侧 `a176be9` 提供的 `stop_after_close` 能力 **未被 CNN 消费**——CNN `.venv` 装的 wheel `account_runner.py` == core `893fc96` 且不含该符号，CNN `backtest/` 全树 0 处引用。所以即使 pin 就绪，cutoff 能力在 CNN 也调不到 |
| #21 | W1 CA cutoff PIT 层（v3） | **卡在"known_at 证据不足"的主动 fail-closed**：v3 前置门 `v12_hash_audit.json` **PASS（4812/4812，2,221,465,003 B 全读全核）**，但 `outputs/` 不存在，八分支未启动。统计已明：公告日 ≤cutoff 2,497 条、登记日 ≤cutoff 1,306 条、未来 ex 2,279 条中 **1,959 条公告日晚于 cutoff** | 本轮复核 `ANALYSIS.md` 原文；`v12_hash_audit.json` 的 `status`/`verified_count` 字段实测确认 |

### 5.2 五条"条件保留"的保留条件

| Q1 编号 | 路线 | 保留条件（明确到可执行） |
|---|---|---|
| #2 | CNN 主模型 A/B（排序基线） | **只能作排序基线/对照**，不得作达标候选；其 2026-01~08 数字属**烧样本**，不得用于新规则验收；若复用须在 2026-09 后干净样本上重新冻结评估 |
| #4 | 树 HGB/XGB 截面 rank | **只能作"更优的截面排序基线"**，用于集成/辅助过滤；不得直接转产；持仓 20 只的形态**永久排除**（违反 ≤10） |
| #5 | precision 精确优先规则包 | 已进 `research/README.md` 待验收队列第 2 项；**必须"预注册冻结后、2026-09 后新数据一次性考试"，不得在 2026 烧样本上再调阈值** |
| #9 | m_t 波动缩放（vol targeting） | **仅作风险控制假说**；保留条件=必须先接进真实执行引擎（引擎版从未做）+ 预注册 + 2026-09 后干净样本；**禁止**重解释为方向信号（方向线已证伪） |
| #11 | goal 旧线分散版 | **仅方法线索**（低换手/分散/惯性）；旧数字过期不作现行绩效；100 只持仓违反 ≤10，本金 200 万与 W2 100 万口径不同，**不可横向拼接** |

### 5.3 一句话回答：离"可执行、跑赢沪深300、持仓≤10 的策略"还差哪几件

**还差 5 件，按依赖顺序：**

1. **core ↔ CNN 对齐**：把 core `df38c2e`（含 `a176be9` 的 `stop_after_close` + 挂单留存）重 build wheel、bump 版本、`uv lock`，并在 CNN 适配层真正接线。现状是"core 有能力、CNN 调不到"。
2. **W1 版 8 接口重建 + pin 重签**：`staged_candidate_runner`/`staged_production_inputs`/`corporate_action_context`/`historical_costs`/`staged_order_strategy`/`raw_market_provider`/`raw_market_inputs`/`corporate_action_snapshot_loader` 的 **W1 语义版本**（`git log --all` 0 命中）；随后用现行文件重算 `fixed_source_sha256()` 的 15 项（现 10 项不符 / 1 项路径不存在）并钉死三个 `TRUSTED_*`。
3. **碎股与 CA 的"证据闭合"**：W1 侧需模拟账户对应的中登获配凭证（否则只能报条件情景）；2025 侧需 000601 id 17917 与 000506 的官方决议原件 + 全 174 码外宇宙补齐。
4. **2026-09 后的考试材料**：① `000300.SH` 与全市场行情补到考试期末（现止于 2026-09-30）；② 训练截止早于考试起点、且**有独立冻结证据**的模型权重；③ 逐日信号/订单/成交/现金/持仓连续账本（现在完全没有）。
5. **全量测试可信度**：把 12 项真红清绿（尤其 `featurenum 80 vs 53`、`RelativeScaler.identity_hash`、`train.py` 的 cfg 键、torch `sample_weight`），否则"982 项全绿"这个结论无法用于任何后续变更守门。

> 排序理由：第 1–2 件是纯工程、成本最低、解锁后续全部 W1/2025 证据；第 3 件依赖外部官方文件；第 4 件依赖数据供应（非本仓库可控）；第 5 件随时可做但优先级低于前四件。

---

## 6. 需要提醒下游的三处旧表述已失真

1. `docs/research/final_delivery_20261030.md:37` 与 `docs/research/worktree_consolidation_20261030/README.md` 说 `test_2025_restricted*` / `test_ca_evidence_adapter` **"全部报错 FileNotFoundError"** → 实测已是 `OK(skipped)`（`9c15347`/`bb4ddd8` 之后）。
2. `final_delivery_20261030.md:37` 说 `prefix_attestor` pin **"15 项中 11 项与主区不符"** → 实测 **10 项不符 + 1 项路径不存在 + 4 项相符**。
3. `AGENTS.md`（CNN 项目根）的 "Architecture" 段仍写 `featurenum=53`，而 `config/defaults.py:92` 已是 **80**；这条不一致正是测试 #11 hysteresis 的来源。

---

## 附：本轮实测命令与时间戳

| 时间（本地 2026-10-30） | 命令 | 结果 |
|---|---|---|
| 12:03 | `git log --oneline -3` / `git rev-parse HEAD` / `git rev-list --count HEAD..origin/main` @cnn | `05047f4…` / 0 差异 |
| 12:03 | `git status --short` @cnn | 5 项 M，0 项 ?? |
| 12:03 | `git log --oneline -3` / `rev-parse` @core | `df38c2e…` / 0 差异 |
| 12:04 | `uv run --project . python -m ruff check .` @cnn | All checks passed（ruff 0.16.5） |
| 12:05 | `uv run python -m unittest discover -s tests` @core | Ran 718 / OK（0.713s） |
| 12:05 | `uv run ruff check .` @core | All checks passed |
| 12:06 | `uv run --project . python -m unittest tests.unit.test_ci_gate` | Ran 6 / OK |
| 12:06 | 同上 + T16 四套件 | Ran 58 / OK |
| 12:08 | `unittest discover -s tests -t .`（无 env） | Ran 982 / FAILED (2, 50, 40) |
| 12:10 | 同上 + `CNN_ALLOW_LEGACY=1` | Ran 982 / FAILED (2, **10**, 40) |
| 12:11 | 逐套件跑 `test_fractional_scenarios` 等 9 套 | §3.3 表 |
| 12:12 | 逐套件跑 CA 六模块 11 套 | 全 OK（126 项） |
| 12:13 | `git diff --numstat` / `py_compile` / `ruff` 单独验 WIP | 5 文件、编译与 lint 通过 |
| 12:14 | 外置证据根 25 目录 `Test-Path` + 文件计数 + 体积 | 25/25 存在，171 目录 / 41,020 文件 / 24.3 GB |
| 12:15 | `ParquetFile(...).metadata` @训练/F60/指数/快照 | 行列表见 §4.2/§4.3 |
| 12:16 | `torch.load(logs/KEEP/baseline/best_model.pth)` | OrderedDict 401 键，stem `[128,45,7]` |
| 12:17 | wheel 内容 SHA vs core 各提交 SHA（LF 归一） | wheel == `893fc96`，缺 `stop_after_close` |
| 12:18 | `fixed_source_sha256()` 15 项逐项复算 | 4 通过 / 10 不符 / 1 缺失 |
| 12:19 | `verification.json` 18 项逐文件复算 | 10 一致 / 8 不一致 |

**本报告只读完成：未修改/删除任何仓库文件，未执行任何 git 写操作（无 add/commit/stash/checkout/reset）。除本报告外未产生新文件。**
