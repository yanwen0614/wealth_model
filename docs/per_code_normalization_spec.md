# Per-Code 分组归一化共识文档（frozen 基线与 rolling 实验边界）

> 生成时间：2026-09-03  
> 数据：`data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`（11.4M行，5166股，58列）  
> 基准：`quant/scripts/export_training_data.py` 的原始因子集合为 48 列；基础列与剔除规则见下。
> 当前默认输出：51 个 raw feature + 18 个 G9 observation mask = **F=69**。
> `F=45`（39+6）和 `F=55` 均为历史 schema/实验，不是当前默认输入。
> frozen 基线总基调：**per-code 分组归一化，不做 window**（用户 2026-09-03 确认）；rolling 仅按 5.1 的 CNN 实验边界启用。

---

## 1. 总体剔除与保留

- **G2 收益率 4列**：`return_1d/5d/10d/20d` 为标签，不入训，**剔除**
- **TOT_SHARE**：A 方案，**剔除**，改用 `turnover`（或 `volume_ratio` 已覆盖）
- **volume/amount**：**剔除**（绝对量不入训，仅保留比值）
- **close 恒0**：`close/prev_close -1 =0` 恒0，**剔除** close 本身（信息由其他 price_rel 覆盖）
- **当前 schema**：默认 selector 使用有序 51 列 raw feature whitelist，G9 的 18 列各追加 observation mask，模型输入为 **F=69**。`close` 是辅助列，不进入模型输入；标识/时间/is_trading、G2、TOT_SHARE、volume/amount、G6/G7 为 named blacklist。
- **双列表漂移保护**：既不在 whitelist 也不在 blacklist 的 parquet 列一律排除，并以 `warnings.warn` 显著列名提示维护者更新 whitelist/blacklist；whitelist 任一缺列直接报错。实验只能用显式 `feature_cols` 覆盖，且必须存在。

> `39+6=45`、`48`、`55` 等历史组合数字保留用于解释旧 schema 和旧实验，不得直接当作当前模型 F。

---

## 2. 各组归一化决策（逐组确认）

> 本表保留早期 frozen 39+6 schema 的分组决策记录；当前运行 schema 以第 1 节的 51 raw + 18 G9 mask 为准，
> rolling 实验的字段范围和算法以第 5.1 节为准。

| 组 | 成员（剔除后） | 缺失率 | 分布特征 | 变换 | Per-Code 操作 | 备注 |
|---|---|---|---|---|---|---|
| **G1 价格水平** 12 | `open/high/low, ma_5/10/20/60, ema_12/26, sar, trend_duokong/shortline` | `ma_60 2.73%, trend 11.47%`, 其余0~1% | `feature/prev_close -1` 后中心0，`open_rel std0.028`, `ma_60_rel std0.128` | `feature/prev_close -1`（prev_close 为同 code 上一日 close） | **per-code robust** `(x - median_code)/(IQR_code/1.349)` + `clip ±5` | 无非线性，已相对化不再 log/asinh；缺失填0 |
| **G2 收益率** 4 | `return_1d/5d/10d/20d` | — | — | — | **跳过，不入训** | 当前标签用未来收益 `open[t+1+horizon]/open[t+1]-1` 另算，horizon=5 |
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

- **所有组**：仅对原始有效值计算/应用变换；变换完成后缺失或非有限输出为中性 `0`，不得先填原始 0 再 robust/winsor。
- **warmup <1%**（如 `ma_60 2.73%, return_*` 已剔除）：最终填0。
- **结构性 53~56% 两融**：填0 + 单 `margin_mask` 通道 `[0,1]`（1=observed）
- **G8 金融行业**（`gross_margin` 9.8% 全空）：填0透传

---

## 5. 实现映射

- 配置：`data/dataset.py` `ParquetDataConfig.normalize = "per_code"`，`per_code_add_mask=True`，默认 `feature_cols` 为批准 51 列 whitelist
- Scaler：`data/scaler.py` `PerCodeGroupedScaler`，`fit(df)` 按 code 独立算 `median/IQR/winsor`，`transform_code(code, feat, cols, close)` 按 code 应用
- 验证集复用：重叠 code 用训练集 per-code 统计，未见 code 使用已保存的全局兜底统计；验证集不得重新 fit
- 持久化：`logs/scaler_per_code.pkl` 仅接受 `v3_per_code` payload，含 canonical JSON SHA-256 `identity_manifest/identity_hash` 与 `schema_manifest`。identity 绑定 resolved parquet path、size/mtime_ns、parquet row/schema digest、fit 日期、特征顺序、normalization/mask/filter/max_codes 和 transform digest。训练仅复用 identity 和 schema 完全一致的缓存，否则重拟合覆盖；旧/非法 payload 不会回退为原始 pickle。验证始终接收内存中的训练 scaler，绝不 fit。
- **验证日期 context（frozen）**：有 `start_date` 时，每股只取一条此前最后 eligible `is_trading` 行参与 relative 变换；变换后立即移除，不能进入标签、group、window 或 index。rolling validation 另按第 5.1 节最多使用 251 个有效交易日。
- 模型：默认 `featurenum=69`（51 raw feature + 18 G9 mask），由 `CNNTransformer` 使用（`train.py` 已有）

### 5.1 Rolling 实验边界

- 默认 `normalize="per_code"` 为 frozen，旧训练命令和逻辑不变；rolling 只可显式使用 `--normalize rolling`。
- 第一阶段 rolling 仅处理 `open/high/low/ma_5/ma_10/ma_20/ma_60/ema_12/ema_26`、`macd`、
  `volatility_5d/10d/20d`、`volume_ratio_5d/10d` 和 `amihud`。价格类与 `macd` 先 relative，再按 `[t-251,t]`
  做 rolling median/IQR robust 并 clip；其余指定列做 rolling 1%/99% winsor。
- `close` 仅作 relative/rolling 辅助列，不作为模型输入；`sar`、`trend_*`、`std_*`、`atr` 等暂不 rolling，
  其他特征按 passthrough/G9 mask 规则处理。
- validation 可使用 split 前最多 251 个有效交易日作为 rolling context；context 不进入 labels、windows 或 index。
- frozen 与 rolling 的 mode、version、schema、state、transform digest 和 checkpoint identity 必须隔离，禁止互用。
- rolling 目前只在 CNN 内实现实验，不实现 quant exporter；quant 回迁仍是未来阶段。

### 5.2 标签和回测边界

- 窗口长度 `T=60`，默认 horizon=5。
- 标签收益：`open[t+1+horizon]/open[t+1]-1`，51 个 BINS 边界对应 `C=52` 类。
- 回测：T 日决策，T+1 open 买入，T+6 open 卖出。
- 旧 close-close 标签和缓存仅作历史记录，不能与当前 open-open 数据、checkpoint 或回测结果混用。

---

## 6. 待办

- [x] G1~G9 逐组讨论确认
- [x] 按本 spec 改造 `dataset.py` 支持 `per_code` 分支并打通 `train.py` 训练（`normalize="per_code"`）
- [x] 小样本验证：`--max_codes 10 --normalize per_code` 检查默认 `x [69,60]` 无 NaN/inf
- [ ] 全量冒烟：`--max_codes 100 --normalize per_code --epochs 1` 验证 loss 收敛
