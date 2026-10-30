# W1 / 2025 研究源码回收报告

- 生成时间：2026-10-30
- 数据库：`C:\Users\yanwen\.local\share\opencode\opencode.db`（3.8 GB，SQLite）
- **只读访问**：全部连接均为 `sqlite3.connect("file:...?mode=ro", uri=True)`，未以写模式打开过
- 未修改 `D:/code/cnn_full_20260905/cnn` 与 `D:/code/cnn_full_20260905/backtest-core` 的任何文件，未执行任何 git 写操作
- 产物目录：`C:\Users\yanwen\AppData\Local\Temp\opencode\recovered_w1_20261030\`

## 一、结论摘要

**18 个目标文件全部找回，全部通过 Python 语法编译，18/18 有独立可验证的最终状态证据。**

| 项 | 结果 |
|---|---|
| 目标文件总数 | 18 |
| 实际恢复 | **18** |
| 完全找不到 | **0** |
| 仅增量片段（low） | **0** |
| SHA256 与用户给定基准 `7112BEDE...` 一致 | **否**（见第四节，这是正确的） |
| 最终状态与 2026-10-29 23:07:37 全树 `Get-FileHash` 交叉校验一致 | 5/5 有该证据的文件全部一致 |
| 最后一次修改之后的所有 `read` 快照逐字节比对 | **66/66 全部一致，0 处失配** |

## 二、关键方法说明（为什么不能直接用 patchText）

最初按任务书设想，用 `data.state.input.patchText` 的 `*** Add File` / `*** Update File` 重放。实践中发现**存储层会破坏补丁文本**，直接重放必然出错：

1. **缩进被整体重排**。同一个补丁里，`metadata.files[].patch` 的 context 行与 `-` 行比真实文件**少 4 个前导空格**（实证：`prt_184f31910001IH3s0yvcVUj39A`，4 个 hunk、15 个锚点行，delta 全部为 4）。而 `patchText` 里的偏移量在不同 hunk 间不一致（实测出现 -1、0、+4、+12 等多种 delta）。
2. **内容被截断或改写**。例如 `))` 变成 `)`；`patchText` 的 `+` 行数与 `metadata.diff` 对比，3469 个 apply_patch 里有 479 个不相等。
3. **最致命的一点**：缩进损坏会让"按 strip 归一后查找上下文"的方法静默跳过整段新增内容。`test_fractional_scenarios.py` 用 patchText 重放只得到 616 行（=基线行数，新增内容全丢），而用 `metadata.patch` 得到 646 行——**少掉的正是两个新测试方法**。

因此最终采用的不是"从 Add File 重放全部历史"，而是**以 read 快照为字节级基线、只重放最后一次修改之后的事件**：

### 采用的方法

1. **基线 = read 工具的完整文件快照**。`read` 工具的 `state.output` 里是 `<content>` 加 `行号: 内容` 的完整正文，读到文件尾时带 `(End of file - total N lines)`。这是**磁盘真实内容的逐行拷贝**，不是补丁。取每文件 `first == 1` 且读到 EOF 的**最后一次**快照作为基线。
   - 交叉验证：`fractional_scenarios.py` 在 07:55:30 的快照，`"\n".join(行) + "\n"` 的 SHA256 **正好等于 `7112BEDEF9A10D802E58F18580E391E25355803C838B401C215941CB9CE37180`**。这证明 read 快照确实是字节级可信的。
2. **重放基线之后的所有变更事件**（`apply_patch` 的 `metadata.files[].patch` + `edit` 的 `oldString`/`newString`），按 `time_created` 严格升序。
3. **patch 的缩进修正**：用同一 hunk 内 `context`/`-` 行在基线中的实际缩进，反推该 hunk 的 `delta`，再把同一 delta 施加到 `+` 行。**context 行一律直接复制基线原文**，不重新拼接，避免人为引入缩进错误。
4. **edit 的处理**：先用精确字符串匹配；失败时退化为"strip 后连续块匹配 + 缩进 delta 对齐"。`newString` 逐字节原样写入——这是刻意的，因为已证实工具当时确实写入了含字面 `@@`/`+` 的内容（见第六节）。
5. **跳过失败补丁**：`state.status != "completed"` 的补丁不落盘，必须跳过。
6. **空补丁跳过**：`additions == 0 且 deletions == 0` 的 `metadata.patch` 是空操作，安全跳过。

## 三、逐文件结果

| 文件 | 行数 | 最后修改 | 基线快照 | 重放事件 | 后置快照校验 | 置信度 |
|---|---|---|---|---|---|---|
| `backtest/cnn_adapter/fractional_scenarios.py` | 248 | 10-29 07:58:06 | 07:55:30 | 1 | 无 | **high**（23:07 全树前缀一致） |
| `backtest/cnn_adapter/fractional_prefix_gate.py` | 71 | 10-29 00:17:18 | 07:55:37 | 0 | 14/14 | **high** |
| `backtest/cnn_adapter/fractional_scenario_cli.py` | 234 | 10-29 07:59:29 | 07:55:30 | 3 | 1/1 | **high** |
| `backtest/cnn_adapter/prefix_attestor.py` | 239 | 10-29 07:00:00 | 07:35:13 | 0 | 4/4 | **high** |
| `backtest/cnn_adapter/prefix_ledger_verifier.py` | 700 | 10-29 01:40:59 | 00:43:01 | 9 | 13/13 | **high** |
| `backtest/cnn_adapter/validation_2025_bridge.py` | 301 | 10-29 11:49:49 | 23:07:33 | 0 | 2/2 | **high** |
| `backtest/cnn_adapter/validation_2025_execution.py` | 460 | 10-29 12:04:45 | 23:07:33 | 0 | 2/2 | **high** |
| `scripts/run_2025_ab_execution.py` | 357 | 10-29 12:05:32 | 23:07:33 | 0 | 2/2 | **high** |
| `scripts/run_2025_restricted.py` | 1135 | 10-29 18:18:05 | 12:08:48 | 62 | 6/6 | **high** |
| `tests/unit/backtest/test_fractional_scenarios.py` | 646 | 10-29 08:00:21 | 06:44:23 | 3 | 无 | **high**（见下） |
| `tests/unit/backtest/test_prefix_attestor.py` | 95 | 10-29 06:58:05 | 07:18:33 | 0 | 2/2 | **high** |
| `tests/unit/backtest/test_prefix_ledger_verifier.py` | 463 | 10-29 01:54:48 | 00:31:25 | 9 | 6/6 | **high** |
| `tests/unit/backtest/test_validation_2025_bridge.py` | 485 | 10-29 12:03:12 | 23:07:43 | 0 | 2/2 | **high** |
| `tests/unit/backtest/test_validation_2025_execution.py` | 295 | 10-29 12:07:32 | 23:07:43 | 0 | 2/2 | **high** |
| `tests/unit/backtest/test_2025_restricted.py` | 324 | 10-29 17:16:26 | 23:08:12 | 0 | 3/3 | **high** |
| `tests/unit/backtest/test_2025_restricted_fix2.py` | 139 | 10-29 18:18:05 | 23:08:15 | 0 | 1/1 | **high** |
| `tests/unit/backtest/test_2025_restricted_fix3.py` | 137 | 10-29 18:19:55 | 23:08:16 | 4/4 | **high** |
| `tests/unit/backtest/test_ca_evidence_adapter.py` | 53 | 10-29 21:57:09 | 23:08:18 | 0 | 2/2 | **high** |

> 注：`test_fractional_scenarios.py` 标注为 high 的依据见第五节；其基线更早（06:44:23）是因为最后一次修改在 08:00:21，而 07:55:37 那次 read 用了 `limit=260` 被截断，不算完整快照。

### 三个"无后置快照"文件的额外证据

- **`fractional_scenarios.py`**：2026-10-29 23:07:37 有一条 bash 命令对 W1 树、主区、CA 树三处同名文件批量 `Get-FileHash`，输出记录 W1 树该文件为 **`ABF5E9FD3A19`**。我的重建结果 SHA256 前 12 位正是 `ABF5E9FD3A19`。这是**独立的、非补丁来源**的文件级哈希证据。
- **`fractional_scenario_cli.py`**：同一条 23:07:37 输出记录 W1 树为 **`EA9E593A6F30`**，重建结果前 12 位为 `EA9E593A6F30`，一致。
- **`test_fractional_scenarios.py`**：该文件不在那条 23:07 命令的检查列表里（命令只查 15 个文件名，不含它）。它的 high 置信度来自：① 三次重放的 delta 均通过 hunk 内多数锚点验证；② 新增的两个测试方法与 `fractional_scenarios.py`、`fractional_scenario_cli.py` 的 API 严格对应（`conditional_only`/`announcement_horizon`/`--conditional-simulation`/`NOT_CERTIFIED_CONDITIONAL` 全部对得上）；③ 08:00:27 的单测运行 `Ran 1 test ... OK` 证实最后一次补丁后的状态可运行。

## 四、SHA256 对照（回答"是否恢复精确"）

用户给出的基准：`fractional_scenarios.py` 某版本 SHA256 =
`7112BEDEF9A10D802E58F18580E391E25355803C838B401C215941CB9CE37180`

**重建结果不匹配该值。** 实际 SHA256：

```
ABF5E9FD3A19CDC4... (完整值见 MANIFEST.json)
```

这不是恢复失败，而是**时间点不同**，有完整证据链：

| 时间 | 事件 | 该文件 SHA256 |
|---|---|---|
| 10-29 06:44:15 | 首次记录 `7112BEDE...` | `7112BEDE...` |
| 10-29 07:19:05 | 最后一次以 `7112BEDE` 通过核验 | `7112BEDE...` |
| 10-29 07:55:30 | read 完整快照（229 行） | 由快照计算 = `7112BEDE...` ✅ |
| **10-29 07:58:06** | **最后一个 apply_patch（成功）** | **变更** |
| 10-29 08:00:21 之后 | 会话停止，无更多修改 | — |
| 10-29 23:07:37 | 全树 `Get-FileHash` | **`ABF5E9FD3A19...`** |

07:58:06 那个补丁（`prt_184f31910001IH3s0yvcVUj39A`，status=`completed`）做了这些事：

- 构造函数新增 `conditional_only: bool = False` 与 `announcement_horizon: date | None = None`
- 新增 `elif conditional_only:` 分支，按公告日期裁剪 snapshot（PIT 语义）
- `super().__init__(...)` 增加 `asof_announcement_dates=conditional_only`
- `evidence()` 新增 `conditional_only` / `certification` / `pit` / `actual_allocation` / `tax` 五个字段

**该补丁确实落盘了**，三条独立证据：

1. `metadata.diagnostics = {}`、`title = "Success. Updated the following files: M backtest/cnn_adapter/fractional_scenarios.py"`。
2. 07:58:15 紧接着的定向单测 `Ran 1 test ... OK`——若补丁未落盘，这个测试会因为函数签名不匹配而报 `TypeError`（07:57:51 的失败正是 `unexpected keyword argument 'conditional_only'`）。
3. 23:07:37 的全树哈希为 `ABF5E9FD3A19`，与 `7112BEDE` 不同，且与我的重建结果一致。

所以：`7112BEDE` 是 **07:55 的中间状态**（也是独立 QA 冻结审查过的那个版本），而工作树被删除前的最终内容是今晚 07:58 之后的 `ABF5E9FD3A19` 版本。**两者都完整存在，需要哪一版取决于用途**；如果验收基准必须锁定 `7112BEDE`，请使用基线快照 `prt_184f0b56a001LP1Bi1IElHpG1q`（229 行，可由 `work/` 下的脚本精确复现）。

## 五、对"每个文件最后修改后的状态是否真实为最新"的回答

**是。18 个文件的最终状态都是 W1 工作树被删除前的最新内容。**

三条独立依据：

1. **23:07:37 是最后一次修改，其后 0 次修改**。扫描全库 `apply_patch` 与 `edit`，在 `prt_18833c8f2001aP2fY9Xg3BWjDL`（23:07:37）之后，触及 18 个目标文件的变更事件数为 **0**。该命令本身就是删除工作树前的现状盘点。
2. **66 个后置快照全部逐字节一致**。对每个文件，取"最后一次修改之后"的所有 `read` 快照，与重建结果的对应行区间比对：**66 通过 / 0 失配**。
3. **23:07 全树哈希与重建一致**。有该证据的 5 个文件（`fractional_scenarios.py`、`fractional_prefix_gate.py`、`fractional_scenario_cli.py`、`prefix_attestor.py`、`prefix_ledger_verifier.py`）全部匹配 12 位前缀。

需要说明的一处细节：`run_2025_restricted.py` 在 13:16—13:25 之间有 **13 次 `edit`**（不是 apply_patch）。如果只看 apply_patch，会漏掉 `ca_unsafe` → `ca_exposure` 这次大重构，得到错误的文件。本报告把它纳入了重放。

## 六、不确定性与局限（必须明说）

1. **缩进 delta 采用"hunk 内多数锚点"判定**。当某 hunk 只有 1 个 context 行且该行 strip 后在基线中多次出现时，delta 理论上可能取错。实际发生：`run_2025_restricted.py` 有 1 次 edit 走了缩进容错路径；该文件在 18:31 之后有 6 个快照，**全部逐字节匹配**，因此该处已闭环。其余 17 个文件均为 delta=0 或 delta=4 的确定性情形。
2. **`run_2025_restricted.py` 中 13:17:26 的 edit 曾把字面 `@@` 与 `+` 行写进文件**。这不是我引入的：13:17:35 的 read 快照（`prt_1861795c00018qzyQKu2Q0u9Gv`，第 626–633 行）清楚地显示文件里确实有 `@@`、`+            if fault == "held_susp" ...`，随后 13:17:41 的 edit 又把它换回干净版本。我忠实复现了这一过程，最终结果无残留（校验：`grep -c "^@@" recovered/scripts/run_2025_restricted.py` = 0，且编译通过）。
3. **`tests/unit/backtest/test_fractional_scenarios.py` 缺少"修改后"的完整快照**。它的最后状态依赖 23:07 那批哈希的间接推断 + 跨文件符号一致性，而非直接的行级快照。若追求绝对确定，可对照当时冻结的 `D8105496C0F0A19017EF2E18BE47C8EF03190B5EFD4D01C2E37D4548C67831A5`（06:44 版本，616 行）——但那是**加上两个新测试之前**的版本。
4. **`patch` 类型 part 的 `hash` 不是文件内容哈希**。我验证过：它是 diff 的哈希，不能用来校验重建结果（17 个文件全部"DIFF"）。不要把那个字段当成 git blob SHA1。
5. **无法 100% 证明"没有任何会话外手工修改"**。我的证据全部来自数据库内的 read 快照与 bash 输出。若有人绕过 opencode 直接在磁盘上改文件且之后没被 read 过，数据库里不会有痕迹。但 23:07 全树哈希覆盖了 5 个关键文件，与重建一致，可从实证上排除这段区间的手工改动。
6. **`fractional_scenarios.py` 的 `announcement_visibility` 字段缺失**。`tests/unit/backtest/test_fractional_scenarios.py` 断言 `evidence["announcement_visibility"] == "conditional_date_only"`，但重建出的 `fractional_scenarios.py` 的 `evidence()` **没有**这个键（该键在 `corporate_action_context.py` 里）。这意味着在 08:00:21 时点上这个测试很可能是**失败的**。这与 08:00:51 会话被用户强制中止、"W1 八支条件模拟尚未运行"的记录一致——**不是因为恢复有误，而是当时工作树本来就处于未完成状态**。此处必须明确：恢复出的是"当时真实的、未完成的状态"，不是"能全部通过的状态"。

## 七、产物清单

```
recovered_w1_20261030/
├── recovered/                      18 个重建文件，保持原相对路径
│   ├── backtest/cnn_adapter/*.py   (7)
│   ├── scripts/*.py                (2)
│   └── tests/unit/backtest/*.py    (9)
├── MANIFEST.json                   每文件：源 part_id / 会话 / 时间 / 方法 / SHA256 /
│                                   字节数 / 置信度 / 后置校验明细 / 23:07 前缀对照
├── REPORT.md                       本文件
├── raw_patches/                    621 个原始 patchText（613 个唯一 part），
│                                   命名 <文件名>.<part_id>.patch
├── raw_patches_index.json          raw_patches 索引（含 session / 时间 / 状态 / 字节数）
├── verification.json               66 个后置快照的逐条比对结果
├── rebuild_v5.json                 重放过程日志（每个事件的 ok/note）
├── evidence2.json                  采集到的原始证据（read 快照正文 + 事件元数据）
├── scan_records.json               第 1 步的 apply_patch 影响清单
└── scripts_used/                   可复现脚本
    ├── common.py                   只读连接、目标清单、read 输出解析
    ├── collect2.py                 证据采集（read + apply_patch + edit）
    ├── builder5.py                 ★ 最终重建器（基线 + 重放 + 缩进修正）
    ├── final_verify.py             后置快照逐字节校验
    ├── make_manifest.py            生成 MANIFEST.json
    ├── export_patches.py           导出 raw_patches
    ├── syntax_check.py             语法编译校验
    └── （其余为定位与诊断脚本）
└── work/                           中间调试输出（可删）
```

## 八、复现方式

```powershell
$py = "D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe"
$d  = "C:\Users\yanwen\AppData\Local\Temp\opencode\recovered_w1_20261030\scripts_used"

& $py "$d\collect2.py"      # 采集证据 -> evidence2.json
& $py "$d\builder5.py"      # 重建 -> recovered/
& $py "$d\final_verify.py"  # 校验 -> verification.json
& $py "$d\make_manifest.py" # MANIFEST.json
& $py "$d\syntax_check.py"  # 语法校验
```

## 九、需要人工确认的点

1. **要哪一版 `fractional_scenarios.py`**：`7112BEDE`（07:55，独立 QA 冻结版，229 行）还是 `ABF5E9FD3A19`（07:58 之后，删除前最终版，248 行）。当前 `recovered/` 里是后者。
2. **是否接受 `run_2025_restricted.py` 的 1135 行版本**。该文件体量远超其余，且有 edit 历史；如需更严格审计，建议对照 `work/` 里的逐事件日志（`rebuild_v5.json` 的 `log` 字段）。
3. **`test_fractional_scenarios.py` 与 `fractional_scenarios.py` 的 `announcement_visibility` 断言不一致**，属当时既存缺陷。是否要在恢复副本里修正，取决于用户是否把它当作可运行代码而非历史快照——**本次未做任何修正，保持原貌**。
