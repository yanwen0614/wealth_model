# 工程总图 ENGINE_MAP（2026-10）

> 唯一训练入口 `train.py`，默认 `relative E0 / F53 / H10 / 52类EMD`。
> 回测唯一入口 `backtest/cnn_adapter/`（open-open，佣万2min5+印花卖万5+过户万1双边，仅long-only）。
> 红线：2026-01~08烧掉样本不验收，只认2026-09后干净样本；`logs/`不入库（除`KEEP/baseline`）。

## 1. 生产链路（改动走质量门）

| 层 | 文件 | 职责 |
|---|---|---|
| 入口 | `train.py`、`train_retail.py` | CLI→config→dataloader→模型→Trainer，`featurenum`实测派生 |
| 配置 | `config/defaults.py` | `NORMALIZE=relative`、`BINS=linspace(-0.38,0.38,51)`、`AdamW 3e-4`、`SEQ60/H10` |
| 数据 | `data/dataset.py`、`schema.py`、`scaler.py`、`rolling_scaler.py`、`feature_cache.py` | `P18/R16/N12/G6=52+mask=F53`，`COLUMN_RULES`集中注册，`is_trading`过滤，warmup不作标签，`CACHE v3`，可选`--cs_rank F69`/`--mkt_factors F80` |
| 模型 | `models/cnn_transformer/model.py`、`retail_friendly/` | CNN[k1,3,5,7,10]+Transformer(d256/n8/L4)；零售BCE pos_weight=2 |
| 损失 | `criterion/emd_loss.py`、`dual_loss.py` | 默认EMD(p2+smooth0.1)，双头λ0.2 |
| 训练 | `training/trainer.py`、`factory.py` | 依赖`run_log_dir`预建，早停+ReduceLROnPlateau |
| 回测 | `backtest/cnn_adapter/` | open-open，`rolling/target`两模式，无空头 |

## 2. 脚本（生产评估 vs 只读研究）

生产（`scripts/`）：`run_backtest.py`（真实引擎）、`eval_bins_mapping.py`
（推理出`preds_full*.npz`四键`exp_ret/true_ret/dates/codes`）、
`eval_three_way.py`（截面复核基准）、`analyze_preds.py`、`plot_topn_curve.py`。
`frozen/` READ ONLY禁import。

研究（已入库）：`research/m_research/scripts/m00~m08,dt_*`（m_t全套）、
`research/goal_repro/r1~r3`（树复现）、`research/precision/`、
`research/alpha_attribution/`、`research/unified_recalc/`、
`research/market_neutral/`（见§4，脚本+小产物入库，大npz留TEMP/logs）。

## 3. 文档（三层）

- 入口契约：`AGENTS.md`、`README_TRAINING_CHAIN.md`、`pyproject.toml`
 （torch cu130/cu126，`tgw→../quant/wheels`别动）。
- 决策事实源：`docs/per_code_normalization_spec.md`（P/R/N/G+ColumnRule）、
  `docs/prediction_target_and_tree_2026.md`（α/m+损失+择时+树定位总收口）、
  `docs/archive/`（冻结A/七路关闭/大扫除编目`logs_manifest.csv`）。
- 研究报告：`research/m_research/REPORT.md`（m方向幅度不可行、仅波动
  IC+0.18显著、双塔证伪+预注册§5）、`logs/tree_verify/REPORT.md`、
  `logs/tree_rebuild/SUMMARY.md`、`paper_jkx/{README,STATE_FREEZE}`（已停止）。

## 4. 实验治理（注册表为准，此处只留规则）

> 明细（总表/结论/待验收队列/TEMP草稿政策）见 `research/README.md`，
> 此处不重复贴表，结论以注册表为准。
> 规则：脚本+小json/csv入库；`*.npz/parquet/pth`一律不入库；各研究目录与
> `scripts/frozen`为只读快照（ruff exclude），生产禁import；`__pycache__`不入库。

## 5. 产物资产（`logs/`不入库，指针在此）

- 主模型：`logs/preds_full{A,B}_{2025,2026}.npz`+`eval_full*.json`+
  `bt_2026_final_*/`（2026 target -7%，rolling -40~-49%）。
- 树：`logs/tree_verify/preds_p1/p2_*.npz`（16个，close+openopen双口径）+
  `metrics_table/bt_table.json`（VAL 0.10~0.11/TEST 0.07~0.08，target噪声区）。
- m研究：`logs/m_research/`（naked +42.6%→门+7.2%，双塔+51.4%→+9.3%）。
- 本轮：`%TEMP%/{unified_recalc,market_neutral}/`（树胜A显著+0.048，
  树-B不显著，spread全不显著；IC恒等maxdiff 0）。
- KEEP：`logs/KEEP/`唯一有效存档，`run_*`轮转（保留10/2GiB，dry-run先列清单）。

## 6. 最终结论

> 结论只写 `research/README.md` 总表一份，此处只留一句话：
> 排序树胜A显著、与B相当但变不了钱；m方向/幅度关门，只留波动风控气窗；
> 精确VAL可买、2026不跨regime；下一步等2026-09后干净样本一次性验收。
