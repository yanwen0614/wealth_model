# Project Memory

## Architecture & Decisions

### 整体目标（2026-10-28确立）
利用现有数据、自主探索并验证一套可执行的股票策略，使组合在扣除交易成本后收益非负，且严格跑赢同一时期的大盘（沪深300），同时实际持仓始终不超过10只股票。
- 这是所有技术工作的最高收敛标准；模型训练、归一化、回测引擎、公司行动处理、分批组件、桥接等一切子任务均服务于该目标。
- "可执行"指策略可通过真实税后回测管线完整运行，不依赖合成数据或规避真实市场约束（交易成本、限价、停牌、板别规则、公司行动等）。
- "严格跑赢"指主比较期（如6个月窗口）内组合收益 > 基准收益，不允许事后择优或在buffer期/清算期寻找替代达标路径。
- "实际持仓不超过10只"作为硬约束，非平均或峰值前仓位；策略的信号排序/资金分配/仓位管理须保证任意交易日持仓 ≤ 10只。
- 独立验收标准：2026-09后的干净数据（事前冻结模型信号、连续执行账本、完整同期基准链）为最终考场；2026-01~08已探索不可作新规则验收。

### W1/2025 研究源码回收落库（2026-10-30，commit 8cd25a9 + ff7e606）
- 18 个退役误删的未入库研究源文件已从 `opencode.db` 快照恢复到主区并提交（`8cd25a9`）。证据目录 `C:/Users/yanwen/AppData/Local/Temp/opencode/recovered_w1_20261030/`（只读，勿改）。
- 落盘后 17/18 与 MANIFEST 逐字节一致；`scripts/run_2025_restricted.py` 由后续 `ff7e606` 加了 I001 noqa（+2注释+noqa，不改导入顺序/语义），因此该文件 HEAD 版 SHA 已非 `B1A5E69539CF`。若需原始字节用 `git show 8cd25a9:scripts/run_2025_restricted.py`。
- `fractional_scenarios.py` 落库为 `ABF5E9FD…`（248行，删除前最终态）。独立 QA 冻结的中间态 `7112BEDE…`（229行）**没有**独立文件副本，但可从 `evidence2.json` 的 `part_id=prt_184f0b56a001LP1Bi1IElHpG1q` 229行完整快照 `"\n".join(lines)+"\n"` 无损复现（已验证命中该 SHA）。
- 恢复出的是**当时未完成状态**，不是能全绿的状态：`test_fractional_scenarios` 10 errors（依赖 W1 树版 `CorporateActionContext(asof_announcement_dates=)` 与 `run_staged_window(fractional_scenario=)`，主区 HEAD 均无）、`test_prefix_attestor`/`test_prefix_ledger_verifier` 各 1 error（`prefix_attestor.fixed_source_sha256()` pin 的15项里11项与主区不符，core 硬编码路径指向已退役 `backtest-core-w1-stop-20261028`）。`test_validation_2025_bridge`(17)/`test_validation_2025_execution`(4) 全绿。
- `test_2025_restricted{,_fix2,_fix3}` 与 `test_ca_evidence_adapter` 在主区布局下**导入即崩**：`scripts/run_2025_restricted.py` 顶层 `REVIEW_IDENTITY=verify_reviewed()` 读 `ROOT.parent/staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`（该 JSON 只存在于 `Temp/opencode`，主区父目录 `D:/code/cnn_full_20260905` 下无），且 `REVIEWED` 指向已退役的 `corporate-action-fix-20261027`。
- `test_fractional_scenarios.py:105` 断言 `evidence["announcement_visibility"]`，但 `fractional_scenarios.py` 的 `evidence()` 无该键（该键在 corporate_action_context 里）——当时既存缺陷，被前置的 TypeError 遮蔽。恢复代理的预警准确。
- 补齐这些测试需要另开任务：回收/重建 8 个未在 18 文件内的 W1 版依赖模块（`staged_candidate_runner`/`staged_production_inputs`/`corporate_action_context`/`historical_costs`/`staged_order_strategy`/`raw_market_provider`/`raw_market_inputs`/`corporate_action_snapshot_loader`），它们的历史 pin 在本仓库**任何提交中都不存在**（只在已退役 W1 树里），且 `raw_patches/` 621 补丁中无它们的记录。
- **未提交文件的最后恢复手段是会话数据库** `<用户目录>/.local/share/opencode/opencode.db`（本机约 3.8GB，SQLite，必须 `mode=ro` 只读打开）。`read` 工具输出含完整 `<content>`+行号正文，是磁盘字节级拷贝；以最后一条读到 EOF 的快照为基线、按 `time_created` 重放其后 `apply_patch`/`edit` 事件（跳过 `status != completed`），可重建删除前状态。**不要用 `patchText` 直接重放**：存储层会重排缩进并截断内容，会静默丢新增行。

### CI 零告警门的真实基线（2026-10-30 修正）
- CI `ruff check .` 是 T15 零告警门。`_check_signals.py` **未被 git 跟踪**，故 CI 全新 checkout 里不存在；`ab1138b` 上 CI 的 ruff 是**干净的**。本地看到 `_check_signals.py:1:1 I001` 属其他任务的工作区脏文件，不是 CI 失败项。
- 给 `ruff check` 显式传文件路径会**绕过 pyproject 的 `exclude`**（research/goal、scripts/frozen 等），会冒出 78 个历史告警，不能当作 CI 口径。校验 CI 时要按目录跑 `ruff check .`，或显式按 `exclude` 过滤后再传路径（已验证 199 个文件 All checks passed）。
- `scripts/run_2025_restricted.py` 的导入块必须留在 `sys.path.insert(REVIEWED)` 之后（否则先导入主区 `backtest.*` 触发 `RuntimeError`），因此不能 isort 排序，只能用 `# noqa: I001`（挂在块首行 `import numpy as np` 上，注释行挂 noqa 无效）。

### 2026-10-27 State Acquisition 独立审计发现
- `IS_WD_SEC` 在 quant 项目映射为退市风险警示，但样本反证：000001.SZ 20210514 现金分红0.18，PRECLOSE=23.07-0.18=22.89，IS_WD=1；300896.SZ 20210316 现金3.5+转增0.8，PRECLOSE=(750.88-3.5)/1.8=415.21，IS_WD=1且IS_XR=1。样本支持 WD=除息、XR=除权，但无独立字段证书，保留原名；quant COLUMN_MAPPING 不是证书，原始SDK值未因映射受损。详见 `docs/research/20261026/INDEPENDENT_AUDIT_REPORT_20261027.md`。
- 是否暂停上市在quant手动维护、SDK无此字段；本地prd/pre/test的history_status表无该列，但指定 `Z:/dev/quant_data_dev.db` 有该列。402缺日匹配数据库不等于官方盘前证据。
- 402暂停缺日已核官方PDF：000670.SZ 2020-04-07暂停、2022-08-22恢复；000792.SZ 2020-05-22暂停、2021-08-10恢复；四份公告原始PDF与重新下载哈希一致，全部缺日落在暂停区间内。

### 历史板别数量规则
- 2019上交所科创板限价单最低200股、最多10万股，并非200股整数倍；不足200股卖出余额须一次申报。已审规则表达 min=200、step=1、max=100000；策略当前仍按100股保守取量，不能把取量步长误当法规步长。
- 主板规则 min=100、step=100、max=100万；创业板限价上限30万。resolver绑定真实策略和信号日→下一执行日；未知板别拒绝并留证；持仓如122股时全余额卖出不能被永久锁住。历史规则证据见 `C:/Users/yanwen/AppData/Local/Temp/opencode/evidence_closure_review_20261027/CORRECTIONS.md`。

### State Assembly 数据契约
- IS_ST/SUSP/WD/XR 保留原值字符串 '0'/'1'，不 or "" 掩盖；row_hash 用11字段 canonical JSON（含字段名、稳定数值、allow_nan=False）再 SHA256；source_sha256引用 probe_result/manifest 的实际源哈希，不生成 verified/known 字段。
- 公司行动原始数据保留分红、送股、转增、配股原始字段及未知项；不可把缺失上市日或税务规则默认为已知。实际解释器导入主区 `.venv/Lib/site-packages/backtest_core` wheel，不假设本地 editable；core `account_runner.py` SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。

### Git worktree 共享 .venv 钩子（2026-10-30）
- `scripts/githooks/post-checkout` 在 `git worktree add`/`checkout` 后把主 worktree 的 `.venv` 链接进新树；安装须 `git config core.hooksPath "$(git rev-parse --show-toplevel)/scripts/githooks"`（**必须绝对路径**：相对路径按当前 worktree 解析，在不含该钩子文件的旧分支树内失效）。
- **junction 致命风险（实测）**：`git worktree remove -f` 会顺着目录联接删穿目标，把主 `.venv` 整个清空（本次会话曾因此清空 3.7 万文件，已 `uv sync --offline` 恢复）。真 symlink 下 remove -f 只删链接、目标完好。故钩子优先 symlink（pwsh 7 在开发者模式下可建；powershell 5.1 不行），junction 仅最后手段并打印警告。删含 junction 的树前先删该树 `.venv` 链接。
- `.gitignore` 规则必须写 `.venv` 而非 `.venv/`：带斜杠只匹配目录，匹配不到 symlink 形式的 .venv；钩子同时把 `.venv` 幂等追加进 `info/exclude`，使旧分支 worktree 也保持 `git status` 干净。
- `.gitattributes` 锁定 `scripts/githooks/* text eol=lf`，防 core.autocrlf 把 shebang 变 CRLF 导致钩子不执行。
- 删除 worktree 可能因 `.opencode/memory/MEMORY.md`（被跟踪且 run 期被 memory 子系统写回）报 `Directory not empty`；先删该目录再 remove。

## [2026-10-29 00:45] 工作树退役与 W1 前缀探索
- 数量规则、staged-runner-v2、旧 corporate-action-context 三棵空闲树已归档全部未提交/ignored 数据、逐文件hash及ZIP校验后 `git worktree remove --force` 指定树并 `git branch -d`；报告和可恢复ZIP在 `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/REPORT.md`。主区WIP未改。当时（2026-10-29）保留的 CA整合树、W1研究树及独立core树，已于 2026-10-30 全部退役删除，见下一条。
- 2026-10-30 主区 owner 又按用户指示"直接删除不存档"退役 4 棵树：corporate-action-fix-20261027（79cc2b7 内容已 merge 进 main）、w1-fractional-scenarios-20261028、validation-2025-restricted-20261029、backtest-core-w1-stop-20261028；报告 `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261030/REPORT.md`。唯一保留物是 `w1_stop_after_close_20261030.patch`（SHA `D13E06BB908233510F9C919FD4E16D977A167C2F39F2A792D62AAC46C5FDFE3B`，145行，基线 core `893fc96`）。因此 `git worktree list` 现仅剩主区属预期，不是本轮 hook 操作造成。
- W1 floor/ceil 仅条件探索，无法得知虚拟账户真实获配。fix5代码在三天截止后交付于 `w1_prefix_fix5_20261028/`；owner自测94项，真实八条前缀尚未执行、可信attestor/attestation/proof pin皆None。独立质量门 `w1_prefix_independent_qa_20261028/reverify4/` 已完成：**mini 质量门 PASS（仅合成/mini 范围）**，但真实 W1 cutoff 八分支未证明、真实 12 路径 proof 为 BLOCKED、绩效目标 LOCKED（三个生产 pin 均为 None）；原 reverify3 因可伪造证明、截止后行被裁掉等 FAIL。原 wheel 与隔离 core 身份不同，真实 prefix 等价仍待逐事件证明。不得把 mini PASS 扩大解释为生产 proof PASS。

## [2026-10-28 14:00] T01–T06 全量准备与机械回测
- 隔离树（**已于 2026-10-30 退役，79cc2b7 已 merge 进 main，树与分支均删除**）原位于 `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027`，branch `research/corporate-action-fix-20261027`，base ce7d1c6；退役时四个公司行动文件冻结，生产接线 `core → ctx → recorder → bridge`、CA hook、数量 resolver 与 finally 审计已完成。独立质量门及退出证据复核 PASS：`C:/Users/yanwen/AppData/Local/Temp/opencode/staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md`；378回测测试（2 skip）、109定向、Ruff/Pyright通过，16文件hash冻结于 `staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`。
- 全量准备 `staged_prepared_inputs_20261027_v12`：raw 4424、states 253分片、两窗coverage/fees、manifest+sha256匹配、原始日志 EXITCODE=0，耗时2040.9秒；tmux批处理显式cd工作树。W1 coverage 510692对（missing 17029/unknown 17909），W2 570696对（missing 15620/unknown 16605）。不得把全部缺失归因停牌或上市前：W2已枚举120缺bar中110 suspended、10状态unknown，汇总其余缺口缺逐条明细。`source_known=False`、`actual_after_tax_target_eligible=False`。
- v8按全窗判断空代码导致000792.SZ跨窗失败，已改按窗；v10日期外层循环配单代码懒缓存导致反复扫描253分片，已改代码外层；v6/v9无声退出与工具会话结束重合、无WER/OOM，工具作业对象回收为主要证据。长任务用tmux（psmux起始主目录，显式cd，短轮询；WMI为备选）；保留v1-v11失败证据不覆盖。
- 八窗原始结果 `C:/Users/yanwen/AppData/Local/Temp/opencode/staged_mechanical_results_20261028_v1`，tmux `cnn_eight_windows_v1` 自然退出0，但八窗均INCOMPLETE，实际税后目标资格0/8。独立逐账复核 `eight_windows_second_audit_20261028/audit.md`：W2 B1/S1/S2/C70主期机械NAV变化 +23.6794%/+7.8805%/+7.2273%/+16.9639%，沪深300 -5.4350%，逐日正持仓峰值5，buffer末均清仓；机械结果不是实际税后达标。E日S1/S2仍各持603185.SH 400股，次日清仓；B1/C70在buffer第2日清仓。主比较S2−B1=-16.4520个百分点，不能事后择优。
- W1四窗于2021-06-08同一 `dividend:27726`（300502.SZ）因非整股 fail-closed 中断，无完整收益：登记B1=4000、S1/S2各1300、C70=2800股；每股转增0.4002532，每股现金0.2717082元。目标2021-030官方PDF已核 `https://static.cninfo.com.cn/finalpage/2021-06-01/1210131886.PDF` SHA `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`：第1–3页确认每10股转4.002532、派2.717082、回购股不参与；第3页尾数由大到小排序、同尾随机、6月8日记入；第4页无限售股份当日可交易。缺全体账户排序/中登分配结果，虚拟账户实际获配仍未知，禁止直接改成0.4或假定取整。第3页现金税随持股期差异化，20%即时扣缴只属压力情景。
- W2公司行动context确实接入；旧 `corporate_action_provider=none` 不能推断未接线。三个实际股息事件000799/002821/600098已登记并按20%现金压力政策到账；此非实际个人税制。纠正后的证据见 `w2_exposure_evidence_20261028/README.md`。条件固定路径税额重估不能证明动态税后收益，见 `ca_uncertainty_bounds_20261028/`。
- W1 300502次日原卖单限价46.18元，而2021-06-08最高34.55元，条件下原单不能成交；假设floor/ceil的一股差可经整手/槽位/资金影响后续，不构成完整收益差上界。2026-09后存在部分行情，但尚无事前冻结模型信号、连续执行账本和完整同期基准链，见 `clean_exam_data_inventory_20261028/clean_exam_inventory.md`。2026-01~08已探索不可当新规则独立验收。

## [2026-10-27 22:27] 路径与配置事实
- gap文件为 `staged_execution_input_snapshot_20261027_v1/task1_v3/data/gap_index_v1.parquet`；同目录canonical和gap schema不同，不能整目录扫描。canonical SHA `36f7ea0e085bcdd03b58dca2a11e5494574f3a55e6625b781b132d876058b755`。
- W2模型 `three_day_models/W2_F4_v1/run_20261026_212052/best_model.pth` SHA `03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4`；信号列 code/date/exp_ret/true_ret/status/label_availability/buy_eligible，W1 4186码、W2 4424码。
- W1 anchor 2020-12-31、E 2021-06-30；W2 anchor 2021-06-30、E 2021-12-31；4424代码均有板别映射，预检PASS。预算100万元、五槽每槽20万元，固定B1/S1/S2/C70；E收盘禁止进入buffer的新BUY，E−1订单可在E执行。

## [2026-10-29 21:53] 000601.SZ 公司行动事件审计（id 17916/17917/17918）
- 为核验2025模拟A中guard触发的000601.SZ dividend:17916事件，对韶能股份2025半年报、2024年报、2024中期三个公司行动事件进行定向公开取证。
- 2025半年报（id 17916）：新浪转载全文声明"半年度不派发现金红利，不送红股，不以公积金转增股本"，但巨潮/深交所官方PDF附件未找到可核实的URL，不能以新浪替代官方原件；零金额/进度码不能单独判定"不分配"。
- 2024年报（id 17917）：年报摘要声明"不派发现金红利，不送红股也不以资本公积金转增股本"，但后续股东大会决议及实施状态的官方原件未核实。
- 2024中期实施（id 17918）：巨潮官方实施公告PDF已下载，SHA-256 `710E27D900FEA7317085CB37862C6D40353EA6C49F4B100BE7893D1B7F82A698`，此为另一独立事件，不能替代前述事件核验。
- 取证材料存于 `C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_000601_official_20261029/FINDINGS.md`。后续补充定位线索已给到新浪链接但官方PDF定向追查尚未完成结果即会话结束。