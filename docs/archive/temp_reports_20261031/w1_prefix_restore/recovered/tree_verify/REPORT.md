# 树模型正式验证报告（tree_verify）

> 执行日期 2026-10-03。任务：对树模型（16 截面 rank + GBDT/XGB）做**与主链路完全同口径**的正式验证。
> 纪律：**不改仓库源码**；脚本 `%TEMP%\opencode\tree_verify\`；产物 `logs/tree_verify/`（gitignore）。
> 数据：`Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`（12,254,385 行 × 58 列）。
> **⚠️ 2026 年（2026-01~08）属烧掉样本，本报告所有 2026 数字仅作图景/口径对比，不得用于验收。**

---

## 0. 口径声明（与主链路对齐）

| 项目 | 主模型 A/B | 本报告树模型 |
|---|---|---|
| 训练区间 | 2013-01-01 ~ 2024-12-31 | **同** |
| 验证区间 | 2025-01-01 ~ 2025-12-31 | **同** |
| 测试区间 | 2026-01-01 ~ 2026-08-31 | **同** |
| 特征 | 52 raw（P18+R16+N12+G6）+ mask，F=53 | 16 逐日截面 `rank(pct=True)`（缺失→0.5） |
| 标签 | 52 类分桶（EMD）；评估 `xs_rank_ic` 用 `true_ret` | H5 `close[t+5]/close[t]-1`；另存 open-open 可执行口径 |
| 评估脚本 | `scripts.eval_bins_mapping`（其 `xs_rank_ic_mean`） | `scripts.eval_three_way`（`rank_ic_mean`） |
| 回测 | `scripts.run_backtest`（adapter） | **同引擎同参** |
| 费率 | 佣万2 min5 + 印花卖万5 + 过户万1双边 | **同** |

**口径一致性验证（关键）**：主模型 A/B 的 2025/2026 预测缓存经本报告用的 `eval_three_way` 重跑，**逐位复现**官方数字：
- A：2025 RankIC `0.0547`、2026 `0.0611`（与 `logs/eval_fullA_{2025,2026}.json` 的 `xs_rank_ic_mean` 完全一致，n×天亦一致）
- B：2025 `0.0780`、2026 `0.0684`（与 `logs/eval_fullB_2025/2026.json` 一致）

因此下方 A/B 与树模型数字**同脚本、同分日截面、同 IC 定义**，可直比。

**样本口径差异（如实说明）**：树模型 TEST n=828,264（155 天），主模型 2026 缓存 n=768,549（149 天）。主模型评估含窗口 warmup、标签日 horizon=10；树模型标签 H5 仅需末尾 5 日、无窗口。逐日截面 IC 不受余样本影响，但 top-N 组合的绝对收益口径窗口略宽（树模型多约 6 个驱动日）。此差异在两模型间不可避免，已在解读中保守处理。

---

## 1. 阶段 1：固定切分（单次训练，2025 验证 / 2026 测试）

### 1.1 截面指标（RankIC / ICIR / t / top10 / top100 逐日宏平均）

| 模型 | 2025 IC | ICIR | t | top10 | top100 | 2026 IC | ICIR | t | top10 | top100 |
|---|---|---|---|---|---|---|---|---|---|---|
| 树 HGB（close5d） | **0.1050** | 1.031 | 16.07 | +2.89% | +1.72% | **0.0830** | 0.542 | 6.75 | +1.92% | +0.59% |
| 树 HGB（open-open） | 0.0971 | 0.951 | 14.83 | +0.96% | +1.44% | 0.0772 | 0.507 | 6.29 | +0.05% | +0.25% |
| 树 XGB-GPU（close5d） | 0.1028 | 1.030 | 16.06 | +2.95% | +1.67% | 0.0822 | 0.536 | 6.67 | +2.69% | +0.69% |
| 主模型 A（CNN-Transformer 基线） | 0.0547 | 0.555 | 8.45 | +2.98% | +2.55% | 0.0611 | 0.666 | 8.13 | −0.98% | +0.20% |
| 主模型 B（lr1e-4+dual_head） | 0.0780 | 0.713 | 10.86 | +2.47% | +2.46% | 0.0684 | 0.546 | 6.67 | +0.18% | +0.25% |

**读法**：树模型 IC 全面领先（2025 +0.027~0.030 vs A、+0.019~0.027 vs B；2026 +0.009~0.015 vs B、+0.016~0.022 vs A）。但 **2025 主模型 top10 绝对收益并不逊色**（A +2.98% vs 树 +2.89%/2.95%），**2026 树模型 top10 由主模型 A 的 −0.98% 翻正为 +1.92%/+2.69%**。IC 优势未完全转化为 top10 收益优势。

### 1.2 回测（`scripts.run_backtest`，open-open，同引擎同参）

**2026 target（`--target_size 200 --sell_buffer 500 --exit_on_nonpositive`）**

| 模型 | 年化 | Sharpe | MDD | NAV(期末/期初) | 超额(对 HS300) |
|---|---|---|---|---|---|
| 主模型 A | −6.99% | −0.626 | 15.39% | 0.956 | −5.12% |
| 主模型 B | −7.02% | −0.514 | 17.95% | 0.956 | −5.16% |
| 树 HGB 单次 | **+0.23%** | **+0.006** | 19.56% | 1.002 | +3.33% |
| 树 XGB 单次 | **+2.25%** | **+0.107** | 18.27% | 1.015 | +5.35% |
| 基准 HS300 | −1.86% | 0.001 | 10.49% | 0.989 | — |

**2026 rolling（`--topn 10`）**

| 模型 | 年化 | Sharpe | MDD | NAV |
|---|---|---|---|---|
| 主模型 A | −48.80% | −2.920 | 43.40% | 0.662 |
| 主模型 B | −40.61% | −2.094 | 41.68% | 0.726 |
| 树 HGB 单次 | −57.08% | −3.958 | 50.01% | 0.572 |
| 树 XGB 单次 | −58.12% | −4.500 | 47.88% | 0.562 |

---

## 2. 阶段 2：滚动重训（expanding，诚实口径）

**折法**：初训 2013-01 ~ 2021-12，此后每半年用**决策日之前全部数据**重训，预测其后 6 个月，共 10 折覆盖 2022-01 ~ 2026-08。
**无泄漏断言**（逐折）：`max(train_date) < min(pred_date)`；额外 7 自然日 purge 使训练末端标签 `t+5` 不越过预测起点，10 折全部通过。

### 2.1 截面指标

| 模型 | 2025 IC | 2026 IC | 2026 top10 |
|---|---|---|---|
| 树 HGB 滚动 | 0.1052 | 0.0767 | +1.58% |
| 树 XGB 滚动 | 0.1017 | 0.0768 | +2.33% |
| （对照）树 HGB 单次 | 0.1050 | 0.0830 | +1.92% |
| （对照）树 XGB 单次 | 0.1028 | 0.0822 | +2.69% |

### 2.2 回测（同引擎同参）

| 模型 | 2026 target 年化 | Sharpe | MDD | 2026 rolling 年化 | Sharpe |
|---|---|---|---|---|---|
| 树 HGB 滚动 | +2.02% | 0.098 | 19.56% | −60.77% | −4.277 |
| 树 XGB 滚动 | +1.85% | 0.088 | 18.76% | −60.56% | −4.752 |
| （对照）树 HGB 单次 | +0.23% | 0.006 | 19.56% | −57.08% | −3.958 |
| （对照）树 XGB 单次 | +2.25% | 0.107 | 18.27% | −58.12% | −4.500 |

**滚动重训的影响**：2025/2026 IC 与单次切分几乎持平（±0.005），2026 target 年化从 +0.2%~+2.3% 稳定在 +1.9%~+2.0%，**没有出现主模型那种单期高估→滚动崩塌的现象**；rolling top10 本就深度亏损，滚动后略更差。**诚实口径下树模型 2026 target 仍是 +1.9%~+2.0%，优于主模型 A/B 的 −7%。**

> **与主模型口径差异（重要）**：主模型**未做滚动重训**（A/B 均为 2013-2024 单次训练），因此阶段 1 的单次切分树模型才是与主模型的**同口径**对比。滚动数字（阶段 2）为树模型的额外诚实性检验，无主模型对应项。

---

## 3. 结论

1. **同口径下树模型确实全面优于主模型**，但优势集中在**排序能力与 2026 绝对收益**，而非 2025 的 top-N 收益：
   - 截面 RankIC：2025 `0.105/0.103` vs A `0.055`/B `0.078`（+0.03 / +0.03~0.03）；2026 `0.083/0.082` vs A `0.061`/B `0.068`（+0.02 / +0.01）。
   - 2026 target 绝对收益：树 `+0.2%~+2.3%` vs A/B `−7.0%`，**翻转约 +7~9pp**；滚动诚实口径仍 `+1.9%~+2.0%`。
   - 2026 rolling top10：树 `−57%~−61%` 反而**比主模型 A/B 的 `−41%~−49%` 更差**——排序强≠短线组合强，5 日固定换仓在 2026 震荡市对任何模型都是负端。
2. **差距量级**：截面 IC 领先约 **+25~55%（相对）**，2026 target 绝对收益领先约 **+9pp**。但 **2025 top10 树模型并未胜过主模型 A**（+2.89% vs +2.98%），说明 IC 领先主要在尾部/中段，头部 alpha 被主模型的截面损失吸收了一部分。
3. **置信度**：**中**。支持证据——IC 优势在 2025/2026 两年、单次/滚动两种训练方式下一致且 t 统计量高（树 t≈6.3~16.1）。削弱证据——(a) 2026 为烧掉样本；(b) 树模型回测窗口比主模型多约 6 个驱动日，target 绝对收益差距被口径放大；(c) target 净值的绝对水平极低（树 NAV 1.002~1.015），年化 +2% 几乎等于零收益，**并非可交易的 alpha**，仅相对主模型的 −7% 更“不亏”；(d) rolling 模式树模型更差，说明优势不稳定依赖持仓周期。
4. **总判定**：**在纯截面排序任务上，树模型（16 截面 rank + GBDT/XGB）是比主模型更有效、更廉价、更稳（无需滚动重训即不崩）的基线**；但**绝对收益层面双方都未突破市场，树模型的 `+2%` 仍属噪声区间**，不足以支撑“替换生产模型”。建议：树模型作**截面排序/风险因子**入模（如与主模型集成或作辅助过滤），**不建议**直接替换主模型做 5 日 rolling。

---

## 4. 无泄漏声明

- 阶段 1：训练集 2013-01~2024-12 严格早于验证 2025、测试 2026 起点，逐样本标签由训练区间内 `close[t+5]` 计算，测试标签不参与任何 fit。
- 阶段 2：每折 `assert max(train_date) < min(pred_date)`，且训练末端再 purge 7 自然日，确保标签 `t+5` 不穿越预测起点；10 折全部通过（见 `p2_{hgb,xgb}_meta.json.folds[].max_train_date/min_pred_date`）。
- 阈值校准：`eval_three_way` 的 precision 阈值仅在 VAL 校准，绝不回看 TEST。
- 回测：`scripts.run_backtest` 使用各模型**自有预测缓存**，preds 文件中不含未来收益；引擎直读 parquet 真实 OHLC。

---

## 5. 脚本与复现命令

脚本目录 `%TEMP%\opencode\tree_verify\`（仓库源码零改动）：

| 脚本 | 用途 |
|---|---|
| `p1_train.py` | 阶段 1 单次切分训练（`--model hgb/xgb`，2013-2024/2025/2026） |
| `p2_roll.py` | 阶段 2 expanding 滚动重训（10 折 + 无泄漏断言） |
| `run_p2.ps1` | tmux 后台驱动 p2（会话名 `tree_verify`） |
| `extract_table.py` | 汇总截面指标表 |
| `extract_bt.py` | 汇总回测指标表 |
| 特征数据 | `%TEMP%\opencode\tree_rebuild\data\X_cs.npy` 等（沿用上轮重建，16 cs rank + H5 标签） |

```powershell
$env:PYTHONPATH="D:\code\cnn_full_20260905\cnn"
$T="C:\Users\yanwen\AppData\Local\Temp\opencode\tree_verify"
$Z="Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"

# 阶段 1 训练
uv run --project . python -u $T\p1_train.py --model hgb
uv run --project . python -u $T\p1_train.py --model xgb
# 阶段 2 滚动（或 tmux 后台跑 run_p2.ps1）
uv run --project . python -u $T\p2_roll.py --model hgb
uv run --project . python -u $T\p2_roll.py --model xgb

# 截面评估（close5d）
uv run --project . python -m scripts.eval_three_way --val_start 2025-01-01 --val_end 2025-12-31 `
  --test_start 2026-01-01 --test_end 2026-08-31 --horizon 5 `
  --val_cache logs/tree_verify/preds_p1_hgb_val.npz --test_cache logs/tree_verify/preds_p1_hgb_test.npz `
  --out logs/tree_verify/eval_p1_hgb_close.json --report logs/tree_verify/eval_p1_hgb_close.txt
# 主模型同口径复核
uv run --project . python -m scripts.eval_three_way --val_start 2025-01-01 --val_end 2025-12-31 `
  --test_start 2026-01-01 --test_end 2026-08-31 --horizon 10 `
  --val_cache logs/preds_fullA_2025.npz --test_cache logs/preds_fullA_2026.npz `
  --out logs/tree_verify/eval_mainA_samecaliber.json --report logs/tree_verify/eval_mainA_samecaliber.txt

# 回测（open-open，同引擎同参）
uv run --project . python -m scripts.run_backtest --preds logs/tree_verify/preds_p1_hgb_test_openopen.npz `
  --parquet $Z --mode target --target_size 200 --sell_buffer 500 --exit_on_nonpositive `
  --out_dir logs/tree_verify/bt_p1_hgb_target
uv run --project . python -m scripts.run_backtest --preds logs/tree_verify/preds_p1_hgb_test_openopen.npz `
  --parquet $Z --mode rolling --topn 10 --out_dir logs/tree_verify/bt_p1_hgb_roll10
# 滚动版同理，preds 换 preds_p2_{hgb,xgb}_roll_2026_openopen.npz

# 汇总
uv run --project . python -u $T\extract_table.py
uv run --project . python -u $T\extract_bt.py
```

---

## 6. 失败 / 不可复现 / 口径说明

- **样本口径差异（非 bug）**：树模型 TEST n=828,264 vs 主模型 768,549，因标签 horizon（5 vs 10）与窗口 warmup 过滤差异；逐日 IC 不受影响，绝对收益回测窗口略宽已在结论中保守处理。
- **target 净值水平极低**：树模型 2026 target 年化 +0.2%~+2.3%、NAV 1.002~1.015，**属噪声区间**，仅相对主模型 −7% 更优，不构成可交易 alpha。
- **rolling 模式全负**：三模型（A/B/树）2026 rolling top10 均 −41%~−61%，与既往“rolling 崩塌”结论一致，非本次引入。
- **阶段 1 单次切分才是与主模型的同口径对比**：主模型未滚动，阶段 2 滚动为树模型额外诚实性检验。
- **XGB best_iter 达 500（打满）**：XGB 早停未触发，属超参上限，未作额外调参（保持与上轮重建 X3 配置一致）。
