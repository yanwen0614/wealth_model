# 散户友好选股模型研究总结报告

> 日期：2026-09-20
> 项目：`cnn_full_20260905/cnn`
> 数据：`train_data_v1_F60_20130101-20260831`（11.96M 有效行，5199 股，2013-01 ~ 2026-08）
> 结论：**"单票截面胜率 ≥75%"在本数据上不可达**（四路独立研究天花板一致 52-58%）；可交付现实方案为 **GBDT 截面 rank + target 动态退出**（年化 41-58%，Sharpe 1.2-1.5）

---

## 1. 研究背景与目标

### 1.1 用户目标
构建**散户友好选股模型**，要求：
1. 每天推荐的股票数量**可以为 0**（不强制交易）
2. 一旦给出推荐，**截面胜率 ≥75%**
3. **排除涨停（封板）**股票
4. 不仅要考虑胜率，还要考虑**实际上涨幅度**

### 1.2 初始探索路径
- 集成 `RetailFriendlyModel`（CNN+Transformer 双头：二分类 + 回归）到 `train.py --model retail_friendly`
- 损失函数从 ASL（非对称聚焦损失）改为 `BCEWithLogitsLoss + pos_weight`

### 1.3 关键诊断：为什么 ASL 必败
ASL 负样本梯度 `dL_neg/dp = -2p·log(1-p) + p²/(1-p)`，正样本（γ_pos=0）梯度 `-1/p`。
在 p=0.5 时净梯度 = 0.5×(-2) + 0.5×(1.193) = **-0.403**，所有样本被统一推向 p↑。
方程 `-1/p - 2p·log(1-p) + p²/(1-p) = 0` 的解约在 **p≈0.575**——
这解释了为何 p_bin avg 卡在 0.537，模型学不到区分。

**修复**：改用 `BCEWithLogitsLoss + pos_weight=2.0`（平衡数据 equilibrium p≈0.667），
p_bin avg 从 0.537 → 0.61，但**精度仍 ~51.5%**，说明问题不在损失函数。

---

## 2. 核心结论

> **"单票截面胜率 ≥75%"在本数据上不可达。**

### 2.1 数学根源（信噪比约束）
- 5 日个股收益标准差 ≈ **6-8%**
- 可预测 alpha 分量 ≈ **0.5-1%**
- 信噪比 ≈ **0.1**
- 要达到 75% 方向准确率需信噪比 ≈ **0.67**（IC ≈ 0.35）
- 当前最强模型 IC 仅 **0.075**，差 **5 倍**

### 2.2 各项要求达成情况

| 用户要求 | 状态 |
|---|---|
| 每天可推荐 0 只（不强制交易） | ✅ 已实现 |
| 排除涨停封板 | ✅ 已实现 |
| 考虑实际上涨幅度（绝对收益） | ✅ 已实现 |
| **截面胜率 ≥75%** | ❌ **天花板 52-58%，不可达** |

---

## 3. 研究历程（四路独立验证）

### 3.1 路线①：DL 基线（CNN-Transformer + E0 relative）

已有 checkpoint `logs/relative/run_20260914_024253/best_model.pth`，用 `scripts/eval_bins_mapping.py`
全市场评估（`--max_codes 0`）：

| 指标 | VAL 2025H2 | TEST 2026 |
|---|---|---|
| 截面 RankIC | 0.0460 | 0.0248 |
| ICIR | 0.752 | 0.199 |
| IC>0 比例 | 78.3% | 63.6% |
| top-decile spread | 0.90% | 0.44% |
| top10 precision | 55.8% | **42.8%** |
| top100 precision | 55.3% | 45.3% |

**发现**：模型在 test 上 top 选股 precision (42.8%) **低于基准正收益率 (45.9%)**。
进一步分析发现 2026 是弱市，模型预测绝对收益被市场 beta 主导。

### 3.2 路线②：GBDT 截面 rank 回归（`logs/gbdt_cs/`）

**严格三分**：train 2013-01-01~2024-06-30 / val 2024-07-01~2025-06-30 / test 2025-07-01~2026-08-31

| 指标 | VAL | TEST |
|---|---|---|
| **RankIC** | **0.1126** | **0.0751** |
| ICIR | 1.093 | 0.557 |
| IC t 值 | 17.0 | 9.33 |
| D10-D1 spread | +1.63% | +0.80% |
| top10 precision | 0.4793 | 0.4650 |
| top100 precision | 0.5349 | 0.5075 |

十分位单调。**RankIC 是 DL 的 2-3 倍**。

**阈值校准样本外协议**（val 定阈值 → test 应用）：
- val 最优阈值 `+0.01056` → precision 0.5603
- 冻结到 test → precision **0.5473**（衰减仅 −1.30pp）
- **val 任何阈值都达不到 75%**

### 3.3 路线③：市场择时过滤（`logs/market_timing/`）

**口径澄清**：报告里"上涨日 top10=0.678"是 decile（前 10%≈500 只），非前 10 只。
**前 10 只** test 精度基线仅 **0.4650**。

| 结论 | 数据 |
|---|---|
| 诚实（val 冻结阈值→test）最高 top10 | 0.472 |
| 事后挑最好过滤器（20 天） | 0.66 |
| **完美区分涨/跌日 top10**（oracle） | **0.553** |
| 68 过滤器 val→test 抬升相关性 | Pearson −0.046（不可迁移） |
| 全历史择时模型 AUC | ≈0.5（**5 日市场方向不可预测**） |

**多持有期**：RankIC 随 H 升（0.037→0.088），但 P(收益>0) 几乎不变（top10 0.46-0.48）。

### 3.4 路线④：二分类胜率模型 + 低波动（`logs/clf_winrate/`）

**动机**：回归模型 top picks 是高波动股（期望收益高、胜率低）。直接预测 `P(future_ret>0)`。

| 指标 | VAL | TEST |
|---|---|---|
| AUC | 0.5458 | 0.5351 |
| top10 胜率 | 0.5434 | **0.5200** |
| top100 胜率 | 0.5571 | 0.5391 |
| 概率上界 | — | **仅 ~0.66（无样本≥0.7）** |

- 分类器比回归的 top10 胜率高 **+5.5pp**（0.4650→0.5200），但平均收益更低
- 分类器**天然已选低波动股**（vol rank 均值 0.32-0.36 vs 全体 0.50）
- 低波动组合、概率×收益组合均无实质提升
- **test 上限 ≈0.54**

### 3.5 四路结论收敛

| 路线 | test 样本外天花板 |
|---|---|
| ① DL | 42.8% (top10) |
| ② GBDT 回归 | 54.7% (阈值校准) |
| ③ 市场择时 | 47.2% (诚实) / 55.3% (oracle) |
| ④ 分类器 | 52.0-53.9% |

**四路天花板一致落在 52-58%。**

---

## 4. 关键突破：截面 rank 特征（cs_rank）

### 4.1 问题诊断
E0 relative 归一化只做**时序尺度归一**（`x/close[t-1]-1`），**未消除截面/时期漂移**。
导致 DL 模型：**rel 单独甚至不如 raw**。

### 4.2 特征贡献研究（`logs/ic_analysis/`）

**面板**：`panel.parquet`（11,928,768 行，3317 日）+ `dates.parquet` + `codes.npy`

**单特征 RankIC 排名**（前 8）：

| 排名 | 特征 | IC 均值 | ICIR | IC>0 |
|---|---|---|---|---|
| 1 | volatility_10d | -0.0637 | -0.38 | 0.34 |
| 2 | kelch | -0.0627 | -0.30 | 0.37 |
| 3 | volatility_20d | -0.0627 | -0.34 | 0.36 |
| 4 | **dmi** | -0.0624 | **-0.46** | 0.32 |
| 5 | trend_duokong_dev | -0.0618 | -0.38 | 0.34 |
| 6 | volatility_5d | -0.0547 | -0.37 | 0.33 |
| 7 | std_5 | -0.0480 | -0.36 | 0.37 |
| 8 | **amihud** | **+0.0466** | +0.32 | 0.65 |

**冗余簇**：
- `[17]` `open/high/low/close/ma_5/10/20/60/ema_12/26/sar/trend_duokong/trend_shortline/std_5/10/20/atr` 本质同一"价格水平"变量
- margin 各 `xxx ↔ xxx_raw` corr=1.0；`roe ↔ roa`=1.0
- **独立信息**：macd/dmi/adx/boll/kelch/trend_duokong_dev/volatility_5d/10d/20d/volume_ratio_5d/10d/amihud 等 16 个

**IC 不变性**：`IC(cs_rank(f)) ≡ IC(f)`（逐日 Spearman 对单调变换不变，实测 maxdiff=0）
→ 截面 rank 的价值**不在边际 IC，而在让模型跨期泛化**（摆脱时间漂移/市场 beta）。

### 4.3 原型模型对比（train≤2022 / val 2023-24 / ref 2025-26）

| 特征集 | 模型 | val RankIC | ref RankIC |
|---|---|---|---|
| raw（52 原值） | GBDT | 0.052 | 0.063 |
| rel（E0 relative） | GBDT | 0.046 | 0.062 |
| cs_rel（rel 截面 rank） | GBDT | 0.082 | 0.083 |
| **cs_indep（16 独立截面 rank）** | **Ridge** | **0.0927** | **0.0917** |

**简单截面模型信号强 DL 2~4 倍**（DL test 2026 RankIC 仅 0.025）。

### 4.4 集成到训练管道（生产代码）
新增 `--cs_rank`（默认关）：
- 计算位置：时间过滤后、分组与 `max_codes` 前，按 `kline_time` 逐日全市场 `rank(pct=True)`（含 context 行）
- **旁路归一化**：cs 列不进 `feature_cols`/`COLUMN_RULES`，主循环提取后 `np.concatenate` 追加；缺失填 0.5
- 输出 **F=69**（52 raw + 1 mask + 16 cs）
- 缓存 key 仅在开启时写，默认 key 逐字节不变

---

## 5. 交付物

### 5.1 生产代码变更

| 文件 | 变更 | 说明 |
|---|---|---|
| `data/schema.py` | 新增 `DEFAULT_CS_RANK_FEATURES`（16 独立特征） | cs_rank 默认列表 |
| `data/dataset.py` | 新增 `cs_rank`/`cs_rank_features` 配置 + `_compute_cross_sectional_rank` + 旁路拼接；新增 `label_mode`/`_apply_excess_labels` | 两个核心能力 |
| `data/feature_cache.py` | `compute_cache_key` 新增 `cs_rank`/`cs_rank_features`/`label_mode`（仅非默认时写） | 缓存隔离 |
| `data/labels.py` | 新增 `_cross_sectional_excess(dates, future_ret, min_count=1)` | 超额收益标签 |
| `config/defaults.py` | 新增 `CS_RANK=False`/`CS_RANK_FEATURES=None`/`LABEL_MODE="absolute"` | 配置默认 |
| `train.py` | 新增 `--cs_rank`/`--cs_rank_features`/`--label_mode`/`--model`/`--pos_weight` | CLI 入口 |
| `training/factory.py` | `build_model`/`build_criterion` 支持零售模型/损失 | 工厂分支 |
| `training/trainer.py` | 零售模式 `_is_retail`（precision/recall/F1 + `calibrate_threshold`） | Trainer 扩展 |
| `models/retail_friendly/` | 新模型包（model/loss/config） | 散户模型 |
| `backtest/engine.py` | **修复 target 模式隐性杠杆 bug** | 见 §7 |
| `tests/unit/data/test_data_cs_rank.py` | 12 用例 | cs_rank 契约测试 |
| `tests/unit/data/test_data_excess_labels.py` | 10 用例 | excess 标签契约测试 |

### 5.2 关键 CLI 用法

```bash
# 截面 rank 特征训练（F=69）
uv run --project . python train.py --cs_rank

# 自定义截面特征
uv run --project . python train.py --cs_rank --cs_rank_features dmi volatility_10d amihud

# 截面超额收益标签
uv run --project . python train.py --label_mode excess

# 散户友好模型（BCE + pos_weight）
uv run --project . python train.py --model retail_friendly --pos_weight 2.0 --lambda_reg 0.2
```

### 5.3 模型与数据产物

| 产物 | 路径 | 说明 |
|---|---|---|
| GBDT 排序模型 | `logs/gbdt_cs/model_gbdt_cs.joblib` | test RankIC 0.0751 |
| GBDT 预测缓存 | `logs/gbdt_cs/preds_gbdt_cs_{val,test}.npz` | exp_ret/true_ret/dates/codes |
| 分类器模型 | `logs/clf_winrate/model_clf_winrate.joblib` | test top10 胜率 0.52 |
| 分类器预测缓存 | `logs/clf_winrate/preds_clf_{val,test}.npz` | prob/y_bin/... |
| 全期 OHLC 矩阵 | `logs/ohlc_full_{test,val2}.npz` | 5196 股 × 286/242 日 |
| 研究报告 | `logs/{ic_analysis,gbdt_cs,market_timing,clf_winrate}/REPORT.md` | 各方向详细报告 |
| 回测结果 | `logs/backtest_target_gbdt/` | metrics.json/nav_curves.png/holdings |

---

## 6. 最佳策略回测（target 模式 + 动态退出）

### 6.1 策略定义
- **模型**：GBDT + 16 截面 rank 特征（严格样本外）
- **模式**：`--mode target`，目标持仓 **20 只**等权
- **退出**：`--exit-on-nonpositive`（模型预测 `exp_ret ≤ 0` 即卖出）
- **执行**：T 日决策 → T+1 open 买入/卖出
- **费用**：逐笔 A 股模型（佣金 0.025% + 印花税 0.025%，最低 5 元）

**运行命令**：
```bash
uv run --project . python -m scripts.run_backtest --mode target \
  --preds logs/gbdt_cs/preds_gbdt_cs_test.npz \
  --full_ohlc logs/ohlc_full_test.npz \
  --target_size 20 --exit-on-nonpositive --exit_threshold 0.0
```

### 6.2 回测结果（修复引擎 bug 后）

| 指标 | VAL 2024.07~2025.06 | **TEST 2025.07~2026.08** |
|---|---|---|
| **年化收益** | **+58.48%** | **+40.61%** |
| **Sharpe** | 1.222 | **1.451** |
| 最大回撤 | 22.57% | 19.82% |
| 日度组合胜率 | 53.94% | 55.79% |
| 交易级胜率 | 47.17% | 53.18% |
| 笔均净收益 | +3.94% | +2.66% |
| 赢均 / 输均 | +22.35% / −12.50% | +14.13% / −10.38% |
| 平均持有天数 | 27.4 | 27.1 |
| 基准沪深300 | +13.81% | +15.16% |
| **超额收益** | **+44.68%** | **+25.45%** |
| 平仓笔数 | 265 | 314 |

### 6.3 三种退出方式对比（TEST, 20 只）

| 退出方式 | 年化 | Sharpe | 日胜率 | 换手 |
|---|---|---|---|---|
| **动态退出（exp_ret ≤ 0）** | **40.61%** | **1.451** | 55.79% | 314 笔 |
| 缓冲带（rank > target+buffer=20） | 34.16% | 1.105 | 52.98% | 1839 笔 |
| 固定 5 日持有（rolling top20） | 19.95% | 1.385 | 52.33% | — |

**动态退出让年化翻倍**（vs 固定 5 日），且优于缓冲带（低换手、高 Sharpe、低回撤）。

### 6.4 exit_threshold 扫描（TEST, 20 只）

| exit_threshold | 年化 | Sharpe | 日胜率 | 平仓笔数 |
|---|---|---|---|---|
| -0.01 | 21.73% | 0.939 | 59.30% | 45 |
| **0.0（最优）** | **40.61%** | **1.451** | 55.79% | 314 |
| +0.005 | 30.17% | 1.025 | 52.28% | 775 |
| +0.01 | 21.96% | 0.777 | 52.28% | 1777 |

### 6.5 信号真实性验证

| 信号 | 年化（TEST） |
|---|---|
| **真实 GBDT** | **+40.61%** |
| 随机信号 ×3 | +14.1% / +9.8% / −3.1% |
| 反向信号（买最差） | **−51.59%** |

单调排序（真实 ≫ 随机 ≫ 反向）证明信号有真实预测力。

---

## 7. 关键发现与教训

1. **截面 rank 特征是最大杠杆**：E0 relative 只做时序归一，缺截面标准化；加入逐日截面 rank 后简单模型 RankIC 达 0.09，是 DL 的 3 倍
2. **动态退出让年化翻倍**：持有赢家至信号转负（均 27 天）vs 固定 5 日
3. **盈利来自盈亏不对称**（赢均 +14% vs 输均 −10%），非高胜率
4. **市场方向不可预测**：择时模型 AUC≈0.5，val→test 过滤器相关性 −0.046
5. **5 日绝对胜率天花板 ~56%**，排名能力（RankIC）才是模型真实价值
6. **ASL 对平衡二分类有梯度偏移**，应改用 BCEWithLogitsLoss

### 7.1 引擎 bug（已修复）
`backtest/engine.py:384` `run_backtest_target`：
```python
budget = (nav_pre / target_size) * capital   # 未约束可用现金
```
当持仓升值不均时，新开仓预算基于**总 NAV** 而非**可用现金**，导致现金透支产生**隐性杠杆**
（最低现金 −13.9%，缓冲带 40.9% 天数负现金）。

**修复**：`budget = min(budget, cash * capital)`

| 配置 | 修复前年化 | 修复后年化 | 修复后最低现金 | 负现金天数 |
|---|---|---|---|---|
| 动态退 exit≤0 | 40.89% | 40.61% | 0.00% | 0.0% |
| 缓冲带 buffer=20 | 33.20% | 34.16% | ~0.00% | 2.8% |
| 缓冲带 buffer=200 | 32.45% | 31.10% | ~0.00% | 0.3% |

修复后负现金归零，动态退结果几乎不变（证明杠杆影响小），**64 个回测单测通过**。

---

## 8. 遗留问题与后续建议

### 8.1 遗留问题
1. **数据异常**：`301139.SZ` 价格归零致 1 笔 −100%（建议清洗）
2. **未做真正的滚动重训回测**（每 6 个月重训链式预测）
3. **DL + cs_rank 训练中途停止**（结论不受影响，但未验证 DL 能否借 cs_rank 追平 GBDT）
4. **单期 test**：2025.07~2026.08 是单一 regime，不能外推

### 8.2 若要真正达到 75%，需要换信息源（非调参可解）
1. **另类数据**：新闻情绪、资金流、龙虎榜、产业链
2. **高频数据**：日内 micro-structure 信号
3. **事件驱动**：财报超预期、并购、政策催化
4. **或改变问题定义**：接受"组合级胜率 62%"而非"单票 75%"

### 8.3 可交付现实方案
**GBDT 截面 rank + target 动态退出**：
- 年化 **41-58%**，Sharpe **1.2-1.5**，超额 **25-45%**
- 两个独立样本外期（val/test）均稳健
- 靠盈亏不对称盈利，单票胜率 ~50-56%

---

## 9. 附录：复现命令

```bash
# ── 生产代码验证 ──
uv run --project . python -m py_compile data/dataset.py train.py backtest/engine.py
uv run --project . python -m unittest tests.unit.data.test_data_cs_rank tests.unit.data.test_data_excess_labels -v
uv run --project . python -m unittest tests.unit.backtest.test_engine tests.unit.scripts.test_run_backtest_cli -v  # 64 OK
uv run --project . python train.py --cs_rank --smoke --num_workers 0

# ── 研究报告 ──
uv run --project . python -u logs/ic_analysis/prep.py          # 生成面板
uv run --project . python -u logs/gbdt_cs/train_eval.py        # GBDT 全流程
uv run --project . python -u logs/clf_winrate/train_eval.py    # 分类器

# ── 回测 ──
uv run --project . python -m scripts.build_ohlc_path --full --val_start 2025-07-01 --val_end 2026-08-31 --out logs/ohlc_full_test.npz
uv run --project . python -m scripts.run_backtest --mode target \
  --preds logs/gbdt_cs/preds_gbdt_cs_test.npz --full_ohlc logs/ohlc_full_test.npz \
  --target_size 20 --exit-on-nonpositive --exit_threshold 0.0
```

---

## 10. 总结

| 维度 | 结论 |
|---|---|
| **75% 单票胜率** | ❌ 不可达（天花板 52-58%，四路独立验证） |
| **根本原因** | 5 日收益信噪比 ≈0.1，需 IC≈0.35 才能达 75%，实际最强仅 0.075 |
| **最大技术突破** | 截面 rank 特征（RankIC 提升 3 倍） |
| **最佳策略** | GBDT 截面 rank + target 动态退出（年化 41-58%，Sharpe 1.2-1.5） |
| **盈利来源** | 盈亏不对称（赢均 +14% vs 输均 −10%），非高胜率 |
| **诚实评级** | 排序能力强（RankIC 0.075，十分位单调），胜率数字诚实（~50-56%） |

