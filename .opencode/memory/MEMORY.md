# Project Memory

## 当前架构
- 唯一训练入口：`train.py`。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`（`RelativeScaler` E0 + `PerCodeGroupedScaler` E1）与 `data/rolling_scaler.py`（rolling）；memmap 缓存层在 `data/feature_cache.py`。
- 模型：`models/cnn_transformer/`；训练：`training/`；损失：`criterion/`；回测：`backtest/`。
- 评估 CLI：`scripts/eval_bins_mapping.py`（截面 IC/xs_rank_ic/spread，`--max_codes 0` 全市场，`--preds_cache` 存 exp_ret/true_ret/dates/codes）；`scripts/build_ohlc_path.py`（`--full` 出全期日频矩阵）；`scripts/run_backtest.py`（rolling/target 回测 + 指数基准 + 强买门槛）；`scripts/plot_topn_curve.py`；`scripts/run_eval_full.sh` 串联。

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
- **schema（T01）**：`FEATURE_GROUPS={P:18,R:16,N:12,G:6}`，`APPROVED_RAW_FEATURES`=**52**（`close` 解禁进 P）；`G9_OBSERVATION_SOURCE`=18，`G9_MASK_COLUMNS=("g9_observed_mask",)`（1 列）；`PROHIBITED_COLUMNS` 去 close；`column_group`/`default_feature_cols(normalize)`/`g9_observed_mask(frame)`。**F_out=52+1=53**。`EXPORT_FACTORS`/`BASE_COLUMNS` 未动。
- **ColumnRule/RelativeScaler（T02）**：`ASINH_CLIP=5.0`/`P_CLIP=(-5,5)`/`N_CLIP=(0,1)`/`AMIHUD_SCALE=1e12`/`RELATIVE_DENOMINATOR="close"`/`G9_RAW_CLIP`(6 列)；`COLUMN_RULES`(52, 由 FEATURE_GROUPS 生成)；`column_rule(col)` 未知 raise；模块级 `_relative_transform`（分母 `isfinite & !=0`）；`RelativeScaler(feature_cols, add_mask=True)` 无 `fit`，末尾 1 个 `g9_observed_mask`；digest payload=`COLUMN_RULES`+version+`G9_MASK_COLUMNS`。
- **PerCodeGroupedScaler E1（T03）**：按 `COLUMN_RULES` 路由；仅 P 组 fit 每股 median/IQR（在 `x/close[t-1]-1` 上），transform `(v-med)/(IQR/1.349)` clip±5；R/N/G 确定性；未见 code 回退 `global_stats`；未知列 raise；1 shared mask；`SCALER_VERSION="v4_per_code"`、`TRANSFORM_VERSION="per_code_transform_v4"`（旧 v3 payload load raise）。对外 API 全保留。
- **RollingNormalizer（T04）**：`ROLLING_SCOPE_FEATURES={e0:(),e1:P,e2:P,e3:P+vol(21),e4:+vol_ratio/amihud(24),e5:+G raw(30)}`；默认 `scope="e5"`。scope P→relative+rolling robust；scope VOL/VOLUME/G→rolling winsor；非 scope 按 `COLUMN_RULES`；末尾恰 1 列 shared mask（e5 G9 raw 入 scope 也**不短路**）；`_validate_feature_cols` 允许 close；`ROLLING_VERSION="v2_rolling_scope_e0_e5"`、`ROLLING_TRANSFORM_VERSION="rolling_transform_v2"`、`PAYLOAD_VERSION="v2_rolling_state"`；digest 含 scope 名。
- **dataset（T05）**：`normalize` 增 `relative`（无状态、无 fit、无落盘）；`_cache_key`/`_scaler_identity` mode-aware；`_resolve_scaler_on_cache_hit` 增 relative 重建分支；`rolling_scope` 默认 `e5`；`CACHE_FORMAT_VERSION="v3_relative_groups"`；`num_features=len(feature_cols_out)`。
- **train/CLI（T06）**：`ROLLING_SCOPES=("e0".."e5")`；`configure_preprocessing` 支持 `{per_code,rolling,relative}`（relative→`SCALER_PATH=None`+`./logs/relative`）；删 `featurenum==69` 断言，改 `resolve_featurenum`；CLI `--normalize relative`/`--rolling_scope e0..e5`/`--feature_cols`/`--featurenum`；metadata 含 `feature_cols`+`feature_cols_out`；rolling 维度不符改 warning。`config/defaults.py`：`ROLLING_SCOPE="e5"`、`featurenum=53`、**`LEARNING_RATE=3e-4`**。
- **eval/scripts（T07）**：mode 白名单增 relative、scope e0..e5、featurenum 实测派生（缺失 raise 不静默 45）、relative 无 state 重建、`run_eval_full.sh` 唯一 `--preds_out`、`multi_seed_train.py` 同步；`tests/unit/scripts/__init__.py` 使 discover 递归。
- **T08/T09**：旧契约测试增量同步完成；6 份文档同步为 F=53 与新分组。
- **整体 review**：VERDICT=PASS；修 M1（dataset 默认 parquet→F60）、M4（relative digest 增 mask_columns）、L1（inf 分母统一）、LR 1e-4→3e-4。既有 64 项仓级 ruff 报错为未触碰文件存量。

## E0–E5 redesign 训练/评估结果（2026-09-14 完成，`--lr 3e-4 --batch_size 1024 --num_workers 4 --seed 42 --epochs 50 --patience 5`）
- 训练并发受 **RAM 限制（15.9GB，单臂 num_workers=4 即占满）→ 必须串行**；单臂约 2h。后台 psmux `cnn_e0e5` + 控制器 `cnn_ctrl`。六臂均 **epoch3 达最优、epoch8 早停**。
- 评估区间 2026-01-01~08-31（**154 交易日，794,501 样本**）。

| 臂 | mode/scope | Best Val Loss/Acc | run 目录 | 截面 RankIC |
|---|---|---|---|---|
| E0 | relative | 0.0562 / 0.1043 | `logs/relative/run_20260914_024253` | 0.0248 |
| E1 | per_code | 0.0562 / 0.1005 | `logs/run_20260914_045053` | 0.0302 |
| E2 | rolling e2 | 0.0562 / 0.1033 | `logs/rolling_e2/run_20260914_064942` | 0.0415 |
| E3 | rolling e3 | 0.0564 / 0.1016 | `logs/rolling_e3/run_20260914_093155` | **0.0441** |
| E4 | rolling e4 | 0.0561 / 0.1013 | `logs/rolling_e4/run_20260914_115221` | 0.0339 |
| E5 | rolling e5 | 0.0561 / 0.1029 | `logs/rolling_e5/run_20260914_141450` | 0.0399 |

- 截面排序能力为正（IC>0 胜率 63–68%、ICIR 3.2–7.2，E2 多空分离最好）；但正常回测（剔涨停+成本）下无正超额。
- 产物：`logs/preds_*_2026-08-31.npz`、`logs/ohlc_path_2026-01-01_2026-08-31.npz`、`logs/ohlc_full_2026-01-01_2026-08-31.npz`。

## 回测口径（2026-09-14 升级，task 20260914_2303_backtest-fee-target-exit）
- **费用模型（rolling/target/benchmark 统一，`backtest/engine.py`）**：买佣 `max(买额×0.00025, 5)`；卖佣 `max(卖额×0.00025, 5)` + 印花税 `卖额×0.00025`；单笔净收益 `(卖额−卖佣−印花税−买额−买佣)/(买额+买佣)`；纯函数 `commission`/`net_return_after_fees`。`--capital` 默认 **100 万**（折算最低 5 元佣金）。旧 `--cost_rate` 保留但显式传入仅告警忽略。**结果对本金极敏感**（本金越小，最低佣金越 binding）。
- **基准 = 大盘指数**：`benchmark_index_nav(index_dates,index_close,trade_days)` 纯函数（指数 close-to-close、按 trade_days 对齐、缺失日收益 0、起点 1.0、不计费率）。CLI `--index_dir`（win32 默认 `Z:/test/kline_index/day`）、`--benchmark_index`（默认 `000300.SH` 沪深300）。**超额=策略 annual − 指数 annual**。旧 `benchmark_nav`（全截面等权）保留仅测试、CLI 弃用。
- **评估范围**：`--topn` 默认 `5 10 20`；target 默认 `sell_buffer=500`；新增 `--exit-on-nonpositive`（预测 exp_ret ≤ `--exit_threshold`（默认0）即卖，替代 rank buffer）。`BacktestResult.avg_cash_ratio`（rolling 恒 0.0；target 实测，含首日/末日全现金）。
- **对账结论（无 bug）**：「逐日 TopN 均值」正收益 ⨯ 回测亏损的根因 = **可交易性剔除**：E2 top5 全样本均值 +0.458%，其中 9 只 T+1 open 涨停（不可买）均值 +59.4%；剔除后 kept 均值 -0.287%。归因链 E2 top5 `+25.9%(gross) → -39.4pp(可交易性) → -6.3pp(成本) → -7.6pp(复利/波动) = -27.3%`。
- **Benchmark 沪深300 annual -3.43%**（2026-01~08）。

### 回测结果（新口径：费用+指数基准+小组合）
- **rolling top5/10/20（年化，超额 vs 沪深300 -3.43%）**：六臂全负；最好 E4 top10 -10.56%（-7.13%）、E3 top20 -15.66%（-12.23%）。`avg_cash_ratio=0%`。
- **target size5/10/20（buffer=500）**：E0 s5 +4.96% / E5 s5 +5.18% / E4 s20 -5.88% 相对较好，其余多为负；E1 s5 -76%（少数票主导，方差极大）。
- **target size5/10/20（`--exit-on-nonpositive`）**：E0 最稳（s5/s10/s20 = +22.5%/+29.4%/+18.9%）；E1 s10/s20 正；E2/E3/E4/E5 不稳定甚至为负。`avg_cash_ratio` 0.2%~12%。
- **结论**：小组合方差极大、无一致正超额；rolling 全面跑输沪深300。
- 产物：`logs/backtest_idx_e0e5_rolling/`、`logs/backtest_idx_target_{b500,exitnp}_s{5,10,20}/`。commit `aa1e586`（code）+`4073bad`（docs）。

## 强买门槛 + s50 + E0–E5 综合结论（2026-09-15，task 20260915_0005_add-strong-buy-gate）
- **新特性**：target 模式 `--strong_buy_threshold F`（默认 0.0=关闭、负值 raise）——买入带（`rank<=target_size`）候选 `exp_ret >= F` 才买，否则跳过留现金**不补位**；执行顺序 `min_edge → strong_buy → 涨停检查`；metrics 只增 `strong_buy_threshold`/`n_skipped_strong_buy`。`backtest/engine.py` `run_backtest_target` + `scripts/run_backtest.py`。默认 0.0 与改动前逐位一致。
- **s50 补跑**（b500/exitnp，另见 T05 表）：`exitnp` 下 s50 **六臂全正超额**（E1 +31.5 最强、E0 +14.0）；`b500` 仅 E1 +6.7。s50 明显比 s5/s10/s20 稳定。
- **强买门槛扫描**（0/2%/3%/5% × b500/exitnp × s5/s10/s50，24 组；产物 `logs/backtest_sbg_*`）：阈值↑ → `avg_cash_ratio`/`n_skipped_strong_buy` 单调↑；**2% 近乎无效**（模型头部预测已 >2%），3% 中等，5% 现金比 45–67%、样本骤减、方差极大。**无一致正超额**（E0 exitnp s5 t5% +72.1% 最好，但同规则 E2 -52.3%）→ 门槛是「空仓/风险预算」开关而非选股 α。
- **E0–E5 综合最好配置 = E0（`--normalize relative`）**：唯一 exitnp 四档全正（超额均值 +23.5%），无状态/零拟合；其次 **E1 per_code（仅 size≥50 更优，+17.3%）**。**E3 RankIC 最高（0.0441）但未转化为可交易超额**；E2/E4/E5 不推荐（E5 加 G9 raw 无增益）。
- **保留**：单 seed、单区间（154 日）、t 值弱、exitnp 含择时成分；结论暂定，需多 seed + 换手/行业暴露归因。
- 详见 `docs/per_code_normalization_spec.md` §7。

## 性能事实（RTX3070 / torch 2.12.0+cu130 / Windows / 16 线程 15.9GB）
- 训练瓶颈是每 step ~868 次 kernel launch（~62ms 固定 CPU）→ **batch=1024**；epoch≈14–16min。
- **内存是并发硬约束**：单臂（num_workers=4）即占满 ~16GB，禁止并行多臂。
- `torch.compile` 不可用；rolling `_rolling_column` 已向量化，rolling 缓存各 ~15-20min。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit   # 315 OK
uv run ruff check .                                         # 仓级仍有存量（未触碰文件）
uv run --project . python train.py --smoke --num_workers 0
```

## 历史结果（旧 F=69 schema / lr=1e-4，不可与新 F=53 结果混用）
- E1 per_code 0.0568/0.0947；E2 rolling e2 0.0565/0.1042；E3 rolling e3 0.0565/0.0961；E4 rolling e4 0.0563/0.0971；均 6 epoch 早停。
- 评估（154 日）：E1 RankIC -0.0058 / Top5 -43.0%；E2 0.0215 / -52.7%；E3 0.0039 / -52.1%；E4 0.0109 / -60.9%。

## 已知变更
- [2026-09-13 10:15] T05 修复 `_FeatureView` 重复全量 mmap（WinError 1455）：`_MMAP_REGISTRY`+`_open_shared_mmap`。commit 4bc7f26。
- [2026-09-13 13:40] T01 向量化 `rolling_scaler._rolling_column`；commit 0a22d1f。
- [2026-09-13 20:1x] context warmup 窗口；commit `42ffe0c`。
- [2026-09-14] redesign 全流程 T01–T10 落地 + 整体 review 修复；commit `178f24e`（code）+ `475391c`（T10 结果）。文档在 `docs/agent/task/20260913_2331_rolling-normalization-redesign/`。
- [2026-09-14] E0–E5 训练+评估全部完成。
- [2026-09-14] 三种评估口径对账完成，确认无 bug、根因为涨停不可买样本污染直接法。
- [2026-09-14] 回测口径升级（费用模型 + 指数基准 + 小 TopN + avg_cash_ratio + target 退出规则）；commit `e763405`(plan)/`aa1e586`(code)/`4073bad`(docs)。文档在 `docs/agent/task/20260914_2303_backtest-fee-target-exit/`。
- [2026-09-15] add-strong-buy-gate：target `--strong_buy_threshold`（T01–T05 全 PASS，discover 315 OK）+ 24 组扫描；规划文档 commit `fd955ea`。结论落 `docs/per_code_normalization_spec.md` §7。