# HARNESS_PROGRESS — 测试基线漂移修正 + 回测谱系 H=10 对齐

- task_dir: `docs/agent/task/20261031_1700_test-baseline-drift/`
- tag: `test-baseline-drift`
- base_commit（Phase 0）: `f60955d`
- 重编译工程: **否**（Python，全量单测实测 66.6s < 120s）→ 无 R0 预热任务

## Phase 0 基线（实测）

| 项 | 值 |
|---|---|
| 全量测试命令 | `uv run --project . python -m unittest discover -s tests -t . -q` |
| 实测结果 | `Ran 1013 tests in 66.617s` → `FAILED (failures=2, errors=10, skipped=40)` |
| 目标结果 | `failures=0, errors=10, skipped=40`（error 集合须逐项不变） |
| 待消除 FAIL #1 | `tests.unit.config.test_config_defaults.TestConfigDefaults.test_featurenum_placeholder_matches_new_schema` — `AssertionError: 80 != 53` |
| 待消除 FAIL #2 | `tests.unit.training.test_training_retail_wrapper.TestApplyArgsRetailNamespace.test_parquet_helper_passthrough` — `AssertionError: True is not false`（`:75`） |
| 既有 10 E（不修） | prefix_attestor, prefix_ledger_verifier, test_data_feature_pipeline, log_manager_collision×2, decile_diagnosis×2, trainer_unified, training_retail_wrapper×2（`KeyError: 'CNNTransformerConfig'`） |

## R0 预热

不适用（非重编译工程）。`heavy_build=false`。

---

## R1 — 陈旧断言对齐（T1, T2）

**Review 重点**：断言方向（改测试而非改生产默认值）、无魔数/无重复防御、同文件既有 error 未被顺手修绿、`tests/unit/data/*` 的 F=53 正确断言未被误改。
**test_scope**：fast

| task_id | 任务 | 状态 | 依赖 | 验收 |
|---|---|---|---|---|
| T1 | featurenum 断言 53→80 + schema 派生式交叉断言 | done | — | `test_featurenum_placeholder_matches_new_schema` GREEN；`config/defaults.py` 零改动 |
| T2 | cs_rank/mkt_factors 断言 False→True + 显式关闭对照 | done | — | `test_parquet_helper_passthrough` GREEN；同文件 error 数仍为 2；`train.py` 零改动 |

**Gate 结果**：PASS（8 关卡全过）
**修复轮次**：fix: 0 / logic 回调: 0

---

## R2 — 谱系常量与公式对齐（T3）

**Review 重点**：5 处 horizon 字面量全同步；`_config_hash` 算法/键集零改动；`LABEL_FORMULA` 派生式定义顺序；`EXP_RET_MAPPING` 未误改；B4 包装而非替换；`__init__` re-export 可用；单测锁 5 的三处全改。
**test_scope**：**full**（risk=high：公共契约/谱系身份变更）

| task_id | 任务 | 状态 | 依赖 | 验收 |
|---|---|---|---|---|
| T3 | `PREDICTED_HORIZON` 5→10、`LABEL_FORMULA` 派生式、（I1/I2）测试锁 5→10 + 新增 B4/B5 | done | — | 常量 10；provenance `horizon="10"`/`label_formula` 精确匹配；`config_hash` payload 捕获 10 且长度 40；`runner.py` 除 import 外零改动 |

**Gate 结果**：PASS（8 关卡全过）
**修复轮次**：fix: 0 / logic 回调: 0

---

## R3 — `--horizon` 死参数收紧（T4）

**Review 重点**：`parser.error` 路径 `SystemExit(2)` + 可诊断 stderr；`args.horizon` 仍不进 `run_cnn_backtest`；shell 调用点同步为 10；新增 import 不越模块边界；help 说清「不改变回测行为」。
**test_scope**：fast

| task_id | 任务 | 状态 | 依赖 | 验收 |
|---|---|---|---|---|
| T4 | `--horizon default=None` + 一致性校验（I3）、`run_eval_full.sh:76` 同步、新增 B1-B4 用例 | done | T3 | 不传→None；10→通过且不进 kwargs；5→`SystemExit(2)` + stderr 含 `--horizon`/`10` |

**Gate 结果**：PASS（8 关卡全过）
**修复轮次**：fix: 0 / logic 回调: 0

---

## 批次固定回归门槛

| 批次完成后 | 期望全量结果 |
|---|---|
| R1 | `failures=0, errors=10, skipped=40` |
| R2 | `failures=0, errors=10, skipped=40`（总数 = 1013 + 新增用例） |
| R3 | `failures=0, errors=10, skipped=40`（同上） |

error 集合必须与 Phase 0 逐项一致（见「Phase 0 基线」表）。

## Phase 2.5 / Phase 3 / Phase 4

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 2.4 squash | done | 3 批次合为 `5401f92`（文档另提 `7ad5fb3`、归档 `0dfb353`） |
| Phase 2.5 整体质量门禁（batch_id="ALL"） | FAIL→已修 | 代码/测试/P&L 全过；文档 4 处事实错误（HIGH 1 + MEDIUM 3）已修 |
| Phase 3 REPORT.md | done | 见同目录 REPORT.md |
| Phase 4 归档 | pending | 目录名追加 `_archive` |

