# 八项不可复现项的补全可行性分析（2026-10-30）

- **性质**：只读分析。未修改/删除任何仓库文件，未执行任何 git 写操作。
- **唯一写操作**：本文件。
- **输入报告**：`../10-五问探索/q3_reproducibility_report.md`、`../10-五问探索/q4_blockers_solutions_report.md`、`../10-五问探索/q5_next_plan_report.md`
  > **路径订正**：任务书给的 `C:/Users/yanwen/AppData/Local/Temp/opencode/{q3,q4,q5}*.md` 三个文件**不存在**。三份报告的实况在仓库内 `docs/research/review_20261030/`（q3 25163 B / q4 43743 B / q5 34531 B，均已被 `84ca4fe` 前后入库）。本分析读的是仓库版本。
- **本轮实测新增证据**：A5 全提交穷举、D3 端到端打通、URL 假阳性剔除后的 E2 路径重算、TRANSPLANT 树可重建性验证、`run_identity.py` 存在性核查。凡与 Q3 数字不一致处均在下文标注。

---

## 1. 总表

| 项 | 卡点形态 | 最佳补救 | 成本 | 补完判定 | 复原还是新建 | 与不做清单冲突 |
|---|---|---|---|---|---|---|
| **A4** 八窗重跑 | **缺 runner 源码 pin**（不是缺数据）。`_verify_prepared` 只校验 artifacts+core，不校验 runner；历史产物 `attempt_audit.json`/`manifest.json` **无任何 cnn-side runner 哈希**（实测键集：`core_runner_sha256` 有、cnn runner 无） | 三角互证：commit(79cc2b7) + v12 manifest(4812/4812) + 账本恒等式(2.33e-10)；并为**将来**加 runner pin 门 | 小~中 | **部分** | **三角互证=复原（限于"输入+账本"，不含"进程"）**；重跑=新建 | **部分冲突**：N4（不重跑求收益）。三选一方案里只有"加门+三角互证"不冲突 |
| **A5** v12 来源 | **缺 4 个文件的字节**（`raw_market_inputs/provider` + 各自 test）。已用 177 提交×3 行尾变体×全历史穷举确认**从未落盘** | 出**限定性声明**：4812 artifacts 中 4808 可追溯、4 项标 UNREPRODUCIBLE | 小 | **部分（限 4 项除外）** | **声明=复原**（是对既有事实的准确描述，不是新建证据） | **不冲突**（N5 明确"不猜内容"；标 UNREPRODUCIBLE 正是 Q3 P2-8 建议） |
| **B3** 证明链 | 15 项 pin 中 5 DIFF + 1 MISS 指向不存在字节；**两份"独立"清单同源**（53ce8d8e/000c382d 同时失效） | 只重建 2 项（`fractional_scenarios`/`_cli`，`git show 8cd25a9` 可取），其余 4 项+1 MISS 标 UNREPRODUCIBLE，**保留红灯** | 中 | **仍否**（证明力不因重建 2 项而恢复） | 重建的 2 项=复原；整体结论=仍否 | **强冲突**：N1（不重签）、N2（不修绿）→ 判"不能补" |
| **B4** 八分支重执行 | 4 个依赖树全删；`prefix_ledger_verifier.py` 硬编码 5 处路径 | 无可行补救（改路径=新建，不改=必然失败） | 大 | **仍否** | 只能新建 | **强冲突**：N4（不重跑）、N3（不重建字节副本）→ 判"不能补" |
| **C2** 2025 重跑 | PYTHONPATH + `REVIEWED` 指向已删树；`main_root` 硬编码；`review_identity_available()=False` 实测 | 改 `CNN_2025_EVIDENCE_ROOT` 只能换根，**不能造出 `corporate-action-fix-20261027`** | 大 | **仍否** | 只能新建 | **冲突**：N6（不改 NOT_EVALUABLE）+ N4 → 判"不能补" |
| **C3** 测试验证力 | 40 用例 33 skip，统一原因"依赖已退役树"；skip 计数无 CI 门 | 加 CI skip 阈值门（只防将来）+ 逐条标注"哪些断言因 skip 而从未真跑" | 小 | **部分**（能把"伪装绿"变"显式红/显式 skip 统计"，但不能把 skip 变 pass） | 加门=新建（防复发）；标注=复原 | **不冲突**（不动 N2 的红灯） |
| **D3** F=45 旧口径 | **Q3 判"不可复现"过严**：v3 scaler 代码在 `4f7c4cd`、legacy39 pkl 在盘（untracked）、checkpoint 在 `logs/KEEP/run_20260905_183102`（untracked）**全部实测可用** | 用 `git show 4f7c4cd:data/scaler.py` + legacy39 pkl + KEEP checkpoint 重算指标 | 中 | **部分→可升"是"（限指标，不含训练重跑）** | **复原**（用当时的代码+当时的权重+当时的 scaler） | **不冲突**（N13 只禁把 pkl 提交进 git，不禁使用它） |
| **E2** 换机重建 | 74→实测 **58 处/31 文件**（Q3 口径偏大，见 §3 E2）；分 **生产 25/14** + **只读快照 33/17**；4812 artifacts 键全为绝对路径；P0-1 已复制 6 根+112 外部依赖，**但漏了至少 1 个被代码引用的根** | ① 修生产侧 14 文件 25 处；② 一律走 sidecar `RELOCATION_MAP`；③ 补拷遗漏根 | 中 | **部分→否**（代码侧可改，冻结产物侧不可改） | 修代码=新建能力；改 manifest=破坏身份 | **冲突**：N14（不改 manifest 键）→ 只能 sidecar + 代码相对化 |

**计数变化（若全部按最佳补救执行）**：是 0 项 / 部分 5 项（A4、A5、C3、D3、E2）/ 仍否 3 项（B3、B4、C2）。
其中 **D3 是最有可能从"否"直接升到"是"的一项**（Q3 判定偏保守，本轮已实测打通端到端）。

---

## 2. 八节明细

### A4 · 八窗回放的"实际运行"不可复现

#### 2.1 卡点的精确形态（本轮实测更正 Q3）

Q3 §A4 列了三个阻断点。本轮实测确认两个、并**新增一个更关键的**：

| 阻断点 | Q3 表述 | 本轮实测 | 形态 |
|---|---|---|---|
| ① cwd 指向已删树 | `run_eight_windows_v1.cmd` 首行 `cd /d ...\corporate-action-fix-20261027` | 确认（cmd 文件仍在，逐字读出） | **路径**（可改） |
| ② `--run-root` | `mkdir(exist_ok=False)` | 确认（`staged_production_inputs.py:634`） | **行为**（可改） |
| ③ **runner 无 pin** | `_verify_prepared` 不校验 runner 自身 | **确认，且更严重**：历史产物里**根本没有可校验的东西** | **签名/元数据**（不可追补） |

第 ③ 点的实测细节（这是 A4 真正的死结，Q3 只说了一半）：

- `_verify_prepared`（`staged_production_inputs.py:617-627`）实际只做四件事：manifest 自校验 → `artifacts` 逐条 `file_sha256` → **core 文件** `file_sha256` → core import 路径一致性。**runner 自身源码（`staged_production_inputs.py` 及整个 import 闭包）不在任何校验里**。
- 我做了 runner 的 AST 传递闭包：**13 个模块**（`staged_production_inputs` + `corporate_action_context` + `corporate_action_snapshot_loader` + `quantity_rules` + `raw_market_inputs` + `raw_market_provider` + `staged_candidate_runner` + `staged_order_strategy` + `common` + `corporate_actions` + `historical_costs` + `staged_allocation` + `staged_execution_bridge`）。
- `SOURCE_HASHES_FINAL.json` 覆盖其中 **8/13**，**5 个未 pin**：`common.py`、`corporate_actions.py`、`historical_costs.py`、`staged_allocation.py`、`staged_execution_bridge.py`。（这 5 个都是 W2 八窗实际会执行的代码，却完全不在任何 pin 清单里——这是 A4 与 B3 的又一个共同缺口。）
- **但历史八窗产物里没有任何一处记录 cnn-side runner 哈希**。实测 `W2_B1/manifest.json` 的 `effective_config` 键集包含 `core_runner_sha256`（`aa156ec2…`）、`core_engine_version`、`core_policy_version`、`core_schema_version`、`prepared_manifest_sha256`、`action_input_fingerprint` —— **唯独没有 cnn runner 的 sha**。
- 更关键：`W1_B1/attempt_audit.json` 与 `W2_B1/manifest.json` 里**都没有 `controlled_run_identity` 键**。而 `run_identity.py`（`capture_run_identity`）**早在 `7f0fb2a`（2026-10-26）就存在**，`prefix_attestor.py:210` 也早已在读取 `attempt_audit.json["controlled_run_identity"]`。
  → **结论：W1 的 prefix 实验用了 run_identity，W2 的八窗没用。** 这不是"忘了记"，是 W2 八窗走了不走 `run_identity` 的那条 runner 路径（`staged_production_inputs.run_prepared_windows`）。
  → 这意味着**即便今天重建目录、修好 cwd、跑通成功，也无法证明"跑的是当初那一版 runner"**。Q3 的"静默版本漂移"判断成立且不可修补（对历史那次）。

#### 2.2 补救选项（保守 → 激进）

**选项 1（保守，推荐）：三角互证替代重跑**

用三份互相独立的既有介质交叉锁定"当时输入 + 当时账本"：

| 角 | 介质 | 实测强度 |
|---|---|---|
| 角 1：**commit** | `79cc2b7`（2026-10-29 23:23）是八窗运行的唯一候选树（`run_eight_windows_v1.cmd` 的 cwd 指向它，`TRANSPLANT.json` 记录移植基线 `ce7d1c6`） | 我核对了 `TRANSPLANT.json` 的 6 个文件哈希在 git 全历史中的命中：**2/6 命中**（`quantity_rules.py`、`test_quantity_rules.py`），**4/6 未命中**（`staged_order_strategy.py`、`staged_candidate_runner.py`、两个 test） |
| 角 2：**v12 manifest** | 4812/4812 校验通过（P0-1 已在新根重验，`verify_relocated_result.json`：`verified_count=4812, missing=0, mismatched=0, unmapped=0`） | **完全可用** |
| 角 3：**账本恒等式** | `nav = cash + Σmv + receivables`，独立重算 max abs err = 2.33e-10 | **完全可用** |

**三角互证的强度上限（必须写明）**：

- 能证明：**输入是那份输入**（角 2）+ **账本自洽**（角 3）+ **主干代码属于 79cc2b7 这一代**（角 1 的 2/6 命中 + core pin 命中）。
- **不能**证明：① 跑的确实是 `79cc2b7` 那一版 `staged_production_inputs.py`（`TRANSPLANT.json` 的 4/6 未命中，说明运行树上的这 4 个文件**不是任何 git 提交的字节**）；② 中间没有 patch 过；③ 进程环境（torch 版本、线程数）。
- 因此三角互证的上限是：**"输入可信 + 账本自洽 + 代码大体属于该代"，但"进程可重放"永远缺失**。这正是 Q3 的"部分"口径，不能升"是"。

**选项 2（中）：加 runner pin 门，但只对将来有效**

动作：改 `_verify_prepared`，把 runner 及其 AST 闭包的 sha256 写进 manifest，运行时比对（Q3 P1-5 建议）。

- 成本：**小**（半天，20~40 行 + 测试）。
- 前置：无。
- **效力**：**对历史那次零帮助**（历史 manifest 里没有这个字段，加了也读不到）。它的价值是"下一次跑不会再静默漂移"——是**新建能力**，不是**复原历史**。
- **必须写清**：加了这道门之后，若有人拿它去"重跑八窗"，跑出来的是**新 run**，不是 2026-10-28 的那次。`summary.json` 会重新生成，`main_return` 可能因环境差异而不同。**不能冒充原结论。**

**选项 3（激进）：真重跑**

动作：重建目录结构 + 改 cwd + 改 `mkdir` 语义 + 在新目录跑一遍。

- 成本：**中**（1~2 天，八窗 × 4 策略 × 2 窗，含 8.29 GB 账本目录）。
- **前置阻塞**：W1 四窗必然再次撞上 `dividend:27726`（300502.SZ 碎股）fail-closed，`main_return` 仍为 `None`。实测 `summary.json`：W1 四策略全部 `INCOMPLETE` + `main_return=None`，错误统一为 `noninteger_or_unrepresentable_share_quantity`。**所以"重跑八窗"最多只能复现 W2 四窗，W1 四窗永远拿不到收益。**
- **效力**：**纯新建**。即使 W2 四窗重跑出与 2026-10-28 完全相同的 `+23.6794%/+7.8805%/+7.2273%/+16.9639%`，那也只能证明"今天这一版代码能复算这个数"，**不能证明"当初跑的就是这一版"**（因为 4/6 文件哈希对不上任何提交）。
- **与 N4 冲突**：N4 明确"不重跑 W1 真实八分支去求收益"。W2 重跑不在 N4 字面范围内，但会重新生成冻结产物，**踩 R4 红线**（为让结果变好而改动已冻结产物）。

#### 2.3 补完后的证据效力

| 方案 | 判定从"否"→ | 复原还是新建 | 能支撑的最强弱结论 |
|---|---|---|---|
| 选项 1 三角互证 | **部分** | **复原**（描述既有事实） | "W2 四策略账本在给定输入下自洽，且输入完整性 4812/4812 可验；代码代次可锁到 79cc2b7 一代但非逐字节" |
| 选项 2 加 runner pin | 仍否（历史）→ 是（将来） | **新建** | "从今天起，runner 版本漂移会被拦住" |
| 选项 3 重跑 | **仍否**（且制造新证据） | **新建** | "今天的代码能算出同类数字"——**不能冒充原结论** |

#### 2.4 与不做清单冲突检查

- **N4（不重跑 W1 真实八分支去求收益）**：选项 3 直接冲突（W1 四窗重跑必 fail-closed，且 N4 已判"投入换不来验收资格"）。**服从 N4 → 选项 3 降级为不建议**。
- **N7（不因 tmux 退出码 0 就认为八窗跑通）**：三角互证时必须重申——历史那次的 `EXITCODE=0` 只证明批处理结束，八窗全部 `INCOMPLETE`（实测确认）。
- **R4（不改冻结产物）**：选项 3 会新生成 `summary.json`，与原件并列即污染。**服从 R4**。
- 选项 1、2 **不冲突**。

**A4 结论：能补，但只能补到"部分"。最佳补救 = 选项 1（三角互证，复原输入与账本）+ 选项 2（加门，只保将来）。不建议选项 3。**

---

### A5 · v12 prepared 输入来源可追溯性

#### 2.5 卡点的精确形态

- 缺的**不是路径、不是 schema、不是签名，是 4 个文件的字节**。
- 这 4 个：`raw_market_inputs.py`（pin `000c382d…`）、`raw_market_provider.py`（`53ce8d8e…`）、`test_raw_market_inputs.py`（`aa9d7205…`）、`test_raw_market_provider.py`（`a736ab4e…`）。
- **本轮独立复核（比 Q3 更彻底）**：遍历 `git rev-list --all` 全部 **177 个提交**，对 4 个文件 × 3 种行尾变体（raw / LF / CRLF）全排列比对，**全部零命中**。Q3 的"从未落盘"结论**成立且已升级为定论**。
- 补充确认：`SOURCE_HASHES_FINAL.json` 的 16 项中，本轮实测 **12 项命中**（含 6 项仅 LF 归一命中）、**4 项 MISS**——与 Q3 §A5 完全一致。

#### 2.6 补救选项

**选项 1（保守，推荐）：限定性声明**

动作：写一份声明，明确"16 项中 12 项可追溯、4 项不可追溯"，并把 4 项在 `SOURCE_HASHES_FINAL.json` 里显式标 `UNREPRODUCIBLE` + 原因。

成本：**小**（半天，纯文档 + 一处 JSON 注释性字段）。

**准确措辞（可直接采用）**：

> **v12 冻结输入来源可追溯性——限定性声明**
>
> `staged_prepared_inputs_20261027_v12/manifest.json` 记录的 4812 个 artifact 中，**4812 项全部通过 SHA-256 复算**（P0-1 迁址后重验：`verify_relocated_result.json`，`verified_count=4812/4812`，`missing=0`，`mismatched=0`，`unmapped=0`）。就此而言，**该输入的"内容完整性"是全量可验证的**。
>
> 但其"**来源可追溯性**"只能作出限定性主张：`SOURCE_HASHES_FINAL.json` 的 16 项源文件 pin 中：
> - **12 项可追溯**：可在 git 提交（含 LF 归一）或当前工作区逐字节复现；
> - **4 项不可追溯**：`raw_market_inputs.py`（`000c382d…`）、`raw_market_provider.py`（`53ce8d8e…`）、`test_raw_market_inputs.py`（`aa9d7205…`）、`test_raw_market_provider.py`（`a736ab4e…`）。经全部 177 个 git 提交 × 3 种行尾变体穷举，**在任何已落盘介质中均不存在与之匹配的字节**。判定：pin 记录时写入的可能是未经落盘的内存态内容，或落盘后又被修改而 pin 未更新。
>
> **因此本项结论限定为：除上述 4 项外，全部可追溯。** 这 4 项不满足"可从仓库+冻结介质重建"的定义，**不得**被视为已验证、**不得**以任何推测内容替代。凡引用 v12 输入的下游结论（如 W2 四策略回放），其证据强度上限为"输入内容完整、但其中 4 个源模块的版本不可考证"。
>
> 声明日期：2026-10-30。依据：`../10-五问探索/q3_reproducibility_report.md` §A5 与本轮 177 提交全历史穷举。

**选项 2（中）：从 `raw_patches` 或 `opencode.db` 反向找**

成本：**中**。前置：需要 `opencode.db` 只读打开 + 621 个 raw_patches 全量扫描。
**实测已否**：`docs/research/review_20261030/recovered_w1_20261030/raw_patches/` 下**没有任何 `raw_market*` 的补丁记录**（实测 `Get-ChildItem -Filter "*raw_market*"` 返回空）。`MEMORY.md` 也记载"`raw_patches/` 621 补丁中无它们的记录"。
→ **此路已封。**

**选项 3（激进）：猜内容重建**

**直接违反 N5**。且 Q3 已判"猜出来的不是原始版本，是假复现，比缺失更危险"。**不采用。**

#### 2.7 补完后的证据效力

- 选项 1 能把 A5 从 **"否" → "部分（限 4 项除外）"**。
- **这是"复原"而非"新建"**：声明描述的是既有事实（12 项确实可追溯、4 项确实不存在），没有制造任何新证据。
- 最多能支撑的弱结论：**"v12 输入的 4812 个 artifact 内容完整，其中 4808 项（≈99.92%）的源文件版本可考证；4 项不可考证，占比 0.08%。"**
- **不能**支撑："v12 完全可追溯"。必须保留那个洞的可见性。

#### 2.8 与不做清单冲突检查

- **N5（不猜 4 个 pin 的内容）**：选项 3 冲突，已排除。选项 1、2 不冲突。
- Q3 §P2-8 本身就建议"把这 4 项显式标注为 `UNREPRODUCIBLE` 并写清原因"——**正是选项 1**。Q5 §P1-4 也把"标 UNREPRODUCIBLE"列为该做项。

**A5 结论：能补，可补到"部分（限 4 项除外）"。最佳补救 = 选项 1 限定性声明。这是全部八项里"投入产出比最高"的一项。**

---

### B3 · W1 prefix 结论的可信证明链

#### 2.9 卡点的精确形态

- `prefix_attestor.fixed_source_sha256()` 15 项 pin：**4 EXACT / 3 仅行尾 / 7 真实差异 / 1 MISSING**（Q3 口径修正后的实测值）。
- 7 项真实差异中：**2 项可复原**（`fractional_scenarios.py` = `7112BEDE`、`fractional_scenario_cli.py` = `4e6246db`，均可用 `git show 8cd25a9:` 或 `evidence2.json` 快照重建）；**5 项不可复原**（`staged_candidate_runner` `37fcf150`、`staged_production_inputs` `cef7b7bb`、`staged_order_strategy` `9c87f2e1`、`raw_market_provider` `53ce8d8e`、`raw_market_inputs` `000c382d`）。
- 1 MISSING：`account_runner.py` 的 core pin `4d3a28c4`，路径指向已退役树。
- **致命点（Q3 §B3 已点出，本轮确认）**：`53ce8d8e` / `000c382d` **同时出现在 A5 和 B3 两份"独立"清单里，且两边都指向不存在的字节**。→ 两份清单同源，**互证能力为零**。

#### 2.10 补救选项

**选项 1（保守）：只重建 2 项 + 其余标 UNREPRODUCIBLE + 保留红灯**

成本：**小~中**（重建 2 项半天；标注半天）。
效力：重建的 2 项 pin 会从 DIFF 变 PASS（`test_prefix_attestor` 的失败点会前移到下一个 DIFF 文件），**但整体证明链依然断裂**——因为 5 项不可复原 + 1 MISS 是结构性缺失。

**选项 2（中）：重签三个 `TRUSTED_*`**

**直接违反 N1**。且 Q5 §P1-4 已写死充要条件：① 15/15 全部可复现（**永远不成立**）；② 第三方独立签署；③ 签完立刻真跑八分支。条件 ① 已被 177 提交穷举否定。**不采用。**

**选项 3（激进）：放宽 pin 容差让它变绿**

**直接违反 N2**，且 Q3 明确警告"它是 pin 断裂的唯一自动告警，修绿=拆警报器"。**不采用。**

#### 2.11 补完后的证据效力

- **仍否**。证明链的核心价值是"证明这些代码就是当初跑的那一版"，而 5 项永久不可满足 → 证明力无法恢复。
- 重建的 2 项是**复原**（`git show 8cd25a9:` 是真字节），但**整体判定不变**。
- 最多能支撑："15 项中 9 项可确证（4 EXACT + 3 行尾 + 2 重建），6 项不可确证"——这比"全不可确证"稍好，但**离"可信证明链"还差 6 项**。

#### 2.12 与不做清单冲突检查

- **N1（不重签）**：选项 2 冲突 → 排除。
- **N2（不把红灯修绿）**：选项 3 冲突 → 排除。
- 选项 1 不冲突，但**收益极低**（只把告警点前移，不恢复证明力）。

**B3 结论：不能补（判"否"）。可做的是"标注 UNREPRODUCIBLE + 保留红灯"，但那不叫补，叫如实记账。**

---

### B4 · W1 真实八前缀重新执行

#### 2.13 卡点的精确形态

- 缺的是**4 个目录**（Q3 实测 `Test-Path` 全 False）：
  - `w1-fractional-scenarios-20261028`
  - `backtest-core-w1-stop-20261028`
  - `staged_w1_prefix_fix5_attestation_20261028`
  - `staged_w1_prefix_fix5_runs_20261028`
- 而 `prefix_ledger_verifier.py` **硬编码 5 处路径**（`prefix_ledger_verifier.py:26/28/30/49/50`）。不改代码必然失败；改了代码就不再是"原始验证"。

#### 2.14 补救选项

**选项 1：重建目录结构**

成本：**大**。且——**这些目录的实际内容（隔离 core 的 `4d3a28c4` 版本、fix5 的 attestation 输出）在任何介质中都不存在**（Q3 已穷举）。所以"重建目录"只能是**造一个空壳或造一个新版本**。

→ **这是"新建"，不是"复原"。** 造出来的目录会让 `prefix_ledger_verifier` 跑通，但验的是**新造的东西**，不是 2026-10-28 那次。

**选项 2：改代码让路径可配**

成本：**中**。但改完 = 不再是原始验证器（`prefix_ledger_verifier` 的语义就是"验那份固定路径下的那份产物"）。

**选项 3：真跑八分支**

**违反 N4**（不重跑 W1 真实八分支去求收益）。且必然再次撞碎股 fail-closed（A1 中登配发未知，永久无解）。

#### 2.15 补完后的证据效力

- **仍否，且不可改善**。
- 三个死因叠加：① 原始产物目录不存在；② 硬编码路径不改则必败、改则失去原义；③ 即便跑通，A1（碎股真实获配）永久无解 → 结论仍只能是"条件情景"。
- **Q5 §P1-2 已做过裁决**：选项 (a)「完整做完 cutoff-safe 前缀 + 真实八分支重跑」**不建议**，理由是"即便全绿，A1 仍无解，投入换不来验收资格"。**本轮完全同意。**

#### 2.16 与不做清单冲突检查

- **N4（不重跑 W1 真实八分支）**：选项 3 直接冲突 → 排除。
- **N3（不重建 8 个 W1 版接口的字节级副本）**：选项 1 冲突 → 排除。
- **R4（不改冻结产物）**：任何重建都会污染原结论的边界。

**B4 结论：不能补。三个选项全部踩线或有硬阻塞。服从 N3/N4，判"仍否"。**

---

### C2 · 2025 A/B 重跑

#### 2.17 卡点的精确形态

- 缺的是**一个目录**：`corporate-action-fix-20261027`（既审树，已于 2026-10-30 删除）。
- 三重失效（Q3 §C2）：
  1. `launch_command.txt` 的 PYTHONPATH 指向已删树；
  2. `scripts/run_2025_restricted.py:23` `REVIEWED = TEMP / "corporate-action-fix-20261027"`；
  3. `main_root = D:/code/cnn_full_20260905/cnn` 硬编码。
- **本轮新增实测**：`scripts/run_2025_restricted.py:20-21` 有 `CNN_2025_EVIDENCE_ROOT` 环境变量可覆盖 `TEMP`。我实跑验证：
  - 设为 `C:/Users/yanwen/AppData/Local/Temp/opencode` → `review_identity_available() = False`（因为 `corporate-action-fix-20261027` 不存在）；
  - 设为 `D:/code/cnn_full_20260905/evidence_tmp_20261030` → `SOURCE_HASHES` 找到了（因为 P0-1 复制了 `staged_production_integration_delivery_20261027`），但 `REVIEWED` **仍不存在** → `review_identity_available() = False`。
  → **环境变量只能换"根"，不能凭空造出那个已删目录。** 这是决定性的：`verify_reviewed()` 要求 16 项逐字节命中，缺目录即 fail-closed，且 Q2 的代码明确写了"不提供降级通道"。

#### 2.18 补救选项

**选项 1（保守）：承认不可重跑，只保留 C1 的"拒绝交付"证据**

成本：**0**。效力：C1 已判"是"（中断证据自足），C2 判"否"不影响 C1 的价值。

**选项 2（中）：重建既审树**

需要 16 个文件全部逐字节命中 `SOURCE_HASHES_FINAL.json`。**实测其中 4 项（`raw_market_*`）永远无法命中**（同 A5）。→ 即便造出目录，`verify_reviewed()` 也会在 `raw_market_inputs.py` 处抛 `ValueError`。**此路必败。**

**选项 3（激进）：改 `verify_reviewed` 跳过 4 项**

**这等于拆掉 fail-closed 门**。Q3 明确警告不要做。且会让 `NOT_EVALUABLE` 的证据链失去可信度。

#### 2.19 补完后的证据效力

- **仍否**。
- 选项 2 是"新建一个长得很像的树"，但因为 4 项 pin 永远不匹配，**它连"像"都做不到**（会直接报错）。
- 最多能支撑：**无**。C2 的重跑能力不可恢复。

#### 2.20 与不做清单冲突检查

- **N6（不把 NOT_EVALUABLE 改成 EVALUABLE）**：任何"重跑出结果"的路径最终都会诱导把状态改掉 → 冲突。
- **N4（不重跑求收益）**：精神一致。
- **N5（不猜 pin 内容）**：选项 2 若靠猜 4 项内容来造树 → 冲突。

**C2 结论：不能补。服从 N4/N5/N6，判"仍否"。C1（证据自足）的价值不因 C2 不可重跑而减损——恰恰相反，C1 的价值就在于它"拒绝交付"的记录完整可查。**

---

### C3 · 2025 相关 4 个测试的验证力

#### 2.21 卡点的精确形态

- 缺的是**验证覆盖**（不是字节、不是路径）：
  - `test_2025_restricted`：24 用例，**18 skip**
  - `test_2025_restricted_fix2`：7 用例，**7 skip**（全 skip）
  - `test_2025_restricted_fix3`：7 用例，**7 skip**（全 skip）
  - `test_ca_evidence_adapter`：2 用例，**1 skip**
  - 合计 **40 用例 / 33 skip**
- skip 的机械原因是 `unittest.skipIf(not entry.review_identity_available(), "原因：依赖已于 2026-10-30 退役的 corporate-action-fix-20261027 既审树")`（`test_2025_restricted_fix2.py:18`）。
- **本轮实测复现**：`review_identity_available()` 返回 `False`（两种 `CNN_2025_EVIDENCE_ROOT` 设置下都是）。所以 skip 是**确定性的**，不是偶发。
- **核心问题不是"测试红了"，而是"测试绿了但没测"**——这是 Q3 判"否"的理由，也是本轮认为**最容易误读**的一条。

#### 2.22 补救选项

**选项 1（保守，推荐）：CI 加 skip 统计门**

动作：在 CI 里统计 `skipped` 数，对 2025/W1 相关模块设阈值（如 skip 率 >30% 则 FAIL 或至少 WARN 并打印）。

成本：**小**（半天）。
前置：无。
效力：**只防将来**。它让"33/40 skip 的绿色"不再能伪装成"验证通过"。对历史那次，它什么也改不了（历史结果已经发生）。

**选项 2（中）：逐条标注"哪些断言因 skip 而从未真跑"**

动作：在每个 skip 用例上加 `reason` 说明"本用例验证的 X 在 2026-10-30 后已无介质可验"，并生成一份 `SKIPPED_COVERAGE.md` 列出所有 skip 覆盖的断言。

成本：**小~中**（1 天）。
效力：**复原**（如实描述现状）。

**选项 3（激进）：把 skip 改回真跑**

需要重建既审树 + 4 项 pin 命中。**已被 A5/C2 证明不可能。** 若靠放宽条件让它跑 → **违反 N2 精神**（拆警报器）。

#### 2.23 补完后的证据效力

- **部分**。选项 1+2 能把"绿得可疑"变成"绿但明确标注 33 项未测"。
- 这是**"复原"+ "新建"混合**：标注是复原，CI 门是新建。
- 最多能支撑："该模块的 7 个用例从未真跑，其覆盖的断言在 2026-10-30 后不可验证"——这比"OK(skipped=7)"诚实得多，但**不等于验证通过**。

#### 2.24 与不做清单冲突检查

- **N7（不因测试 OK(skipped) 就认为验证通过）**：选项 1、2 与之一致（正是为了贯彻 N7）。
- **N2（不把 attestor 红灯修绿）**：C3 的整改不涉及 `test_prefix_attestor` → 不冲突。
- **N15（不为让 982 项全绿而改测试迁就代码）**：选项 1、2 不改测试语义，只加统计和标注 → 不冲突。

**C3 结论：能补，可补到"部分"。最佳补救 = 选项 1（CI skip 门）+ 选项 2（逐条标注）。这是纯文档/CI 工作，成本最小、收益最直接。**

---

### D3 · 旧 F=45 口径的指标复现 ⭐（本轮推翻 Q3 判定的唯一一项）

#### 2.25 卡点的精确形态（并纠正 Q3）

Q3 §D3 的判定是"**否**"，理由是：
1. 当前 `data/schema.py` 只有 52 raw + 1 shared mask = F=53；
2. 旧 F=45 需要 39 raw + **6 个** margin/short mask；
3. "这 6 个 mask 的 schema 已从代码中移除"；
4. `scaler_per_code_legacy39_2026.pkl` 是唯一载体（untracked）；
5. `logs/KEEP/scaler_per_code.pkl` 是 52→53，而 `config.json` 记的 `SCALER_PATH=logs/scaler_per_code.pkl` 在默认位置不存在。

**本轮实测发现第 3 条不成立**：

- 6-mask 的 schema **没有从代码中移除**，它完整保留在 git 历史里：
  - `23389d8`（2026-09-08）`data/scaler.py`：`SCALER_VERSION = "v3_per_code"` / `TRANSFORM_VERSION = "per_code_transform_v3"`，`mask_cols = [f"{c}_mask" for c in self.feature_cols if COL_TO_GROUP_PER_CODE.get(c) == "G9_Margin"]`（**6 个独立 mask**）。
  - `4f7c4cd`（2026-09-08 切新 parquet）：仍是 v3，同一 mask 逻辑。
  - `178f24e`（2026-09-14）才改成 v4（1 个 shared mask）。
  - 而且 **v3 的 `scaler.py` 是自包含的**（`GROUP_DEFS_PER_CODE` / `COL_TO_GROUP_PER_CODE` / `PER_CODE_CONFIG` 都定义在同一文件内，不 import `data.schema`）。
- **端到端实测（我已跑通）**：
  1. `git show 4f7c4cd:data/scaler.py` → 独立加载 v3 scaler；
  2. `PerCodeGroupedScaler.load('logs/KEEP/scaler_per_code_legacy39_2026.pkl')` → **LOAD OK**，`feature_cols_out` = 45，`mask_cols` = 6 个（`margin_balance_ratio_mask` … `short_sell_vol_ratio_mask`），version `v3_per_code`，`transform_version` `per_code_transform_v3`（与 pkl 内 `schema_manifest` 完全一致）；
  3. 从 `Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet` 读 39 列 → `transform_code('000001.SZ', arr, feature_cols)` → **输出 (500, 45)**，6 个 mask 列非零率 0.786/0.994/0.994/0.988/0.786/0.994，NaN=0，inf=0；
  4. `logs/KEEP/baseline/best_model.pth` 用 `ModelConfig(featurenum=45, cnn_out_channels=128, cnn_kernel_sizes=[1,3,5,7,10], d_model=256, nhead=8, num_encoder_layers=4, dropout_rate=0.3)` **strict load OK，401 keys**；forward `[4,45,60]` → `[4,52]` **跑通**。
- **第 5 条也不完全成立**：`logs/KEEP/run_20260905_183102/best_model.pth`（这是 `eval_base_2026_formal.txt` 第 1 行引用的那个 checkpoint）**实际存在**，位于 `logs/KEEP/run_20260905_183102/`（untracked，但未丢）。实测 sha256 = `ec952b87…`，401 keys，stem `(128,45,7)`。
- **仍成立的部分**：`config.json` 里 `SCALER_PATH=logs/scaler_per_code.pkl` 在默认位置确实不存在（只有 `logs/KEEP/scaler_per_code.pkl`，untracked）。

→ **精确形态：缺的不是代码、不是 schema、不是权重，缺的是"把这三样正确组装起来跑一遍"的一个脚本 + 一份 parquet 的列选择。所有介质都在盘上。**

#### 2.26 补救选项

**选项 1（保守，推荐）：按 F=45 口径重算指标**

动作：
1. 用 `git show 4f7c4cd:data/scaler.py` 得到一个**只读**的 v3 scaler 模块（不改主区）；
2. 加载 `logs/KEEP/scaler_per_code_legacy39_2026.pkl`；
3. 读 F60 parquet 的 39 列 + close，按 code 分组、`transform_code`；
4. 组装 `[N, 45, 60]` 窗口，用 `logs/KEEP/baseline/best_model.pth`（或 `run_20260905_183102`）推理；
5. 用 `scripts/eval_bins_mapping.py`（`e62d9f3` 版本，已含"52原样/11映射/13映射/日截面指标/多空spread"全部输出）算指标，与 `logs/KEEP/eval_base_2026_formal.txt` 逐项比对。

成本：**中**（2~4 天，主要成本在全市场 5195 只 × 490571 窗口的推理，约数小时 GPU/CPU + 调试）。
前置：无外部依赖（parquet 在 `Z:`，pkl 在 `logs/KEEP/`，权重在 `logs/KEEP/`，脚本在 git 历史）。

**选项 2（中）：只做"装载+前向"的形式验证**

动作：只验证"v3 scaler 能加载 + F=45 模型能前向"，不重算指标。
成本：**小**（半天，我本轮已实际做完）。
效力：能证明"链路是通的"，但**不能证明"指标能复现"**——因为没跑全量推理。

**选项 3（激进）：重训 F=45**

成本：**大**（50 epoch × 1225 万行）。且**没有必要**：权重已有（tracked/untracked 各一份）。

#### 2.27 补完后的证据效力

- 选项 1 能把 D3 从 **"否" → "是（限指标复现，不含训练重跑）"**。
- **这是"复原"而非"新建"**：用的是**当时的代码**（`4f7c4cd` 的 scaler）+ **当时的权重**（`logs/KEEP/baseline/best_model.pth`，2026-09-29 冻结）+ **当时的 scaler**（legacy39 pkl）。三者都是原始介质，不是重造。
- 唯一"新建"的是**组装脚本**。但组装脚本不参与数值计算，只做"读→变换→推理→统计"的胶水。
- 最多能支撑："`logs/KEEP/baseline` 的旧指标可被独立复算，误差在 [待测] 内"。
- **注意边界**：不能支撑"重训会得到同样权重"（D4 位级确定性不成立，Q3 判"部分"）。所以 D3 升"是"只覆盖**指标复现**，不覆盖**训练复现**。

#### 2.28 与不做清单冲突检查

- **N13（不把 19.4 MB 的 scaler pkl 直接提交进 git）**：选项 1 **只是读取** pkl，不提交 → **不冲突**。但若要长期保全，应按 Q5 §P0-3 复制到 `D:/backup` + 落一份 `SCALERS_IDENTITY.json`（**实测该文件当前不存在**，这是 D3 的残余风险）。
- **R4（不改冻结产物）**：选项 1 只读权重与 pkl，输出到新目录 → 不冲突。
- **N8（不在 2026-01~08 做新规则验收）**：D3 复算是**复现旧指标**，不是"新规则验收" → 不冲突。但必须**只做比对，不得据此调参或择优**。

**D3 结论：能补，可补到"是（限指标复现）"。这是本轮唯一推翻 Q3 判定的项。Q3 的"否"建立在"6 个 mask 的 schema 已从代码中移除"这一前提上，而该前提经实测不成立。**

---

### E2 · 换机/换目录重建

#### 2.29 卡点的精确形态（并纠正 Q3 的数字）

Q3 §E2 称"**74 处绝对路径，分布在 34 个文件**"。**本轮实测复算为 58 处 / 31 文件**（`*.py`，剔除 `s:/` URL 假阳性后 56 处 / 30 文件；含 URL 假阳性则 58/31）。差异原因：Q3 的口径包含 `s://` 开头的 URL（如 `https://pytorch.org/...` 的 `s://pytorch`），那是假阳性。

**分类统计（任务要求的核心）**：

| 类别 | 处数 | 文件数 | 可否修改 | 说明 |
|---|---:|---:|---|---|
| **生产代码（可改）** | **25** | **14** | ✅ 可改 | 其中 **2 处为 URL 假阳性** → 真实可改 **23 处 / 13 文件**。分布：`backtest/`(6) + `config/`(1) + `models/`(1，假阳性) + `scripts/`非frozen(6 文件) + `tests/`(3 文件) |
| **只读快照（不可改）** | **33** | **17** | ❌ 不可改 | `scripts/frozen/**`(11) + `research/**`(22)，pyproject `exclude` + AGENTS 明定 READ ONLY |
| **合计** | **58** | **31** | — | — |

> 口径说明：`*.py` 中 `[A-Za-z]:[/\\]` 共 58 处 / 31 文件。其中 2 处是 `https://` 被 `[A-Za-z]:/` 误匹配（`models/cnn_transformer/model.py`、`scripts/run_2025_restricted.py` 各 1）。**真实绝对路径 = 56 处 / 30 文件**；其中生产侧 23 / 13，只读快照 33 / 17。

生产侧的 14 个文件（全部列出，可直接开工）：

| 文件 | 处数 | 绝对路径性质 |
|---|---:|---|
| `backtest/cnn_adapter/prefix_ledger_verifier.py` | 5 | 4 处 Temp 已删树 + 1 处 `D:\code\...\.venv` |
| `backtest/cnn_adapter/prefix_attestor.py` | 1 | Temp 已退役 core 树 |
| `config/defaults.py` | 1 | `Z:/test/train_data/...F60...parquet`（win32 分支） |
| `models/cnn_transformer/model.py` | 1 | **URL 假阳性**（`https://pytorch.org/...` 的 `s://`），非真路径 |
| `scripts/run_2025_restricted.py` | 2 | 1 处 `D:/code/cnn_full_20260905/cnn` + 1 处 URL 假阳性 |
| `scripts/audit_z_corporate_actions.py` | 2 | `Z:/dev/quant_data_dev.db`、`Z:/dev/kline/day` |
| `scripts/build_ohlc_path.py` | 1 | `Z:/test/...F60...parquet` |
| `scripts/eval_bins_mapping.py` | 1 | 同上 |
| `scripts/eval_three_way.py` | 1 | 同上 |
| `scripts/run_backtest.py` | 1 | `Z:/test/kline_index/day` |
| `tests/unit/backtest/test_fractional_scenarios.py` | 3 | Temp 证据根 |
| `tests/unit/scripts/test_run_backtest_cli.py` | 3 | `D:/idx`、`D:/no/such/...`（测试用假路径，可改） |
| `tests/unit/config/test_config_defaults.py` | 2 | `D:/tmp/cache`（测试假路径，可改） |
| `tests/unit/backtest/test_historical_costs.py` | 1 | Temp harness |
| **合计** | **25** | 其中 **2 处是 URL 假阳性**（model.py + run_2025_restricted），真实可改 **23 处/13 文件** |

**除路径之外的换机障碍（比路径更硬）**：

| 障碍 | 实测 | 可解性 |
|---|---|---|
| v12 manifest 的 4812 artifacts **全以旧绝对路径为键** | 确认（`C:` 4809 / `Z:` 1 / `D:` 2） | **不可改**（N14：改键即改身份）。只能靠 sidecar `RELOCATION_MAP.json` |
| P0-1 已复制 6 根 + 112 外部依赖，`verify_relocated.py` → **4812/4812** | 确认（`verify_relocated_result.json`：`missing=0, mismatched=0, unmapped=0`） | ✅ 已解决 |
| **P0-1 漏了至少 1 个被代码引用的根** | 实测：`validation_2025_local_inputs_20261029`（`test_2025_restricted_fix3.py:24` 的 `CA_ROOT`）**在 evidence 副本中不存在**（`Test-Path` = False），只留在 Temp | **可补**（P0-1 补拷） |
| `Z:` 盘是 **UNC 网络盘**（`\\192.168.0.123\quant-data`） | 实测 `Get-PSDrive Z` → `DisplayRoot \\192.168.0.123\quant-data` | **换机必断**。`config/defaults.py` 的 `DEFAULT_PARQUET` 在 win32 下硬指 `Z:` |
| 3 个证据根不在任何 git | 确认（Q3 实测） | P0-1 已复制到 `D:`（部分缓解，但副本仍无版本控制） |
| `logs/KEEP/*.pkl`（D3 唯一载体）untracked | 确认；`D:/backup` 与 `SCALERS_IDENTITY.json` **均不存在**（实测） | **P0-3 尚未执行** |

#### 2.30 补救选项

**选项 1（保守，推荐）：代码侧相对化 + sidecar 映射 + 补拷**

动作，按优先级：
1. **补拷遗漏根**：`validation_2025_local_inputs_20261029`（及任何 `test_2025_restricted*` 会读的根）追加到 `evidence_tmp_20261030` + `RELOCATION_MAP.json`；
2. **生产侧 14 文件 25 处**改成 `Path(__file__).resolve().parents[N]` 相对推导 + 环境变量覆盖（如 `CNN_EVIDENCE_ROOT`、`CNN_DATA_ROOT`）；
3. **`config/defaults.py`** 加环境变量覆盖（`CNN_PARQUET_PATH`），保留 `Z:` 作为 fallback；
4. **`prefix_ledger_verifier.py` / `prefix_attestor.py` 的已删树路径**：这三处指向的东西**本身就不存在**（B3/B4 已判），改成"缺失即明确报 `UNREPRODUCIBLE`"而不是硬编码路径；
5. 冻结产物侧**一律不动 manifest**，只用 sidecar。

成本：**中**（1~2 天）。
前置：无。
效力：能让"生产链路"在换机后跑通；**但不能让历史证据在换机后"原样"重验**，因为 manifest 键仍是旧路径（只能靠 sidecar 翻译）。

**选项 2（中）：把 manifest 键改写成新路径**

**直接违反 N14**（冻结产物改键即改身份）。**不采用。**

**选项 3（激进）：把整个 evidence 根 git init + LFS**

成本：**中~大**（13.4 GB）。效力：解决"无备份"，但不解决"绝对路径"。

#### 2.31 补完后的证据效力

- **部分**。目标不是"把 E2 从否变是"（那不可能，因为冻结产物的键不可改），而是：
  - **生产链路**：换机后能跑（代码相对化 + 环境变量）；
  - **历史证据**：换机后能"经 sidecar 翻译后"重验（`verify_relocated.py` 已验证这条路可行，4812/4812）；
  - **永远做不到**：让 `_verify_prepared` 在不加 sidecar 的情况下直接在新机通过（因为它读的是 manifest 里的旧绝对路径）。
- **主要部分是"新建能力"**（代码相对化），**次要部分是"复原"**（补拷遗漏根 + 补 `SCALERS_IDENTITY.json`）。

**"换机重建还差几类东西"——本轮结论：3 类**

| # | 还差什么 | 现状 | 成本 |
|---|---|---|---|
| 1 | **代码侧路径相对化** | 生产 14 文件 25 处未改；只读快照 17 文件 33 处不可改（但也不影响主链路） | 中（1 天） |
| 2 | **遗漏的证据根补齐** | 至少 `validation_2025_local_inputs_20261029` 未复制；`D:/backup/*.pkl` 与 `SCALERS_IDENTITY.json` 不存在 | 小（半天） |
| 3 | **外部数据源的可替代性** | `Z:` 是 UNC 网络盘（`\\192.168.0.123`）；`config/defaults.py` win32 硬指 `Z:`；F60 parquet 4.28 GB 在 `Z:` | 小~中（加环境变量）/ 大（若要拷 4.28 GB 进仓库则不可行） |

#### 2.32 与不做清单冲突检查

- **N14（不改 manifest 4812 键）**：选项 2 冲突 → 排除。选项 1 用 sidecar → 不冲突。
- **N13（不把 pkl 提交 git）**：选项 1 只备份不提交 → 不冲突。
- **Q3 P0-1 原建议"迁完更新 manifest 键"**：Q5 已明确反对（"不建议改原始 manifest"）。**本轮同意 Q5**：sidecar 优于改键。

**E2 结论：能补，可补到"部分"。差 3 类东西（代码相对化 / 遗漏证据根 / 外部数据源可替代性）。生产侧真实可改的只有 23 处（25 处含 2 处 URL 假阳性）；只读快照的 33 处按 AGENTS 不可改，但也不阻塞主链路。**

---

## 3. 诚实排序：按"值得补"的投入产出比

### 第一梯队（强烈建议做，投入小、收益确定）

| 排名 | 项 | 理由 | 成本 | 产出 |
|---|---|---|---|---|
| **1** | **A5 限定性声明** | 纯文档。把"全不可追溯"的模糊恐惧，换成"4808/4812 可追溯、4 项已知不可追溯"的精确边界。**这是把"否"变"部分"的最低成本路径** | 小（半天） | 判定升"部分"；消除后来者"再找找"的无效劳动 |
| **2** | **C3 skip 门 + 逐条标注** | 纯 CI/文档。33/40 skip 伪装成绿是**最容易被误读**的风险，且修复成本极低 | 小（半天~1 天） | 判定升"部分"；让"绿≠验证"变成制度 |
| **3** | **D3 F=45 指标复算** | **本轮唯一可能升"是"的项**，且所有介质都在盘上（我已验证装载+前向全通）。唯一成本是组装脚本+全量推理 | 中（2~4 天） | 判定升"是（限指标）"；**推翻 Q3 判定** |

### 第二梯队（建议做，但只能升"部分"，且需要接受"无法复原进程"）

| 排名 | 项 | 理由 | 成本 | 产出 |
|---|---|---|---|---|
| **4** | **A4 三角互证 + runner pin 门** | 三角互证能锁住"输入+账本"（这两样确实是对的），runner pin 门能保将来。**但"进程可重放"永久缺失**，所以上限就是"部分" | 小~中（1~2 天） | 判定升"部分"；将来不再漂移 |
| **5** | **E2 生产侧相对化 + 补拷** | 25 处可改，剩下 33 处在只读快照里（不影响主链路）。换机障碍从"确定性失败"降为"需 sidecar" | 中（1~2 天） | 判定升"部分"；顺带补上 P0-1 的漏拷 |

### 第三梯队（可做但收益极低，或只是"如实记账"）

| 排名 | 项 | 理由 | 成本 | 产出 |
|---|---|---|---|---|
| **6** | **B3 只重建 2 项 + 标 UNREPRODUCIBLE** | 重建 2 项只让告警点前移；6 项结构性缺失无法弥补。**这不是"补"，是"记账"** | 小~中（1 天） | 判定**仍否**；但记录更准确 |
| **7** | **A5 的"选项 2"（找 raw_patches）** | 已实测否（`raw_patches` 无任何 `raw_market*` 记录） | — | **不要做**，已封 |

### 明确建议不补（补了也只是新建，或直接踩线）

| 项 | 为什么不补 |
|---|---|
| **B4 八分支重执行** | 三个死因叠加：产物目录不存在 + 硬编码路径 + A1 碎股永久无解。**踩 N3（不重建字节副本）+ N4（不重跑求收益）**。Q5 §P1-2 已裁决"不建议"，本轮同意 |
| **C2 2025 重跑** | 环境变量只能换根不能造树；造树必因 4 项 pin 永不匹配而失败。**踩 N4/N5/N6** |
| **B3 重签 TRUSTED_\*** | 充要条件"15/15 可复现"永远不成立。**踩 N1**。重签=另行签收，不是复原 |
| **任何"让 test_prefix_attestor 变绿"的操作** | **踩 N2**。它是 pin 断裂的唯一自动告警，修绿=拆警报器 |
| **A4 选项 3（真重跑八窗）** | W1 四窗必 fail-closed（`dividend:27726`），最多复现 W2；且会新生成 `summary.json` 污染原件（**R4**）。跑出来的是**新建**，不能冒充原结论 |

### "证明力上限已锁死"的项（补了也只是新建）

| 项 | 上限锁死在什么程度 |
|---|---|
| **A4** | 上限 = "输入可信 + 账本自洽 + 代码属该代"。**进程不可重放**（`TRANSPLANT.json` 4/6 文件不是任何提交的字节） |
| **E2** | 上限 = "生产链路可换机跑 + 历史证据需 sidecar"。**冻结产物的绝对路径键永远不可改**（N14） |
| **C3** | 上限 = "skip 被显式统计和标注"。**33 个用例永远无法真跑** |
| **B3/B4/C2** | 上限 = 无。已判"不能补" |

---

## 4. 对 Q3 判定的异议（单独列出）

### 4.1 D3：**Q3 判"否"过严，应可升"是（限指标复现）"**

**Q3 原文（§D3）**：
> - 当前 `data/schema.py` 只有 52 raw + 单一 `g9_observed_mask` = **F=53**
> - 旧 F=45 需要 39 raw + **6 个** margin/short mask
> - **这 6 个 mask 的 schema 已从代码中移除**
> - `logs/KEEP/scaler_per_code_legacy39_2026.pkl`（**untracked**）是唯一载体

**反证（本轮实测）**：

1. **"6 个 mask 的 schema 已从代码中移除"不成立**。它完整保留在 `23389d8` / `4f7c4cd` 两个提交的 `data/scaler.py` 里：
   ```python
   # 4f7c4cd:data/scaler.py
   SCALER_VERSION = "v3_per_code"
   TRANSFORM_VERSION = "per_code_transform_v3"
   self.mask_cols = [f"{c}_mask" for c in self.feature_cols
                     if COL_TO_GROUP_PER_CODE.get(c) == "G9_Margin"]
   ```
   且该文件**自包含**（不 import `data.schema` 的 mask 定义），所以可直接从 git 取出运行。

2. **端到端实测已通过**（三层全部验证）：
   - `git show 4f7c4cd:data/scaler.py` → 加载 → `PerCodeGroupedScaler.load(legacy39.pkl)` → **LOAD OK**，`feature_cols_out`=45，`mask_cols`=6 个，`transform_version`=`per_code_transform_v3`（与 pkl 内 `schema_manifest` 完全一致）；
   - `transform_code('000001.SZ', 39列数组, feature_cols)` → **(500, 45)**，6 个 mask 列非零率 0.786~0.994，NaN=0/inf=0；
   - `best_model.pth` strict load（401 keys，stem `(128,45,7)`）→ forward `[4,45,60]` → `[4,52]` **跑通**。

3. **"`scaler_per_code.pkl` 在默认位置不存在"只对路径成立，对介质不成立**：`logs/KEEP/scaler_per_code.pkl`（52→53）与 `logs/KEEP/scaler_per_code_legacy39_2026.pkl`（39→45）**都在盘上**，只是 untracked。

4. **额外发现**：`logs/KEEP/run_20260905_183102/best_model.pth`（`eval_base_2026_formal.txt` 第 1 行引用的 checkpoint）**实际存在**（sha256 `ec952b87…`，401 keys），Q3 未提及。

**唯一仍成立的 Q3 论点**：`config.json` 记的 `SCALER_PATH=logs/scaler_per_code.pkl` 在默认位置确实不存在。但这只影响"按 config.json 一键复现"，不影响"手工组装复现"。

**结论**：D3 应判 **"部分"**（若只做装载+前向验证，本轮已完成）→ **可升"是（限指标复现）"**（若做全量指标重算）。Q3 的"否"建立在一条可被证伪的前提上。

### 4.2 E2：**Q3 的"74 处 / 34 文件"数字偏大，实为 58 处 / 31 文件**

**Q3 原文（§E2）**：`tracked 的 py 文件中 74 处绝对路径，分布在 34 个文件`。

**本轮实测**：
- `*.py` 中含 `[A-Za-z]:[/\\]` 的：**58 处 / 31 文件**（含 `s://` URL 假阳性 2 处）；
- 剔除 URL 假阳性：**56 处 / 30 文件**；
- 复现 Q3 的 74/34 需要把 `*.md` 也算进去（`*.py + *.md` = 186 处 / 60 文件，也不等于 74/34）；
- 在 `05047f4`（Q3 的基线 HEAD）上实测：**79~80 处 / 41~42 文件**（`*.py`），比当前更多。差异来自 `b9254bb` 删掉的 12 个 `research/m_research` 死代码文件。

→ Q3 的 74/34 既不对应当前 HEAD（58/31），也不对应它自己的基线 HEAD（79/41）。这是**口径或时点不一致**，不影响结论方向（绝对路径确实很多），但**影响"要改多少"的工作量估算**。

**分类统计（Q3 未做，本轮补上）**：生产可改 23 处/13 文件（25/14 含 2 处 URL 假阳性）；只读快照不可改 33 处/17 文件。

### 4.3 A5：Q3 判"否"正确，但**可以降为"部分（限 4 项除外）"**

Q3 的判据是"结论与运行过程都不可重建 → 否"。但 A5 的对象是**"来源可追溯性"这个属性**，而不是"某个结论"。如果按"16 项中 12 项可追溯"来表述，属性本身是**部分成立**的。Q3 §P2-8 其实已经建议"标 UNREPRODUCIBLE 并保留记录"，那本质上就是"部分"的表述。→ **建议把 A5 改判"部分（限 4 项除外）"，并采用 §2.6 的措辞。** 这不是推翻 Q3 的事实判断（4 项确实不存在），而是**修正其判定粒度**。

### 4.4 A4：Q3 判"否"正确，且本轮发现**比 Q3 描述的更严重**

Q3 说"`_verify_prepared` 不校验 runner 自身源码版本"。本轮进一步实测：**历史产物里根本没有记录 cnn-side runner 哈希**（`effective_config` 只有 `core_runner_sha256`，无 cnn runner sha；`attempt_audit.json`/`manifest.json` 均无 `controlled_run_identity`）。所以这**不是"校验逻辑缺失"**，而是**"证据本身没被记录"**——加了校验门也读不到历史数据。→ Q3 的"否"成立，且理由应升级。

### 4.5 无异议的项

**B3 / B4 / C2 / C3**：Q3 的判定与本轮实测一致，无异议。

---

## 5. 汇总：八项一句话结论

| 项 | 一句话结论 |
|---|---|
| **A4** | **部分能补**——三角互证能锁住"输入+账本"（都是真的），但"进程可重放"永久缺失（历史产物根本没记 runner 哈希） |
| **A5** | **部分能补**——出一份"4808/4812 可追溯、4 项永久不可追溯"的限定性声明，是八项里投入产出比最高的 |
| **B3** | **不能补**——5 项 pin 指向从未落盘的字节 + 两份"独立"清单同源失效；重签踩 N1、修绿踩 N2 |
| **B4** | **不能补**——4 个依赖目录全删 + 硬编码 5 处路径 + A1 碎股永久无解；踩 N3/N4 |
| **C2** | **不能补**——环境变量只能换根不能造树；造树必因 4 项 pin 永不匹配而失败；踩 N4/N5/N6 |
| **C3** | **部分能补**——加 CI skip 门 + 逐条标注，能把"伪装绿"变"显式未测"，但 33 个用例永远无法真跑 |
| **D3** | **能补（本轮推翻 Q3）**——v3 scaler 在 `4f7c4cd`、legacy39 pkl 在盘、F=45 checkpoint 在 `logs/KEEP/run_20260905_183102`，三层已实测跑通；可升"是（限指标复现）" |
| **E2** | **部分能补**——生产侧 23 处/13 文件可改（25/14 口径含 2 处 URL 假阳性），只读快照 33 处/17 文件不可改；差 3 类东西（代码相对化 / 漏拷证据根 / Z: 网络盘可替代性） |

---

## 6. 报告元信息

- **本轮实测脚本**：均在 `C:/Users/yanwen/AppData/Local/Temp/opencode/_ro_*.py`（只读，可删）。
- **未修改任何仓库文件**；`git status` 未因本分析变化。
- **对 Q3 的修订建议汇总**：
  1. **D3：否 → 部分（可升"是，限指标复现"）**，前提"6 mask schema 已移除"不成立；
  2. **E2：74 处/34 文件 → 58 处/31 文件**（当前 HEAD），并补分类统计（生产 25/14、只读 33/17）；
  3. **A5：否 → 部分（限 4 项除外）**，判定粒度应对准"可追溯性"这一属性；
  4. **A4：理由升级**——不是"校验逻辑缺失"，而是"历史产物根本没记 cnn runner 哈希"。
