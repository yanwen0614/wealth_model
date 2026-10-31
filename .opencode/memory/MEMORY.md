# Project Memory

## Architecture & Decisions

### 整体目标（2026-10-28确立）
利用现有数据、自主探索并验证一套可执行的股票策略，使组合在扣除交易成本后收益非负，且严格跑赢同一时期的大盘（沪深300），同时实际持仓始终不超过10只股票。
- 这是所有技术工作的最高收敛标准；模型训练、归一化、回测引擎、公司行动处理、分批组件、桥接等一切子任务均服务于该目标。
- "可执行"指策略可通过真实税后回测管线完整运行，不依赖合成数据或规避真实市场约束（交易成本、限价、停牌、板别规则、公司行动等）。
- "严格跑赢"指主比较期（如6个月窗口）内组合收益 > 基准收益，不允许事后择优或在buffer期/清算期寻找替代达标路径。
- "实际持仓不超过10只"作为硬约束，非平均或峰值前仓位；策略的信号排序/资金分配/仓位管理须保证任意交易日持仓 ≤ 10只。
- 独立验收标准：2026-09后的干净数据（事前冻结模型信号、连续执行账本、完整同期基准链）为最终考场；2026-01~08已探索不可作新规则验收。
- **当前无一策略通过联合验收**（截至2026-10-30，全部 26 条路线无一达标）。

### 文档地图（2026-10-30 建立，最终轮整理）
- **`docs/README.md` 是文档导航唯一入口**，含根级/docs/research/docs/archive/docs/agent 全部索引、阅读顺序建议、已知文档债务。
- `docs/research/review_20261030/README.md` 是本轮工程整理包索引；其中 **`下一次实验必读.md`** 为下次动手前强制阅读（四条真实事故+四条硬规范+检查清单+15条教训）。
- `docs/research/20261026/source_drafts/` 收 33 份原存 Temp 的 three_day_*/handoff/qa 过程草稿（防证据孤本）；正式结论以 `docs/research/20261026/` 上级目录为准。
- Temp 下已无任何 .md 文件（全部迁入仓库）。review_20261030 包重组为 00-必读 / 20-专项审计 / 30-清理与退役 / 90-评审记录 四子目录，q1~q5 五份探索报告已删除（先提交 `3d422bb` 入库再删，可 `git show` 取回）。

### backtest/cnn_adapter 代码结构（2026-10-30 重组织）
- 平铺 24 个模块拆为 3 个子包 + 生产主干留根：`ca/`（公司行动 5 个）、`w1_prefix/`（W1 研究链 6 个）、`validation_2025/`（2025 受限链 2 个）；根级保留 runner、market、staged_*、order_strategy 等生产模块。
- 使用 `git mv` 保留文件历史。30 处 import 同步更新，3 处硬编码路径（`prefix_attestor.py`）修正子包层级。
- 测试结果与基线一致：1002 tests, 2 failures / 10 errors / 40 skipped（2 failures 为 pin 不符故意保留）。

### 2026-10-30 工程整理最终状态（HEAD 88fd64b）
- **仓库**：cnn main `88fd64b` 已推送 `origin/main`（2026-10-31，与远端同 hash），core `df38c2e` 已推送同步。主区无未提交改动。
- **本轮提交链**（10-27~30 共 30+ 提交）：从 `ab1138b`（quantity_rules 补入库）起，经仓库复原/行尾修复/测试修复/文档入库/死代码删除/模块重组织/T18修复等，最后 `07d1831`/`a5a7bf2`/`88fd64b` 收 WIP。
- **测试基线**：CI 门全绿（ruff 零告警、core 718 OK、CNN 最小门 58 OK）。CNN 本地全量 1002 项：2 failures / 10 errors / 40 skipped（2 failures 为故意保留的 pin 告警，其余归因测试滞后/可选依赖/Windows 文件锁，无引擎错误）。
- **证据保全**：7 个根已复制到 `D:/code/cnn_full_20260905/evidence_tmp_20261030/`（5,863 文件 / 13.4 GB / SHA256SUMS / 4812/4812 校验通过）；第 7 根 `recovered_w1_20261030` 由项目内补拷，逐文件哈希 1:1 全对。Temp 原件未删。
- **大清理**：`paper_jkx/logs/` 删除 16.27 GB（48 个小文本证据另存 `D:/code/cnn_full_20260905/paper_jkx_logs_small_evidence/`）；`logs/tree_verify/`+`logs/tree_rebuild/` 删除 3.21 GB（63 个评估结果另存）；`uv cache prune` 释放 8.17 GB。共释放约 19.5 GB。
- **死代码删除**：14 条放弃路线专属代码 30 文件删除（`b9254bb`）；`docs/`、主链路、frozen、config 默认值一律不动。

### core wheel 对齐已完成（2026-10-31）
- 问题：core `a176be9` 的 `stop_after_close` 只在源码里，cnn 的 wheel 停在 `893fc96`，CNN 全树 0 处引用 —— 能力做了但调不到。
- core bump **0.1.0 → 0.1.1**（`pyproject.toml` + `__init__.__version__` + `test_package_smoke`），重新 `uv build --wheel`，cnn `wheels/` 换成 `backtest_core-0.1.1-py3-none-any.whl`（sha256 `bbb061c2…`，与 `uv.lock` 一致）。
- **版本纪律**：同名 wheel 会被 uv 缓存命中导致升级无感，故必须 bump。默认值/公式未改，`policy_version` 保持 `v1`，仅 `engine_version` 随 `__version__` 前移。
- **`uv.lock` 只改自身包版本行**：`uv lock` 会把镜像源（清华）全刷成 pypi.org（113 行无关 churn），已回退。core lock 用「只改 version 行 + `uv sync --locked` 验证」处理。
- CNN 接线：`run_staged_window(stop_after_close=...)` 透传 core；CLI 新增 `--stop-after-close`（此前完全没有该参数）；`run_single_from_cli` 转发；停止日写入 `provenance.stop_after_close`/`pending_orders` 并进入 `config_hash`（否则不同停止日撞同一身份）。
- 接线时暴露的真实缺陷：停止后 buffer 日无回调，`_write_outputs` 按 calendar 全量取 `recorder.daily` 键会 `KeyError` —— 已改为只写实际观测到的交易日。
- 实测停止语义：基线 9 快照/6 成交 → 停止版 6 快照/3 成交，快照止于 E 日，E 日挂单留存为 `pending_orders`。
- 验证：core 718 OK；cnn ruff 零告警；CI 最小门 58 OK；全量 1007 项 2F/10E/40S 与基线逐项一致。

### 文档精简（2026-10-31，HEAD 8e8edee）
- owner 要求「只保留精简的文档结论，不需要保留过程性内容」。
- **`docs/agent/task/`：22 目录 → 2**。删 20 个已完结过程目录（61 文件），独有结论抽成 `docs/agent/task/agent_task_conclusions.md`（E0–E5 对照 / 费用与退出 / 强买门槛 / 换手行业归因 / checkpoint NumPy）。保留 `20261027_staged-order-strategy`（scope B 仍 pending）、`20261030_2200_workspace-consolidation`（待改写）。
- **`docs/research/`：83 文件 → 55**（1.4 MB → 600 KB）。删一次性操作记录、纯评审过程、未执行计划、已过时状态、`recovered_w1` 的 5 个机器 JSON（约 600 KB）。
- **保留判定依据**：`source_drafts/`、`90-评审记录/`、`worktree_retirement/REPORT.md`、`recovered_w1/MANIFEST.json`、`20261026/{ENGINEERING_STATUS,staged_order_strategy_delivery,corporate_action_tax_tdd_plan}.md`、`z_corporate_actions_audit.json` 均因 `MEMORY.md` / `scripts/research/README.md` / `scripts/audit_z_corporate_actions.py` 还在引用而保留。
- 修 3 处断链：`per_code_normalization_spec.md:134` 的任务目录指向 → `agent_task_conclusions.md`；`checkpoint_compat_delivery` 的已删文件哈希表；`docs/README.md` 的 `review_20261030/q1`（早已删除）。
- 原 `RESEARCH_CONSOLIDATION_AUDIT` 4 项结论中 3 项已过时（均已推送 / T18 已 `os.walk` / agent/task 已索引），按实测现状并入 `final_delivery §8`，只保留「T18 覆盖缺口 + `logs_manifest.csv` 未补录」。

### 测试基线必须带 CNN_ALLOW_LEGACY=1
- 直接跑全量得到 **50 errors** 全是 `LegacyBacktestDisabledError`（`backtest/legacy.py` 默认拒绝旧引擎），**不是代码缺陷**。
- 加大 `CNN_ALLOW_LEGACY=1` 后才是真基线 **2F/10E/40S**。跑全量核对必须带此环境变量，否则会误判为回归。

### P0 冷备份已完成（2026-10-31 00:01）
- 位置 **`G:\backups\cnn_full_20261030\`**（C 盘 → G 盘异卷），含 `README.md` 恢复说明。
- **opencode.db**：`sqlite3.Connection.backup()`（源 `mode=ro`，pages=4096，耗时 340s），**不用文件级复制**（WAL 活动期会拿到不一致快照）。已 `wal_checkpoint(TRUNCATE)`+`journal_mode=DELETE` 收尾为**自包含单文件** 3,836,485,632 B，sha256 `ec9218b8…`，`integrity_check=ok`。备份快照滞后源库 8 messages/32 parts（= 拷贝期间本会话写入），session 数一致 892。
- **scaler pkl（4 个，非 2 个）**：全部复制并逐文件 sha256 1:1 匹配 + `SCALER_IDENTITIES.json` 身份凭证。实测口径：`scaler_per_code.pkl`=**v4_per_code 52→53**（5126 股，mask `g9_observed_mask`）；`scaler_per_code_legacy39_2026.pkl`=**v3_per_code 39→45**（6 个 G9 mask，D3 复现唯一载体）；`scaler_per_code_old.pkl`=v2_per_code 39→45（仅 20 股）；`scaler.pkl`=早期标量（无 version 字段）。
- 脚本留在 `C:\Users\yanwen\AppData\Local\Temp\opencode\p0_*.py`（未入库，按用户要求不入工作区）。

### 八项不可复现的定论（2026-10-30，fill_gap_analysis 复核）
- **不能补（3）**：B3 证明链（pin 指向从未落盘字节）、B4 八分支重执行（依赖树删+路径硬编码+A1 碎股无解）、C2 2025 重跑（换根造不出已删树）。三项均与 N1~N6 不做清单强冲突。
- **部分补（4）**：A4 八窗重跑（三角互证只能锁"输入+账本"，进程角永久缺；历史产物根本没记 cnn-side runner 哈希，TRANSPLANT.json 6 文件 4/6 对不上任何提交）、A5 v12 来源（可出"4808/4812 可追溯、4 项 UNREPRODUCIBLE"限定声明）、C3 测试验证力（加 CI skip 门+标注）、E2 换机重建（58 处/31 文件，生产侧 25 处可改、只读快照 33 处不可改）。
- **推翻 Q3 可补（1）**：D3 F=45 旧口径——v3 scaler 代码在 `4f7c4cd`、legacy39 pkl 在盘、checkpoint 在 `logs/KEEP/run_20260905_183102`，端到端可走通（限指标复现，不含训练重跑）。N13 边界：可用 pkl，不许提交进 git。
- **关键认知**：`git merge` 让代码齐备 ≠ 可复现。缺的是代码之外五类——没落盘的字节、写死的路径、删掉的目录、没签的名、旧 schema。

### quant 源头历史缺口定论（2026-10-30，quant_source_audit）
- quant 仓 `D:\code\quant` HEAD `cdee171b`。
- **缺口不是取数漏，是源头本来无行情**：v12 的 60,144 gap + 34,514 unknown 100% 可归因四类真实非交易（上市前/退市后/官方暂停/停牌）；随机抽 200 条 gap 反查源头命中 0/200。
- 停牌/上市前/退市后的行情永远补不了（没发生过的事），能补的只有标签（大半已补，剩 `_market_coverage` 一小步）。停牌行 `is_susp_sec=1` 已在 canonical；gap_index 59,491 条已标 pre_listing。
- **唯一真数据窟窿**：200 只 dev / 187 只 prd 退市股完全没有 kline 文件（`_get_code_list` 只取 active）。可修（改取数范围+重跑落盘+抽验）。但训练数据排查确认：这 200 只退市股在两个训练 parquet 里均为 0 行，故训练黑名单排除数 = 0。
- 999 限价 1,833 条集中双创上市 1~5 日，改映射语义即可；229 个空登记日均为未实施方案（金额=0、进度≠3），可补兄弟行解释。
- **永久缺失**：SDK 无"暂停上市"字段（约 4 万条是人工维护 13 只，勿误认为源头逐日状态）；`history_status` 只有 2014 起异常事件行。

### CI 零告警门的真实基线（2026-10-30 修正）
- CI `ruff check .` 是 T15 零告警门。`_check_signals.py` 未被 git 跟踪（已删），CI 全新 checkout 里不存在。
- 给 `ruff check` 显式传文件路径会绕过 pyproject 的 `exclude`（research/goal、scripts/frozen 等），冒出 78 个历史告警。校验按目录跑 `ruff check .`。
- `scripts/run_2025_restricted.py` 导入块必须留在 `sys.path.insert(REVIEWED)` 之后，只能用 `# noqa: I001`（挂 `import numpy as np` 行）。

### pin 体系状态（2026-10-30 d5c0dc3 后）
- `prefix_attestor.fixed_source_sha256()` 15 项实测：**7 通过 / 7 真差异 / 1 路径缺失**（行尾误伤已由 d5c0dc3 按内容身份比对消除）。
- 三个公证签名 `TRUSTED_PREFIX_{ATTESTATOR,ATTESTATION,PROOF}_SHA256` 从头到尾为 `None`。
- 决定：**不重签**（条件永远不成立），改为标注 `UNREPRODUCIBLE`；`test_prefix_attestor` 保持红作为唯一自动告警，禁止修绿。

### 测试现状（2026-10-30 实测）
- 全量 1002 tests：2 failures / 10 errors / 40 skipped。2 failures 为 `test_prefix_attestor`/`test_prefix_ledger_verifier` 的 pin 不符（**故意保留**）。
- `test_fractional_scenarios`：29 tests OK (skipped=7) — skip 因依赖模块接口不符。
- `test_validation_2025_bridge`(17) / `test_validation_2025_execution`(4)：真全绿。
- 其余 errors 归因：测试滞后/可选依赖/Windows 文件锁，无引擎或数据契约失败。

### 会话数据库恢复方法（本轮唯一救命手段）
- `<用户目录>/.local/share/opencode/opencode.db`（约 3.8 GB，SQLite，必须 `mode=ro`）。
- 以 `read` 工具最后读到 EOF 的快照为基线，按 `time_created` 重放其后 `apply_patch`/`edit`（跳过 `status != completed`）。**不要用 `patchText` 直接重放**：存储层会重排缩进并静默丢行（实测 616 行 vs 正确 646 行）。
- 本轮 18 文件靠此法恢复，已验证与 `8cd25a9` 逐字节相同。但不可重复到从未被会话读写过的文件。
- **已有冷备份**（2026-10-31）：`G:\backups\cnn_full_20261030\opencode_db\opencode_20261030_235223.db`。

### Git worktree 共享 .venv 钩子（2026-10-30）
- `scripts/githooks/post-checkout` 在 worktree add/checkout 后链接主区 `.venv`；安装须 `git config core.hooksPath` 用**绝对路径**。
- **junction 致命风险**：`git worktree remove -f` 会顺着目录联接删穿目标清空主 `.venv`。优先 symlink。
- `.gitignore` 规则须写 `.venv` 而非 `.venv/`（带斜杠匹配不到 symlink）。

### State Assembly 数据契约
- IS_ST/SUSP/WD/XR 保留原值字符串 '0'/'1'，不 or "" 掩盖；row_hash 用 11 字段 canonical JSON 再 SHA256。
- 公司行动原始数据保留分红/送股/转增/配股原始字段及未知项；不可把缺失上市日或税务规则默认为已知。
- `IS_WD_SEC` 语义经样本反证支持为"除息"而非"退市风险警示"（000001.SZ 20210514、300896.SZ 20210316 两例），但无独立字段证书，保留原名。

### 历史板别数量规则
- 科创板限价单 min=200、step=1、max=100000（并非 200 股整数倍）；主板 min=100、step=100、max=100万；创业板限价上限 30 万。
- 策略当前按 100 股保守取量，不能把取量步长误当法规步长；未知板别拒绝并留证。

## 关键数据事实

### W1/W2 八窗（2026-10-28 机械回放）
- W2 四策略主期（2021-06-30~12-31）机械 NAV 变化：**B1 +23.6794% / C70 +16.9639% / S1 +7.8805% / S2 +7.2273%**；沪深300 价格指数 -5.4350%；超额分别 +29.1144 / +22.3990 / +13.3156 / +12.6624 个百分点；逐日正持仓峰值 5 只；账本恒等式误差 2.33e-10。
- 四者必须并列报告，**禁止事后只挑 B1**。E 日仍有持仓，buffer 末 2022-01-06 清仓，buffer 收益不计入主期。
- W1 四窗 2021-06-08 全部在 `dividend:27726`（300502.SZ）碎股 fail-closed 中断，无收益数字。中登实际尾数分配未知，**永久只能报条件情景**。
- 八窗全部 INCOMPLETE。W2 有完整账本（不是算错），W1 是中断（不是亏损）。

### 2025 A/B
- A 于 2025-08-22 遇 000601.SZ `dividend:17916`；B 于 2025-06-06 遇 000506.SZ `dividend:63844`；均 fail-closed 中断，`NOT_EVALUABLE`。
- `ca_evidence_adapter` 状态 `DEADLINE_CLOSEOUT/BLOCKED`（无正式 adapter 及 FREEZE 产物）。

### 已证伪的负面清单（不要加回，2026-10-30 死代码已删）
方向择时门（三类独立证据：AUC CI 含 0.5；m_t +42.59%→+7.23%；双塔 +51.43%→+9.25%，bootstrap 差 -16.1pp P=0.012）、每日触发式调仓（触发率 96%）、高换手 rolling（年化 -43.3%/-15.3%）、单票 75% 胜率（需 IC 0.35 实测 0.075）、pure_reg 纯回归、JKX 图像线（七路全灭）、20 只以上持仓目标、冻结 A（底仓 20 只超 10 只上限）、market_neutral（做不了空头）、E0–E5 配置优选（33 配置总 P&L -11.77，电子 +22.74，**剔除电子亏 34.5 NAV 百分点**，故 `NORMALIZE=relative` 的证据基础已被抽掉）、λ 消融、regime 聚类、损失消融旧口径、旧 CNN 分类器（准确率 9.75%，52 类乱猜 1.9%）。以上 14 条专属代码已于 `b9254bb` 删除。

### 外置证据目录（已保全）
- `D:/code/cnn_full_20260905/evidence_tmp_20261030/`：7 根（staged_mechanical_results_20261028_v1、validation_2025_ab_real_20261029_v2、staged_prepared_inputs_20261027_v12、staged_production_integration_delivery_20261027、three_day_signals、three_day_models、recovered_w1_20261030）+ `_external_deps`，5,863 文件 / 13.4 GB，EVIDENCE_PRESERVATION_REPORT.md 含完整校验记录。
- `logs/KEEP/`：33 目录/279 文件/0.39 GB；`baseline/best_model.pth` 15,014,178 B 可 `torch.load`（**F=45 / per_code / H5 旧基线**，非现行 F=80）。

### 数据边界
- 行情与沪深300 均止于 **2026-09-30**，2026-10 后 0 行——干净考试当前无法开考。
- 2026-01~08 为烧样本，不得用于新规则验收；2026-09 整月只能空跑联调不能验收；干净考试起算日应为 **2026-10-01** 后且连续多个交易日。
- 训练 parquet 11,413,377 行 × 58 列可读；F60 4.28 GB 至 2026-08-31。
- 训练黑名单排除数 = 0（200 只无 kline 退市股在 parquet 中均为 0 行）。

## 工作树状态
- CNN 与 core 均只剩主区单工作树，全部 research 分支已删。
- 四棵工作树已于 2026-10-30 全部退役（CA、W1、2025、core），无保留 ZIP 归档。core `stop_after_close` 补丁（a176be9）已在 core 主区合并提交。
- 三棵旧树归档 ZIP 仍存于 `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/`。

## 待办与已知缺口（2026-10-31 更新）
- **P0 已完成（2026-10-31）**：opencode.db 冷备份 + 4 个 scaler pkl 异盘保全（含身份 JSON），均在 `G:\backups\cnn_full_20261030\`。
- **core wheel 对齐已完成（2026-10-31），三个仓全部升到 0.1.1**：core `1f0c83f` + cnn `8205f27` + quant `e4b4814`，均已推送。三个 `wheels/backtest_core-0.1.1-py3-none-any.whl` 是同一份构建（sha256 `bbb061c2…`），两个 venv 实测 `__version__=0.1.1` 且 `stop_after_close` 在签名中。
  - **重要事实**：cnn 旧 wheel 虽标 `0.1.0` 但语义是 `893fc96`（非 v0.1.0 tag）；quant 的 `0.1.0` 才是真 tag（`92c33da3…`/`bf3bf1b`）。两者本来就不是同一构建，故 quant 此次是真实 0.1.0→0.1.1（跨 1078 行改动）。
  - quant 侧验证：符号契约 35 项全通过；`tests/unit/backtesting` **390 passed / 3 skipped**，与 0.1.0 逐项一致（零行为漂移）。quant 的 backtesting adapter 未使用 `stop_after_close`，纯依赖对齐。
  - **quant 测试的两个环境前置**（否则会误判为升级破坏）：① Windows 缺 `fcntl`（来自 `src/core/model_bridge/feature_cache.py`），需注入桩；② 必须设 `QUANT_REPO_ROOT`，否则 17 个 q02/q04 用例因 `PathConfig.get_repo_root()` 抛错而假失败。
- **`uv lock` 的镜像源陷阱（三仓通用）**：直接 `uv lock` 会把 tsinghua 镜像 URL 批量刷成 pypi.org（core 113 行 / quant 1035 行）。正确做法：`git checkout -- uv.lock` 后只手工改 backtest-core 的 4 行（version / path / filename / hash），再用 `uv sync --frozen` 验证。quant `uv sync --frozen` 会卸掉 pytest（不在 dev 组），需 `uv pip install pytest pytest-asyncio` 装回。
- **P1 未完成**：CA snapshot 的 `asof_announcement_dates` 能力（**过滤键必须是 announcement/known_at，绝不能是 ex_date**——300502 是公告在前 ex 在后的反例）；补 2 个真缺接口；pin 标 `UNREPRODUCIBLE`；行业中性复测（E0 默认值证据已被行业归因抽掉但未改默认）；quant 数据源 `AD_HOST` 8600 端口不可达；T18 同类「假设目录层级」扫描逻辑复查（`collect_rotation_plan` 已改 `os.walk`，但 `logs/` 17 个不匹配 `run_*` 的顶层目录仍永不进入轮转计划）；`docs/archive/logs_manifest.csv` 需补录。
- **P2 候选**：A=W2 证据资格补强（unknown 双极端敏感度，8~12h）；B=干净考试 harness 空跑（1~2d）；C=≤10 只低换手政策族（3~5d，下限 6 只是资金效率要求，峰值仍须 ≤10）。
- **wheel 入库注意**：`wheels/*.whl` 被 `wheels/.gitignore`（内容为 `*`）忽略，已有 committed wheel 靠 `git add -f` 入库；新增/替换 wheel 时必须 `-f`，否则 pyproject 指向的文件不在仓库里。