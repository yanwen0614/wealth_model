# 变更摘要报告 — test-baseline-drift

## 需求

修正三处「代码默认值已演进、测试/常量未跟改」的漂移，并把回测谱系元数据对齐到真实的 H=10 标签口径：

1. `tests/unit/config/test_config_defaults.py` 断言 `featurenum==53`，实际默认已 80
2. `tests/unit/training/test_training_retail_wrapper.py` 断言 `cs_rank/mkt_factors is False`，实际默认已开
3. `backtest/cnn_adapter/predictions.py` 硬编码 `PREDICTED_HORIZON = 5`，实际训练/缓存都是 H=10

附带：`scripts/run_backtest.py --horizon` 是死参数（能传、无任何读取点），误导调用方以为可配。

## 变更内容

| 文件 | 操作 | 行数 |
|---|---|---|
| `backtest/cnn_adapter/predictions.py` | 修改 | +7 / −7（`PREDICTED_HORIZON` 5→10、`LABEL_FORMULA` 改由常量派生、6 处 horizon 注释同步） |
| `scripts/run_backtest.py` | 修改 | +11 / −2（`--horizon` 默认 `None` + 一致性校验、help 说明） |
| `scripts/run_eval_full.sh` | 修改 | +1 / −1（`--horizon 5`→`10`） |
| `tests/unit/config/test_config_defaults.py` | 修改 | +16 / −1（断言 53→80 + schema 派生式交叉断言） |
| `tests/unit/training/test_training_retail_wrapper.py` | 修改 | +8 / −2（断言改 True + 显式关闭对照） |
| `tests/unit/backtest/test_cnn_adapter_predictions.py` | 修改 | +59 / −4（3 处锁 5 改 10 + 新增 4 用例） |
| `tests/unit/scripts/test_run_backtest_cli.py` | 修改 | +65（新增 4 用例） |
| `docs/agent/handoff-cnn-experiment-20261031.md` | 修改 | 交接文档对齐实测基线 |
| `AGENTS.md` | 修改 | 基线描述两处 |
| `docs/agent/task/{两个历史任务}` | 重命名 | 追加 `_archive` |

## 质量关卡

| 批次 | 任务 | TDD | 关卡 | 结果 |
|---|---|---|---|---|
| R1 | T1, T2 陈旧断言对齐 | red 真实（改动前实测 `80 != 53` / `True is not false`） | 8 关卡全 PASS | PASS |
| R2 | T3 谱系常量对齐 H=10 | red 真实（5 个断言改动前全 FAIL） | 8 关卡全 PASS + A/B 双跑验证 P&L 不变 | PASS |
| R3 | T4 `--horizon` 收紧 | red 真实（复原旧实现后 B1/B3/B4 均 FAIL） | 8 关卡 PASS（1 条 MEDIUM docstring，已收敛） | PASS |
| ALL | 整体终审 | 复原 `f60955d` 栈：8 个新用例全 RED | 代码/测试/P&L/CLI 全过；**文档 4 处事实错误** | FAIL→已修 |

终审发现并已修正的文档问题（均为「把改动前实测写成当前状态」）：

1. **HIGH** §4.5 写「provenance horizon 恒为 5」—— 实际已是 10，与同节 §5.6(b) 自相矛盾
2. **MEDIUM** §5.1 标题仍写「2F/10E/40S」—— 正文已 0F
3. **MEDIUM** §5.1 + AGENTS.md 写「缺目录退化 3F/30E」—— 实测 1F/30E/40S（含 1 个断言失败，非全是 FileNotFoundError）
4. **MEDIUM** 「唯一残留 horizon=5 源」不成立 —— `eval_bins_mapping.py` / `eval_three_way.py` 默认也是 5

## 关键验证数据

| 项 | 改动前 | 改动后 |
|---|---|---|
| 全量测试 | 1013 项 / 2F/10E/40S | **1021 项 / 0F/10E/40S** |
| `config_hash`（rolling top10） | `aa899b50…` | `08b983c7…`（**预期变**，入参 horizon 5→10） |
| `data_fingerprint` | `0ce5e693…` | `0ce5e693…`（未变） |
| annual / sharpe / mdd / final_nav | -0.4451 / -2.513 / 0.4136 / 695813.51 | **逐项相同** |
| `--horizon 5` | 静默接受、无效果 | exit 2，不创建 `--out_dir` |
| `--horizon 10` vs 不传 | 均无效（default=5 死参数） | 两者 `metrics.json` 完全相同 |

反向验证：注入 `PREDICTED_HORIZON=5` 重跑可精确复现旧 hash `aa899b50…`，证明差异只来自 horizon 入参。

## 遗留风险（显著留痕，需独立任务）

### R1｜`run_backtest` 不校验 `--preds` 的真实 horizon（本次改动使其更危险）

用 parquet 真实 OHLC 反推 11 个 npz 的 `true_ret` 口径，实测：

| npz | 真实 horizon |
|---|---|
| `preds_fullA_2025/2026`、`preds_fullB_2025/2026`、`m_research/preds_B2025_xgbgate` | H=10 |
| `preds_jkxI5_2025/2026`、`preds_jkxI30_2025/2026`、`m_research/preds_dualalpha_2025`、`_gate` | **H=5** |

`scripts/run_backtest.py` 的 `load_preds()` 只校验四键与长度，不校验 horizon。改动前
`PREDICTED_HORIZON=5` 与 H=5 缓存至少自洽；改动后 H=5 缓存会被盖上
`provenance.horizon="10"` 与含 `"horizon":10` 的 `config_hash` —— **从「不精确」变为「主动错标」**。

本轮实验只用 `preds_fullA_2025.npz`（已确认 H=10），不受影响。已在交接文档 §4.1 补真实 horizon 表。

**建议独立任务**：`load_preds` 增加 horizon 自证（用 parquet 复算 2–3 个样本与 `true_ret` 对齐，
不一致即 `parser.error`），或最小方案：消费 H≠10 缓存时打 warning。

### R2｜多个生成脚本的 `--horizon` 默认仍是 5

`scripts/eval_bins_mapping.py:542`、`scripts/eval_three_way.py:352`、`scripts/run_eval_pipeline.py:172,235`
的 horizon 默认都是 5。交接文档 §4.3 曾推荐「用 `eval_bins_mapping` 重新生成 npz」——
不显式传 `--horizon 10` 就会产出 H=5 缓存。已在 §4.1 补充必须显式传 10 的警示。

改这些脚本会改变评估标签语义与 BINS 派生，需独立任务 + 独立验收，本次未动。

### R3｜`PREDICTED_HORIZON` 与 `config HORIZON` 是两个独立字面量

运行期无硬连接（`backtest` 不反向依赖 `config` 是既有模块边界约定），只靠
`test_matches_training_horizon` 跨层断言兜底。属可接受的设计取舍。

## 红线遵守

- 未重签任何 pin；未把 `test_prefix_attestor` / `test_prefix_ledger_verifier` 的 error 改绿
- 未顺手修 `test_training_retail_wrapper` 的 2 个既有 `KeyError` error
- 未改 `backtest/engine.py`（legacy 冻结区）、`data/dataset.py`（HORIZON 已正确）
- 未改 `scripts/run_eval_pipeline.py`（KD9 明确不修）
- `_config_hash` 算法与 payload 键集零改动，B4 测试用 `wraps=` 包装而非替换
