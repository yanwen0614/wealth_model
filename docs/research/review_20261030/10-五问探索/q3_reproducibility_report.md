# Q3 可复现性独立核验报告

- 核验对象：Q1（失败路线）、Q2（当前进度）中**已声称成立**的研究结论是否可复现
- 核验方式：**只读**。实测哈希、行尾归一、git 对象检索、pin 分类、测试实跑、账本恒等式重算、uv 离线 dry-run
- 基线：CNN 主区 HEAD `05047f4`，backtest-core HEAD `df38c2e`
- 唯一写操作：本文件
- 判定口径：
  - **是** = 换一台干净机器、仅凭仓库内 + 已归档的冻结输入，可重算得到同一结论
  - **部分** = 结论本身可独立复算，但产生该结论的**运行过程**无法重放
  - **否** = 结论与运行过程都不可重建
- 成本：**小** ≤ 半天且无外部依赖；**中** 需补齐源码/重建冻结树 1~3 天；**大** 需原始字节或原始介质，可能永久不可得

---

## 0. 结论总表

| # | 结论项 | 可复现 | 缺什么 | 补齐成本 |
|---|---|---|---|---|
| A1 | W2 制造/信号/checkpoint 数据完整性 | **是** | 无（哈希全部实测命中） | 小 |
| A2 | W2 冻结输入 v12 完整性（4812 artifacts） | **是** | 无（`_verify_prepared` 实测通过 16.8s） | 小 |
| A3 | W2 四策略账本 NAV 恒等式（误差 2.33e-10） | **是** | 精确复核脚本未入库（需自写 ~30 行） | 小 |
| A4 | W2 八窗回放**实际运行** | **否** | 启动 cwd 指向已删树；`--run-root` 强制新建；runner 源码版本无 pin | 中 |
| A5 | v12 prepared 输入的**来源可追溯性** | **否** | 4 个源文件 + 2 个测试在**任何提交/索引/磁盘副本中都不存在** | 大 |
| B1 | W1 ceil 根因（decimal/float 取整） | **是** | 无（纯 stdlib，`repro_decimal_float.py` 自足） | 小 |
| B2 | W1 八条真实前缀的账本**一致性** | **是** | 无（`outputs/` 8 分支账本与基线逐行一致） | 小 |
| B3 | W1 prefix 结论的**可信证明链** | **否** | `prefix_attestor` 15 项 pin 中 7 项真实差异 + 1 项缺失，均不可复现 | 大 |
| B4 | W1 真实八前缀**重新执行** | **否** | 4 个依赖树全部已删；`prefix_ledger_verifier.py` 硬编码这些路径（5 处） | 大 |
| B5 | W1 cutoff（`stop_after_close`）能力 | **部分** | 补丁在，但需 CRLF→LF 才能 apply；且 CNN 侧 `.venv` 无该能力 | 中 |
| C1 | 2025 A/B 中断**证据自足性** | **是** | 无（`NOT_EVALUABLE` 三元证据齐全且互证） | 小 |
| C2 | 2025 A/B **重跑** | **否** | PYTHONPATH + `REVIEWED` 均指向已删树；`main_root` 硬编码 | 大 |
| C3 | 2025 相关 4 个测试的**验证力** | **否（skip ≠ pass）** | 40 个用例中 33 个 skip，原因即「依赖已退役树」 | 大 |
| D1 | `logs/KEEP/baseline` 旧权重可加载 | **是** | 需显式 `featurenum=45` 等 8 个参数，非默认值 | 小 |
| D2 | 现行训练链可跑通（`--smoke`） | **是** | 无（24s/epoch，F=80） | 小 |
| D3 | 旧 F=45 口径的**指标复现** | **否** | 6 个 mask 列的 schema 已不存在；`scaler_per_code.pkl` 未入库 | 大 |
| D4 | 训练**位级确定性** | **部分** | 有种子但无 `use_deterministic_algorithms`/`CUBLAS_WORKSPACE_CONFIG`/TF32 关闭/generator | 中 |
| E1 | 本机依赖可离线重建 | **是** | 无（`uv sync --offline --dry-run` = no changes；3 wheel 已 tracked） | 小 |
| E2 | 换机/换目录重建 | **否** | 74 处绝对路径（34 文件）；4812 artifacts 全以绝对路径为键；3 个证据根不在任何 git | 大 |
| E3 | core 能力一致性（cutoff） | **部分** | `.venv` 是 `893fc96`，无 `stop_after_close`；core 主区 `df38c2e` 有 | 中 |

**小计**：可复现 8 项 / 部分 3 项 / 不可复现 8 项。

---

## A. W2 四策略机械回放

### A1–A3 可复现部分（实测通过）

| 对象 | 声称值 | 本人实测 | 结论 |
|---|---|---|---|
| `three_day_signals/W2_F4_full_CPU_v1/signals.parquet` | — | `dc39dd8c…8178d9c` | 命中 |
| `three_day_models/W2_F4_v1/run_20261026_212052/best_model.pth` | `03625b7d…` | `03625b7d85e31c…` | 命中 |
| `signal_W1.parquet` | — | `99198e06…` | 命中 |
| W1 checkpoint | — | `a1e35967…` | 命中 |
| `staged_prepared_inputs_20261027_v12/manifest.json` | — | `a8ad2b0bafebee23…` | 命中 |
| 4812 artifacts 全量校验 | 全部存在且匹配 | `_verify_prepared` 通过，**16.8s**，**4812/4812** | 命中 |
| W2 四策略 NAV 恒等式 | max abs error 2.33e-10 | 独立重算 = **2.3283064365387e-10** | 命中 |

恒等式本身：每个交易日 `nav = cash + Σmarket_value + receivables`。
四策略为固定 B1/S1/S2/C70，预算 100 万、五槽每槽 20 万。

**这条结论是本次核验中最扎实的一环**：数据、账本、恒等式三者互相独立可验，且不依赖任何已删除的代码。

### A4 不可复现：八窗回放无法原样重跑

三个独立阻断点：

1. `staged_production_integration_delivery_20261027/run_eight_windows_v1.cmd` 首行 `cd /d C:\...\corporate-action-fix-20261027` —— 该树已于 2026-10-30 删除。
2. `--run-root` 用 `mkdir(exist_ok=False)`：即便修好 cwd，原 target 目录已存在，直接抛异常。
3. **最关键**：`_verify_prepared` 只校验 artifacts 内容 + `core_path`/`core_sha256`，**完全不校验 runner 自身源码版本**。这意味着即使有人重建目录、改掉 cwd 跑通，也无法证明跑的是当初那一版 runner —— 属**静默版本漂移**，比直接报错更危险。

### A5 不可追溯：4 个源文件 + 2 个测试的 pin 指向不存在的字节

`SOURCE_HASHES_FINAL.json` 共 16 项。16 项按三种独立路线穷举后分类：

- **12 项可复现**（git 提交 / worktree / 行尾归一后命中）
- **4 项在任何地方都不存在**：

| 文件 | 声明 pin | 已穷举的三条路线 | 结果 |
|---|---|---|---|
| `raw_market_inputs.py` | `000c382d56bf` | 提交 / 工作区 / **冻结 git index blob `c97d7d48` → `039f47194d`** | 全 MISS |
| `raw_market_provider.py` | `53ce8d8e99c1` | 同上，blob `37deaa45` → `3347a8e8` | 全 MISS |
| `test_raw_market_inputs.py` | `aa9d72059026` | 同上，blob `bbca7c0b` → `68ddcd11` | 全 MISS |
| `test_raw_market_provider.py` | `a736ab4e7501` | 同上，blob `a602be01` → `00cf1e7d` | 全 MISS |

第三路线说明：本人在 Temp 发现一个**冻结的 git index 文件** `staged-source-guard-fix-index-20261027`（`DIRC`, 459 entries, 52562 B），用 `GIT_INDEX_FILE` 挂载后 `git cat-file -p <blob>` **全部可取**（blob 未丢），但这些 blob 的实际内容哈希与 pin **仍不一致**。

→ **结论升级**：这四个文件不是"git 里丢了"，而是 **pin 记录时记录的就是未经落盘的内存态字节（或记录后又被改过）**。任何离线重建都不可能命中。

其余差异多为 CRLF/LF 假差异（如 `staged_order_strategy.py` pin `4101d8af` = 当前工作区 raw 字节）。

---

## B. W1 prefix 与 ceil 精度

### B1–B2 可复现部分

**ceil 根因**（`w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md` + `repro_decimal_float.py`）：
纯 stdlib，无外部依赖，可在任何机器上复现「转增比例浮点运算导致 ceil 多算一股」的根因。**这是本次核验中唯一完全不依赖任何冻结介质的结论。**

**八前缀账本一致性**：`w1_real_prefix_exploration_20261029_v2/outputs` 的 8 个分支（5 个 exit0 / 3 个 exit1，全部 `INCOMPLETE`）与基线逐行一致，外部审计已独立核对。

**历史文件恢复**：`recovered_w1_20261030/recovered/` 18/18 与 `MANIFEST.json` 逐字节一致；当前工作区仅 10/18（另 8 个已被 `436cb73`/`ff7e606` 改动）。

两个可无损重建的历史快照：

| 目标 SHA | 行数 | 重建路径 | 实测 |
|---|---|---|---|
| `7112BEDE…` | 229 | `evidence2.json` → `part_id=prt_184f0b56a001LP1Bi1IElHpG1q`，`"\n".join(lines)+"\n"` | **命中** |
| `4e6246dbdd` | 208 | 同上机制（`fractional_scenario_cli.py`） | 命中 |
| `ABF5E9FD…` | 248 | = `7112BEDE` 基线 + 1 个 `completed` update（+25/−6） | 命中 |

注意 `ABF5E9FD` 是删除前最终态，**没有独立文件副本**，只能靠上述基线+补丁推导 —— 这条路径本身依赖 `opencode.db`，见第 3 节。

### B3 不可复现：可信证明链断裂

`prefix_attestor.fixed_source_sha256()` 的 15 项 pin，本人逐项实测分类：

| 分类 | 数量 | 说明 |
|---|---|---|
| **EXACT** | 4 | `prefix_ledger_verifier.py`、`quantity_rules.py`、`staged_allocation.py`、`staged_execution_bridge.py` |
| **仅行尾差异** | 3 | `historical_costs.py`（CRLF）；`corporate_action_context.py`、`corporate_action_snapshot_loader.py`（LF） |
| **真实差异** | 7 | 见下表 |
| **MISSING** | 1 | `account_runner.py`，路径指向已退役树 |

> 口径修正：任务描述给的 4/2/8/1 与实测 4/3/7/1 差 1 项，差在 `corporate_action_snapshot_loader.py` 判为行尾差异而非真实差异。

7 项真实差异的**可复现性**：

| 文件 | pin | 可复现 | 依据 |
|---|---|---|---|
| `fractional_scenarios.py` | `7112BEDE` | **是** | `evidence2.json` 快照可无损重建 |
| `fractional_scenario_cli.py` | `4e6246dbdd` | **是** | 同上 |
| `staged_candidate_runner.py` | `37fcf150` | **否** | 全盘 + 全部提交 + 冻结 index 均无 |
| `staged_production_inputs.py` | `cef7b7bb` | **否** | 同上 |
| `staged_order_strategy.py` | `9c87f2e1` | **否** | 同上 |
| `raw_market_provider.py` | `53ce8d8e` | **否** | 与 A5 同一 pin，同样不存 |
| `raw_market_inputs.py` | `000c382d` | **否** | 与 A5 同一 pin，同样不存 |

**关键交叉验证**：`53ce8d8e` 与 `000c382d` **同时出现在 A5（SOURCE_HASHES_FINAL）和 B3（prefix_attestor pin）中，且两条链都指向不存在的字节**。两个本应互相独立的冻结清单，在同样的 4 个文件上共同失效 —— 说明它们来自同一次落盘，而不是两次独立记录。这削弱了"两份清单互证"的证明力。

core pin `4d3a28c4…` 同样**不在 core 任何提交、任何行尾变体中**。

### B4 不可复现：真实运行依赖全部消失

实测 `Test-Path` 全部为 False：

- `w1-fractional-scenarios-20261028`
- `backtest-core-w1-stop-20261028`
- `staged_w1_prefix_fix5_attestation_20261028`
- `staged_w1_prefix_fix5_runs_20261028`

而 `prefix_ledger_verifier.py` **硬编码了这 5 处路径**，不改代码则必然失败，改了代码则不再是原始验证。

### B5 部分：cutoff 补丁可用但需转换

`w1_stop_after_close_20261030.patch`（145 行，全 CRLF）在 `893fc96` 基线上**必须先转 LF 才能 apply 成功**。apply 后 LF SHA = `0bb5c30c…` = core `a176be9`/`df38c2e` 内容 —— 即补丁已被 core 主区吸收，但 pin `4d3a28c4` 永远无法满足。

---

## C. 2025 A/B 中断（NOT_EVALUABLE）

### C1 可复现：中断证据自足

`validation_2025_ab_real_20261029_v2/` 下证据齐全且互相一致：

| 文件 | 关键内容 |
|---|---|
| `run_summary.json` / `account_status.json` / `annual/{A,B}/summary.json` | A/B 均 `NOT_EVALUABLE` + `INCOMPLETE` + `ABORTED_AT_UNKNOWN_EVENT` |
| 同上 | `main_end_nav = null`（未做收益计算，未凑数） |
| `annual/A/summary.json` | 终端持仓 `000601.SZ` **33,600 股** |
| error | `dividend:17916:...record_date_unknown_positive_holdings` |
| prepared manifest | `8b54f573…` 实测匹配 |
| `full_opportunities.jsonl` | 各约 **1.29 GB** |

`launch_command.txt` 的 PYTHONPATH 指向已删树、`scripts/run_2025_restricted.py` 硬编码 `REVIEWED = TEMP/"corporate-action-fix-20261027"` 与 `main_root = D:/code/cnn_full_20260905/cnn`。

**这是全项目里"拒绝交付"做得最正确的样本**：它在无法确定分红登记日时，选择 `main_end_nav = null` 并标记 `INCOMPLETE`，而不是猜测日期凑出一个收益数字。这个行为本身完全可复现（理由与证据都留在盘上）。

### C2 不可复现：重跑不可行

原命令必失败（cwd + REVIEWED + main_root 三重失效），与 A4 同构。

### C3 不可复现：测试的验证力已被 skip 掏空

实测 4 个测试文件：

| 测试文件 | 结果 |
|---|---|
| `test_2025_restricted` | Ran 24, OK (**skipped=18**) |
| `test_2025_restricted_fix2` | Ran 7, OK (**skipped=7**) |
| `test_2025_restricted_fix3` | Ran 7, OK (**skipped=7**) |
| `test_ca_evidence_adapter` | Ran 2, OK (**skipped=1**) |

合计 40 个用例，**33 个 skip**，跳过原因统一为「依赖已于 2026-10-30 退役的 corporate-action-fix-20261027 既审树」。

→ **绿 ≠ 验证**。三方能得到同样的绿色结果，但三方得到的是同样的"没测"。这是本次核验里最容易被误读的一条：如果有人拿 `OK` 当验证通过，就会得出完全错误的信心。

顺带记录另一处同类现象：`test_fractional_scenarios` 现为 `Ran 29 OK (skipped=7)`，而 `test_prefix_attestor` 为 `Ran 4 FAILED (errors=1)`（`ValueError: source fixed SHA mismatch: ...staged_candidate_runner.py`）—— 后者恰好把 B3 的 pin 断裂暴露出来了，**这个红灯是有价值的，不应被修绿**。

---

## D. 模型与训练链

### D1 可复现：旧权重可 strict 加载（但条件苛刻）

`logs/KEEP/baseline/best_model.pth`（tracked，2 文件）实测 **401 keys，stem = (128,45,7)**。

- 仅当显式传入：`ModelConfig(featurenum=45, seq_len=60, num_classes=52, cnn_out_channels=128, cnn_kernel_sizes=[1,3,5,7,10], d_model=256, nhead=8, num_encoder_layers=4, dropout_rate=0.3)` 时，`strict load` = **0 missing / 0 unexpected**
- 用 `ModelConfig()` 默认（kernel `[3,5,7]`、`cnn_out_channels=60`）则 **48 missing / 168 unexpected**

→ 权重是好的，**默认配置是错的**。任何"加载 baseline 看看"的尝试若不显式传这 8 个参数，会静默得到形状不匹配的模型。

`config.json` 记录：`per_code` / H5 / BINS ±0.25 / DUAL_HEAD λ=0.2 / lr 1e-4 / EPOCHS 50 / PATIENCE 2。

### D2 可复现：现行链路能跑

`train.py --smoke` 实测跑通：约 **24s/epoch**，F=80、relative、H10、SEED=42、20 codes、1 epoch。

### D3 不可复现：旧 F=45 口径无法重建

- 当前 `data/schema.py` 只有 52 raw + 单一 `g9_observed_mask` = **F=53**
- 旧 F=45 需要 39 raw + **6 个** margin/short mask
- 这 6 个 mask 的 schema 已从代码中移除
- `logs/KEEP/scaler_per_code_legacy39_2026.pkl`（**untracked**）是唯一载体
- `logs/KEEP/scaler_per_code.pkl` 是 52→53（**untracked**），而 `config.json` 记录的 `SCALER_PATH=logs/scaler_per_code.pkl` **在默认位置不存在**

→ 权重能加载，但**产生该权重的特征口径无法由现行代码重建**。这意味着 `logs/KEEP/baseline` 的旧指标不可能被重算验证。

### D4 部分：位级确定性不成立

已有：`set_all_seeds`（random/numpy/torch/cuda + `cudnn.deterministic=True` + `benchmark=False`），SEED 默认 42 且写入 config。

缺失：
- 无 `torch.use_deterministic_algorithms`
- 无 `CUBLAS_WORKSPACE_CONFIG`
- 无 TF32 关闭
- DataLoader `shuffle=True` 无 `generator` / `worker_init_fn`

→ 单机单卡单 worker 大致可复现；跨机、跨卡、多 worker **不保证位级一致**。

---

## E. 环境与依赖

### E1 可复现：本机可离线重建

- `uv sync --offline --dry-run` 实测：`Resolved 164 packages`、`Would make no changes`（本机缓存充足）
- `uv.lock`（249,978 B，revision 3）锁定全部依赖含 hashes
- `wheels/` 三个本地 wheel **已 tracked**：`backtest_core-0.1.0-py3-none-any.whl`、`AmazingData-1.1.8`、`tgw-1.0.8.7`
- torch 走 `download.pytorch.org` 专用 index（`torch==2.12.0+cu130`）

→ **离线可用只是本机 uv 缓存的结果**。新机器必须联网。

### E2 不可复现：换机/换目录即断

- tracked 的 py 文件中 **74 处绝对路径**，分布在 **34 个文件**
- 生产树关键处：`prefix_attestor.py:17`（`CORE_SOURCE` → 已退役树）、`prefix_ledger_verifier.py:26/28/30/49/50`（Temp + `D:\code`）、`scripts/run_2025_restricted.py:1016`（`D:/code/cnn_full_20260905/cnn`）、`config/defaults.py:10`（`Z:/test/train_data/...F60...parquet`）
- Temp 证据中 **907 个 JSON** 含 `C:\Users\yanwen` 绝对路径
- v12 manifest 的 **4812 artifacts 全部以绝对路径为键**
- 三个证据根**都不在任何 git 仓库**（实测无 `.git`）：
  - `staged_mechanical_results_20261028_v1`（W2 账本）
  - `staged_prepared_inputs_20261027_v12`（冻结输入）
  - `validation_2025_ab_real_20261029_v2`（2025 A/B）

→ 换机/改目录后，slug 全部失配，`_verify_prepared` 会直接失败。这不是"可能有问题"，是**确定性失败**。

### E3 部分：core 能力不一致

| 位置 | 版本 | `stop_after_close` |
|---|---|---|
| CNN `.venv` 内 installed `backtest_core` | `893fc96`（LF `f77462f4` / raw `aa156ec2`） | **无（0 处引用）** |
| core 主区 HEAD | `df38c2e` | **有（11 处）** |

`core_sha256 = aa156ec2` 在 manifest 中，因而**今日仍匹配** —— 这是正确的，因为 W2 的 2021 年回放确实不需要 cutoff。

但任何**需要 cutoff 的 W1 结论，在 CNN 侧无法复现**：`.venv` 里没有那个能力。

---

## 1. 最危险的三处不可复现点

排序依据：**"丢了就永远没了"**，而非"看起来最严重"。

### 第 1 位：Temp 证据根 ~24 GB 不在任何 git、无备份

路径：`C:/Users/yanwen/AppData/Local/Temp/opencode/`

| 内容 | 体积 | 唯一性 |
|---|---|---|
| W2 账本 `staged_mechanical_results_20261028_v1` | 7.72 GB | 唯一 |
| v12 prepared 输入 | 1.88 GB | 唯一 |
| 2025 A/B `validation_2025_ab_real_20261029_v2` | 2.66 GB | 唯一 |
| W2 checkpoint / signals | — | 唯一 |
| 官方法证 PDF | — | 唯一 |

**为什么最危险**：
1. 它在 **`Temp` 目录**下。Windows 清理工具、磁盘清理、任何 `Remove-Item $env:TEMP` 都会无提示删除。
2. 它**不在任何 git 仓库**（实测三个根均无 `.git`）。
3. 它**无任何备份**。
4. 上面 8 项"可复现"结论中的 A1/A2/A3/B2/C1 **全部依赖它**。它一旦消失，本次报告中 5 项"是"会立刻同时变成"否"。

这是整份报告里唯一的**单点全损风险**：一个目录消失，直接干掉一半的"可复现"判定。

### 第 2 位：W1 版 8 个接口 + 隔离 core 树已删除，pin 指向不存在的字节

不可复现的具体 SHA：

- `37fcf150`（staged_candidate_runner）
- `cef7b7bb`（staged_production_inputs）
- `9c87f2e1`（staged_order_strategy）
- `53ce8d8e`（raw_market_provider）
- `000c382d`（raw_market_inputs）
- core `4d3a28c4`

**为什么危险**：我已用**三条独立路线**穷举（git 提交 / 工作区磁盘 / 冻结 git index blob），全部 MISS。其中冻结 index 里的 blob 对象**确实存在且可取**，但内容哈希与 pin 不符 —— 说明 pin 记录的不是任何已落盘状态。

→ **这不是"再找找就能找到"，而是"从来没存在过"**。W1 prefix 的证明链**永久不可重建**。

且注意交叉失效：`53ce8d8e`/`000c382d` 在 A5 与 B3 两份"独立"清单中**同时指向不存在**，说明两份清单同源，**不能互证**。

### 第 3 位：单一可变介质（`opencode.db` 3.8 GB + untracked pkl）

| 对象 | 风险 |
|---|---|
| `~/.local/share/opencode/opencode.db` | 3,836,485,632 B，最后写 2026-10-30 13:06，**可变、无备份** |
| `logs/KEEP/scaler_per_code.pkl` | **untracked** |
| `logs/KEEP/scaler_per_code_legacy39_2026.pkl` | **untracked**，是 F=45 口径（D3）的唯一载体 |

`opencode.db` 是**未提交文件的最后恢复手段**（本次 18 个文件即由此恢复），但它：
- 只覆盖"被会话读写过"的文件，不是全量快照
- 自身是 SQLite，需 `mode=ro` 只读打开
- **一旦被 VACUUM、清理或损坏，B1 的 `ABF5E9FD` 重建路径与全部未入库研究源码同时消失**

而 `scaler_per_code_legacy39_2026.pkl` 消失，则 D3 从"不可复现"变成"永久不可复现" —— 连唯一的特征口径载体都没了。

---

## 2. 「复现包」建议

目标：让"下一次核验"不必再依赖 Temp 目录、已删树、单一 SQLite。按**投入产出比**排序。

### P0（今天必须做，成本小，否则随时全损）

1. **把 24 GB 证据根迁出 `Temp`**
   - 目标：`D:/code/cnn_full_20260905/evidence/`（或任何非 Temp、非系统盘清理范围的路径）
   - 至少迁这 6 个：`staged_mechanical_results_20261028_v1`、`staged_prepared_inputs_20261027_v12`、`validation_2025_ab_real_20261029_v2`、`recovered_w1_20261030`、`staged_production_integration_delivery_20261027`、`three_day_signals`/`three_day_models`
   - 迁完**更新 manifest 里的绝对路径键**（4812 条），否则 `_verify_prepared` 仍失败

2. **给证据根做一次 `git init` + 只提交小文件**
   - 大 parquet 用 `.gitattributes` 走 LFS 或干脆不收
   - 收：所有 `manifest.json`、`*.json`、`*.md`、`*.cmd`、`*.ps1`、`SOURCE_HASHES_FINAL.json`、`MANIFEST.json`
   - 这样即便大文件丢了，**至少有清单知道丢了什么**

3. **`logs/KEEP/*.pkl` 立即入库**
   - `scaler_per_code.pkl`、`scaler_per_code_legacy39_2026.pkl` 都是小文件，是 D3 唯一载体
   - 当前 untracked，`git clean -xdf` 即永久丢失

4. **`opencode.db` 定期冷备份**
   - `sqlite3 ... "VACUUM INTO 'D:/backup/opencode_YYYYMMDD.db'"`（只读源、写新文件）

### P1（本周，成本中，解决 A4/C2/B4 这类"跑不了"）

5. **把 runner 源码版本纳入 pin 校验**
   - 现状：`_verify_prepared` 只校验 artifacts + core，**不校验 runner 自身**
   - 改法：把 runner 及其 import 闭包的 `sha256` 写进 manifest，运行时比对
   - 这是**唯一能防住"静默版本漂移"**的办法，优先级高于修 cwd

6. **把 `--run-root` 的 `mkdir(exist_ok=False)` 换成可复现的语义**
   - 建议加 `--run-root` 允许已存在 + 显式 `--reuse` 标志，同时把 target 目录的内容哈希写进产物
   - 否则每次复现都只能新建目录，历史结果无法原地重验

7. **消灭 74 处绝对路径**
   - 优先改生产树的 4 个文件：`prefix_attestor.py`、`prefix_ledger_verifier.py`、`scripts/run_2025_restricted.py`、`config/defaults.py`
   - 改成 `Path(__file__).resolve().parents[N]` 相对推导 + 环境变量覆盖
   - 这是 E2 从"否"变"是"的唯一路径

### P2（需要接受现实的地方，成本大，可能无解）

8. **接受 4 个源文件 pin 永久不可满足**
   - `000c382d`/`53ce8d8e`/`aa9d7205`/`a736ab4e` 已三条路线穷举，**不要再去"找"**
   - 正确做法：在 `SOURCE_HASHES_FINAL.json` 里把这 4 项**显式标注为 `UNREPRODUCIBLE`** 并写清原因
   - **保留这个记录本身就是价值** —— 让后来者知道"这里有个洞"，好过让人误以为全绿

9. **接受 skip 不等于 pass**
   - 建议在 CI 里**统计 skip 数并设阈值**（如 2025 相关模块 skip > 30% 则 FAIL）
   - 否则 33/40 skip 会长期伪装成绿

10. **F=45 旧口径若还要用，必须重建 6 个 mask 列**
    - 这是一次真正的 schema 考古，成本大
    - 若接受"旧指标不再复核"，则应在 `logs/KEEP/baseline/` 放一份 `READ_ONLY_DO_NOT_REPRODUCE.md` 说明

### 不建议做的事

- ❌ **不要把 `test_prefix_attestor` 的红灯修绿**。它报 `ValueError: source fixed SHA mismatch` 正是 B3 断裂的**唯一自动告警**。改成 skip 或放宽容差，等于拆掉警报器。
- ❌ **不要为了"复现"去猜 `000c382d` 的内容**。pin 不匹配意味着版本未知，猜出来的东西不是原始版本，会制造假复现。
- ❌ **不要把 `NOT_EVALUABLE` 改成 `EVALUABLE`**。C1 的价值就在于它拒绝了不完整的收益计算。

---

## 3. 附：本次核验的副作用披露

| 项 | 说明 |
|---|---|
| `logs/relative/run_20261030_124129/` | D2 执行 `train.py --smoke` 产生（F=80、1 epoch、约 24s）。目录被 gitignore，`git status` 仍为 5 项未变。**需 owner 决定是否删除。** |
| `C:/Users/.../Temp/opencode/__q3_tmp_core`、`__q3_core_try` | 本次自建临时目录，**已自行删除** |
| `C:/Users/.../Temp/opencode/__q3_idx.txt` | 本次核查 git index 用的临时列表（459 行），可删 |
| 其它 | 未修改、未删除任何项目文件；未执行任何 git 写操作 |

---

## 4. 一句话总结

> 这个项目的**数据与账本是真的**（A1–A3、C1 实测全中），**结论是真的**（B1–B2、D1 可独立复算），但**"怎么得到这些结论"的过程已经大面积不可重放** —— 8 项不可复现中，有 5 项的死因是同一个：**源码树被删、Temp 证据无备份、pin 指向从未落盘的字节**。好消息是这三件事**现在还能补救**（P0 四项成本都很小），坏消息是它们全在 `Temp` 下、无备份、且其中一项（`000c382d` 那一族）已经确定无解。

**当前唯一可立即执行的最高优先级动作**：把 `C:/Users/yanwen/AppData/Local/Temp/opencode/` 里的 6 个证据根迁出 Temp 并做一次哈希清单存档。
