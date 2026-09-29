# scripts/frozen — 冻结归档（READ ONLY，不再扩展）

> 来源：`scripts/h10_rolling/*`（7 文件）+ `scripts/wf_xgb_cs.py`，经 `git mv` 迁入，
> 历史保留可查（`git log --follow scripts/frozen/<file>`）。冻结结论见
> `docs/archive/000_INDEX.md`（研究脚本行）与主链路冻结A文档。

## 冻结声明

- 本目录为**历史复现证据**，默认不可达：生产代码（`train.py` / `backtest/cnn_adapter/*` /
  `scripts/run_*.py` / `scripts/eval_*.py`）**禁止 import 本目录任何模块**。
- 不再扩展、不修 bug、不跟随主链路口径变更（如 `F53/H10/relative`、adapter 唯一入口）。
  其中 `run_rolling_backtest.py` 仍直引旧 `backtest.engine`（冻结当时口径），与生产 adapter
  口径不一致属预期，禁直接对比数字。
- 如需复现历史结论，手动执行本目录脚本即可；新研究请走生产路径，禁以 frozen 为模板复制。

## 内容

| 文件 | 来源 | 用途 |
|------|------|------|
| `run_rolling_backtest.py` | `h10_rolling/` | H10 rolling 回测入口（旧 engine 口径） |
| `engine_replica_core.py` | `h10_rolling/` | 旧引擎复制品核心 |
| `combine_rolling_preds.py` | `h10_rolling/` | rolling preds 合并 |
| `ensemble_voting_27.py` | `h10_rolling/` | 27 票集成投票 |
| `final_combo_voting_halving.py` | `h10_rolling/` | 最终组合投票 + 减半 |
| `halving_drawdown.py` | `h10_rolling/` | 减半回撤分析 |
| `weighted_ic_eval.py` | `h10_rolling/` | 加权 IC 评估 |
| `wf_xgb_cs.py` | `scripts/` 根 | Walk-forward XGB 截面回归（年频×固定近5年窗口） |

## 复现命令（新模块路径）

```bash
# H10 rolling 回测（旧 engine 口径，仅历史复现）
uv run --project . python -m scripts.frozen.run_rolling_backtest --help
# Walk-forward XGB（dry-run 先验证）
uv run --project . python -m scripts.frozen.wf_xgb_cs --dry_run
uv run --project . python -m scripts.frozen.wf_xgb_cs --out_dir logs/wf_annual_fixed5y
```
