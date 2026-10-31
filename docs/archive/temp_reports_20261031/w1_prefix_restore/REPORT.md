# 误删文件恢复报告（w1_prefix_restore）

- 执行时间：2026-10-30
- 任务：只读从 `opencode.db` 找回被误删的 `logs/tree_verify/REPORT.md` 与 `logs/tree_rebuild/SUMMARY.md`
- 红线遵守：仓库文件零修改、`opencode.db` 零修改（仅 `mode=ro` 只读 URI）、产物只落 Temp

## 0. 一句话结论

| 目标 | 结论 | 字节数 | 行数 |
|---|---|---:|---:|
| `logs/tree_verify/REPORT.md` | **完整恢复**（full-read） | 12,295 | 177 |
| `logs/tree_rebuild/SUMMARY.md` | **不可恢复**（数据库无正文，仅有存在性证据） | 原 8,909 → 恢复 0 | 原未知 → 恢复 0 |

---

## 1. 扫描范围与检索方法

### 1.1 数据库与连接方式

- 路径 `C:\Users\yanwen\.local\share\opencode\opencode.db`（3,836,485,632 B ≈ 3.83 GB）
- 旁路 `opencode.db-wal` 40,771,552 B（一并扫描，未遗漏未 checkpoint 的数据）
- 连接一律 `sqlite3.connect(f"file:{DB}?mode=ro", uri=True)`，全程只读
- `part` 表总行数 **153,479**；表结构 `id, message_id, session_id, time_created, time_updated, data`

### 1.2 检索阶梯（逐步收紧，共 6 层）

| 层 | SQL / 手段 | 命中 | 说明 |
|---|---|---:|---|
| L1 | `data LIKE '%tree_verify%' OR data LIKE '%tree_rebuild%'` | **221** | 逐条 JSON 解析，统计 type/tool 分布 |
| L2 | L1 结果中 `input.filePath` 或 `command` 含 `tree_verify`/`tree_rebuild` | **28** | 定位真正指向这两个目录的工具调用 |
| L3 | `data LIKE '%REPORT.md%' OR '%SUMMARY.md%'` 且含 tree 关键词 | 93 → 收敛 18 | 排掉 research/README.md 等无关引用 |
| L4 | `data LIKE '%"tool":"read"%'` 且含 tree 关键词 | **54** | 只看 read，找正文 |
| L5 | `data LIKE '%"type":"patch"%'` 全量（不设关键词） | **3,211** | 检查 patch 记录是否含 tree_* 路径 → **0 命中** |
| L6 | 原始字节扫描（`mmap` 全库 + WAL，正则 `<path>…tree_rebuild|tree_verify…SUMMARY/REPORT.md</path>`） | 见 §2 | 绕过 SQLite 页结构，捞碎片与已删页 |

### 1.3 L1 的 221 条 type/tool 分布

```
tool/bash        75      tool/read        54      reasoning    53
text             17      tool/invalid      3      tool/write    5
tool/edit         4      tool/openchamber  4      tool/grep     2
tool/task         2      tool/glob         1      tool/memory_save 1
```

---

## 2. `logs/tree_verify/REPORT.md` —— 完整恢复

### 2.1 来源

| 字段 | 值 |
|---|---|
| part_id | `prt_1815a2590001TKXZ76Epy40nn2` |
| session_id | `ses_e7ea68330ffeiBwnE0pU7fASq6` |
| time_created | 1793171531152 → **2026-10-28 15:12:11** |
| tool / status | `read` / `completed` |
| input.filePath | `D:\code\cnn_full_20260905\cnn\logs\tree_verify\REPORT.md` |
| 原始 output 字符数 | 9,460 |

该 part 的 output 结构：

```
<path>D:\code\cnn_full_20260905\cnn\logs\tree_verify\REPORT.md</path>
<type>file</type>
<content>
1: # 树模型正式验证报告（tree_verify）
2:
...
177: - **XGB best_iter 达 500（打满）**：...
(End of file - total 177 lines)
</content>
```

### 2.2 恢复方式

1. 用 `re.search(r"<content>\n(.*)\n</content>\s*$", output, re.S)` 取正文块；
2. 剥离尾标 `\n(End of file - total N lines)`，用 N 作独立校验值；
3. 行号解析器 `^(\d+): (.*)$`（**实测格式就是「数字 + 冒号 + 空格」，无 `->`、无 tab**），逐行剥离；
4. 以 `\n` 拼接并补末尾换行，UTF-8 无 BOM 写盘。

### 2.3 校验结果（4 项全过）

| 校验 | 期望 | 实测 | 结果 |
|---|---|---|---|
| 解析行数 vs 尾标 | 177 | 177 | PASS |
| 行号连续性 | 1..177 无缺无重 | 1..177 | PASS |
| 文件字节数 vs 原目录清单 | **12,295** | **12,295** | **EXACT MATCH** |
| 异常行（不匹配行号格式） | 0（正文行） | 1（正文末尾空行，非正文） | OK |

> 字节数精确命中是本恢复最强的证据：`prt_173b32931001oJf8TjyJ901TOv`（2026-10-25 23:34:43）的 `Get-ChildItem ... Select Name, Length` 输出记录 `REPORT.md 12295`，恢复结果 12,295 B 与之逐字节一致。SHA256 = `49eac43a9b9710eb723a40a138ceb08070b065df8de9171c79ca2cbdb3d27d6a`（LF 行尾、末尾有换行）。

### 2.4 置信度：**高**

理由：(a) 单次 read 即完整（尾标自证 177 行、无截断标记）；(b) 字节与原清单精确吻合；(c) 正文语义自洽（标题、六节结构、脚本清单齐全）。唯一残余风险：该 read 发生在 2026-10-28，而文件最后写入是 2026-10-03 —— 但 10-03 至 10-28 之间无任何写入该文件的记录（L5 的 3211 条 patch 中 0 命中 tree_*），故 10-28 读到的即 10-03 定稿版。

---

## 3. `logs/tree_rebuild/SUMMARY.md` —— 不可恢复

### 3.1 存在性已被证实（这点不含糊）

| 证据 | part_id | 时间 | 内容 |
|---|---|---|---|
| 目录清单 | `prt_173b32931001oJf8TjyJ901TOv` | 2026-10-25 23:34:43 | `SUMMARY.md  8909  2026/10/3 10:39:12` |
| 目录清单（复现） | `prt_180dd95f3001KDBLBzkm0gRY0W` | 2026-10-28 12:56:07 | 同上一字不差 |
| 资产清单 JSON | `prt_173c02551001Bmw34bAXDnjRLe` | 2026-10-25 23:50:37 | `"conclusion_file": ".../logs/tree_rebuild/SUMMARY.md"` |
| 应用日志（非 DB） | `opencode.log` | 2026-10-03 02:39:12 | `evaluated permission=edit pattern="logs\tree_rebuild\SUMMARY.md"` + `formatting file` + `touching file` |
| 应用日志（非 DB） | `opencode.log` | 2026-10-03 03:29:53 / 2026-10-07 17:55:19 | 两次 `permission=read` + `touching file` |

即：文件真实存在（8,909 B，2026-10-03 10:39:12 最后修改），且至少被 opencode 读写过 2 次。

### 3.2 但数据库里没有正文 —— 三层证据

**证据 A：read 记录只有一条，且失败**

全库 `tool=read` 且 filePath 含 `SUMMARY.md` 且路径含 tree 的，只有：

```
prt_180ddf41d001MvV04iB0vYAdyv
session ses_e7f26fe05ffecHsK53BXYjVz9h
time 2026-10-28 12:56:32
tool read  status=error  output=null
input.filePath = D:\code\cnn_full_20260905\cnn\logs\tree_verify\SUMMARY.md
```

两条独立的错：路径是 `tree_verify\SUMMARY.md`（不是 `tree_rebuild`），且读失败（文件不存在于该目录）。`state.output` 为 `null`，零字节可提取。

**证据 B：写入记录为零**

- `tool=write` / `tool=edit` / `apply_patch` 中 input 指向 `SUMMARY.md` 且含 tree 的：**0 条**。
- 全库 `type=patch` 共 3,211 条，逐条解析 `files` 字段，含 `tree_rebuild` 或 `tree_verify` 的：**0 条**（patch 只存 hash + 路径，本可作最后希望，但它压根没记这个文件）。
- 3,211 条 patch 中涉及 `cnn/logs/` 下任何文件的：**0 条**（`logs/` 被 gitignore，编辑器快照机制不跟踪）。

**证据 C：原始字节扫描无正文**

对 3.83 GB 主库 + 40.8 MB WAL 做 `mmap` 全文正则扫描：

- `SUMMARY.md` 原始出现 **1,583** 次，其中邻近 `tree_rebuild` 的 **731** 次。
- 逐个检查这 731 处附近的 6 KB 窗口，是否同时出现 `<path>…tree_rebuild…SUMMARY.md</path>` + `<content>` / `(End of file - total N lines)` / `totalLines`：
  - 命中的 **全部** 是别的文件（`docs/prediction_target_and_tree_2026.md`、`research/README.md`、资产清单 JSON、以及本次排查自身产生的记录）；
  - **没有任何一处是 `tree_rebuild\SUMMARY.md` 的 read 输出正文**。
- 对照组：同样方法扫 `tree_verify\REPORT.md`，立刻命中 8 处 `<path>…REPORT.md</path>` + `<content>` 完整正文（§2 的来源即其中之一），证明扫描方法有效、不是漏扫。

**根本原因**：`opencode.log` 显示 2026-10-03 与 2026-10-07 的会话确实读过该文件，但那些会话（如 `ses_ee87f0903ffeqzXYDyhpVvARBN`）在当前库中 **session/part/message 三张表全为 0 行** —— 已被清理。日志中同期可见 `message=cleanup prune=7.days`。DB 内 `part` 按天分布从 2026-09-20 直接跳到 2026-10-15，**2026-10-03 当天 part 数为 0**。也就是说：真正含正文的那次 read 记录，在 7 天保留期到期时被删除，早于 2026-10-28 那次（读错路径的）尝试。

### 3.3 结论与缺失区间

- **不可恢复**。数据库内无任何 `tree_rebuild/SUMMARY.md` 的正文记录。
- 严格表述：**行 0（首行）至末行全部缺失**；不存在「行 X 至 Y 存在」的情况，一个字符都没拿到。原文件 8,909 B / 行数未知（无任何清单记录其行数）。
- **未做任何猜测填充**。`recovered/tree_rebuild/` 目录为空（未落任何占位文件，避免被误当恢复产物）。

---

## 4. 顺带查清的两处易混淆点

1. **不是 `tree_verify/SUMMARY.md`**。曾有会话（`ses_e7f26fe05ffecHsK53BXYjVz9h`）试图读 `logs/tree_verify/SUMMARY.md` 并报错，容易让人误以为 SUMMARY.md 属于 tree_verify。实际上 `SUMMARY.md` 只在 `tree_rebuild`（8,909 B），`tree_verify` 里是 `REPORT.md`（12,295 B）。`research/README.md:35-36` 的引用与目录实况一致。
2. **`REPORT.md` 与 `docs/prediction_target_and_tree_2026.md` 的高度重合不是恢复出错**。后者第六节是 REPORT.md 的压缩摘要（含 8 个模型的 IC/回测对照表），二者独立存在、内容互相印证。这反而给 REPORT.md 的恢复提供了第四重旁证。

---

## 5. 产物路径

```
C:\Users\yanwen\AppData\Local\Temp\opencode\w1_prefix_restore\
├── MANIFEST.json                         # 结构化清单（part_id/session/时间/字节/SHA256/方式/置信度）
├── REPORT.md                             # 本报告
├── recovered\
│   ├── tree_verify\REPORT.md             # 12,295 B / 177 行 / 完整
│   └── tree_rebuild\                     # 空目录 —— SUMMARY.md 不可恢复，未落占位文件
└── (扫描脚本) scan.py scan2..scan14.py rebuild_report.py rawscan_db*.py rawscan_wal.py dump.py dump.txt
```

## 6. 对 `research/README.md` 引用的建议

- `logs/tree_verify/REPORT.md`：可以继续引用，内容已保全（建议把 Temp 副本纳入正式证据目录）。
- `logs/tree_rebuild/SUMMARY.md`：**引用应改为“已丢失，不可恢复”**，或改指向 `docs/prediction_target_and_tree_2026.md` 第六节（它是 SUMMARY.md 结论的压缩版，含同款数据表）。继续保留原路径引用会让读者去找一个永远找不到的文件。
