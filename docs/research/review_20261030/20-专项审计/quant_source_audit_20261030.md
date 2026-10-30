# quant 侧历史缺口来源可解性调查（只读）

调查日：2026-10-30。范围：quant 仓源码/文档/schema、Z 盘 dev/prd 库与 parquet、quant 本地 HDF 缓存、cnn 侧 v12 冻结输入产物。只读：SQLite 全部 `mode=ro` + `PRAGMA query_only=ON`，未改任何文件，未下载数据，未跑训练/回测。

## 0. 一句话结论

**W1/W2 的"缺口"不是取数漏了，而是这些 (股票,日期) 在源头本来就没有行情。** v12 的 60,144 条 gap 与 34,514 条 unknown（W1 17,909 + W2 16,605）**100% 可归因到四类真实非交易原因**（上市前 / 退市后 / 官方暂停上市 / 停牌），**随机抽 200 条 gap 反查源头 bar 命中 0 条**。因此"从获取源头补 W1/W2 缺口"这个方向不成立。源头真正能补的是**解释标签**（把 unknown 变成"已知非交易"）和**一处真的数据落盘缺口**（200 只 dev / 187 只 prd 退市股完全没有 kline 文件）。永久缺失是：SDK 无"暂停上市"字段、`history_status` 只有 2014 起的异常事件行、退市股历史日线大面积未落盘。

## 1. quant 仓与数据链路

### 1.1 仓身份

| 项 | 值 | 证据 |
|---|---|---|
| 路径 | `D:\code\quant` | `Get-ChildItem D:\code` 目录列表 |
| HEAD | `cdee171b35c69edcaa638928cd57297636355045`（2026-10-20 15:17:03 +0800，merge: resolve conflict in memory after archive sync） | `git rev-parse HEAD`、`git log -1` |
| 工作区状态 | `M uv.lock`、`?? docs/research/`（本地脏，非本次改动） | `git status --short` |
| 顶层 AGENTS.md | **不存在**；只有 `CLAUDE.md` 与 `MISTAKES.md` | `Test-Path AGENTS.md` → False |
| 模块级 AGENTS.md | `src/core/AGENTS.md`、`src/core/{database,data_fetcher,data_storage,data_pipeline,data_reader,backtesting,model_bridge,factor,common,amazing_data}/AGENTS.md` | 全仓 `AGENTS.md` 枚举（venv 内第三方除外） |

`CLAUDE.md` 明确：数据根是独立 `quant-data/` 目录（`QUANT_DATA_ROOT`），dev/prd 两套库 + parquet；调度唯一真源是 `flows/`（Prefect）。本机 `.env` 只含 `AD_USER/AD_PASSWORD/AD_HOST/AD_PORT/AD_LOCAL_DATA_PATH`（键名枚举，未读值），`AD_LOCAL_DATA_PATH="./data/AmazingData_local_data"`。

### 1.2 三者的关系：SDK 是源，DB 与 parquet 是两种加工产物

```
AmazingData SDK（远程 tgw，AD_HOST/AD_PORT，互联网模式）
  │  get_history_stock_status / query_kline / get_dividend / get_stock_basic ...
  │  可选本地 HDF 缓存：data/AmazingData_local_data/basedata/{hist_stock_status,hist_code_list}/*.h5
  ▼
src/core/data_fetcher/*            （只取数，返回 DataFrame，不落盘）
  ▼
src/core/data_storage/*            （DatabaseStorage → SQLite；ParquetStorage → 每码一 parquet）
  ├── Z:\dev\quant_data_dev.db  / Z:\prd\quant_data_prd.db   结构化表
  └── Z:\{dev,prd}\kline\day\{code}.parquet 等             行情/因子
  ▼
scripts\export_training_data.py    （复权K线 + 股本 as-of + 60因子 + is_trading 合成行 → 单文件训练 parquet）
  ▼
cnn 侧 data/test/train_data/*.parquet（训练） / Z:\dev\kline\day（回测 staged 链路）
```

关键判定：

- **SDK 是唯一源**；DB 与 parquet 都是 SDK 的加工产物，二者不是互相的源。DB 里没有的，parquet 里也不会有，反之亦然的例外只有下面 1.3 的两处。
- **DB 是"事件表"不是全量快照**：`history_status` 只存异常事件行（ST/停牌/除权/退市风险/非标准涨跌幅），正常交易日**没有行**。证据：`src/core/database/AGENTS.md`「HistoryStatus.记录类型（alembic 008）：该表只存异常事件行」；`src/core/data_fetcher/history_status.py:12` 头部注释；实测 2021-12-31 全库该日仅 194 行（同期 4422 只在市）。
- **行情的"停牌/未上市合成行"只存在于训练导出产物**：`scripts/export_training_data.py:10` `is_trading=False 为停牌/未上市合成行：OHLC/因子=NaN`，`:616` `out['is_trading'] = grid.isin(set(df['kline_time']))`，`:628-630` 上市期 ∩ SSE 日历生成网格。**Z:\dev\kline\day 是原始日线，无合成行**——这就是训练侧"没缺口"、回测侧"有缺口"的根源。

### 1.3 DB 与 parquet 不一致的两处（重要）

| 现象 | 证据 | 含义 |
|---|---|---|
| `000670.SZ` 在 DB 有 247 行暂停上市记录（2020-04-07~2022-08-22 逐日 `是否暂停上市=1`），但 SDK `get_history_stock_status` 对该码两个窗口都返回 **0 行**（`batches/batch_0001/raw/{W1,W2}全窗_000670_SZ.parquet` 均 0 行） | DB 查询 `select count(*) from history_status where 证券代码='000670.SZ' and 是否暂停上市=1 and 交易日期 between 20201231 and 20220106` → 247；parquet `num_rows=0` | DB 里这些行**不是 SDK 来的**，是 `scripts/backfill_paused_listing.py` 手动按交易日展开写入的（`PAUSED_RANGES` 硬编码 13 只，第 41 行起） |
| `600240.SH` 已退市（`stock_basic.delistdate=20200205`），SDK 两窗均 0 行；DB 也无窗口内行 | `stock_basic` 查询 + 两个 raw parquet 均 0 行 | 退市后无状态行，属正常 |
| **DB 的 `是否ST=1` 与 SDK 的 `IS_ST_SEC="1"` 在窗口内有 10 条不一致**（DB 有、SDK 无） | 逐条比对 `history_status where 是否ST=1 and 交易日期 between 20201231 and 20220106`（scope 内 29,601 条）与 canonical `is_st_sec=="1"`（29,591 条），差集 = `000017.SZ`(06-21,06-22)、`000408.SZ`(05-12)、`000409.SZ`(04-12)、`000422.SZ`(06-10,06-11)、`000504.SZ`(04-28)、`000536.SZ`(05-11)、`000572.SZ`(05-27)、`000595.SZ`(07-15)。反查 `000017.SZ` 2021-06-21：DB `(ST=1, 停牌=1)`、SDK `(is_st_sec=0, is_susp_sec=1)` | **DB 与 SDK 各有各的口径**：DB 行来自历史累积（可能是当时 SDK 给的值或旧版本语义），SDK 当期重采给 0。差异量 10/29,601（0.03%），对 W1/W2 判定无实质影响，但说明**不能把 DB 当作 SDK 的等价快照**；任何"从 DB 复算状态"的方案都要预期这种量级的残余差异。停牌列反而完全一致（scope 内 1,508 == 1,508，差集空） |
| `dev` 有 5215 个 kline 文件，`stock_basic` 有 5415 码；`prd` 有 5228 个文件 | `Get-ChildItem Z:\dev\kline\day` 计数 5215；DB `select count(*) from stock_basic` = 5415；Z:\prd\kline\day 计数 5228 | 200 只（dev）/187 只（prd）无 kline 文件，**其中 dev 缺失的 200 只 `delistdate` 全部非空（退市股）**，只有 `000585.SZ` 一只 `is_listed` 仍为 1（状态位自相矛盾，见 §6.3）；prd 比 dev 多 13 个文件、也多补了 13 只退市股。即退市股历史日线大面积未落盘 |

### 1.4 CNN 侧 prepared inputs ↔ quant 源对应

`staged_prepared_inputs_20261027_v12/manifest.json` + `integration_inputs.json` 的 `config` 段（第 3–30 行）：

| cnn 输入 | 路径 | quant 侧来源 |
|---|---|---|
| `raw_market_root` | `Z:/dev/kline/day` | quant `KlineDayUpdatePipeline` → `ParquetStorage('kline_day')`（`src/core/data_pipeline/data_update_pipeline/kline_day_update_pipeline.py:45` 只取 `active` 码） |
| `index_path` | `Z:\dev\kline_index\day\000300.SH.parquet` | `IndexKlineDayUpdatePipeline` |
| `state_path`（canonical_state_v3.parquet，1,033,541 行 / 247 日 / 4422 码） | 本地派生 | **SDK `get_history_stock_status` 86 批直采**（`state_acquisition_20261027/full_state_v1`，86 批 × 50 码，19 分 27 秒，1,007,108 行）+ 172 码复用本地 HDF（`scope_manifest.json`：`完整缓存代码=172`，`需SDK代码=4252`） |
| `gap_index_path` | 本地派生 | 全码 × 窗口日历 − canonical 已有日期（`assemble_state_v3.py` 主循环末尾） |
| `ca_manifest_path` | `staged_execution_input_snapshot_20261027_v1/delivery_manifest_v4.json` | `Z:/dev/quant_data_dev.db` 的 `dividend`、`right_issue` 表只读导出（`dividend_right_issue_extract_v2.py`） |
| `quantity_sources[*].metadata_path` | `security_metadata.json` | `stock_basic` 导出的 `market_code/listdate/delistplate_name` |
| 训练链路（另一条） | `data/test/train_data/*.parquet` | `scripts/export_training_data.py` 产物；`backtest/cnn_adapter/market.py:1-5` 注释说明"train_data parquet 直读、OHLC 为后复权" |

**两条 cnn 侧行情路径不要混**：训练读 train_data（含 `is_trading` 合成行、后复权），staged 回测读 `Z:/dev/kline/day`（原始价、无合成行、逐码一文件）。缺口问题只出现在后者。

## 2. 缺口分类与可解性（核心）

### 2.0 先把口径对齐：三个数字不是一回事

| 口径 | W1 | W2 | 合计 | 证据 |
|---|---|---|---|---|
| `coverage_*.json` `missing_bar_count`（无 bar） | 17,029 | 15,620 | 32,649 | `coverage_W1.json` / `coverage_W2.json` 首部 |
| `coverage_*.json` `unknown_count`（含"有 bar 但限价未知"） | 17,909 | 16,605 | 34,514 | 同上 |
| `gap_coverage.jsonl`（gap_index 行数） | 45,218 | 14,926 | 60,144 | `gap_summary.json` |
| 其中在 coverage 宇宙内的 gap（W1 减少 29,029 = 238 只非宇宙码） | 16,189 | 14,926 | 31,115 | 逐行 join `gap_coverage.jsonl` × `market_coverage_*.jsonl` 的 code 集合 |

关键事实（实测）：

- **W2 的 14,926 条 gap 与 14,926 条"无 bar 且无 state"的 coverage 行是同一集合**（`gap - cov = 0`、`cov - gap = 0`）。W2 的 `unknown_count=16,605` = 15,620 无 bar + 985 有 bar 但限价未知。
- **W1 有 29,029 条 gap 属于"从未进入 W1 信号宇宙"的代码**（238 只，全部 `listdate >= 2021-07-01`，即 W1 期末后才上市）——这些是 assemble 阶段按"全 F4 代码并集 × 窗口日历"机械展开的产物，不是执行侧缺口，也不该计入 coverage。`staged_production_inputs.py:343-345` `_empty_codes()` 已用 `_absence_reason` 把这些码整体豁免（`allow_empty_window`）。
- W1 `unknown_count=17,909` = 17,029 无 bar + 880 有 bar 但限价未知。

**因此"5.6%"这个比例对应的是 W2 的 16,605/570,696，其中 15,620 是真正的"无 bar"，985 是"有 bar 但 SDK 没给限价"。**

### 2.0b 五类缺口速查矩阵

| 类别 | 数量（W1+W2，coverage 口径） | 成因 | 源头有没有 | 能否补 | 成本 |
|---|---|---|---|---|---|
| 停牌 | 1,534 对 | 当日停牌无成交 | **有**：`是否停牌=1` 100% 命中 | 行情不能补；标签已在 canonical | 小 |
| 上市前 | 59,491（含 29,029 非宇宙） | 未上市 | **有**：`stock_basic.listdate` 零空 | 行情不能补；标签已判 | 小 |
| 退市后 | 251 | 已退市 | **有**：`stock_basic.delistdate` | 行情不能补；标签已判 | 小 |
| 暂停上市 | 402 行 / 394 distinct | 官方暂停上市 | **DB 有（人工 13 只）、SDK 无字段** | 只能人工公告取证 | 大 |
| 限价 unknown（有 bar） | 985 + 880 | 双创新股前 5 日无涨跌幅限制，SDK 给 999 哨兵 | **有**（999 是语义值不是缺失） | 改映射语义即可 | 小 |
| （附）退市股无 kline 文件 | 200 只 dev / 187 只 prd | 只更新 active 码 | SDK 可返回历史（间接证据） | **可真实补数** | 中 |
| （附）公司行动空登记日 | 2025 窗口 229 行 | 未实施方案无登记日 | 源头本就无值 | 只能补语义（取进度=3 兄弟行） | 小 |

### 2.1 停牌缺口

| 项 | 结论 |
|---|---|
| 成因 | 股票当日停牌，交易所无成交，SDK 日线不返回该 bar。`HistoryStatusFetcher` 对停牌码本就返回"确认无数据"（status=-76 语义，`src/core/data_fetcher/kline.py:28`），`KlineDayUpdatePipeline` 还用 `load_current_suspensions()` 预过滤当前停牌码（`kline_day_update_pipeline.py:53-62`）→ 停牌日永远不会写进 `kline/day` |
| 数量 | W1 840 对、W2 694 对，共 1,534 对 |
| 源头有没有 | **有，而且是逐日精确的**。`history_status.是否停牌=1` 对全部 1,534 对**逐一命中 100%**：W1 840/840、W2 694/694，DB 返回 `(是否停牌=1, 是否暂停上市=NULL)`。抽查 `000663.SZ 2021-09-22`、`002265.SZ 2021-11-22`、`002256.SZ 2021-08-03` 均确认：DB 有停牌行、`Z:\dev\kline\day` 无 bar、canonical_state 有 `is_susp_sec=1` 行 |
| 能否补 | **不能补行情**（停牌日本来就没有行情，补出来就是伪造）。**能补标签**，而且标签已经在了：canonical_state 里这些码的 `is_susp_sec=1` 已存在（实测 canonical 有 1,508 行 `is_susp_sec=1` / 365 码，抽样 300 行对 DB 命中 300/300），`derive_execution_state()`（`staged_production_inputs.py:86`）已把 `is_susp_sec="1"` 映射为 `market_state="suspended"`。所以停牌行的 `verified_state` **不是** unknown（`_market_coverage` 里 `states.get((code,day))` 命中），unknown 只来自 `bar is None` 和 `limit_known=False`（`unknown_fields=['bar','limit_known']`），因为 `derive_execution_state:80-84` 要求 `high_limited/low_limited` 为正才 `limit_known=True`，而停牌日 SDK 给的是 0 |
| 停牌是否进 gap_index | **不进**。gap_index 是"窗口日历 − canonical 已有日期"，停牌日 canonical 有 status 行，故不产生 gap。实测停牌 1,534 对**在 `gap_coverage.jsonl` 中命中 0 条**（W1 840→0、W2 694→0）。所以停牌只体现在 `coverage_*.json` 的 `missing_bar_count`，不影响 60,144 这个数字 |
| 120 条 110 suspended 的依据能否批量复算 | **能，且已在源头可批量复算**：`select 证券代码,交易日期,是否停牌 from history_status where 是否停牌=1`（走 `(code,date)` 索引），或直接读 canonical_state 的 `is_susp_sec` 列（1,508 行）。`suspension_utils.load_suspension_dates()`（`src/core/data_pipeline/data_validator/validators/suspension_utils.py:117-140`）就是这条查询的现成封装 |
| 成本 | **小**：一次 DB 查询（< 1 秒）或读现成 canonical parquet 列；不需要重跑 SDK |

### 2.2 上市前缺口

| 项 | 结论 |
|---|---|
| 成因 | 股票尚未上市，或代码进入 F4 宇宙但窗口早于上市日。SDK 不返回上市前任何 kline/status 行（实测 `301020.SZ`（listdate 20210706）、`688789.SH`（20210708）在 2021-06-30~07-07 时段 SDK 返回 **0 行**，两个 raw parquet 都是 0 行） |
| 数量 | W1 44,852（其中 29,029 属非宇宙码）、W2 14,639，合计 59,491（`gap_summary.json` `pre_listing: 59491`） |
| 源头有没有 | **有，字段级精确**。`stock_basic.listdate`：5415 行**无一为空**（`select count(*), sum(listdate is null) from stock_basic` → `(5415, 0)`，范围 19901201–20260515）。用 `listdate` 复算 60,144 条 gap 的归因：W1 `before_listdate=44,852`、W2 `before_listdate=14,639`，**与 gap_coverage 的 `pre_listing` 逐条完全一致，零残留** |
| 能否补 | **不能补行情**（上市前无行情）。**能彻底消除 unknown**：`_absence_reason()`（`staged_production_inputs.py:329-339`）已经在用 `quantity_sources[0].metadata_path` 的 `listdate` 判 `pre_listing`，且 gap_index 的 59,491 条已全部标注 `pre_listing`。coverage 侧的 unknown 只需在 `_market_coverage`（`staged_candidate_runner.py:386-425`）里对"已判 pre_listing/post_delisting 的 (code,date)"视作已知非交易而不是 unknown——**这是纯标签改动，不改任何行情/状态值** |
| 成本 | **小**：已有 `_absence_reason` 与 `metadata.listdate`，改动只在 coverage 归类逻辑（且属 cnn 侧，不在本任务范围） |

### 2.3 unknown 缺口（抽查：源头到底有没有这根 bar）

| 项 | 结论 |
|---|---|
| 定义 | 15,620（W2）/17,029（W1）条 `bar_present=false`。其 `verified_states` 为 null 的只有 **10 条**（W2 的 `301020.SZ` 4 + `688789.SH` 6），其余全部有 state 记录 |
| 成因（已 100% 分解） | W2 的 15,620 无 bar = `pre_listing` 14,639 + `post_delisting` 129 + `official_pause_interval` 158 + 停牌 694。W1 的 17,029 无 bar = 宇宙内 `pre_listing` 15,823 + `post_delisting` 122 + `official_pause_interval` 244 + 停牌 840（另有 29,029 条非宇宙 pre_listing 不计入 coverage） |
| **抽查反查源头（关键实验）** | 从 60,144 条 gap 中按 `seed=20261030` 随机抽 **200** 对，逐对打开 `Z:\dev\kline\day\{code}.parquet` 查该日是否真有 bar：**命中 0 条**（`BAR_EXISTS=0`，`no_file=0`）。即"CNN 侧没取到"**不是 pipeline 漏取**，源头确实没有 |
| 第二组抽查（限价 unknown） | 985 条 W2 + 880 条 W1 "有 bar 但限价未知"逐对连 canonical_state：985/985、880/880 全部匹配，`high_limited` 全部为 0、`high_lmt_rate` 全部为 999.0 → **源头给的就是"无涨跌幅限制"哨兵值**，不是 CNN 侧丢了 |
| 是 pipeline 漏还是源头就没有 | **源头就没有 bar**。唯一例外是 `301020.SZ`/`688789.SH` 这 10 条：它们的 gap 归因是 `pre_listing`（正确），只是 SDK 对该码整段时段返回 0 行所以 `verified_states` 也为空——仍属"上市前无数据"，非漏取 |
| 能否补 | 无 bar 的 15,620 条**不能补**（停牌/未上市/暂停上市/退市，本无行情）。**能补的是把 unknown 降级为"已知非交易"** |
| 成本 | **小**（标签侧）；**大**（若要求"补出真实 bar"，不可能） |

### 2.4 公司行动登记日空（2025 的 229 个空登记日）

| 项 | 结论 |
|---|---|
| 现象复现 | 174 码、2024-12-31~2025-12-19 窗口内 `dividend` 359 行，其中 `股权登记日` 空 229、`除权除息日` 空 229、`派息日` 空 231、`分红实施公告日` 空 229、`红股上市日` 空 355（与 `docs/research/final_delivery_20261030.md` 记载一致，本次独立复现数字完全相同） |
| 成因 | **不是加工丢字段，是这些行本身是"预案/股东大会通过"阶段记录，尚未实施**。按 `方案进度` 交叉：`('1',空)=151`、`('2',空)=77`、`('4',空)=1`、`('3',非空)=130`。全库规律：`方案进度='3'` 的 42,632 行**登记日零空**（`select count(*), sum(股权登记日 is null) from dividend where 方案进度='3'` → `(42632, 0)`）。229 条空行的 `每股派息税前`、`每股派息税后`、`每股送转` **全部为 0.0**，即"金额为零的未实施预案"，不是"有金额但丢了日期" |
| 源头有没有 | **源头就是没有**——这是供应商数据语义（未实施方案没有登记日），不是 SDK 缺列。SDK 文档确认 `DATE_EQY_RECORD`（登记日）是标准字段（`docs/AmazingData开发手册.md:2270` 附近 DIV_PROGRESS 段；colum mapping 见 `src/core/data_fetcher/dividend.py:38-39`）。**该字段在 SDK 里存在，只是这些行取值为空** |
| 是不是源头缺 vs 加工丢 | **加工没丢**。`DividendFetcher.COLUMN_MAPPING` 完整映射 `DATE_EQY_RECORD→股权登记日`，`fetch_batch` 三路拆分不会丢列；导出脚本 `dividend_right_issue_extract_v2.py` 用 `SELECT *` + 原样 JSON，实测 229 空与 DB 查询结果逐字段一致。dev 与 prd 两库同数字（dev 4,586 进度=3 / prd 4,586），所以也不是单库漂移 |
| 能否补 | **能，但只能"补解释"不能"补日期"**。补法：按 `(证券代码, 分红年度)` 聚合，取 `方案进度='3'` 的兄弟行（同一事件通常有 `1→2→3` 三行，`3` 行带全日期）。实测 2025 全库 4,252 条"空登记日且有正派息"中，**4,250 条存在同 `(code,年度)` 的进度=3 兄弟行**，只有 2 条无兄弟（`301139.SZ 20251231` 派息 0.0073、`689009.SH 20251231` 派息 12.514，均为 2026-03/04 的预案，尚未实施）。**结论：229 条中 100% 是"未实施"语义（金额为 0），事件级只需看进度=3 的行** |
| 成本 | **小**（聚合查询 + 语义过滤）。**风险**：若下游把"非进度3行"当作已实施事件，会导致重复计算权益；正确做法是只消费 `方案进度='3'`（或 `股权登记日 is not null`）的行 |

### 2.5 退市 / 暂停上市

| 子项 | 结论 |
|---|---|
| 退市标记 | **有**。`stock_basic.delistdate`（非空 224 行）+ `is_listed`（0/1）+ 名称带"(退市)"。`code_list.remove_date` 另有 288,068 行（含 A/HKT 两类）。复算：251 条 `post_delisting` gap 全部落在 `delistdate` 之后，零残留 |
| 暂停上市标记 | **DB 有列、但源头 SDK 没有**。`history_status.是否暂停上市` 是**手动维护列**：`src/core/data_fetcher/history_status.py:14-16` 明确「API 无此字段，该列为手动维护」；`src/core/database/models/factor.py:41` 注释同；写入唯一入口是 `scripts/backfill_paused_listing.py`，硬编码 **13 只** `PAUSED_RANGES`（`:40-54`）。实测库中 `是否暂停上市=1` 共 4,047 行，全部落在这 13 只里 |
| 暂停上市覆盖度 | **方向是对的，但成因是人工区间，不是源头日粒度数据**。W1/W2 窗口内 DB `是否暂停上市=1` 只有 2 只：`000670.SZ` 247 日、`000792.SZ` 147 日（合计 394 distinct `(code,date)`）。`gap_coverage.jsonl` 的 `official_pause_interval` 是 402 条，多出的 8 条 = **两窗重叠日（2021-06-30、07-01、07-02、07-05 共 4 个交易日）× 2 只码**，因为 gap_index 按窗口各记一条（`assemble_state_v3.py` 主循环末尾按 `W1全窗`/`W2全窗` 分别出 gap）。按 `(code,date)` 去重后 gap 与 DB **逐条完全一致，差集为空** |
| 退市整档缺文件 | **200 只退市股在 dev 无 kline 文件、187 只在 prd 无文件，且缺文件的码 100% 都是退市股**（dev `missing=200` 中 `delistdate is not null`=200；prd `missing=187` 中 187）。这属于真实的历史数据未落盘：`KlineDayUpdatePipeline._get_code_list()` 只取 `active`（`is_listed=1 且未退市`，`src/core/data_reader/base.py:691`），退市后不再更新；历史上是否曾落盘取决于该码在跑批时是否 `active`。实测 dev 有 24 只退市股存在文件（如 `600240.SH` 到 2020-01-23，早于 `delistdate=20200205`），说明 SDK/落盘链路对已退市码本身没有硬限制。**这一项是真正可以从源头补的**：用 `KlineFetcher` 指定退市码与 `listdate~delistdate` 区间重拉 |
| 暂停上市期间 KD 数据 | 停牌/暂停上市日在 `kline` 无 bar 是交易所事实；DB 里 `是否暂停上市=1` 的日行是人工补的，**不要误认为源头有逐日证券状态**。后续若换标的需重新做官方公告取证（`docs/research/20261026/INDEPENDENT_AUDIT_REPORT_20261027.md` 已记录 402 缺日核 PDF 的流程） |

## 3. 可执行的补缺方案（只给方案，不执行）

> **前置约束**：`staged_prepared_inputs_20261027_v12` 已冻结（`manifest.json` 1,029,809 字节，`manifest.sha256` = `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`）。任何重跑都必须写**新目录**（如 `..._v13`），不得覆盖 v12；`SOURCE_HASHES_FINAL.json` 里 pin 的 16 个文件同样不得改。

### 3.1 方案 A：只补"解释标签"，不重跑 SDK（推荐，成本小）

**能消掉**：15,620（W2 停牌/上市前/退市后/暂停上市）、17,029（W1）、880 + 985 条"有 bar 但限价未知"的 unknown 归类。

步骤（cnn 侧，无需 quant 重跑）：

1. 已有 `_absence_reason()`（`backtest/cnn_adapter/staged_production_inputs.py:329-340`）已能对每条 gap 判 `pre_listing / post_delisting / official_pause_interval / unexplained`。把它接到 `_market_coverage`（`staged_candidate_runner.py:386-425`）：对 `bar is None` 的行，若 `_absence_reason != "unexplained"` 则记 `known_absent_<reason>` 而不是 `unknown_fields=['bar']`。
2. 停牌部分：用 canonical 的 `is_susp_sec=1`（1,508 行，DB ∩ scope 逐条相等，已验证）作为第五类 `suspended`；停牌日 `limit_known=False` 也应随之记 `known_no_limit_because_suspended`。
3. 限价 unknown（999 哨兵）：从 quant DB 可复算出"该日无涨跌幅限制"（见 3.3），把它标为 `no_price_limit` 而不是 `limit_unknown`。

产出：新增 `coverage_*_explained.json` + `gap_coverage_*_v2.jsonl`，`unknown_count` 应从 16,605 降到 **0**（前提是上述三条全覆盖，实测四类已覆盖 100%）。**不触碰任何行情数值、不改 v12 的 raw/state/signal 文件。**

风险：这是"重新分类"而非"补数据"，必须在报告里显式区分"known absent"与"known value"，否则会被误读成覆盖提升。

### 3.2 方案 B：补退市股历史日线（真数据补缺，成本中）

**能补**：dev 缺 200 只 / prd 缺 187 只退市股的 `kline/day` 文件（理论行数上限约 44.7 万行 = 200 码 × 2014-01-01~delistdate 的 SSE 交易日）。

步骤：

1. 导出缺失码清单：`select market_code, listdate, delistdate from stock_basic` 减去 `Z:/dev/kline/day/*.parquet` 文件名集合（本次已得 200 只，全部 `delistdate is not null`）。
2. 逐码调 `KlineFetcher`，显式给 `begin_date=listdate`、`end_date=delistdate`：
   在 `D:\code\quant` 下执行 `uv run python -m src.core.data_pipeline.cli.main run-now -t kline_day -c <code> --begin-date <listdate> --end-date <delistdate> --full`
   （`--full` 走 `run_now` 单码分支，`begin_date` 不被增量水位覆盖；见 `cli/main.py:150-154` 与 `base.py:1157-1200`）
3. 批量时用 `run-batch -t kline_day -c "code1,code2,..." --begin-date ... --end-date ...`（`cli/main.py:225-260`），每批 50 码。
4. 落盘后按 `scripts/validate_export.py` 的 T3 口径抽验：`history_status(停牌=1) ⊆ is_trading==False`（`validate_export.py:237-248`），确认停牌日仍无 bar。

成本估计：**中**。SDK 侧耗时无法从现有证据外推（现有 86 批 × 50 码 × 2 窗共 19 分 27 秒，覆盖 4,252 码 × 2 个半年窗；退市股要拉 12 年历史，单码数据量约为现有窗口的 20 倍）。按 `kline.py:127` 的 `fetch_batch` 分批能力，200 码可 4 批完成，但单批时长与 SDK 限流未知。落盘体积按 dev 现有 5,215 文件估算约 2–5 GB。**必须先做 3 码试跑并计时**。

风险：
- 会新增 parquet 文件，但**不影响 v12**（v12 的 `raw/` 是副本，`raw_read_statistics.json` 已冻结每码 source_sha256）。只在未来重建 prepared 输入时才会生效。
- 退市股末段可能因"退市整理期停牌"出现 `delistdate` 与实际末根 bar 差 20–50 天（实测 5 只：`000982.SZ` 差 52 天、`000971.SZ` 50、`600565.SH` 47、`002435.SZ` 45、`000150.SZ` 43）。这是真实情况，不是补缺失败。
- **不要在 dev 与 prd 同时跑**，两库共享 SDK 连接池，且 `KlineDayUpdatePipeline` 用 `mkdir` 原子锁。

### 3.3 方案 C：把"999 = 无涨跌幅限制"变成显式语义（成本小）

事实：`canonical_state_v3.parquet` 里 `high_lmt_rate=999` 共 1,833 行 / 370 码，**全部是创业板（1,006）+ 科创板（827）**，`high_limited=0`，且**每一行都落在该码上市后第 1~5 个交易日**（实测 day1=363、day2=366、day3=367、day4=367、day5=370，无一行 beyond day5）。这与注册制新股上市前 5 日不设涨跌幅的规则完全吻合。

所以 999 不是"数据缺失"，是 **SDK 用 999 表达"当日无涨跌幅限制"**（`docs/AmazingData开发手册.md:813` 只写"涨停价上限"，未解释 999）。当前 `derive_execution_state()`（`staged_production_inputs.py:74-77`）用 `_positive(upper) and _positive(lower)` 判 `limit_known`，把 999/cents=0 判成 unknown，是**语义解读缺失**，不是源头缺数。

方案：在映射层加一条显式规则——`high_lmt_rate == 999.0 && high_limited == 0` → `limit_known=True, limit_state="no_limit"`, 绝对限价置 None 但语义明确。**需要 owner 先书面确认 999 的官方语义**（本报告只能给统计证据，不能给供应商字段证书）。

风险：若 999 在别的板块/场景有其它含义，会把真正的未知误标成"无限制"。实测本库 999 只出现在双创板新股前 5 日，但**不能外推到其它年份/板块**。

### 3.4 方案 D：补 `是否暂停上市`（源头无，成本大且不可靠）

`history_status.是否暂停上市` 是人工列（`history_status.py:14-16`）。当前只覆盖 13 只硬编码区间（`backfill_paused_listing.py:40-54`）。

若要扩到全历史：

1. 从交易所公告/巨潮逐事件取证（`docs/research/20261026/INDEPENDENT_AUDIT_REPORT_20261027.md` 记录的 PDF 下载 + SHA 流程）。
2. 按 `trade_calendar` 展开为逐日行，用 `scripts/backfill_paused_listing.py --codes <code> --dry-run` 先验计数。
3. 每次新增都必须留下公告 PDF + SHA，否则不能作为 PIT 证据。

成本：**大**（每只码需人工/半自动取证）；风险：**高**（人工区间一旦错，会把正常交易日标成暂停上市，直接污染状态机）。

**建议不补**，改为在 cnn 侧把"暂停上市"降级为"无 bar 且 `is_susp_sec` 也未标记 → `unexplained`"，并保留为 INCOMPLETE 的显式失败项。

### 3.5 方案 E：`301020.SZ` / `688789.SH` 的 10 条 `verified_states=null`（成本小，可忽略）

这 10 条是 `pre_listing`（`listdate` 分别为 2021-07-06 / 2021-07-08，gap 日期 2021-06-30~07-07），SDK 整段返回 0 行所以既有 bar 也无 status。**已由 `_absence_reason` 正确归因为 `pre_listing`**，无需补数。若要求"零 unknown"，只需让 coverage 计数器接受"pre_listing 且无 state"为已知。

### 3.6 方案 F：公司行动登记日（成本小，只补语义）

不改 `dividend` 表，改**消费侧过滤**：

1. 只消费 `方案进度='3'`（或等价 `股权登记日 is not null`）的行作为"已实施事件"；
2. 对 `进度 in ('1','2','4')` 且金额>0 的行标 `pending_no_dates`（2025 全库 4,252 条，其中 4,250 有进度=3 兄弟行可解析出真实日期）；
3. 对 `301139.SZ`/`689009.SH` 这 2 条无兄弟行的，明确标 `pending_unimplemented`，不要猜日期。

**不重跑 SDK**（源头本来就是空），成本小，风险低。

## 4. 属于永久缺失（无法从源头补）

| # | 内容 | 证据 | 理由 |
|---|---|---|---|
| 1 | 停牌日的真实 bar | 随机抽 200 条 gap，源头 bar 命中 0；1,534 停牌对 DB `是否停牌=1` 100% 命中 | 停牌日本无成交，任何"补 bar"都是伪造 |
| 2 | 上市前 / 退市后 / 暂停上市期间的 bar | 59,491 + 251 条 gap 与 `listdate`/`delistdate` 逐条一致；394 条暂停上市日与 DB 人工行逐条一致 | 证券未在交易，无行情可补 |
| 3 | SDK 的"是否暂停上市"字段 | `history_status.py:14-16`「API 无此字段」；`factor.py:41` 同 | 供应商不提供，只能人工公告取证（13 只以外即缺） |
| 4 | `history_status` 2014 年以前的行 | `select min(交易日期)` = 20140102；2014 前计数 0 | 供应商历史状态数据起点即 2014（`history_status.py:65` docstring「数据源最早只覆盖 2014 年」） |
| 5 | 双创新股前 5 日的**绝对**涨跌停价 | 999 行 `high_limited=0`、`rate=999` | 交易所当日不设限价，不存在"绝对限价"这个数（不是缺失，是无定义） |
| 6 | 退市整理期最后 20–50 天的 bar（已退市码） | 5 只实测末根 bar 早于 `delistdate` 43–52 天 | 退市整理期停牌，交易所无成交 |
| 7 | `dividend` 未实施方案的登记日 | 229 条空行金额全为 0，`进度='3'` 的 42,632 行零空 | 方案未实施，该字段在源头本就不存在值 |

## 5. 与 v12 冻结的关系（不做任何改动）

- v12 manifest 与 `SOURCE_HASHES_FINAL.json` 的 16 文件 pin **本次未触碰**。所有 SQLite 打开均为 `mode=ro` + `PRAGMA query_only=ON`；所有 parquet 均为 `pq.read_table`/`ParquetFile` 只读；HDF 用 `pd.HDFStore(..., "r")` 只读。
- 本报告中所有"补缺方案"若要落地，**必须生成新 generation**（v13 或独立目录），并重新出 manifest + SHA 清单，不得原地重写 v12。
- 若只做方案 A（标签重分类），可以完全不重跑 quant、不改 v12 数据文件，只生成新的 coverage/gap 派生文件。

## 6. 未找到 / 未能确认的项

1. **999 的官方语义证书**：项目内 `docs/AmazingData开发手册.md:813` 只写"涨停价上限"，未定义 999。全部 1,833 行 999 落在双创新股前 5 日的统计规律是本次独立发现，**没有供应商文档或交易所规则原文指向**。需 owner 向供应商确认后才可当 known。
2. **`600240.SH` 的 kline 文件为何早于 delistdate 13 天结束**（末 bar 2020-01-23 vs delist 20200205）：未找到逐日解释，可能为退市整理期停牌或最后一笔交易日差异，未进一步核查。
3. **`000585.SZ`（`is_listed=1` 但已 `delistdate=20220524`）**：`stock_basic` 状态位自相矛盾，无 kline 文件。是否应算"漏更"还是"数据源状态未更新"，未找到证据；建议由 owner 单独核对。
4. **SDK 对已退市码返回历史日线的实测证据**：只有 `600240.SH` 一个间接样本（文件存在且到 2020-01-23）。`preflight_v1/probe_result.json` 只测了 `000151.SZ`/`600519.SH` 两只在市码（`sdk_probe_worker.py:11` `CODES`）。因此方案 B 的"可补"是**基于间接证据的推断，未直接验证**。
5. **仓根下 `quant_data_pre.db` / `quant_data_test.db` / `quant_data_test_bak.db` 三个旧库**本次未查：`src/utils/path_config.py:69-78` 定义 `ENV_ALIASES={"test":"dev","prod":"prd"}`、`RETIRED_ENVS={"pre"}`，三者均不在生产读写路径（`db_path` 只认 `dev/quant_data_dev.db` 与 `prd/quant_data_prd.db`）。
6. **W1 的 29,029 条"非宇宙码 pre_listing"**：这 238 只码 `listdate >= 2021-07-01`（W1 期末后），属 assemble 阶段的机械展开，但**是否为预期行为未找到设计文档确认**（`assemble_state_v3.py` 注释只写"per-window 日期集"，未说明为何用全 F4 并集而非窗口内码集）。

## 7. 报告文件

`C:/Users/yanwen/AppData/Local/Temp/opencode/quant_source_audit_20261030.md`
