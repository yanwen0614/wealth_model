# REVIEW_CHECKLIST — 测试基线漂移修正 + 回测谱系 H=10 对齐

供 Quality Gate 逐项核对。判据来源：`PLAN.md`（接口 I1/I2/I3、预期行为 T1–T4）+ 项目 `AGENTS.md`。
base_commit（首批次基线）= `f60955d`。

---

## 1. 需求符合性

- [ ] **N1** 全量单测从 `2F/10E/40S` 收敛为 `0F/10E/40S`：`test_config_defaults.test_featurenum_placeholder_matches_new_schema` 与 `test_training_retail_wrapper.test_parquet_helper_passthrough` 两个 FAIL 消失。
- [ ] **N2** 10 个既有 error **一个不少、一个不多**（集合与 Phase 0 实测一致）：
  `test_prefix_attestor`、`test_prefix_ledger_verifier`、`test_data_feature_pipeline.test_training_refits_mismatch_but_validation_requires_scaler`、`log_manager_collision` ×2、`test_decile_diagnosis` ×2、`test_trainer_unified.test_validate_epoch_dict_with_tuple_unpack`、`test_training_retail_wrapper.test_main_config_stays_cnn_by_default`、`test_training_retail_wrapper.test_retail_config_uses_isolated_dirs_and_model`。
- [ ] **N3** `PREDICTED_HORIZON == 10`、`LABEL_FORMULA` 求值含 `horizon=10`；`provenance["horizon"] == "10"`。
- [ ] **N4** `--horizon` 传非 10 值被拒绝；传 10 或不传均正常。
- [ ] **N5** 未修改 `data/dataset.py` 的 `horizon` 默认（仍 10）、未修改 `backtest/engine.py`（legacy 冻结区）、未修改 `backtest/cnn_adapter/market.py` 与 `scripts/build_ohlc_path.py`。

## 2. 影响面核查（对照 PLAN.md §Impact）

- [ ] **I1** `PREDICTED_HORIZON` 全部引用点行为符合预期：`predictions.py:41/141/190`、`runner.py:40/352`、`__init__.py:14/26`。
- [ ] **I2** `predictions.py` 内 5 处 horizon 字面量全部同步为 10：模块 docstring `:9`、常量注释 `:39-40`、公式注释 `:42`、`LABEL_FORMULA :43`、`actuals_for_cross_section` docstring `:197`。
- [ ] **I3** `EXP_RET_MAPPING`（`:46`）**未被改动**（其内容不含 horizon，仅确认未误改）。
- [ ] **I4** 无未完成占位：`predictions.py` / `run_backtest.py` 内不得留 `TODO`/`pass` 占位/被注释掉的旧值（如 `# 5`）；注释只描述当前值 10。
- [ ] **I5** `_config_hash`（`runner.py:70-74`）函数体与 payload 键集**零改动**，仅 `horizon` 值随常量变为 10。
- [ ] **I6** `tests/unit/data/*` 中 F=53 断言（`ParquetDataConfig` 默认 `cs_rank=False`/`mkt_factors=False` 时的数据集维度）**未被误改**——它们语义正确。
- [ ] **I7** `tests/unit/training/test_training_retail_wrapper.py` 的 `featurenum=53` 显式传参用例（`:91/:113/:124`）**未被误改**。

## 3. 重复实现检测

- [ ] **D1** 未新增「第二事实源」：没有把 horizon 再写一遍到别处（`LABEL_FORMULA` 必须派生自 `PREDICTED_HORIZON`，不得写死 `horizon=10`）。
- [ ] **D2** T4 未新增公共校验函数（`parse_args` 内联即可），未新增 `--horizon` 的第二个入口。
- [ ] **D3** 未新增与 `HORIZON`/`ParquetDataConfig.horizon` 平行的配置项（无 `BACKTEST_HORIZON` 之类）。
- [ ] **D4** 未在 `scripts/run_backtest.py` 引入 `config.defaults` 依赖（保持 adapter 不反向依赖 config；`PREDICTED_HORIZON` 来自 `backtest.cnn_adapter.predictions`）。

## 4. 接口一致性（对照 PLAN.md §Interface Design）

- [ ] **F1** `I1`：`PREDICTED_HORIZON: int = 10`，类型仍 `int`，`__all__` 与 `__init__.py` 再导出仍可用。
- [ ] **F2** `I2`：`LABEL_FORMULA` 为 `f"...horizon={PREDICTED_HORIZON}"` 派生式，定义位置在 `PREDICTED_HORIZON` **之后**（防 NameError），求值结果与 `horizon=10` 精确相等。
- [ ] **F3** `I3`：`--horizon` 签名 `type=int, default=None`；`parse_args` 返回值仍为 `Namespace`；`SystemExit(2)` + stderr 含 `--horizon` 与允许值；`args.horizon` 仍**不**进入 `run_cnn_backtest` kwargs。
- [ ] **F4** `scripts/run_eval_full.sh:76` 已由 `--horizon 5` 改为 `--horizon 10`（仓库内唯一 CLI 调用点）。
- [ ] **F5** 无静默改签名：`run_cnn_backtest`、`CnnPredictionAdapter.__init__`、`provenance` 的键名/键集未变。

## 5. 8 关卡清单（定义见 `agents/quality-gate.md` Part A）

| # | 关卡 | 判据（本项目 AGENTS.md 口径） |
|---|---|---|
| 1 | 规范一致性（HIGH） | 命名/注释风格与同文件既有代码一致；注释只描述**当前状态**，不得留「原为 5，现改 10」之类历史叙述；改动文件的中文注释风格保持。 |
| 2 | 模块边界（HIGH） | `backtest/*` 不 import `config/*`、不 import `training/*`；`scripts/*` 可 import `backtest.*`；测试可跨层 import。禁止反向依赖。 |
| 3 | 数据安全（HIGH） | 无凭证/路径硬编码新增。 |
| 4 | 接口一致性（HIGH） | §4 F1–F5 全通过。 |
| 5 | 导入合规（MEDIUM） | `scripts/run_backtest.py` 新增 import 放在既有 `backtest.cnn_adapter` 导入块内，按字母/既有顺序；无未使用导入。 |
| 6 | 错误处理（MEDIUM） | T4 用 `parser.error`（argparse 惯例），不得 `print` + `sys.exit`、不得 `try/except` 吞掉；不得用 `assert` 做 CLI 校验（`-O` 下失效）。 |
| 7 | 过度防御（MEDIUM） | B3「显式关闭仍生效」与 B5「跨层一致性」是**测试**，不是生产重复防御，允许；生产代码不得因本次新增 `None` 判断以外的分支（`args.horizon is not None` 是必要判据，非冗余）。 |
| 8 | 性能风险（MEDIUM） | 测试新增断言不引入大文件读取/循环 IO；`test_cnn_adapter_runner.py` 的 payload 捕获不得重复执行整套回测超过既有次数。 |

## 6. TDD 检查（Part C）

- [ ] **TDD1** T1：改动前 `test_featurenum_placeholder_matches_new_schema` 实测 FAIL（`AssertionError: 80 != 53`）→ `red_passed=true`；改后 GREEN。
- [ ] **TDD2** T2：改动前 `test_parquet_helper_passthrough` 实测 FAIL（`AssertionError: True is not false` @ `:75`）→ `red_passed=true`；改后 GREEN，且新增 B3（显式关闭）同轮 GREEN（新增断言本身无 RED 要求，但 B1/B2 的 red 证据必须存在）。
- [ ] **TDD3** T3：改动前 `predicted_horizon==5`/`provenance["horizon"]=="5"` 使 `:50/:164/:165` FAIL；新增 B4（捕获 `_config_hash` payload 为 5）/B5（`5 != 10`）改动前 FAIL → 全 `red_passed=true`；改后全 GREEN。
- [ ] **TDD4** T4：改动前 B1（`args.horizon == 5`，非 None）、B3（`--horizon 5` 被接受，无 `SystemExit`）FAIL → `red_passed=true`；改后 GREEN。
- [ ] **TDD5** 所有 need_test=true 任务均返回 `tdd_verification`，`red_passed`/`green_passed` 全 true。

## 7. 三项验证（Part B）

- [ ] **V1 lint**：`uv run --project . python -m compileall -q data training backtest config scripts models criterion log_manager tests train.py train_retail.py` 无报错；`uv run ruff check .` 零告警（`pyproject.toml` 窄名单）。
- [ ] **V2 typecheck**：项目无独立 typecheck 命令（AGENTS.md 未定义），按 SKILL 规则不判 FAIL；`compileall` 即可。
- [ ] **V3 test**：
  - R1（fast）：`uv run --project . python -m unittest tests.unit.config.test_config_defaults tests.unit.training.test_training_retail_wrapper -q` → 目标两用例 FAIL 消失；同文件 error 数不增加。
  - R2（**full**）：`uv run --project . python -m unittest discover -s tests -t . -q`（tmux 后台）→ `failures=0, errors=10, skipped=40`，总数 = 1013 + 新增用例数。
  - R3（fast）：`uv run --project . python -m unittest tests.unit.scripts.test_run_backtest_cli tests.unit.backtest.test_cnn_adapter_predictions -q` → GREEN。
  - 全程 `--num_workers 0`（AGENTS.md 受限环境约定）。

## 8. 明确不许做（红线）

- [ ] **X1** 不修 10 个既有 error（尤其 `test_training_retail_wrapper` 的 `KeyError: 'CNNTransformerConfig'` 两例——同文件改动只能触及 `test_parquet_helper_passthrough`）。
- [ ] **X2** 不动 `backtest/engine.py`（legacy 冻结区）与 `scripts/frozen/*`。
- [ ] **X3** 不改 `_config_hash` 算法（只让入参 horizon 值随之变）。
- [ ] **X4** 不动 `data/dataset.py` 的 `horizon` 默认值（已为 10）。
- [ ] **X5** 不提交 `docs/agent/handoff-cnn-experiment-20261031.md`（用户未提交改动）与 `.bluecode/`；commit 只用显式 pathspec。
- [ ] **X6** 不碰 `scripts/eval_bins_mapping.py` / `eval_three_way.py` / `run_eval_pipeline.py` 的 horizon（KD7/KD9，已知不一致，超出三处漂移范围）。
- [ ] **X7** 不在 2026-01~08 烧样本上做任何验收；不跑训练/回测取收益数字。

## 9. 已知陈旧文档（记录，不修）

- `scripts/README.md:3,8,41,139,157`：`F45`/`horizon=5`，文件自带「历史快照声明」。
- `data/AGENTS.md`：描述 `ParquetDataConfig` 默认（F=53、cs/mkt 默认关），与训练入口默认（F=80、全开）措辞易混。
- `scripts/run_eval_pipeline.py:172,235`：硬编码 `horizon=5`，其 preds 的 `true_ret` 为 H=5，与新 `PREDICTED_HORIZON=10` 声明存在口径差（KD9 待决）。
- 以上须在 Phase 3 `REPORT.md` 留痕，不在本任务修。
