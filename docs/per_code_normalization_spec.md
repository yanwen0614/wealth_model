# Per-Code 分组归一化共识文档（frozen 基线与 rolling 实验边界）

> 生成时间：2026-09-03  
> 数据：`data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`（11.4M行，5166股，58列）  
> 基准：`quant/scripts/export_training_data.py` 的原始因子集合为 48 列；基础列与剔除规则见下。
> 当前默认输出：**52 个 raw feature（`P18+R16+N12+G6`）+ 1 个共享 `g9_observed_mask` = `F=53`**，列序 `[P→R→N→G→mask]`（`data/schema.py` `FEATURE_GROUPS`/`APPROVED_RAW_FEATURES`）。
> `F=69`（旧 51 raw + 18 逐列 mask）、`F=45`（39+6 mask）、`F=55` 均为**历史** schema/实验，不是当前默认输入。
> 三策略：`relative`（E0 无状态）/`per_code`（E1 静态 per-code）/`rolling`（E2–E5 滚动）；`close` 已解禁进 P 组；E0–E5 矩阵见 5.1。
> frozen 基线总基调：**per-code（P 组静态 robust）归一化，不做 window**（用户 2026-09-03 确认）；rolling 仅按 5.1 的 CNN 实验边界启用。

---

## 1. 总体剔除与保留

- **G2 收益率 4列**：`return_1d/5d/10d/20d` 为标签，不入训，**剔除**
- **TOT_SHARE**：A 方案，**剔除**，改用 `turnover`（或 `volume_ratio` 已覆盖）
- **volume/amount**：**剔除**（绝对量不入训，仅保留比值）
- **close**：历史上以 `close/prev_close -1 ≡0` 为由剔除；redesign 后 **解禁进 P 组**——relative 分母统一取 `close[t-1]`，`close[t]` 自身作相对特征非恒 0。
- **当前 schema（redesign）**：默认 selector 使用有序 **52 列 raw feature**（`P18+R16+N12+G6`）；G9 的 18 列不再逐列追加 mask，而是共享 **1 个 `g9_observed_mask`**（= OR 18 个 G9 列任一 finite），模型输入为 **F=53**。标识/时间/is_trading、G2、`TOT_SHARE`、`volume/amount`、G6/G7 为 named blacklist（`PROHIBITED_COLUMNS`，已移除 `close`）。
- **双列表漂移保护**：既不在 whitelist 也不在 blacklist 的 parquet 列一律排除，并以 `warnings.warn` 显著列名提示维护者更新 whitelist/blacklist；whitelist 任一缺列直接报错。实验只能用显式 `feature_cols` 覆盖，且必须存在。

> 历史组合数字保留用于解释旧 schema/旧实验：`69=51+18 mask`、`45=39+6 mask`、`48`（原始因子集合）、`55`。它们**均非当前模型 F**（当前 `F=53=52+1`）。

---

## 2. 各组归一化决策（逐组确认）

> **当前分组（redesign）**以 `data/schema.py` `FEATURE_GROUPS` 为准（列序 `[P→R→N→G→mask]`）：

| 新组 | 列数 | 列（顺序即输出列序契约） | 变换 | clip |
|---|---|---|---|---|
| **P 价格/量价** | 18 | `open,high,low,close,ma_5/10/20/60,ema_12/26,sar,trend_duokong,trend_shortline,macd,std_5/10/20,atr` | `x/close[t-1]-1`（E1+ 再 robust） | `±5` |
| **R 比值/波动** | 16 | `dmi,adx,boll,kelch,trend_duokong_dev,volatility_5/10/20,volume_ratio_5/10,gross_margin,net_margin,roe,roa,debt_to_equity,amihud` | `clip(asinh(x·scale),±5)`（`amihud scale=1e12`，其余 `scale=1.0`） | `±5` |
| **N 两融 rank** | 12 | G9 rank 6 + `*_ts` 6 | 恒等 | `[0,1]` |
| **G 两融 raw** | 6 | G9 `*_raw` 6 | E0–E4 固定 clip / E5 rolling winsor | `G9_RAW_CLIP` |
| **mask** | 1 | `g9_observed_mask` | OR(18 个 G9 列 finite) | `{0,1}` |

> 下表保留早期 frozen 39+6 schema 的 G1~G9 分组决策记录（**历史**，非当前分组）；当前运行 schema 以上表与第 1 节的 52 raw + 1 shared mask 为准，
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

- **median（中位数）**：P 组 robust 的统计量；E1 用**单股全历史**中位数（静态），E2+ 用 `[t-251,t]` 的 252 窗口滚动中位数，抗极端；替代 `mean`。
- **IQR（四分位距）**：`Q3-Q1`，替代 `std`，同样抗极端；`IQR/1.349` 使尺度对齐正态 std（`IQR_TO_SIGMA=1.349`）。
- **robust**：`(x_rel - median) / (IQR/1.349 + EPS)` 后 `clip ±5`；仅 P 组使用（E0 无统计量，E1 静态，E2+ 滚动）。
- **relative**：`x / close[t-1] - 1`，分母为同股上一日 close（`RELATIVE_DENOMINATOR="close"`），消除量纲；P 组统一先 relative。
- **asinh**：R 组 `clip(asinh(x·scale), ±5)`，保符号并压缩无界重尾（`amihud scale=1e12`，其余 1.0）。
- **clip / winsor**：N 组 `clip[0,1]`；G 组 E0–E4 固定区间 `G9_RAW_CLIP`（缺失填 0），E5 转为滚动 1%/99% winsor。

---

## 4. 缺失分级（per-code 内）

- **所有组**：仅对原始有效值计算/应用变换；变换完成后缺失或非有限输出为中性 `0`，不得先填原始 0 再 robust/winsor。
- **warmup <1%**（如 `ma_60 2.73%, return_*` 已剔除）：最终填0。
- **结构性 53~56% 两融**：填 0 + 单 **共享** `g9_observed_mask` 通道 `[0,1]`（1=任一 G9 列 observed；替代历史 18 个逐列 mask）。
- **R 组缺失**（如 `gross_margin` 9.8% 全空）：变换后缺失填 0（`gross_margin` 已入 R 组走 asinh，历史 G8 白名单已删）。

---

## 5. 实现映射

- 配置：`data/dataset.py` `ParquetDataConfig.normalize` 默认 `"per_code"`（另支持 `relative`/`rolling`），`per_code_add_mask=True`；默认 `feature_cols` 为 `data/schema.py` 批准 **52 列** `APPROVED_RAW_FEATURES`（`default_feature_cols(normalize)`），输出末尾追加 1 个 `g9_observed_mask`。
- 规则注册：`data/scaler.py` `ColumnRule` dataclass + `COLUMN_RULES`（由 `data/schema.py` `FEATURE_GROUPS` 生成，共 52 列），`column_rule(col)` 与 `data/schema.py column_group(col)` 对未知列 raise；命名常量 `ASINH_CLIP=5.0`、`P_CLIP=(-5,5)`、`N_CLIP=(0,1)`、`AMIHUD_SCALE=1e12`、`RELATIVE_DENOMINATOR="close"`、`G9_RAW_CLIP`。
- Scaler 两实现：
  - `RelativeScaler(feature_cols, add_mask=True)`（E0）：**无 `fit`**，P `x/close[t-1]-1`（+`clip±5`）、R asinh、N clip01、G fixed_clip；缺失填 0，`feature_cols_out` 末尾 shared mask。
  - `PerCodeGroupedScaler`（E1）：按 `COLUMN_RULES` 路由，仅 **P 组** `fit(df)` 按 code 独立算 `median/IQR`（在 `x/close[t-1]-1` 相对值上），`transform_code(code, feat, cols, close)` 输出 `(v-med)/(IQR/1.349+EPS)` clip±5；R/N/G 走确定性规则；未见 code 回退 `global_stats`。
- 版本与持久化：`SCALER_VERSION="v4_per_code"`、`TRANSFORM_VERSION="per_code_transform_v4"`；`logs/scaler_per_code.pkl` 仅接受该 payload（旧 `v3_per_code` 拒绝），含 `feature_cols`/`feature_cols_out`/`mask_cols` 与 canonical JSON SHA-256 `identity_manifest/identity_hash`、`schema_manifest`。identity 绑定 resolved parquet path、size/mtime_ns、parquet row/schema digest、fit 日期、特征顺序、normalization/mask/filter/max_codes 和 transform digest。训练仅复用 identity 与 schema 完全一致的缓存，否则重拟合覆盖；旧/非法 payload 不会回退为原始 pickle。验证/评估始终接收内存中的训练 scaler，绝不 `fit`。
- **验证日期 context（frozen）**：有 `start_date` 时，每股取此前最多 `max(seq_len-1,1)` 条 eligible `is_trading` 行作 context，先经同一训练 scaler 变换后保留。context **可进入滑动窗口作 warmup 输入**，但**绝不作为标签日、不产生样本标签**（`valid_starts` 按 `is_context[s+seq_len-1]` 过滤）。评估/验证**标签日覆盖 = 区间交易日数 − `(horizon+1)`**。rolling validation 另按第 5.1 节最多使用 251 个有效交易日。
- **两类 warmup 勿混**：本节 context 指**窗口输入预热**（补足首日窗口所需历史行）；第 4 节 warmup 与 5.1 rolling `min_periods`/frozen fallback 指**归一化统计预热**，二者机制不同。
- 模型：默认 `featurenum=53`（52 raw feature + 1 shared mask），由 `CNNTransformer` 使用；`featurenum` 以 `ParquetDataset.num_features=len(feature_cols_out)` 实测派生为权威，`train.py --featurenum` 缺省 None，显式≠实测 raise。
- **缓存契约**：`data/feature_cache.py` 的 memmap 缓存只存归一化**之后**的 `features`（float32）与小数组，不改变本 spec 的归一化语义；`CACHE_FORMAT_VERSION="v3_relative_groups"`，缓存 key 纳入 mode/scope/`feature_cols_out`/scaler identity 与 seq_len/horizon/bins，命中即等价复建，验证集红线不变（仍复用训练 scaler、绝不重 fit）。

### 5.1 Rolling 实验边界

- 默认 `normalize="per_code"`（E1）为 frozen 基线；`relative`（E0）与 `rolling`（E2–E5）需显式 `--normalize` 选择，`--rolling_scope e0..e5` 默认 `e5`。
- `data/rolling_scaler.py` `ROLLING_SCOPE_FEATURES`（由 `FEATURE_GROUPS` 派生）：`e0=∅`、`e1/e2=P 组 18 列`、`e3=P+volatility_5/10/20`、`e4=+volume_ratio_5/10+amihud`、`e5=+G9 *_raw 6`；滚动列数 0/18/18/21/24/30。
- 入 scope 的 **P 列**先 relative，再按 `[t-251,t]`（window=252、`min_periods=120`、含当日 t）做 rolling median/IQR robust 并 `clip±5`；入 scope 的 **vol/volume/G 列**做 rolling 1%/99% winsor；**非 scope 列**按 `COLUMN_RULES`（P relative+clip / R asinh / N clip01 / G fixed_clip）。
- `close` 已解禁进 P 组（relative 分母 `close[t-1]`）；`ROLLING_VERSION="v2_rolling_scope_e0_e5"`、`ROLLING_TRANSFORM_VERSION="rolling_transform_v2"`、`_RollingDatasetState.PAYLOAD_VERSION="v2_rolling_state"`。shared `g9_observed_mask` 恒追加末尾（e5 下 G9 raw 入 scope 也照常输出，不短路）。
- validation 可使用 split 前最多 251 个有效交易日作为 rolling context（`max(seq_len-1,251)`）；context 先经同一训练 scaler 变换，**可进入窗口作 warmup 输入，但绝不作为标签日、不产生样本标签**（`valid_starts` 过滤 `is_context[s+seq_len-1]`）；标签日覆盖 = 区间交易日数 − `(horizon+1)`。
- `relative`/`per_code` 与 `rolling` 的 mode、version、schema、state、transform digest 和 checkpoint identity 必须隔离，禁止互用。
- rolling 目前只在 CNN 内实现实验，不实现 quant exporter；quant 回迁仍是未来阶段。

#### E0–E5 实验矩阵（`featurenum` 实测=53；seed 42 / batch 1024 / patience 5 / lr 3e-4）

| 臂 | `--normalize` | `--rolling_scope` | 滚动列集（列数） | P 组统计量 |
|---|---|---|---|---|
| E0 | `relative` | `e0` | ∅（0） | 无（仅 relative+clip） |
| E1 | `per_code` | `e1` | P（18，名称占位，静态使用） | 全历史静态 robust |
| E2 | `rolling` | `e2` | P（18） | 252 滚动 robust |
| E3 | `rolling` | `e3` | P + volatility_5/10/20（21） | 252 滚动 robust |
| E4 | `rolling` | `e4` | + volume_ratio_5/10 + amihud（24） | 252 滚动 robust |
| E5 | `rolling` | `e5` | + G9 `*_raw` 6（30） | 252 滚动 robust |

> `e1`/`e2` 列集相同，语义区别在 `normalize`（per_code 静态 vs rolling 动态）；metadata 必须同时记录 `mode` 与 `scope`。非 scope 列在三模式下均按 `COLUMN_RULES` 变换，保证 E 臂间仅「滚动列集」单变量变化。

### 5.2 标签和回测边界

- 窗口长度 `T=60`，默认 horizon=5。
- 标签收益：`open[t+1+horizon]/open[t+1]-1`，51 个 BINS 边界对应 `C=52` 类。
- 回测：T 日决策，T+1 open 买入，T+6 open 卖出。
- 旧 close-close 标签和缓存仅作历史记录，不能与当前 open-open 数据、checkpoint 或回测结果混用。

---

## 6. 待办

- [x] 早期 G1~G9 逐组讨论确认（**历史**）
- [x] redesign：实现 P/R/N/G 分组 + `ColumnRule` + 三策略（relative/per_code/rolling），`schema`/`scaler`/`rolling_scaler`/`dataset`/`train` 已落地
- [x] 小样本验证：`--max_codes 10 --normalize per_code` 检查默认 `x [53,60]` 无 NaN/inf
- [ ] 全量冒烟：按 5.1 的 E0–E5 矩阵重训/评估（`--max_codes` 全量）
