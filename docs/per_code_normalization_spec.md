# Per-Code 分组归一化共识文档（不做 Window，只 Per-Code 分组）

> 生成时间：2026-09-03  
> 数据：`data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`（11.4M行，5166股，58列）  
> 基准：`quant/scripts/export_training_data.py` EXPORT_FACTORS 48 + 基础 7 =55有效（已剔除项见下）  
> 总基调：**per-code 分组归一化，不做 window**（用户 2026-09-03 确认）

---

## 1. 总体剔除与保留

- **G2 收益率 4列**：`return_1d/5d/10d/20d` 为标签，不入训，**剔除**
- **TOT_SHARE**：A 方案，**剔除**，改用 `turnover`（或 `volume_ratio` 已覆盖）
- **volume/amount**：**剔除**（绝对量不入训，仅保留比值）
- **close 恒0**：`close/prev_close -1 =0` 恒0，**剔除** close 本身（信息由其他 price_rel 覆盖）
- **有效特征**：`G1 12 + G3 7 + G4 3 + G5 6 + G8 5 + G9 6 = 39`（G6/G7 各4已剔除），+6 mask = **45**（原47+6=53 → 39+6=45）

---

## 2. 各组归一化决策（逐组确认）

| 组 | 成员（剔除后） | 缺失率 | 分布特征 | 变换 | Per-Code 操作 | 备注 |
|---|---|---|---|---|---|---|
| **G1 价格水平** 12 | `open/high/low, ma_5/10/20/60, ema_12/26, sar, trend_duokong/shortline` | `ma_60 2.73%, trend 11.47%`, 其余0~1% | `feature/prev_close -1` 后中心0，`open_rel std0.028`, `ma_60_rel std0.128` | `feature/prev_close -1`（prev_close 为同 code 上一日 close） | **per-code robust** `(x - median_code)/(IQR_code/1.349)` + `clip ±5` | 无非线性，已相对化不再 log/asinh；缺失填0 |
| **G2 收益率** 4 | `return_1d/5d/10d/20d` | — | — | — | **跳过，不入训** | 标签用未来收益 `close[t+5]/close[t]-1` 另算 |
| **G3 波动率** 7 | `volatility_5/10/20, std_5/10/20, atr` | 0.19~0.93% | 极右偏 `skew 11~131`, `p99/max` 55~725倍，正值下界0 | 无（已比值） | **仅 clip + per-code**：per-code 1/99 winsor clip，不做 log1p，不做 robust | 用户指定“仅clip” |
| **G4 量能** 3 | `volume_ratio_5/10, amihud` | 0.23~0.93% | `volume_ratio` 已是 `volume / shift(1).rolling(N).mean()` 比值，skew 188；`amihud = |ret|/(close*volume+1) rolling20.mean` 量级1e-12 | 无 | **仅 clip + per-code**，per-code 1/99 winsor | `volume/amount` 已剔除；比值已归一化不 log |
| **G5 技术** 6 | `macd, dmi, adx, boll, kelch, trend_duokong_dev` | `macd 1.5%, trend_dev 11.5%` | `macd = (EMA12-EMA26)-Signal9(hist)`，差值 `skew -85, 范围3874, p1 -4.4 p99 4.18`；其余5个已比值/有界 `dmi -31~37, adx 9~55, boll 0.03~0.70` | `macd` 做 `macd/prev_close -1`，其余无 | **macd: `relative + clip + per-code`**；其余5个 **跳过**（已归一化不处理） | `Signal9 = DIF的EMA9`，`DIF=EMA12-EMA26` |
| **G6 估值** 4 | `pe/pb/pcf/ps` | 6~10% | 动态 TTM 比值：`pe=市值/净利TTM, pb=市值/净资产, pcf=市值/经营现金流TTM, ps=市值/营收TTM`，双侧极端 `pe -217万~218万, pcf -210万~3054万` | `asinh` | **暂不入训，已剔除**（原 “仅 asinh + per-code”）|
| **G7 成长** 4 | `revenue_growth, profit_growth, *_qoq` | 4~15% | `YoY=(TTM-4季前TTM)/4季前TTM`, `QoQ=(单季-上季单季)/上季单季`，比值，极端因分母极小（几百万→几十亿，-1万→400万扭亏）`p99 2.3/16, max 2790/40867` | 无 | **暂不入训，已剔除**（原 “仅 clip + per-code”）|
| **G8 质量** 5 | `gross_margin, net_margin, roe, roa, debt_to_equity` | 1.4~9.8% | 比值 `gross 0.26±0.27, roe 0.06±10.6`，有界 | 无 | **跳过** | 已比值，缺失填0透传 |
| **G9 两融** 6 | `margin_* 6` | 53~56% | 已 `rank pct` 归一化 [0,1]，均匀 | 无 | **完全不做 per-code**，仅 `填0 + 单 mask + clip[0,1]兜底` | 存储前已截面 rank，缺失为非标的股全空 |

---

## 3. Per-Code 语义

- **median（中位数）**：60日窗口改为**单股全历史**的中位数，抗极端；替代 `mean`
- **IQR（四分位距）**：`Q3-Q1`，替代 `std`，同样抗极端
- **robust**：`(x - median_code) / (IQR_code/1.349)`，`1.349` 使 IQR 尺度对齐正态 std
- **clip**：`winsor 1/99` 截断到该股 1/99 分位；G1/G6 额外 `clip ±5` 防 residual
- **relative**：`feature / prev_close -1` 用同股上一日 close 作分母，消除量纲

---

## 4. 缺失分级（per-code 内）

- **warmup <1%**（如 `ma_60 2.73%, return_*` 已剔除）：填0（经 relative/asinh 后 0 为中性）
- **结构性 53~56% 两融**：填0 + 单 `margin_mask` 通道 `[0,1]`（1=observed）
- **G8 金融行业**（`gross_margin` 9.8% 全空）：填0透传

---

## 5. 实现映射

- 配置：`data/parquet_dataset.py` `ParquetDataConfig.normalize = "per_code"`，`per_code_add_mask=True`，`feature_cols` 自动剔除 `return_*/TOT_SHARE/volume/amount/close`
- Scaler：`data/per_code_scaler.py` `PerCodeGroupedScaler`，`fit(df)` 按 code 独立算 `median/IQR/winsor`，`transform_code(code, feat, cols, close)` 按 code 应用
- 验证集复用：重叠 code 用训练集 per-code 统计，未见 code 回退全局 median/IQR
- 持久化：`{per_code_stats, global_stats, feature_cols, version: v2_per_code}` pickle
- 模型：`featurenum = 47+1=48`，`CNNTransformer` 自动校正（`main_parquet.py` 已有）

---

## 6. 待办

- [x] G1~G9 逐组讨论确认
- [ ] 按本 spec 改造 `parquet_dataset.py` 支持 `per_code` 分支并打通 `main_parquet.py` 训练（`normalize="per_code"`）
- [ ] 小样本验证：`--max_codes 10 --normalize per_code` 检查 `x [48,60]` 无 NaN/inf，均值≈0
- [ ] 全量冒烟：`--max_codes 100 --normalize per_code --epochs 1` 验证 loss 收敛
