# 已放弃路线死代码删除计划（2026-10-30）

性质：**诊断（diagnosis only）**。本文件写完时尚未删除任何文件。
依据：`docs/research/review_20261030/10-五问探索/q1_failed_research_report.md`（14 条彻底放弃路线的代码载体）。
Owner 口径：结论保留，相关代码可以删。

## 0. 红线自查（本计划的硬约束）

| # | 红线 | 本计划处置 |
|---|---|---|
| 1 | 只删代码不删结论；`docs/` 下 `.md` 一律不删不改 | 删除清单中**无任何 `docs/` 路径**，无任何 `.md` |
| 2 | 不动主链路 `data/ training/ models/ backtest/cnn_adapter/ config/defaults.py criterion/ train.py train_retail.py` | 删除清单中**无以上任一路径**（`criterion/gate_loss.py` 属主链路门控头，保留） |
| 3 | 不动冻结快照 `scripts/frozen/`、`research/goal/`，列入清单等 owner | 二者仅出现在下表"待定"段，不删 |
| 4 | 删前全仓 Grep；被保留代码/保留测试引用的一律不删 | 见第 2 节，逐个文件的引用扫描结果 |
| 5 | 禁 `git add -A`；提交只用显式路径；不 push；不 stash/reset/checkout/clean | 提交用 `git rm` + 显式 `git add` 路径 |

## 1. 引用检查方法（可复现）

1. 语料 = `git ls-files` 全部**已跟踪**文本文件（`.py/.md/.toml/.yml/.sh/.ps1/.json/.txt/.csv` 等），排除未跟踪的
   `docs/research/review_20261030/recovered_w1_20261030/`（另一代理写的只读补丁快照，不属于仓库内容）。
2. 对每个候选文件生成 3 类查询串，全部做**完整串匹配**（非词边界、非 basename），避免 `models`/`dataset`/`train`
   这类通用名假命中（首轮用 basename 词边界口径时确实出现了大量假阳性，已废弃该口径）：
   - 完整仓库路径：`research/m_research/scripts/m06_gate.py`
   - 模块点路径：`research.m_research.scripts.m06_gate` / `scripts.eval_retail_predict` / `paper_jkx.src.train`
   - 仅对脚本类文件追加裸模块名（`paper_jkx` 目录前缀查询需排除自身目录）
3. 结果按 `code`（`.py/.sh/.ps1`）、`md`、`other`（`.toml/.yml/.json/.csv`）三档分类；**判定只认 `code` 档**。
   `docs/` 与 `.md` 是结论载体，不构成"被保留代码引用"。
4. 二次交叉验证：`git grep -n <path|module> -- '*.py' '*.ps1' '*.sh' '*.toml' '*.yml' tests` 单独再跑一遍。

**基线（删前实测）**
- `uv run python -m ruff check .` → `Found 284 errors`，284 项**全部**落在未跟踪的
  `docs/research/review_20261030/recovered_w1_20261030/**`（干净 checkout 里不存在）。
- `ruff check . --extend-exclude=docs/research/review_20261030` → `All checks passed!`（= CI 真实口径基线）。
- CI 最小门 `tests.unit.test_ci_gate + data.test_identity + data.test_transform_kernel +
  training.test_training_preprocessing + data.test_dataset_cache` → `Ran 58 tests ... OK`。

## 2. 候选逐条判定

### 2.1 删除（30 个文件，合计 168,756 字节）

判定同时满足：① 只服务于某条彻底放弃路线；② `code` 档引用为 0（无保留代码/保留测试引用）；③ 不在红线目录。

| 路径 | 所属路线 | 已跟踪 | 被谁引用（Grep） | 判定 | 理由 |
|---|---|---|---|---|---|
| `paper_jkx/src/__init__.py` (73) | #14 JKX 七路 | 是 | code 0；md 仅工程任务文档泛称 | 删 | JKX 图像线整体关闭，包内仅被同目录文件引用 |
| `paper_jkx/src/backtest.py` (3,603) | #14 | 是 | code 0（`scripts.run_backtest` 是本仓库同名不同文件，非本文件）；md = paper_jkx/README | 删 | JKX 专用 preds→npz 转换 |
| `paper_jkx/src/bottom_filter.py` (7,597) | #14 七路之"bottom 过滤" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法之一，报告判定恒等无效 |
| `paper_jkx/src/build_cache.py` (6,754) | #14 | 是 | code 0 | 删 | JKX 成图缓存构建 |
| `paper_jkx/src/conf_weight.py` (17,433) | #14 七路之"确信度加权" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法（±1pp 边际） |
| `paper_jkx/src/dataset.py` (6,851) | #14 | 是 | code 0（仅被同目录 build_cache 引用，该文件同批删）；**注意**：与主链路 `data/dataset.py` 同名不同文件，首轮 basename 扫描的 90+ 命中全部是该假阳性 | 删 | JKX 成图索引 |
| `paper_jkx/src/eval_predict.py` (2,391) | #14 | 是 | code 0；md = paper_jkx/README、STATE_FREEZE | 删 | JKX 推理 |
| `paper_jkx/src/gate_backtest.py` (7,567) | #14 七路之"空仓门" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法（❌ 全灭） |
| `paper_jkx/src/hedge_backtest.py` (3,565) | #14 七路之"对冲" | 是 | code 0；md = paper_jkx/README | 删 | A 股不可执行 |
| `paper_jkx/src/imaging.py` (9,824) | #14 | 是 | code 0（仅被同目录 build_cache 引用，同批删） | 删 | K 线成图 |
| `paper_jkx/src/lowfreq_backtest.py` (7,664) | #14 七路之"降频" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法（净负） |
| `paper_jkx/src/models.py` (2,514) | #14 | 是 | code 0（`models` 泛名假阳性已按完整路径复核为 0） | 删 | 2D-CNN 二分类网络 |
| `paper_jkx/src/regime_analysis.py` (8,628) | #14 七路之"切换" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法（❌） |
| `paper_jkx/src/report_nav.py` (2,244) | #14 | 是 | code 0；md = paper_jkx/README、STATE_FREEZE | 删 | JKX 回测报告 |
| `paper_jkx/src/train.py` (15,901) | #14 | 是 | code 0（`train` 泛名假阳性已排除；主链路 `train.py` 是另一个文件） | 删 | JKX 训练入口 |
| `paper_jkx/src/vol_scale.py` (7,557) | #14 七路之"波缩" | 是 | code 0；md = paper_jkx/README | 删 | 七路抢救改法（❌） |
| `research/market_neutral/scripts/s3_neutral.py` (2,455) | #17 market_neutral | 是 | code 0；md = 同目录 README | 删 | 纸面多空脚本；引擎 long-only 无空头，路线整体判不可交易 |
| `research/m_research/scripts/m01_baseline.py` (3,276) | #7 m_t 方向/幅度 | 是 | code 0 | 删 | 方向基线（12 方法之一） |
| `research/m_research/scripts/m02_linear.py` (3,337) | #7 | 是 | code 0 | 删 | 线性方向方法，R² 全负 |
| `research/m_research/scripts/m03_gbdt.py` (4,230) | #7 | 是 | code 0 | 删 | GBDT 方向方法 |
| `research/m_research/scripts/m04_dl.py` (4,839) | #7 | 是 | code 0 | 删 | DL 四架构方向方法 |
| `research/m_research/scripts/m06_gate.py` (3,635) | #6/#7 市场方向门 | 是 | code 0 | 删 | 方向门控信号生成（滞后一日门） |
| `research/m_research/scripts/m06b_gated.py` (1,123) | #8 双塔方向门 | 是 | code 0 | 删 | 门控版 preds 落盘 |
| `research/m_research/scripts/m07_precision.py` (1,079) | #7 | 是 | code 0 | 删 | 方向信号 precision-coverage（m 线，非 #5 的 precision 规则包） |
| `research/m_research/scripts/m08_asymloss.py` (1,965) | #7/#24 | 是 | code 0 | 删 | 非对称 loss 抬方向天花板，已证无效 |
| `research/m_research/scripts/dt_combine.py` (3,171) | #8 双塔方向门 | 是 | code 0 | 删 | α/m 双塔组合（门控空仓）；报告判定证伪 |
| `research/m_research/scripts/dt_preds.py` (1,534) | #8 | 是 | code 0 | 删 | 双塔门控 preds 落盘（含 `preds_dualalpha_2025{,_gate}.npz`） |
| `scripts/eval_retail_predict.py` (8,059) | #16 单票 75% 胜率 | 是 | code 0；仅 pyproject.toml:138 注释提及"已修"，非导入 | 删 | 零售模型推理→preds 缓存，仅服务 75% 研究 |
| `scripts/run_retail_backtest.py` (16,878) | #16 | 是 | code 0；md = docs/archive/000_INDEX.md、一份任务 REVIEW_CHECKLIST | 删 | 零售综合评分选股回测（75% 路线产物） |
| `scripts/launch_retail_train.ps1` (3,009) | #16 | 是 | code 0 | 删 | 零售训练后台启动器 |

> 保留：`paper_jkx/README.md`、`paper_jkx/STATE_FREEZE.md`（结论与方法对照表）、
> `research/market_neutral/README.md` + `artifacts/*.json`（结论与小产物）、
> `research/m_research/REPORT.md` + `artifacts/*`（结论与 csv/json 结果）。
> 即"删脚本，留结论与数值"。

### 2.2 待定（不删，等 owner 定夺，附原因）

| 路径 | 所属路线 | 被谁引用 | 判定 | 不删原因 |
|---|---|---|---|---|
| `scripts/frozen/*`（9 文件） | 旧 h10 rolling 集成/投票/减半 | 文档多处 | 待定 | 红线 3：ruff exclude 的只读快照，先不动 |
| `research/goal/**`（93 文件） | #11 goal 旧线 / #13 每日触发 / #15 冻结A | 文档 | 待定 | 红线 3：READ ONLY 冻结快照 |
| `research/goal_repro/**`（6 文件） | #12 高换手 rolling（弃）+ target s100/惯性（**条件保留**） | 自身 PLAN/REPORT；`r2/r3` 互相 import `common` | 待定 | **同一脚本内混合**：`r2` 同时跑 rolling top10/50（弃）与 target s100/buf500（保留线索）；删则连带删掉保留线索的载体 |
| `research/m_research/scripts/m00_build.py` | 数据构建（共用） | 无 code 引用 | 待定 | 保留路线 #9 的 `dt_vol/m05_risk` 依赖其产物 `m_daily.parquet` |
| `research/m_research/scripts/m05_risk.py` | #10 regime（弃）**+ #9 波动（保留）** | 无 code 引用 | 待定 | 单文件混合：KMeans regime 与波动/尾部同处一脚本 |
| `research/m_research/scripts/dt_build.py`、`dt_alpha.py` | #8 双塔（弃）+ α 塔（保留线索） | 无 code 引用 | 待定 | `dt_combine_vol/dt_vol_boot` 依赖 `dt_alpha` 产物 `dt_alpha_oos.npz`，删则断掉保留路线的输入链 |
| `research/m_research/scripts/dt_vol.py`、`dt_combine_vol.py`、`dt_vol_boot.py` | #9 波动缩放（**条件保留**，research/README 待验收队列第 1 项） | 无 code 引用 | 待定 | 路线未被放弃 |
| `research/precision/**` | #5 precision 规则包（**条件保留**） | 自身 README | 待定 | 未放弃，在待干净样本验收队列 |
| `research/alpha_attribution/**`、`research/unified_recalc/**` | 归因/口径纠偏（**正向方法资产**） | 自身 README、`scripts/signal_diagnostics.py` 引用 `common_dates.json` | 待定 | 非放弃路线 |
| `scripts/analyze_preds.py` (21,063) | #1 52 类 / #16 75% | 无 code 引用；`docs/ENGINE_MAP_2026.md` §2 列为"生产评估"脚本 | 待定 | **活文档把它归为生产评估**，删会与不可改的文档冲突；请 owner 定夺（若要删需同步改 ENGINE_MAP） |
| `scripts/eval_three_way.py` (22,455) | #16 75% 阈值校准 | 无 code 引用；`docs/ENGINE_MAP_2026.md` §2 列为"生产" | 待定 | 同上：文档归为生产评估；且其截面 IC/precision 报告能力对后续干净样本验收有用 |
| `criterion/gate_loss.py`、`criterion/pure_reg_loss.py`、`criterion/dual_loss.py` | #6 门控 / #24 损失消融（旧口径） | `criterion/__init__.py`、`training/trainer.py`、`train.py` | **留** | 红线 2（`criterion/` 不动）+ 主链路现役（trainer/ train.py 实际导入） |
| `pyproject.toml:132,138` 注释提及 `analyze_preds` / `eval_retail_predict` | #1/#16 | — | 待定 | 属配置注释，非红线但为避免动配置/锁附带的措辞，本轮不改；`eval_retail_predict.py` 删除后该注释指向已删文件 |
| `_check_signals.py`（仓库根，未跟踪） | 一次性探针 | 无 | n/a | 实体已不存在（`Test-Path` = False），不属本任务 |

### 2.3 明确保留（不是某条放弃路线的专属代码）

| 路径 | 原因 |
|---|---|
| `train.py` / `config/defaults.py`（`--dual_head/--lambda_reg/--pure_reg/--gate_loss_*`） | 红线 2。λ/损失选项是**现行训练入口的可选开关**，非 #3/#24 专属死代码；默认值不得改 |
| `models/retail_friendly/**`、`train_retail.py`、`training/factory.py`、`training/trainer.py` | 红线 2（主链路/零售模型现役，被 3 个保留测试套件导入） |
| `data/`、`training/`、`models/`、`backtest/cnn_adapter/`、`backtest/engine.py`、`backtest/legacy.py` | 红线 2 |
| `scripts/run_2025_restricted.py`、`scripts/run_2025_ab_execution.py` | 属"待重做"路线 #19–#21，不是 14 条放弃路线；且被 `tests/unit/backtest/test_validation_2025_*.py` 引用 |
| `scripts/audit_walkforward_execution.py` | **工作区有 owner 未提交改动**（`M`），非本任务范围 |

## 3. 删除后验证与提交口径

1. 删除方式：`git rm -q <显式路径...>`（逐条列出，不用 `-A`）。
2. 验证：
   - `uv run python -m compileall -q` 覆盖保留目录；
   - `uv run python -m ruff check . --extend-exclude=docs/research/review_20261030`
     （= CI 口径；未跟踪目录不在 checkout 内）另跑一次无 exclude 版记录 284→284 说明；
   - CI 最小门 58 项（`.github/workflows/ci.yml` 同款 5 个套件，`python -m unittest` 等价路径）；
   - 追加 `tests.unit.scripts`、`tests.unit.training`、`tests.unit.criterion`、`tests.unit.config` 回归。
3. 提交：`git add` 仅本次删除涉及的显式路径；message：
   `chore: 删除已放弃路线死代码（14 条，结论见 docs）`；不 push。
4. `git status --short` 全量留档（含 owner 既有的 6 项工作区改动，**不提交它们**）。
