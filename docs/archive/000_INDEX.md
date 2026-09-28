# 归档总入口（2026-09-27，与远端 main 合流 a8866a7 后冻结）

## 双轨地图

| 轨 | 位置 | 状态 |
|---|---|---|
| 生产训练 | `train.py + data/ + models/cnn_transformer/ + training/ + criterion/` | 冻结可用，`F53/H10/relative` |
| 生产回测 | `backtest/cnn_adapter/*`唯一路径，`backtest/legacy.py`为历史 | `585a533`确立，勿绕行 |
| 研究脚本 | `scripts/h10_rolling/*, wf_xgb_cs.py, run_retail_backtest.py` | 冻结存档，不再扩展 |
| 论文隔离轨 | `paper_jkx/`（全程 untracked，永不提交） | 已收口，见 `STATE_FREEZE.md` |

## 结论文档

* `data_contract_F53_H10_adapter.md`：数据契约代码实情裁决。
* `main_2015-2026_prereg_A.md`：主链路冻结A（`ses_f43d`）。
* `paper_jkx_2024-2026_seven_routes.md`：论文轨七路收口（`ses_f388`）。
* `logs_manifest.csv`：`logs/`340项编目（KEEP 76 / DELETE 264）。

## 红线

* 2026-01~08 数据已被看过，属烧掉样本：任何新规则不得用 2026 验收。
* 干净考试只认 2026-09 之后的新数据。
* `backtest-core`（`../backtest-core`）为本地 editable 依赖，缺失则 `uv sync` 失败。
