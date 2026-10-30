# 策略探索最终交付说明

**报告日期：2026-10-30**  
**范围：汇总截至报告时点已盘点的模型、策略、数据、执行链路与独立复核证据。**  
**性质：研究交付与验收结论，不是策略达标声明。**

## 1. 总结与联合目标验收

用户目标由三个必须同时成立的条件构成：扣除交易成本后收益非负；严格跑赢同一时期沪深300；实际持仓在任一时点不超过10只。现有研究中**没有任何策略通过这三项联合验收**。个别机械回放在特定假设下同时呈现正收益、正超额和模拟持仓不超限，仍缺独立考试资格所需的PIT、真实可得时间、完整性和税务证据。

“未证明”不等于“证明必亏”。W2四策略是当前较完整的正向机械历史证据；它支持保留复核，不支持宣称找到可执行且经验证的策略。本文不把不同报告、样本、资金规模或持仓口径的收益拼成总冠军。

## 2. 工作树全景与生命周期

截至2026-10-30工作树退役完成，本CNN repo只剩一棵工作树：主区 `D:/code/cnn_full_20260905/cnn`。本地仅剩 `main` 与 `feature/rolling-normalization-cnn` 两个分支。主区HEAD随恢复与收口提交继续前进，**本报告不写死hash**：退役当时的HEAD是merge commit `997bc71`（父提交 `ce7d1c6` 与 `79cc2b7`），其后依次追加了 `quantity_rules` 入库、W1/2025 研究源码恢复与 CI 导入顺序收口，当前值以 `git log --oneline -1` 实查为准。

| 状态 | 路径 | 分支 | 报告时点说明 |
|---|---|---|---|
| 唯一存活：主区 | `D:/code/cnn_full_20260905/cnn` | `main`（HEAD 参见 `git log`） | 退役时的未跟踪 WIP `backtest/cnn_adapter/quantity_rules.py`、`tests/unit/backtest/test_quantity_rules.py` 及 `staged_order_strategy.py` 接线**已入库**，不再是未跟踪项；剩余 dirty 项以 `git status --short` 实查为准 |
| 2026-10-30已删除（无ZIP） | `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027` | `research/corporate-action-fix-20261027`（已删除） | 唯一提交 `79cc2b7` 先经 merge `997bc71` 合入主区，随后工作树与分支一并删除；当时生成的ZIP归档亦按用户指示删除，未保留 |
| 2026-10-30已删除（无ZIP），源码已事后恢复 | `C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028` | `research/w1-fractional-scenarios-20261028`（已删除） | 退役时其未提交研究代码未入任何Git提交、树与ZIP均删；**事后已从会话数据库 `opencode.db` 快照恢复该树对应的 W1 fractional 源码与测试并提交（`8cd25a9`）**，另见下节 |
| 2026-10-30已删除（无ZIP），源码已事后恢复 | `C:/Users/yanwen/AppData/Local/Temp/opencode/validation-2025-restricted-20261029` | `research/validation-2025-restricted-20261029`（已删除） | 同上：树与分支确实不复存在，但2025受限链源码与测试已随恢复提交入库 |

三棵研究树的 worktree 与 `research/*` 分支确实已删除，退役时生成的ZIP归档也按用户指示删除，磁盘与Git中都没有树的副本。**但“因此研究资产永久损失”这个当时结论已被推翻**：退役前的会话记录保存在 `C:\Users\yanwen\.local\share\opencode\opencode.db`，恢复代理以只读方式从其中的 `read` 文件快照为基线、重放其后的变更事件，重建出 18 个目标文件，全部通过语法编译，18/18 有独立可验证的最终状态证据（66 个后置快照逐字节比对全一致；5 个有 23:07 全树哈希的文件前缀全匹配）。恢复证据目录为 `C:/Users/yanwen/AppData/Local/Temp/opencode/recovered_w1_20261030/`（含 `MANIFEST.json`、`REPORT.md`、`raw_patches/`、`recovered/`，只读勿改）。

已恢复并入库的 18 个文件（提交 `8cd25a9`，6382 行新增；该提交内容逐字节比对 MANIFEST 为 18/18 一致。注意当前 HEAD 的 `scripts/run_2025_restricted.py` 已被 `ff7e606` 改动，故现文件 17/18 与 MANIFEST 一致，原始字节用 `git show 8cd25a9:scripts/run_2025_restricted.py`）：

| 已恢复的研究代码 | 原所属工作树 | 现状 |
|---|---|---|
| `backtest/cnn_adapter/fractional_scenarios.py`、`fractional_prefix_gate.py`、`fractional_scenario_cli.py` | W1 fractional | 已入库，可查阅、可演进 |
| `backtest/cnn_adapter/prefix_attestor.py`、`prefix_ledger_verifier.py` | W1 fractional | 已入库，但 pin 陈旧（见下） |
| `backtest/cnn_adapter/validation_2025_bridge.py`、`validation_2025_execution.py`、`scripts/run_2025_ab_execution.py`、`scripts/run_2025_restricted.py` | 2025受限 | 已入库；`run_2025_restricted.py` 后续由 `ff7e606` 加 `# noqa: I001` 守 CI 零告警 |
| `test_fractional_scenarios.py`、`test_prefix_attestor.py`、`test_prefix_ledger_verifier.py`、`test_validation_2025_bridge.py`、`test_validation_2025_execution.py`、`test_2025_restricted{,_fix2,_fix3}.py`、`test_ca_evidence_adapter.py` | W1 fractional / 2025受限 | 已入库；部分通过、部分 skip、部分因缺契约文件报错（见下） |

**恢复不等于可用。** 恢复出的是 2026-10-29 08:00 会话被中止时的真实未完成状态，不是能全部通过的状态。该状态随后又被两类后续提交部分修补（`ff7e606` I001 收口、`436cb73` 修 `fractional_scenarios` 十错与补 `announcement_visibility` 键并给 7 个依赖未回收接口的用例加 `@unittest.skip`），因此**本文不写死通过数以保持可复核**；按当前 HEAD 实测量级如下（复现：`uv run --project . python -m unittest tests.unit.backtest.<模块>`）：

- `test_fractional_scenarios`：恢复态为 10 errors，根因是依赖 W1 树版接口 `CorporateActionContext(asof_announcement_dates=)` 与 `run_staged_window(fractional_scenario=)`（`git log --all -S` 对这两个符号 0 命中）。`436cb73` 后变为 OK(skipped=7)——**要注意这是“跳过”而非“通过”**：7 个用例被显式标为依赖未回收的 W1 版 `staged_candidate_runner`/`staged_production_inputs` 接口（`fractional_scenario` 参数、prefix proof 前置门禁、`--prefix-stop-after-close`/`--information-cutoff` CLI）。
- `test_prefix_attestor` 1 error：`prefix_attestor.fixed_source_sha256()` pin 的 15 项中 11 项与主区不符，且 `core` 路径硬编码指向已退役的 `backtest-core-w1-stop-20261028`。该 pin 在删除前已陈旧（冻结于 07:00，而被 pin 的文件在 07:58 被改），属当时既存缺陷。
- `test_prefix_ledger_verifier` 1 error；`test_validation_2025_bridge`(17) 与 `test_validation_2025_execution`(4) 全绿。
- `test_2025_restricted{,_fix2,_fix3}` 与 `test_ca_evidence_adapter` 全部报错，失败形态是运行期 `FileNotFoundError`（不是“导入即崩”）：这些用例按绝对路径去读已退役树 `corporate-action-fix-20261027/` 与只在 `Temp/opencode` 下的契约文件（如 `staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`、`validation_2025_local_inputs_20261029/ca_full174/delivery_manifest_v4.json`），主区父目录 `D:/code/cnn_full_20260905` 下没有这些路径。具体缺失项随工作区改动而变，**以实时运行输出为准，本文不写死**；`REVIEWED` 亦指向已退役树。
- 两个 pin 世代互相矛盾，不能同时成立，因此不存在“全绿”的恢复态。

外置只读证据目录（如 `eight_windows_second_audit_20261028`、`w1_real_prefix_independent_audit_20261029`、`validation_2025_*`）仍在 `C:/Users/yanwen/AppData/Local/Temp/opencode/` 下，未被本次退役删除；现在它们是源码之外的**时间点冻结证据**，与已入库源码互为交叉校验，而不再是“源码的唯一替代品”。

**仍不可回收的部分必须与已恢复部分分开记。** 18 个文件之所以跑不通，是缺 8 个「W1 版」依赖模块的接口版本：`staged_candidate_runner`、`staged_production_inputs`、`corporate_action_context`、`historical_costs`、`staged_order_strategy`、`raw_market_provider`、`raw_market_inputs`、`corporate_action_snapshot_loader`。注意区分**主区现有同名模块已入库、可查可改**（6 个随 CA 收口入库，`historical_costs` 随 `7f0fb2a`，`staged_order_strategy` 的接线随 `ab1138b`），与**W1 树上的那版接口确实无法回收**：`git log --all` 对这些 W1 版接口符号 0 命中，`raw_patches/` 的 621 个补丁中也没有它们的记录。按主区 HEAD 实测：`CorporateActionContext` 仍无 `asof_announcement_dates` 逐日 as-of 裁剪（`436cb73` 只能让子类自行记录该标志并注明口径不伪装逐日 PIT），`run_staged_window` 仍无 `fractional_scenario` 参数，`prefix_ledger_verifier` 仍依赖该证据字段。因此 W1 条件模拟不能按原样跑通，需要另开任务按 W1 语义重建那层接口，不能宣称“W1 工具链已恢复可用”。

独立 `backtest-core` repo 中与 W1 相关的树 `backtest-core-w1-stop-20261028` 亦已于本次退役删除。其未提交的 `stop_after_close` 补丁先被保存为纯文本，并已正式提交到 core 主区 `D:/code/cnn_full_20260905/backtest-core` 的 `main`，提交 `a176be9`；验证为 718 项测试、Ruff 与 Pyright 全部通过。该补丁因此可复用。

更早一轮（2026-10-28）退役的是另外三棵CNN repo子树，与本轮2026-10-30退役不是同一批。该轮以ZIP保全非基线载荷后再普通删除分支（`git branch -d`，不是强制删除）；各ZIP仅收录对应树的ignored/untracked及其他非基线载荷，具体以各目录清单为准；tracked基线文件由Git HEAD保留，不包含在ZIP载荷中。因此这些归档不等同于完整worktree备份，也不表示包含所有研究目录或全部研究工件。归档逐文件哈希/CRC复核通过，主区WIP未改：

| 已退役工作 | 子树非基线载荷ZIP | SHA-256 |
|---|---|---|
| 数量规则 | `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/board-quantity-rules/board-quantity-rules-full-archive.zip` | `80cef23a7801ff7d594be15815015c35813f3b8d7f83a86bcf026139916df10f` |
| staged-runner-v2 | `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/staged-runner-v2/staged-runner-v2-full-archive.zip` | `097080795cc6fcac3774bf98a9f4c129b256a6a762cf53b421cbbfa66a5f6d98` |
| 旧CA context | `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/corporate-action-context/corporate-action-context-full-archive.zip` | `f3a95769525b8822f75f61e26105ce1084ab09157cf045307691873db4b3848b` |

该2026-10-28退役报告记录每棵树的保全范围、清单、hash与普通branch删除结果。它只对应上述三棵更早退役的子树，既不是本轮2026-10-30退役的记录，也不是当前工作区状态报告；完整过程见 `worktree_retirement_20261028/REPORT.md`。

## 3. 策略研究与有效性矩阵

各研究使用的模型、样本、资金、持仓口径不同，指标不可横向拼接成排名。以下仅概括其对本次联合目标的证据效力。

| 研究线 | 模型/样本/账户口径 | 观察结论 | 联合目标状态 |
|---|---|---|---|
| 旧CNN分类 | CNN分类器；多轮训练与历史分类窗口；组合口径随实验而异 | 部分分类输出塌缩或排序/组合表现不稳定 | 未通过；不是一个冻结的≤10只全链路策略 |
| 截面HGB/tree rank | 梯度提升树截面排序；历史研究样本；既有动态退出组合曾用20只目标仓位 | 排序指标领先部分CNN基线；20只持仓版本违反上限，且有事后筛选和样本已观察问题 | 不通过；不能以IC或正收益替代联合门槛 |
| goal旧线 | 历史目标/组合研究；包含q5等版本 | 旧报告曾有较高早期数字，但持仓≤10未满足、停牌/退市处理不足；后续交易账户口径已修订 | 旧数字过期，不作为现行策略绩效 |
| goal_repro | 两个fold预测段分别为2024-07至2025-06、2025-07至2026-08；RankIC 0.1011/0.0727。R2账户回测本金¥2,000,000 | 高换手版本滚动年化−43.3%/−15.3%；`target s100/buf500` 两段+59.5%/+8.3%，惯性优于buffer0 | 本金¥2,000,000属于goal_repro独立复现，不同于2021 W2每策略¥1,000,000；组合容量/≤10只资格须遵从原报告边界，不能据数字判定达标 |
| 执行换手与buffer | 多种高换手/低换手及缓冲参数；研究各自资金与持仓设定 | buffer/惯性可减少不必要换仓，但结果依赖样本、执行与容量；不是统一资金口径的冠军赛 | 方法线索，不是联合验收 |
| m_t方向/幅度 | 12种方法，2019–2025 expanding walk-forward；方向、收益幅度与门控实验 | 方向AUC约0.50–0.55且置信区间含0.5；回归OOS R²为负。方向门使2025真实引擎年化由+42.59%降至+7.23% | 不支持方向择时门；不得将门控正收益当作有效预测证据 |
| m_t波动控制 | 绝对收益波动预测及波动缩放；报告基准为EQW proxy | abs-return IC +0.1787、R² +0.0366；波动缩放未显著或未由完整引擎验证 | 仅风险控制假说，不是交易alpha，也未验收 |
| alpha-m双塔 | alpha排序与方向/波动双塔；相同研究线历史样本 | 方向门使2025真实引擎年化从+51.43%降至+9.25%；波动缩放未显著且未引擎验证 | 不支持方向门；不得转述为完整策略胜率或联合绩效 |
| 2021 B1/S1/S2/C70 | F4信号；2021 W1/W2；每策略模拟账户初始¥1,000,000，固定五槽、每槽¥200,000，政策事前并列 | W2有完整机械账本；W1碎股事件中断。每个策略均受其固定分批/持仓政策约束 | W2仅历史机械基线；W1无完整收益；八窗均INCOMPLETE |
| 2025 A/B | 5135码信号宇宙；2025候选本地状态仅174码、行情172码；账户各自执行top5资格筛选 | A/B因未知公司行动登记日fail-closed中断；账本保留中断时账户状态，但无主期末NAV、无buffer末NAV/全年终值 | NOT_EVALUABLE；不能比较A/B年度绩效 |

goal_repro、m_research与归因研究主报告现位于主区：`research/goal_repro/REPORT.md`、`research/m_research/REPORT.md`、`research/alpha_attribution/README.md`；这些目录已在 `ce7d1c6` 中随主区存续，不依赖任何研究工作树。`research/goal/`（旧栈只读快照，39 特征/H5）已于 2026-10-30 删除，其结论由 `goal_repro/` 在新栈重做验证。m线以沪深300缺失窗口的EQW proxy为基准，且2026 OHLC缺失；其结果不能替代沪深300同期联合验收。F60数据检查发现73条 `is_trading=True` 但OHLC为0，研究已过滤并对市场输入增加非正价格拒绝，仍不代表全部行情源PIT已认证。

## 4. 2021 W1/W2回放结果与边界

W2主比较期为2021-06-30至2021-12-31，沪深300冻结**价格指数**收益−5.4350%，不含分红再投资。以下收益已扣除回放配置的交易成本，并已体现在期末NAV中：

| 策略 | 期末NAV | 主期收益 | 超沪深300 | 主期已计成本 |
|---|---:|---:|---:|---:|
| B1 | ¥1,236,793.85 | +23.6794% | +29.1144个百分点 | ¥146,403.21 |
| C70 | ¥1,169,639.36 | +16.9639% | +22.3990个百分点 | ¥93,901.05 |
| S1 | ¥1,078,805.32 | +7.8805% | +13.3156个百分点 | ¥42,247.14 |
| S2 | ¥1,072,273.38 | +7.2273% | +12.6624个百分点 | ¥40,887.08 |

四条日账本各129日，现金、持仓市值、应收与NAV逐日核平，最大日结误差≤¥2.33e-10；已计成本包括佣金、印花税、过户费与模型滑点。W2正持仓峰值为5只。E日仍持仓，至buffer末2022-01-06清仓；buffer收益不计入上表主期收益。策略政策事先固定且结果现已可见，必须并列保留，不能事后只选B1。

W1四策略均在2021-06-08的300502.SZ公司行动处理时中断，未得到E日NAV或完整收益。八个窗口（W1/W2四政策）全部为`INCOMPLETE`，实际税后目标资格0/8。W2的数值是受数据、PIT、税务和模拟账户假设限制的机械回放，不是实际账户成交或当时前瞻冻结策略；因此不能称目标验收。

## 5. W1碎股前缀迭代与未闭合事项

300502.SZ官方2021-030公告PDF：`https://static.cninfo.com.cn/finalpage/2021-06-01/1210131886.PDF`，SHA-256 `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`。公告规定每10股转4.002532股、每10股派现金2.717082元（即每股0.2717082元）；不足一股尾数按账户排序、同尾随机分配。四账户登记股数为B1 4,000、C70 2,800、S1/S2各1,300股；真实中登获配数未知。

floor/ceil仅为条件场景，不是实际分配，也不是完整收益差的上下界。v2八分支中5支退出码0但仍`INCOMPLETE`，3支ceil失败；已写的五类账本行仅与原基线现存行一致。截止6/7的记录含6/8待执行单，不证明6/8成交。ceil失败根因为有限精度Decimal数值转成小数字符串，再由`Fraction`做精确整除校验，在6/7登记observer hook触发；不是binary float余数问题，也不是6/8 hook。

fix2、fix3、fix5的mini验证通过其各自限定的机械检查；fix5独立reverify4为mini PASS。可信`PIN`仍空，没有真实prefix/proof在修复后重跑，也没有中登获配凭证。因此该迭代只修复/定位工程问题，未生成W1收益结论。

必须明确记录的后果分两层：**已恢复**——修复后的 prefix、attestor 与 prefix_verifier 源码（`fractional_scenarios.py`、`fractional_prefix_gate.py`、`fractional_scenario_cli.py`、`prefix_attestor.py`、`prefix_ledger_verifier.py`）退役时确未进入任何Git提交，但已从 `opencode.db` 会话快照恢复并随提交 `8cd25a9` 入库，现在可查阅、可演进、可按主区路径复核；**仍不可用**——它们依赖的 8 个 W1 版接口没有回收，`test_fractional_scenarios` 虽在 `436cb73` 后变为 OK 但其中 7 个用例是被显式 `@unittest.skip` 的（依赖未回收接口），两个 pin 世代互相矛盾，按当前 HEAD 仍不是可执行工具链。所以本节关于W1的收益结论**没有变化**：真实 W1 八分支从未成功运行，12 路径 proof 与绩效仍 BLOCKED，三个 `TRUSTED_*` pin 仍为 `None`；现有结论仍须以外置QA报告（`w1_real_prefix_independent_audit_20261029/REPORT.md`、`w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md`、`w1_prefix_independent_qa_20261028/reverify4/REPORT.md`）为准。不得把“fix5 reverify4 mini PASS”表述为已验收的工具链或已延续的研究资产，也不得把“测试 OK(skipped=7)”表述为 W1 已通过；源码已可在主区查阅，但“能查”不等于“能跑通、能出具可信证据”。

## 6. 2025受限链：实现状态与回放中断

2025受限链fix1–fix3围绕未知状态/公司行动保持fail-closed、受限数据接入、记录和审计边界迭代。fix3独立QA reverify3的入口SHA为`b1a5e69539cffbcb0ca7affddc2cfa15b97964c605a91c23f925ba33d96a9316`；38项定向检查、109项回归、Ruff与Pyright通过。结论仅是带假设的条件mini/机械QA，不代表正式adapter完成或策略绩效通过。

该链的执行入口与测试**已恢复入库**：`validation_2025_bridge.py`、`validation_2025_execution.py`、`scripts/run_2025_ab_execution.py`、`scripts/run_2025_restricted.py` 及 `test_validation_2025_bridge.py`、`test_validation_2025_execution.py`、`test_2025_restricted{,_fix2,_fix3}.py`、`test_ca_evidence_adapter.py` 现均在主区，可查阅与演进（`8cd25a9`；`run_2025_restricted.py` 的 I001 由 `ff7e606` 收口）。但**2025受限adapter工作仍不可继续按原样执行**：这些测试按当前 HEAD 全部报错，形态是运行期 `FileNotFoundError`——`test_2025_restricted*` 缺 `ROOT.parent/staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`，`test_ca_evidence_adapter`/`_fix3` 缺 `validation_2025_local_inputs_20261029/ca_full174/delivery_manifest_v4.json`，两份契约文件都只存在于 `Temp/opencode`，主区父目录没有；`REVIEWED` 亦指向已退役的 `corporate-action-fix-20261027`。既不能据此重跑A/B回放，也不能据此声称已实现正式adapter或产出`FREEZE`冻结产物；fix3 QA结论的使用边界不变（见下），源码可查不等于身份已签收。

年度v2账户回放都中断：A于2025-08-22遇到000601.SZ `dividend:17916`，持有33,600股、3次买入、已记录成本¥3,376.20732；B于2025-06-06遇到000506.SZ `dividend:63844`，持有23,600股、4次买入、已记录成本¥4,575.65435。账本保留了中断时的账户状态；两者均无主期末NAV、无buffer末NAV或全年终值，状态`NOT_EVALUABLE`。中断状态与局部交易记录不可外推为全年收益。

000601官方半年报PDF URL为`https://static.cninfo.com.cn/finalpage/2025-08-05/1224387247.PDF`，SHA-256 `A90B9633553D7C38F3BE3B503648E1476158A162FDC66DFC6C3596E4189E0445`；摘要披露不派现金、不送股、不转增。但全文具体页码/公告编号、id17917年度项目的最终股东大会决议原件和表决结果仍未闭合；id17918是独立的2024中期派息事件，不能互代。

000506在2025年称*ST中润。证券报表决材料称2025-058股东大会决议通过相关年度方案，同意278,487,901股（99.8560%）；年报摘要只是预案，巨潮股东大会决议PDF仍缺。证券报证据不能冒充官方PDF原件。CA evidence adapter复核状态为`DEADLINE_CLOSEOUT/BLOCKED`：只有fixture closing tests/logs，来源映射未实现，没有正式adapter及`FREEZE.json`/`FREEZE.sha256`等冻结产物。fixture测试保护默认guard，不授予真实事件override；继续fail-closed。

## 7. 数据覆盖、时点与研究限制

| 数据域 | 已见事实 | 结论边界 |
|---|---|---|
| 2021全市场准备 | prepared输入覆盖4,424代码、253个状态分片；v12完成并有manifest/SHA交叉绑定。W2 expected coverage 570,696对，missing 15,620、unknown 16,605；明细仅120条缺bar可逐条解释 | 不可把全部缺口归因停牌/上市前，也不能推定缺口无影响；`source_known=false` |
| 2025状态/行情 | 190个HDF文件、174码、40,796状态行；268个缺日原因unknown。raw行情仅172/174码、44,116行；000040.SZ、000584.SZ缺文件 | `history_known_at=UNKNOWN`，非PIT；不补零、不解释成无行情/无交易 |
| 2025公司行动 | 359条dividend，登记/除权/实施公告日分别229/229/229空，派息日231空，红股上市日355空 | 进度码和零金额不构成无事件或已实施证明 |
| 公司行动总体 | W2三笔股息有登记和压力税记账；覆盖并非全市场完整 | 未知事件保留unknown并fail-closed |
| 价格/基准 | W2对沪深300价格指数；m_t报告因指数缺口用EQW proxy；PIT/known_at未认证 | 价格指数非全收益；proxy不能冒充沪深300结果 |
| 行情异常 | F60检查有73条`is_trading=true`但OHLC=0 | 已过滤并拒绝非正市场价格输入，不等于全源校验完备 |

既有研究还受生存者偏差、财报字段PIT/披露时间、两融数据时间语义、供数源/历史版本不可用等限制。行日期、文件mtime、当前本地库值都不能单独证明决策时可见。SHA/manifest用于产物身份和传输完整性核对，不是PIT证书。

处理原则是保留unknown，不补位、不填零、不把零金额或进度码推成“无事件”；缺文件与停牌分开。已对部分生命周期缺口做官方暂停公告核验，但不外推到其余代码。模拟20%股息扣税与真实个人税务分开报告。所有输入按manifest/hash绑定来源，来源时点仍未知时不升级known状态。

## 8. 已解决的工程阻塞与QA含义

- 全量准备v12成功：4,424代码、253状态分片及两窗coverage/fees输入完成；manifest和SHA相互核对。长任务改用tmux运行并保留退出状态，避免工具会话结束造成的无声中止。准备成功只证明输入构建流程完成，不证明数据PIT或完整。
- CA整合将真实`backtest_core`执行链、context、recorder/bridge、公司行动hook、板别数量resolver和finally审计接入；数量规则按信号日解析到下一执行日。W1非整数转增保持fail-closed。QA范围包括冻结文件hash、core身份与机械执行回放，不替代实际获配或税务证明。其6个模块——`corporate_action_context.py`、`corporate_action_snapshot_loader.py`、`raw_market_inputs.py`、`raw_market_provider.py`、`staged_candidate_runner.py`、`staged_production_inputs.py`及对应6个测试——均已存在于主区并已提交，**可继续复用**（注意这是主区版本；W1 树上的同名接口版本仍未回收）。
- W1 fractional与2025受限两条研究线的工具（prefix/attestor/prefix_verifier、bridge/execution/run脚本及对应测试）现有**三种不同状态，不能笼统表述**：(a) 源码已从 `opencode.db` 快照恢复并随 `8cd25a9` 入库，可查阅、可演进；(b) 但依赖的8个W1版接口未回收，按当前HEAD部分测试仍报错，**不能当作可运行工具链**；(c) 其证据结论（真实八分支、12路径proof、绩效）从未改变，仍为 BLOCKED/INCOMPLETE，`actual_after_tax_target_eligible=false`。独立core树 `backtest-core-w1-stop-20261028` 的 `stop_after_close` 补丁则已作为提交 `a176be9` 进入core主区 `main`（718项测试、Ruff、Pyright通过），**可复用**。
- 不同版本的QA有过FAIL→修复→限定PASS：ceil Decimal/Fraction根因修复后的mini；W1 fix2/fix3/fix5 mini；2025受限fix3的定向/回归、Ruff、Pyright；公司行动整合的独立机械QA。各PASS都受样本与fixture/mini范围限定；源码虽已恢复，但这些PASS仍不能按当前HEAD原样重跑复验。
- 2025正式adapter/freeze仍BLOCKED；W1修复后真实prefix及可信proof未重跑；八窗仍INCOMPLETE。测试/静态检查通过只说明相应代码路径的工程检查通过，不表示策略收益、目标联合条件或数据来源通过。

准备及整合细节见`staged_prepared_inputs_20261027_v12/manifest.json`、`staged_integration_independent_qa_20261028/reverify1/QA_REPORT.md`及`staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`。这些路径位于临时证据根目录`C:/Users/yanwen/AppData/Local/Temp/opencode/`。

## 9. 费用、税务与持仓容量

W2模拟佣金买卖各万二、最低¥5，卖出印花税千分之一、过户费万分之0.2，并计模型滑点；四策略成本合计见第4节，已进入NAV。换手较高，尤其B1单边换手约初始本金29.05倍；成交真实性、冲击成本模型和真实券商费率没有历史PIT认证。固定成交路径的成本压力重算不改变订单/仓位路径，不是动态收益上下界。

W2现金股息采用20% `cash_dividend_20pct_stress`压力政策，不是已证实的真实个人税额、税务身份或交割日扣税。W2正持仓峰值5是模拟账户账本证据；2025中断前A/B各自只出现局部持仓，A前缀持有1只，但全年峰值未知。不能把这两类模拟持仓表述成已证明真实账户持仓约束。

## 10. 当前建议：证据基线与方法候选

当前不存在已验证的“最佳策略”。最完整的历史执行证据是W2固定四策略，建议B1、S1、S2、C70继续并列留作复核基线；不能因B1收益最高事后选胜者，也不能把历史机械基线提升为达标策略。

下一轮方法候选是假说：截面α排序，配合低换手/惯性目标buffer，并在策略与执行器层面硬性保证持仓≤10，再以预先冻结的费用和执行规则回放。保留原固定B1/S1/S2/C70政策作为比较。`s100`等既有目标数不自动满足10只上限。方向择时`m_t`门已有负向证据，不应加回候选；波动预测可作为风险控制研究，但未经真实执行引擎与干净样本验证，不能称有效策略。

## 11. 后续工作排序与明确门槛

1. 选定未来实际可执行的新鲜考试起点；不得把已观察的2026-01至08或事后推理的过去日期包装成独立样本。
2. 开始前固定并可信时间戳：模型权重与训练截止、代码/环境、证券宇宙、排序与不补位规则、持仓≤10硬约束、订单/退出/限价规则、费用/滑点、CA与税务政策、交易日历、沪深300基准口径和主期/buffer定义；保存内容哈希。
3. 每日不可变保存全市场输入、源发布时间与采集时间、known_at、全榜和拒绝/缺失项；保存订单意图、拒单、成交、费用、现金、持仓及日内峰值。不得删去未知代码后向下补位。
4. 在考试前关闭或显式阻断coverage、PIT、板别、CA、交易日历、费用和benchmark缺口；来源不能证实的事件继续fail-closed。W1若再研究，源码已恢复（`8cd25a9`），但须先补齐未回收的 8 个 W1 版接口、重设与当前文件一致的 pin，并取得模拟账户对应真实登记获配证据，否则只报告条件情景与中断。
5. 对固定≤10候选进行连续样本外回放，覆盖完整主期和预先约定buffer；独立复算输入身份、逐日账本、费用、基准和全程持仓峰值。
6. 预先写出通过/否决条件：完整数据与账本、成本后收益≥0、同锚点同期基准严格超额、全程持仓≤10必须同时满足；任何未知导致资格无法确认即记为未验收，不能择期、择基准或择策略补救。

## 12. 证据索引与报告校正

| 主题 | 主要证据 |
|---|---|
| 原三天汇报与W2目标复核 | `D:/code/cnn_full_20260905/cnn/docs/research/three_day_strategy_report_20261029.md`；`C:/Users/yanwen/AppData/Local/Temp/opencode/w2_goal_acceptance_review_20261029/结论.md` |
| 八窗账本、成本、buffer及coverage | `.../eight_windows_second_audit_20261028/audit.md`；`.../w2_mechanical_risk_review_20261028/audit_report.md`；`.../w2_exposure_evidence_20261028/README.md`；`.../w2_tax_fifo_independent_qa_20261029/独立审计报告.md` |
| W1前缀与ceil根因 | `.../w1_real_prefix_independent_audit_20261029/REPORT.md`；`.../w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md`；`.../w1_prefix_independent_qa_20261028/reverify4/REPORT.md`；源码已在主区（`backtest/cnn_adapter/fractional_scenarios.py`、`prefix_attestor.py`、`prefix_ledger_verifier.py` 等） |
| 2025输入与中断 | `.../validation_2025_local_inputs_20261029/FINAL_REPORT.md`；`.../validation_2025_ab_real_20261029_v2/annual/A/summary.json`及`.../annual/B/summary.json`；`.../validation_2025_restricted_independent_qa_20261029/reverify3/REPORT.md`；源码已在主区（`backtest/cnn_adapter/validation_2025_*.py`、`scripts/run_2025_restricted.py` 等） |
| 000601/000506事件核验 | `.../validation_2025_000601_official_20261029/FINDINGS.md`；`.../validation_2025_000506_official_20261029/evidence.md`；`.../validation_2025_ca_evidence_adapter_20261029/REPORT.md` |
| 模型、目标与m_t研究 | 主区`research/goal_repro/REPORT.md`、`research/m_research/REPORT.md`、`research/alpha_attribution/README.md`；主区`docs/prediction_target_and_tree_2026.md`（`research/goal/` 已于 2026-10-30 删除） |
| 2026-10-30工作树退役与CA合入记录 | 主区`docs/research/worktree_consolidation_20261030/README.md`；主区`scripts/research/README.md`；`79cc2b7`（CA收口）与退役当时的 merge commit `997bc71`（父 `ce7d1c6` + `79cc2b7`），后续HEAD以 `git log` 为准 |
| 研究源码回收（2026-10-30） | 主区提交 `8cd25a9`（18文件，6382行）；证据目录 `C:/Users/yanwen/AppData/Local/Temp/opencode/recovered_w1_20261030/`（`MANIFEST.json`/`REPORT.md`/`raw_patches/`/`recovered/`） |
| 更早一轮（2026-10-28）退役记录 | `C:/Users/yanwen/AppData/Local/Temp/opencode/worktree_retirement_20261028/REPORT.md`（含三份ZIP位置、SHA及退役记录；仅对应2026-10-28那批子树） |

上述省略号均指`C:/Users/yanwen/AppData/Local/Temp/opencode/`。该根下的外置只读证据目录本次未被删除，因此仍可作为索引目标；W1与2025两条线的外置报告是当时时间点的冻结结论，其对应源码已由提交 `8cd25a9` 恢复到主区，两者可互为交叉校验。凡原先指向已删除工作树的相对路径，本索引已改为指向主区路径（`research/...`、`docs/...`、`backtest/cnn_adapter/...`、`scripts/...`）或明确标注为外置只读证据；主区代码与材料归属以 `docs/research/worktree_consolidation_20261030/README.md` 和 `scripts/research/README.md` 为准。原三天汇报先前记载了只读证据盘点并形成总结；本次新增本总稿，归拢此前结论与后续补充的2025证据，不覆盖或改写原报告。原报告较早的2025事件未知结论，结合后续000601/000506定向公开证据，可更新表述为“部分方案/表决信息已找到、官方原件及最终事件链仍未闭合”；不把尚未验证内容升级为确定事实。

## 本次文档修订说明

- **修订日期：2026-10-30（两轮）。**
- **第一轮修订原因：工作树退役导致原文失实。** 原文第2节把三棵研究树列为“活跃”，并把它们描述为分别保全了公司行动执行整合、W1碎股情景与前缀研究、2025受限链材料；同时把 `research/goal` 等目录的归属错误地写成当时的CA整合工作树。上述“工作树仍在并保有其研究材料”的表述在2026-10-30退役后均不成立，已按实际存续状态改写。
- **第二轮修订原因：第一轮基于“18个文件已永久丢失”的判断已被推翻。** 恢复代理只读访问 `opencode.db`，以 `read` 文件快照为字节级基线、重放其后变更事件，重建出全部18个目标文件，提交 `8cd25a9`（6382行新增），逐字节比对 MANIFEST 为 18/18 一致；`ff7e606` 再收口 `run_2025_restricted.py` 的 I001 以守 CI 零告警。因此第一轮中所有“永久丢失/不可恢复/无法复现/已不可考/无法继续”的结论均属过时，已改为分层的“已恢复 / 仍不可用 / 证据不变”三段式表述。**本次修订只改资产存续状态的描述，未改动任何收益数字、PIT、税务、费用或联合验收结论。**
- **当前资产分层（取代第一轮的“不可恢复资产清单”）：**
  - **已恢复并入库**：18 个研究源文件 = `backtest/cnn_adapter/` 7 个 + `scripts/` 2 个 + 对应测试 9 个，提交 `8cd25a9`，可查阅、可演进。`fractional_scenarios.py` 落库为删除前最终态（248 行）；独立 QA 冻结的 229 行中间态可从 `recovered_w1_20261030/evidence2.json` 的 `part_id=prt_184f0b56a001LP1Bi1IElHpG1q` 无损复现。
  - **仍不可用**：需要 8 个未回收的 W1 版依赖模块的接口版本（`staged_candidate_runner`、`staged_production_inputs`、`corporate_action_context`、`historical_costs`、`staged_order_strategy`、`raw_market_provider`、`raw_market_inputs`、`corporate_action_snapshot_loader`；主区同名模块已入库，但 W1 版接口未回收）才能运行；`git log --all` 对这批 W1 版接口 0 命中，`raw_patches/` 621 补丁不含。按主区 HEAD 实测：`test_fractional_scenarios` 为 OK(skipped=7，跳过项即依赖上述未回收接口)、`test_prefix_attestor` 1 error、`test_prefix_ledger_verifier` 1 error、`test_2025_restricted*` 与 `test_ca_evidence_adapter` 运行期报 `FileNotFoundError`（按绝对路径读已退役树/外置契约文件）；`test_validation_2025_bridge`(17)/`test_validation_2025_execution`(4) 全绿。具体通过/错误数随并行提交变化，以实时运行为准。`prefix_attestor.py` 的 pin 删除前已陈旧，且两个 pin 世代互相矛盾，不能同时成立。
  - **证据不变**：真实 W1 八分支从未成功运行；12 路径 proof 与绩效仍 BLOCKED；三个 `TRUSTED_*` pin 仍为 `None`；`actual_after_tax_target_eligible=false`；联合目标仍未验收。
- **仍可复用者：** CA整合的6个模块及其6个测试已合并入主区；core 的 `stop_after_close` 已作为 `a176be9` 进入 core 主区 `main`。
- **未删除者：** `C:/Users/yanwen/AppData/Local/Temp/opencode/` 下的外置只读证据目录仍存在，作为时间点冻结证据与已入库源码互相交叉校验。

## 结论

历史回放、模型研究和工程QA提供了可继续复核的材料，但没有任何候选被证明同时满足成本后非负、严格跑赢同期沪深300、实际持仓任一时点不超过10只。W2四策略应以并列机械基线留存；α排序加低换手buffer及硬持仓上限是后续待验证假说。只有在新鲜样本、事前冻结、数据可得时点清楚、完整账本与基准可独立复算后，才可作联合目标通过结论。
