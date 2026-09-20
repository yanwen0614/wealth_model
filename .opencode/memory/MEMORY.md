# Project Memory

## 当前架构
- 唯一训练入口：`train.py`（支持 `--model cnn_transformer|retail_friendly`）。
- **默认归一化 = E0 (relative)**（`config/defaults.py` `NORMALIZE="relative"`，`SCALER_PATH=None`；`data/dataset.py` `ParquetDataConfig.normalize="relative"`）。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（`RelativeScaler` E0 + `PerCodeGroupedScaler` E1）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`（原默认） + `models/retail_friendly/`（散户友好，`--model retail_friendly`）；训练：`training/`；损失：`criterion/`（原）+ `models/retail_friendly/loss.py`（RetailLoss）；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`（`--full` 出全期日频矩阵）；`scripts/run_backtest.py`（rolling/target 回测 + 指数基准 + 强买门槛）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联。
- 三分评估：`scripts/eval_three_way.py`（严格 train/val/test 对比 + 阈值样本外校准，见下）。
- **GBDT 引擎**：已安装 `xgboost==3.4.1`（GPU 版，`USE_CUDA=True`，CUDA 13.3 构建），替代原 `sklearn.ensemble.HistGradientBoostingClassifier/Regressor` 作为后续 GBDT 生产引擎。

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
- **推荐标准划分**（满足 train≥8y/val≥1y/test≥1y）：train `2013-01-01~2024-06-30`（11.5y）、val `2024-07-01~2025-06-30`（1y）、test `2025-07-01~2026-08-31`（1.17y）。test 280 交易日 / val 242 交易日。
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
- **面板**：`prep.py` → `panel.parquet`（11,928,768 行，3311 日，2013-01~2026-08；`code,date,open,future_ret`+52 特征；`dates.parquet`/`codes.npy` 为整数索引映射）。脚本：`ic_single.py`/`corr.py`/`proto.py`/`importance.py`/`deciles.py`。报告 `REPORT.md`。
- **单特征 RankIC**：波动率簇最强（volatility_10d -0.064、dmi -0.062 ICIR -0.46 最稳）；`amihud +0.047`（唯一正）；价格水平 ≈-0.028；基本面/N/G 组≈0（~52% 缺失）。
- **冗余簇**：`[17]` open/high/low/close/ma/ema/sar/std/atr 同一"价格水平"变量；margin `xxx↔xxx_raw` corr=1.0；roe↔roa=1.0。
- **IC 不变性**：`IC(cs_rank(f)) ≡ IC(f)`（单调变换不变）——提升来自模型跨期泛化。
- **原型（train≤2022/val 2023-24/ref 2025-26）**：`cs_indep`(16特征) Ridge val RankIC 0.093/ref 0.092，D10 精度 val 0.491/ref 0.563 → **简单截面模型信号强 DL 2~4 倍**。

## GBDT 截面 rank 生产模型（logs/gbdt_cs/，2026-09-20，严格三分）
- **脚本**：`features.py`（全样本按 date rank → `X_cs.npy`[11.9M,16]）、`metrics.py`、`train_eval.py`、`rebuild_report.py`、`smoke.py`；另有 `rolling_backtest.py`。
- **划分**：train 2013-01-01~2024-06-30（9.26M）、val 2024-07-01~2025-06-30（1.23M）、test 2025-07-01~2026-08-31（1.44M）。
- **结果（GBDT G3 集成3）**：val RankIC **0.1126**/ICIR 1.093/t 17.0；test RankIC **0.0751**/ICIR 0.557/t 9.33；D10-D1 spread val +1.63%/test +0.80%，十分位单调。**约 DL 的 2~3 倍**。
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

## 集成·共识·组合策略研究（logs/ensemble/，2026-09-20，**胜率最优可交付**）
- **脚本/产物**：`common.py`（对齐/指标/共识/组合）；`run_integration.py`（§1 集成 §2 stacking §3 共识）、`run_walkforward.py`（§4）、`run_wf_consensus.py`（WF-OOS 共识校准）、`run_weighting.py`、`run_portfolio.py`；`probe_best.py`/`probe_segments.py` 诊断；报告 `report_*.{txt,json}` + `REPORT.md`。
- **信号对齐**：gbdt/clf preds 行序完全一致（date/code/true_ret 相同），直接列拼接；DL 仅 test 覆盖（97.5%，`eval_preds_52cls`+`preds_relative_*`），**无 val 覆盖**。
- **集成结论**：rank 集成把 RankIC 抬到 0.082 但**降 topN 胜率**（reg 极端=高波动低胜率）；**clf 单信号最强**（test top100 0.5391）；stacking（LR/Ridge）**不如 clf 单模型**；DL 三路共识 2025H2 0.63→2026 0.52（DL top100 跌破基准 0.4525），**不可用**。
- **共识（WF-OOS）**：val 覆盖率≤50 只/日选 `reg>30%&clf>1%`（val 0.5594）→ test **0.5438**（衰减 -1.6pp）；规则网格 val/test 胜率 Spearman 0.80。**单纯共识天花板 ~0.544，不过 0.55**。
- **Walk-forward**：扩展窗口（锚 2013，预测 2019–2026）test clf top10 0.5350/top50 0.5440/top100 0.5432，优于单次训练（0.5200/0.5362/0.5391），逐年更稳；**生产建议用 WF 刷新**。
- **样本加权**：`hl=1095d`（3 年）test top10 0.5450（baseline 0.5164）；`hl=365d` 显著变差（过拟合近期）。
- **最优可交易策略**：`WF-OOS reg>30%&clf>1% + 宽度过滤(站上MA20股占比>50%)` → test **单票胜率 0.5904**（val 0.5843）、组合胜率 0.697、年化 +27.3%、Sharpe 1.89、MaxDD -9.2%（132 天×~50 只）。四段稳定：2024H2 0.554/2025H1 0.607/2025H2 0.602/2026 0.574。
- **总结论**：集成/共识到不了 0.55；**>0.55、逼近 0.60 靠「高宽度日才推荐」的市场状态过滤**（覆盖 ~47% 交易日）；整体 0.59，仅个别半年破 0.60；**0.75 仍不可达**。

## Target 模式回测与引擎 bug 修复（2026-09-20，**最佳绝对收益策略**）
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

## 多周期 × 多标签扫描（logs/horizon_target/，2026-09-20）
- **脚本**：`common.py`（复用 `gbdt_cs/X_cs.npy` 16 截面 rank 特征 + 由 panel open 重算 `ret_H=open[t+1+H]/open[t+1]-1`，缓存 `returns.npz`）；`run_scan.py`（`--stage horizon|label`，增量写 `results.json`/`preds/`）；`report.py`、`analyze_best.py`、`summary_table.py`；报告 `REPORT.md`。单种子 G3 每次拟合 ~100-240s。
- **H ∈ {1,3,5,10,20,60} × 标签 {reg, excess, rank, thr_{0,1,2,5}%}**（24 组合），严格三分同 gbdt_cs。
- **关键结果（test 单票胜率 P(ret>0)，基准→top10/top100）**：
  - H60_thr_5 表面最高：0.4421→0.5813/0.5489，但 **test 仅 219 日/60≈3.6 独立窗口，非重叠篮子甚至不如随机 → 不可信**。
  - **可信最高：H20_rank 0.4800→0.5529/0.5338；H5_rank 0.4896→0.5511/0.5422**（两半年超额稳定 +5~8pp）。
  - 短中期 **rank（截面百分位回归）目标最优**；excess 无稳定增益；高阈值二分类短周期反而变差。
- **75% 结论：仍不可达**。val 冻结阈值 → test 最高 precision **0.6557（H5_rank，n=122，≈0.45 只/日）**；test 事后 oracle 上限 0.6408；实用 topN ≈0.55。
- **绝对收益（test，非重叠 H 日，topN 等权）**：H5_rank top10 年化 **+90.3%/Sharpe 3.01/MDD -13.0%**（55 笔，随机基准 +21.9%，偏移稳健 +94.6%）；top100 +37.0%/1.70。H20_rank top10 +44.7%/2.61（仅 13 笔）。收益靠盈亏不对称而非高胜率。
- **口径坑**：panel 在 prep 时已丢弃 `future_ret(5)` 非有限行，故重算尾部 `ret_H` 少最后 ~6 行/股（仅样本量微减，无泄露）；41/11.9M 行与 panel future_ret 不一致（open≤0 异常）。长周期指标受**重叠窗口**严重高估，须用非重叠/偏移稳健复核。

## 滚动重训多模型对比（logs/rolling_models/，2026-09-20，**最佳滚动收益：GBDT+Ridge 集成**）
- **协议**：expanding window（初始训练 2013-01~2022-12，每 6 个月重训，链式 OOS 2023-01-03~2026-08-21 共 881 日），与 `logs/gbdt_cs/rolling_backtest.py` 完全一致；输出 npz 与 GBDT 版本**行序严格对齐**（可直接 rank 集成）。脚本 `common.py`/`run_ridge.py`/`run_clf.py`/`run_ens.py`/`run_backtests.py`/`threshold_scan.py`/`evaluate.py`/`analyze.py`，报告 `REPORT.md`。
- **模型**：Ridge(`alpha=30, solver=cholesky`, 目标各窗 0.5/99.5 截尾, 确定性单 seed, ~4s/折)；分类器(`HistGradientBoostingClassifier` 同 GBDT 超参, y=(ret>0), 1 seed, ~200-340s/折, 共 34min)；集成 = GBDT+Ridge 逐日截面 pct rank 等权平均。
- **滚动 RankIC（整体）**：分类器 **0.0980**/ICIR 0.715 > 集成 0.0969/0.580 > Ridge 0.0910/0.530 > GBDT 0.0878/0.614。分年度全部为正（2023/2025 最强 ~0.10-0.11，2024/2026 较弱 ~0.07-0.09），无某年暴雷。
- **回测（target + 动态退出，阈值 GBDT/Ridge=0.0、分类器/集成=0.5）**：**集成全面最优**——size=20 年化 **+45.44%**/Sharpe **1.416**/MDD 34.8%/日胜率 0.5711；size=50/100/200 +39.8/35.5/35.3%、Sharpe 1.2-1.3。单模型：Ridge size=100 +27.39%/Sharpe **1.106**/MDD 34.8%（风险调整最优、仅 242 笔）；分类器 size=100 +28.25%/1.030；GBDT size=200 +28.61%/0.990（size=20 MDD 55% 最差）。基准沪深300 年化 +5.06%/Sharpe 0.369。
- **阈值敏感性**：集成 0.40~0.60 → 年化 34~51%、Sharpe 1.17~1.66（0.40 最优 +51.2%/1.655 但换手更低），结论稳健。
- **集成以两路为限**：加入分类器的三路集成降到 size=20 +32.8%/Sharpe 1.102（`preds_rolling_ens3.npz`），分类器与回归信号重叠、稀释收益。
- **产物**：`preds_rolling_{ridge,clf,ens,ens3}.npz`、`backtest_summary.json`、`nav_curves.npz`、`threshold_scan.json`、`ic_summary.json`、`folds_*.json`。运行顺序：`run_ridge.py` → `run_clf.py` → `run_ens.py` → `run_backtests.py` → `evaluate.py` → `analyze.py`。

## 风险控制 Overlay 研究（logs/risk_overlay/，2026-09-20，**MDD 55.4%/37.8% → <25%**）
- **引擎**：`logs/risk_overlay/common.py` 自包含复刻 `run_backtest_target` + overlay 钩子（`market_ok`/`riskoff_action=hold|clear`/`clear_when`/`cash_cooldown`/`size_sched`/`exposure`/`stop_loss_pct`/`dd_control`）；overlay 全关时与引擎逐日净值 **maxdiff=0**，未改 `backtest/engine.py`，64 单测通过。`prepare_decisions` 预排序缓存使单次回测 30s→1.7s。
- **数据/口径**：`logs/gbdt_cs/rolling/preds_rolling.npz` + `logs/ohlc_full_rolling.npz`，2023-01~2026-08（887 日），无 val/test；信号（指数 MA10/20/60、市场宽度=站上各自 MA20 股占比、指数 20 日年化波动率）全部只用 ≤T 信息。
- **基准**：size20 年化 10.77%/MDD 55.4%；size200 28.61%/37.8%；沪深300 5.06%/24.8%。回撤几乎全部来自 2023-2024 下跌/小盘崩盘（size20 2023 −17%、2024 −9%）。
- **最有效 overlay = 指数 MA 趋势过滤（hold=风险关闭日停买不清仓）**：MA40~80 是宽平台（非刀尖）。`MA40_hold` size20 年化 **35.5%**/MDD **24.2%**/Calmar 1.47；size200 **34.7%**/21.8%/1.59。`MA60_hold` 30.7%/−23.6% 与 29.6%/22.8%。**免费降回撤**（2024 由 −9%→+38~70%）。
- **最低回撤**：`MA60 + 指数20日波动率≤25%` → MDD **19.9%(size20)/20.9%(size200)**，年化 29.6%/27.7%；再加宽度 50% → MDD 18.0%，Calmar 1.58。
- **无效/有害**：①组合净值回撤控制（dd_half 年化掉到 6.5-8.9%、MDD 仅降到 36-39%；dd_zero/clear 卡死在现金，均现金 89-92%、年化≈0）；②个股止损（size200 MDD 反升到 41-43%、换手翻倍，截面 rank 常砍在回撤后反弹的票）；③纯波动率目标（几乎无效，仅与趋势组合有边际增益）。`clear` 不如 `hold`（换手 2-4x、胜率 52%→25%）。
- **空仓专项（`run_cash.py`）**：清仓能把 size200 MDD 压到 ~20%（clear_ma60 20.4%/clear_ma10 20.2%）但年化掉到 17.6-20.0%、2023/2026 转负；size20 清仓 MDD 24.7-30.5% 反而差于 hold 23.6%。高频信号（MA120/宽度/波动）做二级清仓换手 204-244 倍不可用（须配冷却 cd3/cd10）。**降暴露优于清仓**：size200 `hold_ma60_cf3`（停买+3日再入确认）四年全正/每年 MDD≤21%/年化 27.5%；size20 `expo_ma60_br45`（宽度连续降暴露）+27.3%/MDD 23.3%；size200 版 +24.8%/20.7%。
- **结论**：MDD 可降至 <25%（甚至 <20%），趋势过滤近乎免费；代价仅 2026 少赚上行 + 31~48% 平均现金。**仅一段、仅含 2024H1 一次崩盘，whipsaw 风险需警惕**。
- **产物**：`common.py`/`run_overlays.py`/`run_sensitivity.py`/`run_final.py`/`run_cash.py`/`run_check.py`/`verify.py`/`report.py`；`REPORT.md`、`report_{overlays,sensitivity,final,cash}.json`、`navs_final.npz`、`nav_curves_20.png`。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows / 16 线程 15.9GB）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU）→ **batch=1024**；epoch≈14–16min。
- **内存是并发硬约束**：单臂（num_workers=4）即占满 ~16GB，禁止并行多臂。
- `torch.compile` 不可用；rolling `_rolling_column` 已向量化，rolling 缓存各 ~15-20min。
- GBDT（HistGB, 9M×16）单折训练 90–460s（受并发影响）；WF 8 折 ×2 模型约 30min；`panel.parquet`≈1.9GB、`X_cs.npy`≈763MB、`logs/feature_eng/X_all.npy`≈4.05GB。
- 特征工程实验内存技巧：`X_all.npy` 用 memmap 按列读取 + 逐 split 填充，避免 n×k 大矩阵（89 列全集会到 ~8GB）。
- **xgboost GPU 加速**：`xgboost==3.4.1` `USE_CUDA=True`，CUDA 13.3 构建。`device='cuda'` 参数用 GPU 训练，预期显著加速原 HistGB（90–460s/折）训练时间。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit   # 注意：工作区零售/默认归一化迁移致 8F+2E 预先存在
uv run --project . python -m unittest tests.unit.backtest.test_engine tests.unit.scripts.test_run_backtest_cli -v  # 64 OK
uv run --project . python train.py --smoke --num_workers 0  # 原模型冒烟
uv run --project . python train.py --model retail_friendly --smoke --num_workers 0  # 零售冒烟
uv run --project . python train.py --cs_rank --num_workers 0  # 截面 rank 特征训练（F=69）
# 集成研究（logs/ensemble/）
uv run --project . python -u logs/ensemble/run_integration.py
uv run --project . python -u logs/ensemble/run_walkforward.py
uv run --project . python -u logs/ensemble/run_wf_consensus.py
uv run --project . python -u logs/ensemble/run_portfolio.py
uv run --project . python -u logs/ensemble/probe_best.py
# 特征工程（logs/feature_eng/）
uv run --project . python -u logs/feature_eng/build_features.py      # ~11 min
uv run --project . python -u logs/feature_eng/evaluate.py --sets base16,base16_mom --n_seeds 3
uv run --project . python -u logs/feature_eng/feature_ic.py
uv run --project . python -u logs/feature_eng/marginal.py
uv run --project . python -u logs/feature_eng/forward_select.py
uv run --project . python -u logs/feature_eng/winrate_analysis.py --preds logs/feature_eng/preds_base16_mom.npz
# 滚动模型对比（logs/rolling_models/，依次执行）
uv run --project . python -u logs/rolling_models/run_ridge.py
uv run --project . python -u logs/rolling_models/run_clf.py    # 默认 3 seed ~80min；ROLLING_SEEDS=42 单 seed ~34min
uv run --project . python -u logs/rolling_models/run_ens.py
uv run --project . python -u logs/rolling_models/run_backtests.py
uv run --project . python -u logs/rolling_models/evaluate.py
uv run --project . python -u logs/rolling_models/analyze.py
# 风险 overlay（logs/risk_overlay/）
uv run --project . python -u -m logs.risk_overlay.run_check         # 与引擎一致性自检
uv run --project . python -u -m logs.risk_overlay.run_overlays      # 主扫描 ~4min
uv run --project . python -u -m logs.risk_overlay.run_sensitivity
uv run --project . python -u -m logs.risk_overlay.run_final
uv run --project . python -u -m logs.risk_overlay.run_cash          # 空仓专项
uv run --project . python -u -m logs.risk_overlay.report
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
- [2026-09-20] 完成集成/共识/组合策略研究（`logs/ensemble/`）：集成与 stacking 不如 clf 单信号；共识天花板 0.544；`clf 共识 + 宽度过滤` 把 test 单票胜率做到 0.5904（四段稳定 0.55-0.61）；DL 无 val 覆盖且 2026 失效不可用。
- [2026-09-20] **target 模式回测 + 动态退出**：test 年化 +40.61%/Sharpe 1.451，val +58.48%/1.222，动态退出优于缓冲带（34.16%）和固定 5 日（19.95%）。
- [2026-09-20] **修复 `backtest/engine.py` target 模式隐性杠杆 bug**（budget 未约束可用现金），64 单测通过。
- [2026-09-20] **总结论：散户目标"单票截面胜率≥75%"在本数据上不可达**，五路研究（DL/GBDT/择时/分类器/集成共识）天花板一致落在 52-59%；可交付现实方案：胜率优先 = clf 共识 + 宽度过滤（单票 0.59/组合 0.70），收益优先 = GBDT target 动态退出（年化 41-58%，靠盈亏不对称盈利）。
- [2026-09-20] **特征工程实验（`logs/feature_eng/`，两轮独立复现一致）**：脚本 `fe_common/build_features/evaluate/feature_ic/marginal/forward_select/winrate_analysis/redundancy.py`，报告 `REPORT.md`，数据 `X_all.npy`[11.9M,89]=52 raw cs-rank+32 时序衍生+5 rank 交互（4.05GB）。严格三分 + GBDT G3（单种子/3种子集成）+ 对照 Ridge。
  - **RankIC 无提升**：cs52 test 0.0612/0.0623 < base16 0.0748/0.0751；base16_price（价格水平 `x/close-1` 再 rank）0.0712；base16_volchg 0.0737；base16_trend 0.0684；base16_ix 0.0744；all(89) 0.0657；derived_only 0.0624。只有 **base16+7 动量** test 0.0756（+0.0005，持平）；Ridge 侧 base16 0.0746 为最优，加任何衍生组双降。**test RankIC 天花板 ~0.076**。
  - **单特征 IC**：最有价值衍生 = `rel_close_ma_60`(-0.058)/`hl_range`(-0.057)/`rel_atr`(-0.052)/`mom_20`(-0.046)/`dmi_adx_diff`(-0.046)，但 val IC 衰减 ~35%；`ix_vol10_vol5`(-0.065) 与 vol 共线。边际分析（Ridge base16 逐个加）**无任何单特征 test 增量 >0.0012**，val 上最优的 `d_mom_20`(+0.0039) test 为 -0.0003。
  - **val 选择不可信/过拟合**：贪心前向选择 53→7 特征 val Ridge IC 0.1389（>基线 0.1211）→ test 0.0682（<基线 0.0746）；窄阈值 val 0.6748(n=123) → test 0.5374（-13.7pp）。
  - **胜率有实质提升（新）**：`base16_mom`（16+7 动量）GBDT 集成3 + val 冻结阈值（min_n=50，thr≈0.01087）→ **test 单票胜率 0.5688**（val 0.5665，衰减 +0.23pp，n=12573≈45 只/日），同协议基线 0.5473（**+2.15pp**）；val 精度曲线在 n=12k~30k 平坦 0.565~0.569。**top10 0.465→0.5093（+4.4pp）、top20 +2.0pp、top100 +0.1pp**——增益只在 5~10 只头部。对照：Ridge(base16) topN 强（test top100 0.5372/top10 0.5289）但其阈值策略过拟合崩溃（0.5374）。
  - **结论**：**特征工程只雕出 ~2pp 胜率（0.547→0.569），不能推高 RankIC 天花板；base16 仍是 RankIC 最优特征集，胜率最优为 base16+7动量**；冗余（ix_vol10_vol5↔volatility_5d 0.925、d_rel_close_ma_60↔dmi 0.778、d_mom_20↔dmi 0.757、d_hl_range↔kelch 0.623）是其失效主因；X_all 的 base16 列与 `logs/gbdt_cs/X_cs.npy` 完全一致（maxdiff 0）。
- [2026-09-20] **滚动重训多模型对比（`logs/rolling_models/`）**：同 expanding window 协议下，GBDT+Ridge 截面 rank 集成全面最优（size=20 年化 +45.4%/Sharpe 1.416/MDD 34.8%，阈值敏感性 0.40-0.60 稳健）；单模型 Ridge 风险调整最优（size=100 +27.4%/1.106）；分类器滚动 RankIC 最高 0.098 但回测与 Ridge 相当；三路集成（+分类器）反而降到 +32.8%。**收益优先选 GBDT+Ridge 集成，低换手选 Ridge 单模型**。
- [2026-09-20] **风险控制 overlay 研究（`logs/risk_overlay/`）**：指数 MA 趋势过滤（MA40~80，hold）把 MDD 55.4%/37.8% 降到 24.2%/21.8% 且年化升至 35.5%/34.7%（近乎免费）；`MA60+vol≤25%` MDD 19.9%/20.9%；组合净值回撤控制/个股止损/纯波动率目标均无效或有害。产物 `REPORT.md` + JSON + 自包含 overlay 引擎（与引擎 maxdiff=0）。
- [2026-09-20] **空仓专项（`logs/risk_overlay/run_cash.py`）**：清仓能把 size200 MDD 再压到 ~20% 但收益腰斩且 2023/2026 转负；size20 清仓不如 hold；高频信号做二级清仓换手 204-244x 不可用（需冷却）；**降暴露（hold+再入确认/连续 exposure）优于清仓成空仓**。
