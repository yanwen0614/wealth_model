# CNN 策略实验交接 — 2026-10-31

> 只写「做实验需要知道什么」。所有数字为 2026-10-31 实测；未实测的标「假设」。
> 开工前必读：`docs/research/review_20261030/00-必读/下一次实验必读.md`

---

## 0. 现状一句话

**目标未达成**：没有策略通过「税后收益非负 + 跑赢沪深300 + 每日持仓 ≤10」联合验收。
26 条历史路线全灭已归档，不要重启（`docs/research/review_20261030/00-必读/五个问题白话回答.md` §3）。

**当前工作方式**：用 **2026-09 及以前的历史数据做滚动回测**，验证「有效参数的邻域参数也有效」。
暂不用 2026-10 及以后的新数据（数据也不够，见 §3.1）。

---

## 1. 三个仓

| 仓 | 路径 | HEAD | 作用 |
|---|---|---|---|
| cnn | `D:\code\cnn_full_20260905\cnn` | `3f78894` | 模型训练 + 回测适配层 |
| backtest-core | `D:\code\cnn_full_20260905\backtest-core` | `1f0c83f` | 回测引擎（三仓共享） |
| quant | `D:\code\quant` | `e4b4814` | 数据仓储与导出 |

三仓均已推送，工作区干净。`wheels/backtest_core-0.1.1-py3-none-any.whl` 是**同一份构建**
（sha256 `bbb061c2…`）。`stop_after_close` 已从 core 接到 cnn 的 `run_staged_window()` 与
CLI `--stop-after-close`（`backtest/cnn_adapter/staged_candidate_runner.py`）。

回测测试已迁出新框架，**全量测试不再需要任何环境变量**（见 §5.1）。

---

## 2. 数据资产

### 2.1 行情（已到 2026-10，不是历史文档写的 09-30）

| 数据 | 路径 | 最新日期 | 文件数 |
|---|---|---|---|
| 个股日线（原始价） | `Z:\prd\kline\day` | **2026-10-23** | 5,228 |
| 个股日线（后复权） | `Z:\prd\kline_adj\day` | **2026-10-22** | 5,228 |
| 沪深300 日线 | `Z:\prd\kline_index\day\000300.SH.parquet` | **2026-10-19** | 833 |
| 因子产物 | `Z:\prd\alpha_factor` | 2026-10-22 | 5,228 |
| 关系库 | `Z:\prd\quant_data_prd.db`（4.87 GB） | 2026-10-23 | — |

`Z:` 是 UNC 网络盘 `\\192.168.0.123\quant-data`。

### 2.2 训练数据 parquet（两代并存，别用错）

| 文件 | 行×列 | 时间范围 | 说明 |
|---|---|---|---|
| `Z:\test\train_data\train_data_v1_F60_20130101-20260831_26c3db036a26.parquet` | 12,254,385 × **70** | 2013-01-04 ~ **2026-08-31** | **cnn 默认**（`config/defaults.py:10`）。比旧版多 12 个两融因子列 |
| `data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet` | 11,413,377 × 58 | ~2025-12-31 | 旧版，`logs/KEEP/baseline/config.json` 指向它 |

F60 比旧版多 12 列：`margin_*_raw` / `margin_*_ts` / `short_*_raw` / `short_*_ts`。
`APPROVED_RAW_FEATURES`(52) 全部存在于 F60，无缺失。

### 2.3 生成方式

`D:\code\quant\scripts\export_training_data.py`，参数 `--start/--end/--env/--out`。
因子清单 `EXPORT_FACTORS`（60 个），产物 = 复权K线 + 股本as-of + 60因子 + is_trading。

---

## 3. 为什么现在还不用 2026-10 的数据

### 3.1 可算标签日不足（已实测）

标签口径 `future_ret[t] = open[t+1+10]/open[t+1]-1`（`data/labels.py` `_future_ret_open_open`，H=10），
一个信号日需要 t+11 个交易日的数据。

用 A 股交易日历（`trade_calendar` 的 SSE/SZSE）倒推：

| 想要的可算标签日 | 个股数据需覆盖到 | 指数数据需覆盖到 |
|---|---|---|
| 1 个 | 2026-10-23（**已达成**） | 2026-10-19（**未达成**） |
| 5 个 | 2026-10-29 | 2026-10-29 |
| 10 个 | 2026-11-05 | 2026-11-05 |
| 20 个 | 2026-11-19 | 2026-11-19 |

当前实测：个股 2026-10-23、指数 2026-10-19。按指数口径 → **0 个可算标签日**；
按个股口径 → 1 个（10-08）。

**结论**：不是「永远开不了考」，而是样本量太少、没有统计意义。故本轮不用 10 月数据。

### 3.2 重导训练数据也受阻（原因已定位）

`export_training_data.py` 重导到 10 月实测失败：

```
ValueError: self-check 失败：因子整列NaN（非白名单） pe
```

根因：

- 财务源表（`balance_sheet`/`income`/`cash_flow`）**本身齐**，公告日期到 2026-10-24
- 但导出读的 `Z:\prd\alpha_factor` 里 `pe` **全空**（2026-10-31 复抽 10 只，`finite_pe` 全为 0）
- 对照：F60 训练数据里 `pe` 有 11,022,351 个非空值 → 历史上曾完整，**现在这代产物坏了或未重算**

**假设**：需由 quant 的 `flows/quant_feature.py` 重算财务因子才能恢复导出。
**影响范围**：只影响「把训练数据延伸到 10 月」。本轮用历史数据做滚动回测，不受阻。

---

## 4. 下一步：滚动回测 + 参数邻域验证

### 4.1 核心判据（这是本轮的定义）

一个参数「有效」**不算数**，必须满足：

1. 主参数在样本外回测中跑赢沪深300（税后）
2. **该参数的邻域参数也有效**（如 `top_n=10` 有效，则 8/9/11/12 也应有效）
3. 邻域内不能出现符号翻转（正收益 → 负收益）

单点最优一律视为过拟合。这是对历史 26 条路线的直接教训。

### 4.2 现有工具（都已核实存在）

| 用途 | 命令/路径 | 说明 |
|---|---|---|
| 滚动信号生成 | `scripts/generate_walkforward_signals.py` | 参数 `--checkpoint --parquet --calendar --decision-start --decision-end --out-dir` |
| 回测（双模式） | `scripts/run_backtest.py` | `--mode rolling` / `--mode target`，参数见下 |
| 全流程评估 | `scripts/run_eval_pipeline.py` | — |
| 多 seed 训练 | `scripts/multi_seed_train.py` | `--seeds 42,123,2024`，含 λ 抖动 |
| 三分评估 | `scripts/eval_three_way.py` | val/test 严格分离 + 阈值样本外校准 |

`run_backtest.py` 关键参数（target 模式）：
`--target_size`（默认100，买入带名次带宽）、`--sell_buffer`（默认500）、
`--exit_on_nonpositive`、`--exit_threshold`、`--strong_buy_threshold`、`--min_edge`、
`--topn`（rolling 模式，可传多个做对比）。

### 4.3 缺口：没有参数扫描入口

**已核实：仓库里没有任何批量参数扫描脚本**（`scripts/` 下 17 个脚本均无 grid/product 循环）。
要做邻域验证，需要自己写循环——建议外层脚本调 `run_backtest.py`，或直接调
`run_cnn_backtest()`（`backtest/cnn_adapter/runner.py:117`）。

### 4.4 执行顺序

1. **定基线**：选一个已知最优参数点（如 `target_size=100, sell_buffer=500`），跑滚动回测
2. **扫邻域**：对该参数的每个维度取 ±2 档（如 `target_size ∈ {50,80,100,120,150}`）
3. **看平台**：有效参数应落在一片「高原」上，不是孤立尖峰
4. **记录口径**：费用、滑点、基准、持仓上限（≤10）全程冻结，中途不得改

### 4.5 必须遵守

- 每个参数组合都要报告**同期沪深300**对比，不能只报绝对收益
- 持仓峰值必须 ≤10（`_MAX_HOLDINGS = 10` 已硬编码在 `target_strategy.py:54`）
- 滚动窗口必须有明确的 buffer，不可用未来数据
- 一旦发现某参数只有单点有效，直接判定为过拟合，不再深挖

---

## 5. 必须知道的坑（都实测过）

### 5.1 全量测试：无需任何环境变量

```powershell
uv run --project . python -m unittest discover -s tests -t . -q
```

真基线：**1013 项 → 2 failures / 10 errors / 40 skipped**。
`LegacyBacktestDisabledError` 出现 **0 次**（2026-10-31 已完成迁移）。

- 2 failures = `test_prefix_attestor` / `test_prefix_ledger_verifier` 的 pin 不符，**故意保留，禁止修绿**
- 10 errors = 独立既有缺陷，与回测引擎无关：plotly 缺失(2)、Windows 文件锁(2)、
  `train.py` KeyError 'CNNTransformerConfig'(2)、`RelativeScaler.identity_hash`(1)、
  trainer/torch API(1)、config/retail 滞后(2)

回测测试分层：`test_engine.py` 是**空索引文件**（0 测试，注明迁移去向）；
实际覆盖在 `test_metrics_and_benchmark.py`（费率/指标 parity/指数基准）、
`test_cnn_adapter_rolling_semantics.py`、`test_cnn_adapter_target_semantics.py`、
`test_cnn_adapter_regression.py`。

### 5.2 quant 在 Windows 跑测试需三个前置

1. `fcntl` 缺失（`src/utils/auth.py:4`、`src/core/model_bridge/feature_cache.py`）→ 注入进程内桩
2. 必须设 `QUANT_REPO_ROOT`，否则 17 个 q02/q04 用例假失败
3. 跑导出还需 `QUANT_DATA_ROOT=Z:\` 与 `QUANT_DB_ENV=prd`

```python
# 前置桩（写进临时脚本，sys.path 需含 D:\code\quant）
import sys, types
if sys.platform == "win32" and "fcntl" not in sys.modules:
    m = types.ModuleType("fcntl")
    m.LOCK_EX, m.LOCK_SH, m.LOCK_NB, m.LOCK_UN = 2, 1, 4, 8
    m.flock = m.lockf = m.ioctl = lambda *a, **k: None
    sys.modules["fcntl"] = m
```

设好后 `tests/unit/backtesting` = **390 passed / 3 skipped**。

### 5.3 wheel 升级三件套（升级 backtest-core 时才相关）

1. **同名 wheel 会被 uv 缓存命中** → 必须 bump 版本号后才 `uv build`
2. **`uv lock` 会刷镜像源** → 直接把 tsinghua 批量改成 pypi.org（core 113 行 / quant 1035 行
   无关 churn）。正确做法：`git checkout -- uv.lock` 后手工改 backtest-core 那 4 行
   （version / path / filename / hash），再 `uv sync --frozen` 验证
3. **`wheels/.gitignore` 内容是 `*`** → 新 wheel 必须 `git add -f`，否则 pyproject 指向的文件
   不在仓库里（全新 checkout 会挂）。另：`uv sync --frozen` 会卸掉不在 dev 组的 pytest，
   需 `uv pip install pytest pytest-asyncio` 装回

### 5.4 默认参数 ≠ 旧 baseline

| 项 | 现行默认（`config/defaults.py`） | `logs/KEEP/baseline/config.json` |
|---|---|---|
| HORIZON | **10** | 5 |
| BINS | `linspace(-0.38, 0.38, 51)` | `-0.25 ~ 0.25` |
| NORMALIZE | relative | per_code |
| featurenum | 80（52 raw + 1 mask + 16 cs + 11 mkt） | 45 |
| LR / BATCH | 3e-4 / 256 | 1e-4 / 512 |

`logs/KEEP/baseline/best_model.pth` 是 **F=45 / per_code / H=5 旧基线**，不能直接用于现行 F=80。
`logs/KEEP/` 下 4 个 scaler pkl 身份见 `G:\backups\cnn_full_20261030\scalers_KEEP\SCALER_IDENTITIES.json`。

### 5.5 强买门槛的现金口径：新旧引擎不可比（真问题，未修）

`backtest/cnn_adapter/target_strategy.py:348` 预算 = `可用现金 / 当日成交家数`，
被 `strong_buy` / `min_edge` 跳过的槽位，现金会分摊给成交者。
旧引擎 `engine.py:400` 是 `nav / target_size` 每槽固定，跳过即留现金。

实测（target_size=5、3 只被跳过）：旧引擎留 60% 现金，新策略留 **0%**。

影响：`docs/agent/task/agent_task_conclusions.md` §3 的「现金比 14–33%」结论出自旧引擎，
**与当前 adapter 口径不可直接比较**。已在该文档加口径警示。用 `strong_buy` 做实验时务必注意。

---

## 6. 红线

1. 不重签 pin、不把报错测试改绿凑数
2. 不重跑 W1 求收益（缺登记获配证据，只能报条件情景）
3. 不在 2026-01~08 烧样本上验收
4. 不用 20 只持仓（硬约束 ≤10）
5. 不加回方向择时门（已有三类独立负向证据）
6. 不猜丢失文件内容、不把「无法评价」写成「可评价」
7. **不把单点最优当结论**（这是本轮的核心判据，见 §4.1）

---

## 7. 关键文件索引

| 用途 | 路径 |
|---|---|
| 开工前必读（强制） | `docs/research/review_20261030/00-必读/下一次实验必读.md` |
| 26 条路线失败盘点 | `docs/research/review_20261030/00-必读/五个问题白话回答.md` §3 |
| 最终交付与验收状态 | `docs/research/final_delivery_20261030.md` |
| 数据缺口真相 | `docs/research/review_20261030/20-专项审计/quant_source_audit_20261030.md` |
| 训练数据股票问题 | `docs/research/review_20261030/20-专项审计/train_data_stock_audit_20261030.md` |
| 八项不可复现判定 | `docs/research/review_20261030/20-专项审计/fill_gap_analysis_20261030.md` |
| 归一化决策唯一事实源 | `docs/per_code_normalization_spec.md` |
| 历史任务结论汇编 | `docs/agent/task/agent_task_conclusions.md` |
| 训练入口 | `train.py` |
| 回测入口 | `scripts/run_backtest.py` |
| 滚动信号 | `scripts/generate_walkforward_signals.py` |
| 分批回测 | `backtest/cnn_adapter/staged_candidate_runner.py` |
| 数据导出 | `D:\code\quant\scripts\export_training_data.py` |
| P0 冷备份 | `G:\backups\cnn_full_20261030\` |
| 外置证据（14.0 GB） | `D:\code\cnn_full_20260905\evidence_tmp_20261030\` |
| 结论性报告归档（223 份） | `docs/archive/temp_reports_20261031/` |

---

## 8. 建议技能

| 场景 | 技能 |
|---|---|
| **任何 cnn 代码改动** | `quant-model`（兼容别名 `cnn-harness`）—— 3-agent 流水线 + 质量门 |
| 排查「跑不通/结果不对」 | `systematic-debugging` —— 先定位再改 |
| 隔离实验分支 | `using-git-worktrees` |
| 多个独立调研并行 | `dispatching-parallel-agents` |

**只推进实验、不改代码** → 不用加载技能，按 §4 做，但先读 §7 第一行那份必读文档。

---

## 9. 未验证的假设

1. **假设**：`alpha_factor` 财务因子全空是「这代产物未重算」而非永久损坏 —— F60 里同名字段曾完整，但未找到重算入口或责任人确认。
2. **假设**：`kline_index` 比个股慢 4 个交易日是采集节奏差异而非断供 —— 只看到日期差，未查采集日志。
3. **假设**：`Z:\prd\model_features`（5,100 文件，2025-11 ~ 2026-08）是模型侧特征缓存 —— 只看了单文件结构，未追调用方。
4. **未验证**：F60 的 12 个新增两融因子列是否应进 `APPROVED_RAW_FEATURES` 的 52 列口径 —— 只确认 52 列都存在，没确认新 12 列是否该启用。
5. **未验证**：参数邻域「高原」的判定阈值（多宽算宽、多平算平）尚无标准，需本轮实验后固化。
