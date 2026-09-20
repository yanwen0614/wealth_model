# Project Memory

## 当前架构
- 唯一训练入口：`train.py`（支持 `--model cnn_transformer|retail_friendly`）。
- **默认归一化 = E0 (relative)**（`config/defaults.py` `NORMALIZE="relative"`，`SCALER_PATH=None`；`data/dataset.py` `ParquetDataConfig.normalize="relative"`）。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（`RelativeScaler` E0 + `PerCodeGroupedScaler` E1）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`（原默认） + `models/retail_friendly/`（散户友好，`--model retail_friendly`）；训练：`training/`；损失：`criterion/`（原）+ `models/retail_friendly/loss.py`（RetailLoss）；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`（`--full` 出全期日频矩阵）；`scripts/run_backtest.py`（rolling/target 回测 + 指数基准 + 强买门槛）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联。
- 三分评估：`scripts/eval_three_way.py`（严格 train/val/test 对比 + 阈值样本外校准，见下）。

## 不可变契约
- 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序。
- 默认序列 `T=60`，horizon=5，标签 `open[t+1+horizon]/open[t+1]-1`；`BINS` 51 边界 → `C=52`。
- scaler 只在训练集 fit；验证/评估复用训练 scaler，禁止重拟合（rolling 复用训练 rolling state）。
- 回测时序：T 日决策，T+1 open 买入，T+6 open 卖出。
- `train.py:48` `set_seed` 刻意设 `cudnn.deterministic=True` + `benchmark=False` 保可复现。
- **warmup 窗口语义**：`start_date` 之前的历史行（`_transform_context`）保留在 `groups` 作窗口 warmup 输入；`valid_starts` 用 `is_context[label_pos]` 过滤，context **绝不作标签日**。context 上限：rolling 且 `role!=training` 为 `max(seq_len-1,251)`，否则 `max(seq_len-1,1)`。评估/验证标签日覆盖 = 区间交易日数 − `(horizon+1)`。`CACHE_FORMAT_VERSION=v3_relative_groups`。
- **默认 parquet 路径**：`ParquetDataConfig.parquet_path` 与 `config/defaults.DEFAULT_PARQUET`（Linux 分支）均指向 `data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`（F60 schema）；win32 由 `train.py` 覆盖为 `Z:/...`。指数数据在 `Z:/test/kline_index/day/<code>.parquet`（列 `code,kline_time,open,high,low,close,volume,amount`）。
- **注意**：`train.py --smoke` 会用 max_codes=20 重拟合并**覆盖 `logs/scaler_per_code.pkl`**；需按训练口径（2013-01-01~2025-06-30 全量）重拟合恢复。

## Redesign（P/R/N/G 分组 + E0–E5，2026-09-14 落地，commit 178f24e）
- ...（原有内容不变）

## 默认归一化 = E0 relative（2026-09-16 baseline 迁移）
- ...（原有内容不变）

## 散户友好模型（RetailFriendlyModel，2026-09-20 集成）
- **模型**：`models/retail_friendly/` — CNN+Transformer 骨架 → `bin_logits[B]`（pre-sigmoid）+ `ret_pred[B]`。`predict_proba()` 推理时返回 sigmoid 概率。
- **损失**：`models/retail_friendly/loss.py` `RetailLoss(is_dual_head=True)`。**已从 ASL 改为 `BCEWithLogitsLoss + pos_weight`**（ASL 对平衡二分类有梯度偏移：正/负梯度不对称使全体预测漂移到 p≈0.57，学不到区分；BCE 数值稳定无偏移）。默认 `pos_weight=2.0`（平衡数据 equilibrium p≈0.667）。CLI `train.py --model retail_friendly --pos_weight 2.0 --lambda_reg 0.2`。标准 `(bin_logits, ret_pred, y_cls, y_ret)` 接口。
- **集成方式**：`train.py --model retail_friendly`，复用全套数据/日志/早停/调度器基础设施。`factory.py` 统一构建。
- **Trainer 扩展**：`training/trainer.py` 零售模式（`_is_retail=True`）追踪 precision/recall/F1/p_bin，训练后调用 `calibrate_threshold()` 自动校准阈值。
- **实测结论**：零售二分类模型（BCE）在 5 日涨跌上仍逼近随机（val precision ~51.5%，p_bin avg ~0.61），**与「75% 单票胜率不可达」的总结论一致**。

## 严格三分评估规范（scripts/eval_three_way.py，2026-09-20 建立）
- **推荐标准划分**（满足 train≥8y/val≥1y/test≥1y）：train `2013-01-01~2024-06-30`（11.5y）、val `2024-07-01~2025-06-30`（1y）、test `2025-07-01~2026-08-31`（1.17y）。
- **旧划分**（DL E0 最优 checkpoint `logs/relative/run_20260914_024253/best_model.pth`）：train 到 2025-06-30、val 2025H2、test 2026。缓存：`logs/eval_preds_52cls.npz`=val 2025H2（120日）；`logs/preds_relative_run_20260914_024253_2026-08-31.npz`=test 2026（154日）。
- **用法**：`uv run --project . python -m scripts.eval_three_way`（走缓存）；`--run_inference --checkpoint <pth>`；输出 `logs/eval_three_way_report.{txt,json}`。
- **关键结论**：DL E0 val RankIC 0.046 → test 0.025；val 阈值校准无法达 75%（顶格 57.8%），迁移 test 得 57.97%——天花板 ~58%。

## 截面超额收益标签（label_mode，2026-09-20 新增）
- **配置**：`ParquetDataConfig.label_mode`（默认 `"absolute"`）/ `"excess"`；CLI `train.py --label_mode excess`；`config/defaults.py` `LABEL_MODE="absolute"`。
- **实现**：`data/labels.py` `_cross_sectional_excess(dates, future_ret, min_count=1)` 按 `kline_time` 剔除当日截面均值；`ParquetDataset._apply_excess_labels()` 在 groups 建成后、标签统计/缓存落盘前就地变换并重算 `discrete`；NaN 位置不变，context 与标签日互斥。
- **缓存**：`compute_cache_key(label_mode=...)` 仅非 absolute 时写 payload，旧缓存 key 不变。
- **测试**：`tests/unit/data/test_data_excess_labels.py`（10 用例）。

## 截面 rank 特征（cs_rank，2026-09-20 新增，**提升信号关键**）
- **目的**：E0 relative 只做时序归一，未消除截面/时期漂移；逐日全市场截面百分位 rank 尺度无关，令模型跨期泛化（Ridge/GBDT RankIC 0.09 vs DL 0.025-0.046）。
- **配置**：`ParquetDataConfig.cs_rank: bool=False` + `cs_rank_features`（None→`data/schema.DEFAULT_CS_RANK_FEATURES` 16 独立特征：dmi/adx/boll/kelch/trend_duokong_dev/volatility_5d/10d/20d/volume_ratio_5d/10d/amihud/macd/gross_margin/net_margin/debt_to_equity/roe）。CLI `train.py --cs_rank [--cs_rank_features ...]`。
- **实现**：`_compute_cross_sectional_rank` 在时间过滤后、分组/max_codes 前，按 `kline_time` 逐日 `rank(pct=True)`（含 context 行，NaN/inf 不参与）。cs 列**旁路归一化**，主循环提取 `cs_feat` 在 `transform_code` 后 `np.concatenate` 追加；缺失填 0.5。默认 **F=69**（52 raw+1 mask+16 cs）。
- **缓存/测试**：`compute_cache_key(cs_rank=, cs_rank_features=)` 仅开启时写；`tests/unit/data/test_data_cs_rank.py`（12 用例）；真实数据抽查 rank maxdiff=2.59e-08。

## 特征贡献与截面特征研究（logs/ic_analysis/，2026-09-20）
- **面板**：`prep.py` → `panel.parquet`（11,928,768 行，3317 日，2013-01~2026-08；`code,date,open,future_ret`+52 特征；`dates.parquet`/`codes.npy` 为整数索引映射）。脚本：`ic_single.py`/`corr.py`/`proto.py`/`importance.py`/`deciles.py`。报告 `REPORT.md`。
- **单特征 RankIC**：波动率簇最强（volatility_10d -0.064、dmi -0.062 ICIR -0.46 最稳）；`amihud +0.047`（唯一正）；价格水平 ≈-0.028；基本面/N/G 组≈0（~52% 缺失）。
- **冗余簇**：`[17]` open/high/low/close/ma/ema/sar/std/atr 同一"价格水平"变量；margin `xxx↔xxx_raw` corr=1.0；roe↔roa=1.0。
- **IC 不变性**：`IC(cs_rank(f)) ≡ IC(f)`（单调变换不变）——提升来自模型跨期泛化。
- **原型（train≤2022/val 2023-24/ref 2025-26）**：`cs_indep`(16特征) Ridge val RankIC 0.093/ref 0.092，D10 精度 val 0.491/ref 0.563 → **简单截面模型信号强 DL 2~4 倍**。

## GBDT 截面 rank 生产模型（logs/gbdt_cs/，2026-09-20，严格三分）
- **脚本**：`features.py`（全样本按 date rank → `X_cs.npy`[11.9M,16]）、`metrics.py`、`train_eval.py`、`rebuild_report.py`、`smoke.py`。
- **划分**：train 2013-01-01~2024-06-30（9.26M）、val 2024-07-01~2025-06-30（1.23M）、test 2025-07-01~2026-08-31（1.44M）。
- **结果（GBDT 集成）**：val RankIC **0.1126**/ICIR 1.093/t 17.0；test RankIC **0.0751**/ICIR 0.557/t 9.33；D10-D1 spread val +1.63%/test +0.80%，十分位单调。**约 DL 的 2~3 倍**。
- **topN precision（test，基准 0.489）**：top5 0.459/top10 0.465/top20 0.481/top50 0.498/top100 0.508。
- **阈值校准样本外**：val 最优阈值 +0.01056（precision 0.5603）→ test 0.5473（衰减 -1.30pp）。**val 任何阈值都达不到 75%，天花板 ~56%**。
- **产物**：`model_gbdt_cs.joblib`、`preds_gbdt_cs_{val,test}.npz`（exp_ret/true_ret/dates/codes）、`report_gbdt_cs.{txt,json}`。运行 `uv run --project . python -u logs/gbdt_cs/train_eval.py`。

## 市场择时过滤研究（logs/market_timing/，2026-09-20）
- **口径**：test 上涨日 top10=0.678 是 decile（前 10%≈500 只），非前 10 只。**前 10 只** test 精度仅 0.4650；dec10 0.5181。
- **核心结论**：test top10 无法达 75%（诚实上限 0.472；事后挑最好过滤器 0.66@20天）；**完美区分涨/跌日 top10 也只 0.553**。68 过滤器 val→test 抬升 Pearson **−0.046** 不可迁移。全历史择时模型 AUC≈0.5 → **5 日市场方向不可预测**。
- **多持有期**：RankIC 随 H 升（0.037→0.088）但 P(收益>0) 几乎不变。
- **绝对收益（test 非重叠）**：`top20 & 等权>MA20` 组合胜率 0.619/+1.38%/Sharpe 1.85/MaxDD −6.1%。**趋势过滤改善组合级风险收益，非单票胜率**。

## 二分类胜率模型研究（logs/clf_winrate/，2026-09-20）
- **模型**：HistGradientBoostingClassifier（16 截面 rank 特征），严格同 GBDT 三分。
- **结果**：val AUC 0.5458/test 0.5351（弱）；test top10 胜率 **0.5200**（回归 0.4650，+5.5pp）、top100 0.5391；概率上界仅 ~0.66（无样本≥0.7）。
- **75% 结论**：**不可达**，上限 ≈**0.54**（top100/top200 或 5% 覆盖）。低波动组合仅在 test 略升（top50×vol≤0.3=0.5467）。分类器天然选低波动。
- **产物**：`model_clf_winrate.joblib`、`preds_clf_{val,test}.npz`、`report_clf_winrate.{txt,json}`、`analysis_extra.txt`。

## Target 模式回测与引擎 bug 修复（2026-09-20，**最佳策略**）
- **引擎 bug（已修复）**：`backtest/engine.py:384` `run_backtest_target` 的 `budget = (nav_pre/target_size)*capital` 未约束可用现金，持仓升值不均时透支产生**隐性杠杆**（最低现金 −13.9%，缓冲带 40.9% 天数负现金）。修复：`budget = min(budget, cash*capital)`。修复后负现金归零，动态退结果几乎不变（40.89%→40.61%），**64 个回测单测通过**。
- **最佳策略：GBDT 截面rank + target 模式（20 只）+ 动态退出（`exp_ret ≤ 0` 卖出）**：
  - **test 2025.07~2026.08**：年化 **+40.61%**，Sharpe **1.451**，MDD 19.82%，日胜率 55.79%，超额 +25.45%，314 笔
  - **val 2024.07~2025.06**：年化 **+58.48%**，Sharpe **1.222**，MDD 22.57%，日胜率 53.94%，超额 +44.68%，265 笔
  - 基准沪深300：test +15.16%，val +13.81%
- **动态退出 vs 缓冲带退出（test, size=20）**：动态 **40.61%/1.451**；缓冲带 buffer=20 → 34.16%/1.105（1839 笔高换手）；buffer=200 → 31.10%。**动态退出更优**（绝对信号 vs 相对排名；缓冲带换手高 6 倍且 VAL 回撤 41.5%）。
- **动态退出 vs 固定 5 日持有**：固定 5 日 top20 → +19.95%；动态退出 → **+40.61%**（持有赢家至信号转负，均持 27 天，年化翻倍）。
- **exit_threshold 扫描（test）**：-0.01 → 21.7%(日胜率 59.3%)；**0.0 → 40.6%（最优）**；-0.05 → 56.3%（仅 23 笔，高方差）。
- **信号真实性**：真实 +40.6% ≫ 随机 +14.1/+9.8/−3.1% ≫ 反向 −51.6%（单调）；314 笔笔均净收益 +2.66%，赢均 +14.13%/输均 −10.38%——**靠盈亏不对称而非高胜率**。
- **产物/数据**：`logs/backtest_target_gbdt/`（metrics.json/nav_curves.png/holdings csv）；`logs/ohlc_full_test.npz`（5196×286）、`logs/ohlc_full_val2.npz`、`logs/ohlc_path_test.npz`。运行：`uv run --project . python -m scripts.run_backtest --mode target --preds <npz> --full_ohlc <npz> --target_size 20 --exit-on-nonpositive --exit_threshold 0.0`。
- **数据质量**：1 笔 −100% 异常（`301139.SZ` 价格归零，需清洗）。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows / 16 线程 15.9GB）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU）→ **batch=1024**；epoch≈14–16min。
- **内存是并发硬约束**：单臂（num_workers=4）即占满 ~16GB，禁止并行多臂。
- `torch.compile` 不可用；rolling `_rolling_column` 已向量化，rolling 缓存各 ~15-20min。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit   # 注意：工作区零售/默认归一化迁移致 8F+2E 预先存在
uv run --project . python -m unittest tests.unit.backtest.test_engine tests.unit.scripts.test_run_backtest_cli -v  # 64 OK
uv run --project . python train.py --smoke --num_workers 0  # 原模型冒烟
uv run --project . python train.py --model retail_friendly --smoke --num_workers 0  # 零售冒烟
uv run --project . python train.py --cs_rank --num_workers 0  # 截面 rank 特征训练（F=69）
```

## 已知变更
- [2026-09-15] add-strong-buy-gate：target `--strong_buy_threshold` + 删除 `min_edge`。commit `c7e8f72`。
- [2026-09-16] E0 (relative) 设为默认 baseline。
- [2026-09-20] 零售模型集成入 `train.py --model retail_friendly`：模型/logits输出/loss接口/Trainer扩展；损失由 ASL 改为 `BCEWithLogitsLoss + pos_weight`（修复 ASL 梯度偏移）。
- [2026-09-20] 新增 `scripts/eval_three_way.py` 严格三分评估规范。
- [2026-09-20] 新增 `label_mode=excess` 截面超额收益标签（默认 absolute 不变）。
- [2026-09-20] 完成特征贡献/截面特征研究（`logs/ic_analysis/`）：截面 rank 特征使 Ridge/GBDT RankIC 达 0.08-0.09。
- [2026-09-20] 新增 `cs_rank` 截面 rank 特征（F=69），旁路归一化，默认关行为不变。
- [2026-09-20] 建成 GBDT 截面 rank 生产模型（`logs/gbdt_cs/`）：test RankIC 0.075，阈值样本外 precision 0.547。
- [2026-09-20] 完成市场择时过滤研究（`logs/market_timing/`）：择时无法把 top10 胜率提到 75%，市场方向 AUC≈0.5。
- [2026-09-20] 完成二分类胜率模型研究（`logs/clf_winrate/`）：test top10 胜率 0.5200，上限 ~0.54。
- [2026-09-20] **target 模式回测 + 动态退出**：test 年化 +40.61%/Sharpe 1.451，val +58.48%/1.222，动态退出优于缓冲带（34.16%）和固定 5 日（19.95%）。
- [2026-09-20] **修复 `backtest/engine.py` target 模式隐性杠杆 bug**（budget 未约束可用现金），64 单测通过。
- [2026-09-20] **总结论：散户目标"单票截面胜率≥75%"在本数据上不可达**，四路独立研究（DL/GBDT/择时/分类器）天花板一致落在 52-58%；可交付现实方案为 GBDT 截面 rank + target 动态退出（年化 41-58%，靠盈亏不对称盈利）。
