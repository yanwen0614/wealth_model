# PLAN — 测试基线漂移修正 + 回测谱系 H=10 对齐

- task_dir: `docs/agent/task/20261031_1700_test-baseline-drift/`
- tag: `test-baseline-drift`
- base_commit（Phase 0）: `f60955d`
- requirement: 修正三处「代码默认值已演进、测试/常量未跟改」的漂移；全量单测从 2F 恢复为 0F；回测谱系元数据反映真实 H=10 标签口径。

---

## Goal

1. 消除两处陈旧断言失败（`featurenum` 53 vs 80、`cs_rank`/`mkt_factors` False vs True），使全量单测基线从 `2F/10E/40S` 变为 `0F/10E/40S`（10 个 error 为既有环境缺陷，明确不修）。
2. 让回测谱系常量与真实训练标签口径一致：`PREDICTED_HORIZON` 5→10、`LABEL_FORMULA` 同步，使 `provenance.horizon` / `label_formula` / `config_hash` 反映 H=10。
3. 收口 `scripts/run_backtest.py --horizon` 死参数：保留参数但拒绝与谱系常量不一致的取值，避免继续误导为「可配置」。

非目标（明确不做）：修 10 个既有 error；重跑任何回测取收益；改 `data/dataset.py` 的 `horizon` 默认；动 `backtest/engine.py`（legacy 冻结区）；动用户未提交的 `docs/agent/handoff-cnn-experiment-20261031.md`。

---

## Architecture

改动落在三条相互独立的链路上，无跨模块新增依赖：

| 链路 | 事实源（不改） | 陈旧点（本次改） |
|---|---|---|
| 特征维度 | `config/defaults.py:92` `featurenum=80`；`data/schema.py` 52+1+16+11 | `tests/unit/config/test_config_defaults.py:29` 断言 53 |
| 截面开关 | `config/defaults.py:74,76` `CS_RANK=True`/`MKT_FACTORS=True` | `tests/unit/training/test_training_retail_wrapper.py:75-76` 断言 False |
| 回测谱系 horizon | `config/defaults.py:67` `HORIZON=10`；`data/dataset.py:92` `horizon=10` | `backtest/cnn_adapter/predictions.py:41,43` 写 5；`scripts/run_backtest.py:258` 死参数 default 5 |

依赖方向不变：`backtest/` 仍不 import `config/`（`predictions.py` 仅 import `data.schema`），因此新增的「常量 == 配置」一致性由**测试层**验证，不在生产代码里跨层 import。

模块边界：`backtest/cnn_adapter/*` 属 adapter 唯一入口；`tests/` 可同时 import `config`/`data`/`backtest`，不构成反向依赖。

---

## KeyDecisions

### KD1 — 漂移方向：以代码为事实源，改测试；生产默认值不动
`AGENTS.md`「Data Contract」、「Data Contract」条目与 `data/schema.py` 一致声明 `F=80`（52 raw + 1 mask + 16 cs + 11 mkt）为现行默认，F=53/69/45 是历史 schema。因此 T1/T2 只改测试断言，**不改** `config/defaults.py`。实测支撑：`len(APPROVED_RAW_FEATURES)=52`、`len(DEFAULT_CS_RANK_FEATURES)=16`、`len(DEFAULT_MKT_FACTOR_FEATURES)=11`、+1 mask = 80。

### KD2 — T1 断言同时锁「具体值 80」与「派生关系」
只写 `assertEqual(..., 80)` 会让下次 schema 演进再次脱钩；只写派生式又读不出「当前就是 80」。故两条都断言：`== 80`，且 `== len(APPROVED_RAW_FEATURES)+len(G9_MASK_COLUMNS)+len(DEFAULT_CS_RANK_FEATURES)+len(DEFAULT_MKT_FACTOR_FEATURES)`。后者属一次性算术说明，不是重复防御（两式任一漂移都必须失败，正是测试目的）。

### KD3 — T2 必须补 `--no-cs_rank` 对照断言
若只把 `assertFalse` 改成 `assertTrue`，任何人把实现改成「恒 True」也不会被测试发现。故新增对照：显式 `cfg["CS_RANK"]=False`/`cfg["MKT_FACTORS"]=False` 时 `build_parquet_data_config` 必须返回 False（这正是 `--no-cs_rank --no-mkt_factors` 回到 F=53 的路径）。

### KD4 — `PREDICTED_HORIZON` 5→10 是破坏性变更，波及全部历史 `config_hash`（用户已明确接受）
`backtest/cnn_adapter/runner.py:352` 把 `"horizon": PREDICTED_HORIZON` 放入 `_config_hash` 的 payload。常量改动后：
- **算法不动**：`_config_hash`（`runner.py:70`，sha1 of `sort_keys=True` canonical JSON）与 payload 键集合、键顺序语义完全不变，只有 `horizon` 的**值**随之变 5→10。
- **后果**：已存 `logs/bt_*/metrics.json` 的 `config_hash` 与新跑结果不可直接比对；同一窗口新旧结果若要证明「代码变了但数字没变」，不能靠 config_hash 相等，只能靠 `data_fingerprint`（npz 内容哈希，未变）+ 逐日 nav 复算。
- 该破坏性变更是用户显式接受项，不做兼容垫片（不加 `horizon_version`、不加双写），避免留下两套谱系。

### KD5 — `LABEL_FORMULA` 改为由 `PREDICTED_HORIZON` 派生
本次漂移的根因就是「常量改了、公式字面量没改」。故：
```python
LABEL_FORMULA = f"future_ret[t]=open[t+1+horizon]/open[t+1]-1,horizon={PREDICTED_HORIZON}"
```
导出名、类型（`str`）、在 `provenance["label_formula"]` 的透传方式均不变；仅内容随常量联动。收益：同类漂移在结构上不可再发生。

### KD6 — `--horizon` 死参数：选 (b)「保留 + 校验」，不选 (a) 删除
- 实施：`default=5` → `default=None`；`parse_args` 末尾校验：`args.horizon is not None and args.horizon != PREDICTED_HORIZON` → `parser.error(...)`（argparse 惯例，`SystemExit(2)` + stderr 可诊断消息）。
- 理由：
  1. 删除参数会让外部脚本得到 `unrecognized arguments: --horizon 5`，用户无法得知「horizon 已被 adapter 常量锁定」；保留+校验能给出可操作信息（当前唯一允许值）。
  2. `--horizon 10`（与谱系一致）继续被接受，历史脚本可原样跑通；配合 `run_eval_full.sh:76` 把 5 改 10 即可。
  3. 死参数的危害不是「存在」，而是「静默无效」；校验把它变成「显式声明一致或显式报错」，消灭静默。
- 拒绝的方案：`default` 保留 5 只加 warning —— 仍允许静默无效，未解决误导。

### KD7 — 不碰的相邻区域
- `data/dataset.py:92` `horizon: int = 10` 已正确，不动。
- `backtest/engine.py`（legacy 冻结区，`:3,138,210` 的 `horizon=5`）不动。
- `backtest/cnn_adapter/market.py:147` `build_ohlc_path_table(horizon=5)` 与 `scripts/build_ohlc_path.py:76 --horizon 5`：OHLC 路径表已是历史兼容/deprecated 路径（adapter 直读 parquet 真实 OHLC，执行期不使用），不动。
- `scripts/eval_bins_mapping.py:542 --horizon 5`、`scripts/eval_three_way.py:352`、`scripts/run_eval_pipeline.py:24,172,235,359`：这些是**推理/评估侧**的参数，改它们会改变评估标签口径与 BINS 派生，属独立任务（见下「已知不一致」），本次不动。

### KD8 — 10 个既有 error 不修（目标只把 F 从 2 降到 0）
`prefix_attestor`（pin 不符）、`prefix_ledger_verifier`（W1 pin）、`test_data_feature_pipeline`（`RelativeScaler.identity_hash` 缺失）、`log_manager_collision` ×2（Windows 文件锁）、`decile_diagnosis` ×2（plotly 缺失）、`trainer_unified`（torch API）、`training_retail_wrapper` ×2（`KeyError: 'CNNTransformerConfig'`）。均为环境/既有缺陷，`AGENTS.md`「Gotchas」已声明。**注意**：`training_retail_wrapper` 的 2 个 error 与本任务要改的同一文件，改动时不得顺手「修绿」它们——只能改 `test_parquet_helper_passthrough` 一个用例的断言。

### KD9 — 已知不一致（本任务记录但不修，超出三处漂移范围）
`scripts/run_eval_pipeline.py:172` 与 `:235` 在构造评估 `ParquetDataset` 时硬编码 `horizon=5`，若用该脚本产出 preds 缓存，其 `true_ret` 是 **H=5** 标签，而 `PREDICTED_HORIZON=10` 会声明 H=10 —— 这是新增口径不一致的来源。本次处理的 `logs/preds_fullA_2026.npz` 经实测是 H=10（`eval_bins_mapping --horizon 10` 产出路径），与 KD4/KD5 的新声明一致。改 `run_eval_pipeline` 会改变评估标签语义与 BINS 派生，需独立任务 + 独立验收，故**记录为待决事项**（见 Impact「已知不一致」），不纳入本任务批次。若审查认为必须本次处理，应先回退到 Phase 1 修订范围。

### KD10 — 不碰用户未提交的 `docs/agent/handoff-cnn-experiment-20261031.md`
该文件当前为 `M` 状态且有第三方改动，本次任何 commit 都只用显式 pathspec 提交 `task_dir`，不 `git add -A`。

---

## Impact（全仓引用点核查，行号均实测于 `f60955d`）

### A. `PREDICTED_HORIZON` — 生产代码 4 处引用（全部随常量自动生效，无需改）
| 位置 | 角色 | 本任务动作 |
|---|---|---|
| `backtest/cnn_adapter/predictions.py:41` | 常量定义 | **改 5→10**（T3） |
| `backtest/cnn_adapter/predictions.py:141` | `provenance["horizon"] = str(常量)` | 不变（自动变 "10"） |
| `backtest/cnn_adapter/predictions.py:190` | `Prediction.predicted_horizon=常量` | 不变（core 校验 ≥1，10 合法） |
| `backtest/cnn_adapter/runner.py:40,352` | import + `_config_hash` payload | 不变（`_config_hash` 算法/键集不动，仅值变） |
| `backtest/cnn_adapter/__init__.py:14,26` | re-export | 不变 |

### B. `LABEL_FORMULA`
| 位置 | 角色 | 动作 |
|---|---|---|
| `backtest/cnn_adapter/predictions.py:43` | 定义 | **改为派生式，horizon=10**（T3） |
| `predictions.py:141` | `provenance["label_formula"]` | 不变 |
| 代码调用点 | 无（除 provenance 与测试断言） | — |

### C. `horizon=5` 字面量（需同步的地方）
| 位置 | 性质 | 动作 |
|---|---|---|
| `predictions.py:9` | 模块 docstring 口径声明 | **改 10**（T3） |
| `predictions.py:39-40` | 常量上方注释（含 "data.dataset 默认 HORIZON=5"） | **改 10**（T3） |
| `predictions.py:42` | `LABEL_FORMULA` 上方注释 | **改 10**（T3） |
| `predictions.py:197` | `actuals_for_cross_section` docstring | **改 10**（T3） |
| `tests/unit/backtest/test_cnn_adapter_predictions.py:50,164,165` | 锁死 5 的单测 | **改 10**（T3） |
| `scripts/run_backtest.py:258` | 死参数 default=5 | **改 None + 校验**（T4） |
| `scripts/run_eval_full.sh:76` | 唯一 CLI 调用点，传 `--horizon 5` | **改 10**（T4） |
| `backtest/engine.py:3,138,210` | legacy 冻结区 | 不动（KD7） |
| `backtest/cnn_adapter/market.py:147,152`、`scripts/build_ohlc_path.py:76` | deprecated OHLC 路径表 | 不动（KD7） |
| `scripts/eval_bins_mapping.py:542`、`eval_three_way.py:157,352`、`run_eval_pipeline.py:24,172,235,359` | 推理/评估侧独立口径 | 不动（KD7/KD9） |
| `scripts/README.md:3,8,41,139,157` | 已自带「历史快照声明」，且 `:41` 说的是 `train.py --horizon` | 不动（不在本任务范围，见 REVIEW_CHECKLIST「已知陈旧文档」） |

### D. `featurenum` 53 相关
| 位置 | 性质 | 动作 |
|---|---|---|
| `config/defaults.py:92` | `featurenum: 80` 现行事实源 | 不动 |
| `tests/unit/config/test_config_defaults.py:27-29` | 断言 53（实测 FAIL `80 != 53`） | **改**（T1） |
| `tests/unit/training/test_training_retail_wrapper.py:91,113,124` | 显式传 `featurenum=53` 参数（不是漂移，用例通过） | 不动 |
| `tests/unit/data/*`（context_warmup/dataset_cache/rolling_normalization/scaler_*）与 `test_data_schema_labels.py:33` | 均为 `ParquetDataConfig` 默认 `cs_rank=False` 的 F=53 数据集断言，语义正确 | 不动 |
| `tests/unit/scripts/test_eval_preprocessing.py`、`test_train_metadata.py` | 显式构造/传入 53 的夹具 | 不动 |

### E. `cs_rank` / `mkt_factors`
| 位置 | 性质 | 动作 |
|---|---|---|
| `config/defaults.py:74,76` | `True` 现行事实源 | 不动 |
| `train.py:284,286` | `cfg.get('CS_RANK', False)` 透传（cfg 显式 True，故实际 True） | 不动 |
| `tests/unit/training/test_training_retail_wrapper.py:75-76` | 断言 False（实测 FAIL `True is not false`） | **改**（T2） |
| `tests/unit/data/test_data_cs_rank.py:88`、`test_data_mkt_factors.py:108` | 断言 `ParquetDataConfig` 默认关（dataclass 默认 False，仍正确） | 不动 |

### F. 已知不一致 / 待决事项（不在本任务范围，须在 REPORT 留痕）
1. `scripts/run_eval_pipeline.py:172,235` 硬编码 `horizon=5`，其 preds 的 `true_ret` 是 H=5，与新 `PREDICTED_HORIZON=10` 声明矛盾（KD9）。
2. `data/AGENTS.md`「默认输出 F=53」「cs_rank/mkt_factors 可选默认关」描述的是 `ParquetDataConfig` 默认，而训练入口 `config/defaults.py` 默认全开（F=80）；两处措辞易混，但不在三处漂移内。
3. `scripts/README.md` 多处 `horizon=5`/F=45 陈旧（文档自带历史声明）。§F 均**不改**，由 REPORT 记录。

### G. 风险面（无）
`PREDICTED_HORIZON` 只影响谱系字符串与 `config_hash`，不进入成交路径（`predictions_for_date` 仅载 `exp_ret`；`Prediction.predicted_horizon` 不被 core 用于撮合）。故 P&L 不变。

---

## Interface Design

### I1 — `PREDICTED_HORIZON`（谱系常量）
- **位置**：`backtest/cnn_adapter/predictions.py` 模块级常量（定义行 41）
- **签名**：`PREDICTED_HORIZON: int = 10`（原 5）
- **契约**：
  - 语义：回测侧预测所对齐的**训练标签 horizon**，唯一事实源；必须等于 `config.defaults._BASE_CONFIG["HORIZON"]`（当前 10）与 `ParquetDataConfig.horizon` 默认（10）。
  - 前置：无；纯常量。
  - 副作用：无。被 `str()` 化后进 provenance，被原样进 `_config_hash` payload，被赋给 `Prediction.predicted_horizon`（core 校验 `int ≥ 1`）。
  - 错误返回：不适用（常量）。
- **数据结构**：`int`（不变）。
- **调用关系**：`predictions.py:141,190`；`runner.py:40,352`；`backtest/cnn_adapter/__init__.py:14,26` re-export。跨模块无新依赖。
- **兼容性**：**破坏性（仅元数据身份）**。`runner._config_hash` 入参 `horizon` 值变 5→10 ⇒ 所有历史 `config_hash` 失效（KD4，用户已接受）。代码签名/类型不变，无 import 破坏。
- **受影响调用点（全列）**：`runner.py:352`（hash 值变化）、`predictions.py:141`（provenance 值变化）、`predictions.py:190`（`predicted_horizon` 值变化）、`__init__.py:26`（仅再导出）、测试 `test_cnn_adapter_predictions.py:50,164,165`。
- **归属任务**：T3

### I2 — `LABEL_FORMULA`（标签公式谱系串）
- **位置**：`backtest/cnn_adapter/predictions.py:43`（相邻注释 42 行、docstring 9 / 197 行同批更新）
- **签名**：`LABEL_FORMULA: str = f"future_ret[t]=open[t+1+horizon]/open[t+1]-1,horizon={PREDICTED_HORIZON}"`（求值结果 `...horizon=10`）
- **契约**：
  - 语义：唯一描述「`true_ret` 的口径 = 训练标签 future_ret = open-open, horizon=N」。
  - 前置：`PREDICTED_HORIZON` 已定义（同模块，字面量在常量之后）。
  - 副作用：无；经 `provenance["label_formula"]` 原样透传进 `metrics.json`/manifest。
  - 错误返回：不适用。
- **数据结构**：`str`（不变）；内容格式 `future_ret[t]=open[t+1+horizon]/open[t+1]-1,horizon={N}` 保持可被既有字符串断言/metadata 解析识别。
- **调用关系**：`predictions.py:141`；`backtest/cnn_adapter/__init__.py:13` re-export；`scripts/run_backtest.py` 经 outcome.provenance 间接落盘。
- **兼容性**：破坏性（字符串内容变更，历史报告不可字符串比对）；无代码签名变更。改派生式后不再有「常量/公式各写一份」的重复。
- **归属任务**：T3

### I3 — `--horizon` CLI 语义
- **位置**：`scripts/run_backtest.py` `parse_args()`（`:258`）+ 新增模块级校验（`parse_args` 内联即可，不新增公共函数）
- **签名**：
  - 旧：`p.add_argument("--horizon", type=int, default=5)`
  - 新：`p.add_argument("--horizon", type=int, default=None, help="[已锁定] 仅接受与 adapter 谱系常量一致的值（当前 10）；不一致即报错。horizon 由 backtest.cnn_adapter.predictions.PREDICTED_HORIZON 决定，本参数不改变回测行为。")`
  - 新校验（`return p.parse_args(argv)` 之前）：
    ```python
    args = p.parse_args(argv)
    if args.horizon is not None and args.horizon != PREDICTED_HORIZON:
        p.error(f"--horizon 已锁定为 {PREDICTED_HORIZON}（backtest.cnn_adapter.predictions.PREDICTED_HORIZON）："
                f"该参数不改变回测标签口径，收到 --horizon {args.horizon}")
    return args
    ```
    需在 `scripts/run_backtest.py` 顶部新增 `from backtest.cnn_adapter.predictions import PREDICTED_HORIZON`（同包已 import `backtest.cnn_adapter.runner`，无新跨层依赖）。
- **契约**：
  - `args.horizon is None` ⇔ 未传（默认）；`== PREDICTED_HORIZON` ⇔ 显式声明一致，接受且**无任何行为影响**（不进 runner、不进 metrics）；`!= PREDICTED_HORIZON` ⇔ 立即 `parser.error`。
  - 异常：`SystemExit(2)`，stderr 含 `--horizon` 与允许值 `10`。
  - 副作用：改 `metrics.json` 无（horizon 从不落 metrics 的 CLI 段；落盘的是 `provenance.horizon`，来源为常量）。
  - 前置：`PREDICTED_HORIZON` 可 import。
- **数据结构**：`argparse.Namespace.horizon: int | None`（原 `int`，默认 5 → `None`）。
- **调用关系**：`scripts/run_backtest.py:main → parse_args`；`run_adapter_rolling`/`run_adapter_target` 均**不读** `args.horizon`（保持现状，AST 已核实零读取）；唯一仓库内 CLI 调用点 `scripts/run_eval_full.sh:76` 需从 `--horizon 5` 改为 `--horizon 10`。
- **兼容性**：破坏性（CLI 行为）：传 `--horizon != 10` 从「静默忽略」变为「`SystemExit(2)`」。仓库内 1 个调用点同步修；全仓测试无一处使用 `--horizon`（grep `tests/` 无匹配）。
- **归属任务**：T4

---

## 预期行为（Red Test 规格）

> 每个 need_test=true 任务先按本节写/改测试并确认 RED，再实现转 GREEN。

### T1 — `test_config_defaults.test_featurenum_placeholder_matches_new_schema`
| # | 被测行为 | 输入 | 期望输出 | 边界 |
|---|---|---|---|---|
| B1 | 默认配置的模型特征占位数 = 现行 schema 维度 | `make_default_config()["CNNTransformerConfig"]["featurenum"]` | `== 80` | 漂移回 53/69/45 任一值必须失败 |
| B2 | 80 不是魔数，而是 schema 分组的算术和 | `len(APPROVED_RAW_FEATURES)+len(G9_MASK_COLUMNS)+len(DEFAULT_CS_RANK_FEATURES)+len(DEFAULT_MKT_FACTOR_FEATURES)` | `== 80` 且 `== CNNTransformerConfig.featurenum` | schema 任一常量长度变化而占位值未跟改 → 失败 |

RED 判据：改测试后未改代码即 GREEN（本任务只改测试，`config/defaults.py` 已是 80）⇒ 该任务属「陈旧断言修正」，RED 前置状态为「改动前测试 FAIL（实测 `AssertionError: 80 != 53`）」——tdd_verification 的 red_passed 以**改动前实测失败**为证。

### T2 — `test_training_retail_wrapper.test_parquet_helper_passthrough`
| # | 被测行为 | 输入 | 期望输出 | 边界 |
|---|---|---|---|---|
| B1 | 默认配置下 cs_rank 透传为开 | `build_parquet_data_config(make_default_config())` | `pc.cs_rank is True` | 未显式关闭时必须 True |
| B2 | 默认配置下 mkt_factors 透传为开 | 同上 | `pc.mkt_factors is True` | 未显式关闭时必须 True |
| B3 | 显式关闭仍生效（防「恒 True」退化） | `cfg["CS_RANK"]=False` / `cfg["MKT_FACTORS"]=False` 后同上 | `pc.cs_rank is False` / `pc.mkt_factors is False` | 对应 `--no-cs_rank --no-mkt-factors` → F=53 路径 |
| B4 | 既有透传断言保持 | 同 B1 | `pc.seq_len == cfg["SEQ_LEN"]`（60）、`pc.normalize == cfg["NORMALIZE"]`（relative） | 不回归 |

RED 判据：改动前实测 FAIL（`AssertionError: True is not false`，`:75`）；B3 属新增断言，改动后仍须 GREEN。

### T3 — 谱系常量（`tests/unit/backtest/test_cnn_adapter_predictions.py` + 新增 runner 侧用例）
| # | 被测行为 | 输入 | 期望输出 | 边界 |
|---|---|---|---|---|
| B1 | 常量值 | `PREDICTED_HORIZON` | `== 10`（变异为 5/6 必须失败） | int 类型不变 |
| B2 | 每条 Prediction 标注 | `predictions_for_date(date(2025,3,3))` 6 条 | 每条 `pred.predicted_horizon == 10` | 空截面/剔除样本不参与（保持既有用例） |
| B3 | provenance 字符串谱系 | `adapter.provenance` | `["horizon"] == "10"`；`["label_formula"] == "future_ret[t]=open[t+1+horizon]/open[t+1]-1,horizon=10"` | 精确相等（不只用 `assertIn`），且 `EXP_RET_MAPPING` 不含 `horizon` 字样（确认未误改） |
| B4 | config_hash 的 horizon 入参为常量值 | 运行 `run_cnn_backtest(**e2e_kwargs)`，以包装函数捕获 `_config_hash` 的 payload | `payload["horizon"] == PREDICTED_HORIZON == 10`；`len(config_hash) == 40` | 不改 `_config_hash` 算法（包装而非替换，仍调原函数）；同参两次运行 hash 稳定（既有用例保持） |
| B5 | 谱系常量与训练 horizon 不脱钩 | `PREDICTED_HORIZON` vs `make_default_config()["HORIZON"]` | 两者 `== 10` | 未来任一侧单独改动 → 失败（本次漂移的根因防护） |

RED 判据：B1-B3 改动前 FAIL（`5 != 10`）；B4/B5 为新增用例，改动前必须 FAIL（B4 捕获到 `payload["horizon"] == 5`，B5 因 `5 != 10` 失败）。

### T4 — `--horizon` CLI 语义（`tests/unit/scripts/test_run_backtest_cli.py` 新增用例）
| # | 被测行为 | 输入 | 期望输出 | 边界 |
|---|---|---|---|---|
| B1 | 未传时不再是伪装默认值 | `parse_args(["--preds","x.npz","--parquet","q.parquet"])` | `args.horizon is None` | 兼容既有调用（不传即可） |
| B2 | 显式一致值被接受且无行为 | 追加 `--horizon 10` | 不抛异常，`args.horizon == 10`；`run_adapter_rolling` 下 `run_cnn_backtest` 的 kwargs **不含** `horizon` 键 | 证明参数仍不改变回测行为 |
| B3 | 显式不一致值被拒绝且消息可诊断 | 追加 `--horizon 5` | `SystemExit`，`code == 2`；stderr 同时含 `--horizon` 与 `10` | 不接受任何非 10 值（含 6/0/负数） |
| B4 | 错误不静默 | 同 B3 | stderr 非空且 `main()` 未调用引擎 | 不得先执行再报错 |

RED 判据：B1/B3 改动前 FAIL（`args.horizon == 5` 且 `--horizon 5` 被静默接受）。

---

## Task Decomposition

| task_id | task_name | target_files | description | 实现接口 | 依赖 | need_test | risk | batch | accept | expected_behaviors |
|---|---|---|---|---|---|---|---|---|---|---|
| T1 | featurenum 断言对齐 F=80 | `tests/unit/config/test_config_defaults.py` | 把 `test_featurenum_placeholder_matches_new_schema` 的 `53` 改为 `80`，并补 schema 派生式交叉断言（KD2）；不改 `config/defaults.py` | — | — | true | low | R1 | 该用例 GREEN；全文件其余用例不受影响；`config/defaults.py` 零改动 | §预期行为 T1 B1/B2 |
| T2 | cs_rank/mkt_factors 断言对齐默认开 | `tests/unit/training/test_training_retail_wrapper.py` | `test_parquet_helper_passthrough` 中两处 `assertFalse` 改为 `assertTrue`，并新增显式关闭对照（KD3）；**不得**改动同文件另 2 个既有 error 用例 | — | — | true | low | R1 | 该用例 GREEN；同文件 error 用例数量仍为 2（不得变绿凑数）；`train.py`/`config/defaults.py` 零改动 | §预期行为 T2 B1-B4 |
| T3 | 谱系常量与公式对齐 H=10 | `backtest/cnn_adapter/predictions.py`、`tests/unit/backtest/test_cnn_adapter_predictions.py`、`tests/unit/backtest/test_cnn_adapter_runner.py` | I1：`PREDICTED_HORIZON` 5→10；I2：`LABEL_FORMULA` 改派生式 + 模块/注释/docstring 4 处 5→10；测试锁 5→10 并新增 B4/B5；**不改** `runner._config_hash` 算法 | I1, I2 | — | true | high | R2 | `PREDICTED_HORIZON==10`；provenance `horizon="10"`/`label_formula` 精确匹配；`config_hash` payload 捕获到 10 且长度 40；`runner.py` 除 import 外零改动（`_config_hash` 函数体不变） | §预期行为 T3 B1-B5 |
| T4 | `--horizon` 死参数收紧为「一致或报错」 | `scripts/run_backtest.py`、`scripts/run_eval_full.sh`、`tests/unit/scripts/test_run_backtest_cli.py` | I3：`default=5→None` + `parser.error` 校验 + help 文案；`run_eval_full.sh:76` 改 `--horizon 10`；新增 B1-B4 用例 | I3 | T3（import `PREDICTED_HORIZON`） | true | medium | R3 | 未传 → `None`；`--horizon 10` 通过且不进 runner kwargs；`--horizon 5` → `SystemExit(2)` + stderr 含 `--horizon`/`10`；shell 调用点同步 | §预期行为 T4 B1-B4 |

依赖说明：T1/T2/T3 相互独立；T4 依赖 T3 的常量定稿（否则 `parser.error` 的允许值会写错）。T1/T2 只改测试，可与 T3 并行，但按批次串行执行。

---

## Review 检查点划分（Review Batches）

| batch_id | tasks | review 重点 | test_scope |
|---|---|---|---|
| **R1** | T1, T2 | ① 断言方向是否为「以代码为事实源」而非反向改生产默认值；② 是否引入魔数或重复防御（KD2/KD3 边界）；③ `test_training_retail_wrapper.py` 内 2 个既有 error 用例是否**未被顺手修绿**（diff 只能触及 `test_parquet_helper_passthrough`）；④ 是否误改 `tests/unit/data/*` 的 F=53 正确断言 | fast |
| **R2** | T3 | ① `predictions.py` 内 5 处 5→10 是否全同步（docstring 9 / 注释 39-40 / 注释 42 / `LABEL_FORMULA` 43 / docstring 197）；② `_config_hash` 算法与 payload 键集是否零改动（只允许值随常量变）；③ `LABEL_FORMULA` 派生式是否仍在 `PREDICTED_HORIZON` 之后定义（NameError 风险）；④ `EXP_RET_MAPPING` 是否**未**被误改（其中不含 horizon）；⑤ 新增 B4 是否以「包装原 `_config_hash`」而非替换实现；⑥ `__init__.py` re-export 是否仍可 import；⑦ 单测锁 5 的三处是否全改 | **full**（risk=high：公共契约/谱系身份变更） |
| **R3** | T4 | ① `parser.error` 路径是否 `SystemExit(2)` 且 stderr 可诊断（含允许值）；② `args.horizon` 是否仍**未**被传入 `run_cnn_backtest`（无新增行为耦合）；③ `run_eval_full.sh` 调用点是否同步为 10，无残留 `--horizon 5`；④ `scripts/run_backtest.py` 新增 import 是否合法（不越过 `backtest`→`config` 边界）；⑤ help 文案是否说清「本参数不改变回测行为」 | fast |

规模评估：R1 ≈ 25 行（2 文件测试）；R2 ≈ 45 行（1 生产文件 5 处 + 2 测试文件）；R3 ≈ 55 行（1 脚本 + 1 shell + 测试）。均在 150–400 行/批次以下，批次粒度按「可整体验证 + 高风险单独成批」划分（R2 单独成批，符合 SKILL「接口/公共契约落地必须单独成批」）。

基线与回归判定：R1 结束应得 `0F/10E/40S`；R2、R3 结束后仍须 `0F/10E/40S`（新用例计入总数，error 集合必须与 Phase 0 完全一致，不许新增/减少）。

---

## 重编译工程判定

**不命中**（`heavy_build=false`）：本项目为 Python，无增量编译产物；全量单测实测 `Ran 1013 tests in 66.617s` < 120s。故**不生成 R0 预热任务**，各任务按常规 TDD（Generator 自跑测试，`self_test=true`）。

---

## MISTAKES / 历史教训

项目根目录无 `MISTAKES.md`（Phase 0 未传入 `mistakes_md_content`）。本任务新增的反漂移结构（KD2 派生式断言、KD5 常量派生公式、T3-B5 跨层一致性测试）即为对「同类漂移不可再静默发生」的固化。
