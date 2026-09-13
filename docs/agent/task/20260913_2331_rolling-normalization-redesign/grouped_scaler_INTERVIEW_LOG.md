# quant-model 项目 - 归一化层（grouped_scaler）交互式访谈记录

> Module: `grouped_scaler` | Version: v1.0 | Date: 2026-09-13 | task-tag: `rolling-normalization-redesign`
> 规则：每次仅 1 问，标注分类 `[工程]`/`[算法]`/`[工程+算法]`，优先选择题；基于 Phase 1 `grouped_scaler_MODULE_DESIGN.md` 的代码现状。
> 背景：E1–E4 归一化对照实验（per_code vs rolling e2/e3/e4）在 warmup 修复后四臂 TopN 回测全部跑输基准，触发本次 redesign。

## 访谈摘要表

| # | 分类 | 议题 | 结论 |
|---|---|---|---|
| Q1 | [工程+算法] | E0–E5 六臂的接口表达 | **方案 1+2**：新增 `normalize=relative` + scope 预设 `e0/e1`；同时暴露 `--feature_cols` 子集入口 |
| Q2 | [算法] | E0 臂 P 组相对值是否 clip | **clip ±5**（与 E1/E2 仅差统计量，单变量对照干净） |
| Q3 | [工程+算法] | 唯一共享 mask 的合成规则 | **OR(任一 G9 列 finite)**，即"该股是否具备两融数据" |
| Q4 | [算法] | G9 `*_raw` 在 E0–E4 的粗 clip 区间 | **按提议区间**（net_buy[-1,1]、chg_5d[-1,5]、buy[0,1.5]、balance/short[0,1]，缺失填 0） |
| Q5 | [工程] | `train.py:90` 硬编码 `featurenum==69`；导出 config 需含特征列名 | **实测派生为权威**（`--featurenum` 缺省 None；metadata 断言 == `train_dataset.num_features`；模型 config 用实测覆盖；rolling 不硬失败）+ **导出 config.json 必须写入 `feature_cols` 列名** |
| Q6 | [工程+算法] | 新设计对现有默认行为的影响 | **全面替换默认**：新 schema 为唯一口径，旧 51 列/69 维/18 mask 路径移除 |
| Q7 | [工程] | 测试与验收口径 | **TDD + 全套验收**（新规则单测 + 旧契约测试同步 + ruff + `--smoke` + 重建缓存 + 全量 E0–E5 重训评估） |

## 逐题记录

### Q1 [工程+算法] E0–E5 六臂的接口表达
- **提问依据**：Phase 1 §8.6 —— `normalize ∈ {per_code, rolling}`（`data/dataset.py:71`）、`rolling_scope ∈ {e2,e3,e4}`（`data/rolling_scaler.py:43-47`）、per_code 无子集入口（`train.py:117-149` 无 `--feature_cols`）。
- **候选**：① 统一 scope 概念（新增 `relative` 模式 + `e0/e1` 预设）；② 新增 `--feature_cols` 子集入参；③ 新增 `--normalize e0..e5` 六值枚举。
- **用户结论：① + ②**。既新增 `normalize=relative` 与 scope 预设 `e0`（空集/纯 relative）、`e1`（仅 P 组静态），又同时暴露 `--feature_cols`/静态子集，使 per_code 与 rolling 都能收窄。理由：保留"归一化模式"与"列子集"两个正交维度，实验臂用同一框架逐级对照。

### Q2 [算法] E0 臂 P 组相对值是否 clip
- **提问依据**：E0 定义为"P 组仅 relative、无统计量"，但相对值 `x/close[t-1]-1` 仍可能有极端值（低价股/异常 bar）。
- **候选**：① clip ±5；② 不 clip。
- **用户结论：① clip ±5**。E0/E1/E2 的 P 组输出统一 clip 到 [-5,5]，三者仅统计量不同，保证单变量对照。

### Q3 [工程+算法] 唯一共享 mask 的合成规则
- **提问依据**：Phase 1 §8.2 与 mask 必要性分析——18 列有 2.9% 行为"部分有/部分无"，共享单 mask 需定义合成方式。
- **候选**：① OR(任一 finite)；② AND(全部 finite)；③ 代表列 isfinite。
- **用户结论：① OR(任一 G9 列 finite)**。语义等价"该股是否具备两融数据"，混合行归为"有"。17.9→1 个通道，F 从 69 降至 53。

### Q4 [算法] G9 `*_raw` 在 E0–E4 的粗 clip 区间
- **提问依据**：Phase 1 §8.1 —— `*_raw` 原被 `clip[0,1]` 抹掉负值；E0–E4 阶段 `*_raw` 不进滚动，需固定粗 clip。
- **候选**：① 按提议区间；② 统一 `asinh+clip±5`；③ 直接进滚动。
- **用户结论：① 按提议区间**：`margin_net_buy_ratio_raw∈[-1,1]`、`margin_balance_chg_5d_raw∈[-1,5]`、`margin_buy_ratio_raw∈[0,1.5]`、`margin_balance_ratio_raw∈[0,1]`、`short_balance_ratio_raw∈[0,1]`、`short_sell_vol_ratio_raw∈[0,1]`，缺失填 0。E5 起这 6 列转入 rolling。

### Q5 [工程] `train.py:90` 硬编码 `featurenum==69`（重问后定稿）
- **提问依据**：Phase 1 §8.5 —— `build_preprocessing_metadata` 对 `featurenum != 69` 直接 raise（`train.py:90-91`）；`:308-321` 非 rolling 静默自动校正、rolling 维度不符硬失败（`:310-314`）；F 将从 69 → 53。
- **重问原因**：首答"可配参数+缺省推导"未明确"推导的事实源"（实测 vs schema 常量）与不一致时的行为。
- **候选**：① 实测派生为权威；② schema 常量 `EXPECTED_FEATURENUM=53` 为权威；③ 常量缺省 + 不一致报错。
- **用户结论：① 实测派生为权威**：
  - `featurenum` 的唯一事实源 = 运行时 `train_dataset.num_features`（即 `scaler.feature_cols_out` 长度）；
  - `--featurenum` 缺省 `None`，不新增 schema 常量；
  - `build_preprocessing_metadata` 断言 `metadata.featurenum == train_dataset.num_features`，删除 `!=69` 硬断言；
  - 模型 config 以实测值覆盖（含 rolling，取消硬失败，仅记录 warning）；
  - **额外要求**：训练导出/保存 config 时必须写入**特征列名**（`feature_cols`），确保 checkpoint 可自描述、评估/推理无需猜列序。现状 `config.json` 已含部分元数据但需保证 `feature_cols`（及 mask 列）随 config 落盘。

### Q6 [工程+算法] 新设计对现有默认行为的影响
- **提问依据**：close 入特征、R 组 asinh、共享单 mask 会改变默认 F 与默认特征语义（Phase 1 §8.1/§8.2/§8.4）。
- **候选**：① 列级改进转默认；② 全部 opt-in 兼容；③ 全面替换默认。
- **用户结论：③ 全面替换默认**。新 schema 为唯一口径；旧 51 列/69 维/18 mask 路径移除；旧 scaler/缓存/MODULE 产物作废，需重建。

### Q7 [工程] 测试与验收口径
- **提问依据**：Phase 1 文件清单列出 10+ 个与新契约耦合的测试。
- **候选**：① TDD + 全套验收；② 仅 smoke + 重训；③ 单测 + 小样本。
- **用户结论：① TDD + 全套验收**。新规则（P/R/N/G 分组、asinh、单 mask、close 入特征、scope e0/e1/e5、featurenum 推导）先写测试；同步更新旧契约测试；验收 = `unittest discover tests/unit` + `ruff check .` + `--smoke` + 重建缓存 + 全量 E0–E5 重训与截面/回测评估。

## 设计决策汇总（供 Phase 4 SPEC 使用）

### 1. 列分组与处理（F = 52 raw + 1 mask = 53）

| 组 | 列数 | 列 | 规则 |
|---|---|---|---|
| **P 价格量纲** | 18 | open, high, low, **close**, ma_5/10/20/60, ema_12/26, sar, trend_duokong, trend_shortline, macd, std_5/10/20, atr | `x/close[t-1]-1`，clip ±5（+各臂统计量） |
| **R 无界比值** | 16 | dmi, adx, boll, kelch, trend_duokong_dev, volatility_5/10/20, volume_ratio_5/10, gross_margin, net_margin, roe, roa, debt_to_equity | `clip(asinh(x), ±5)` |
| — amihud | 1 | amihud | `clip(asinh(x*1e12), ±5)` |
| **N 已归一化** | 12 | G9 rank 6 + `*_ts` 6 | 保持 `clip[0,1]` |
| **G 原始比值** | 6 | G9 `*_raw` 6 | E0–E4 按 Q4 区间粗 clip（缺失填 0）；E5 起滚动 |
| **mask** | 1 | 共享 `G9_observed` = OR(18 列任一 finite) | 0/1 |

### 2. 实验矩阵 E0–E5（逐级扩列）

| 臂 | P 组 | 滚动范围 | 其余 |
|---|---|---|---|
| E0 | 仅 relative（clip±5） | — | R/G asinh/clip；N clip；单 mask |
| E1 | relative + 静态 per-code 全历史 robust | — | 同上 |
| E2 | relative + rolling 252 robust | P | 同上 |
| E3 | rolling | P + volatility 3 | 同上 |
| E4 | rolling | + volume_ratio 2 + amihud | 同上 |
| E5 | rolling | + G9 `*_raw` 6 | 同上 |

- 接口：`--normalize {relative, per_code, rolling}` + `--rolling_scope {e0,e1,e2,e3,e4,e5}` + `--feature_cols` 子集（Q1）。
- E0 = `relative` + `e0`（空 scope）；E1 = `per_code` + `e1`（仅 P 组静态）；E2–E5 = `rolling` + `e2..e5`。
- E5 必须修复 Phase 1 §8.3：`output_feature_cols` 与实际列数一致、入 scope 的 G9 不再短路 mask。

### 3. 工程契约
- `featurenum` 实测派生为权威，`--featurenum` 缺省 None（Q5）；导出 config 必含 `feature_cols` 列名。
- 新 schema 全面替换默认，旧 51 列/69 维/18 mask 路径移除（Q6）。
- `CACHE_FORMAT_VERSION`、`SCALER_VERSION`、rolling payload version 全部 bump，旧产物作废。
- TDD 先写测试，验收 = 单测 + ruff + `--smoke` + 重建缓存 + 全量 E0–E5 重训评估（Q7）。

### 4. 沿用既有设计（非本次访谈新增，来自前置讨论/已落地）
- warmup context：`start_date` 前历史行作窗口输入、绝不作标签日；训练验证与评估全启用。
- 固定实验变量：seed 42 / epochs 50 / patience 5 / batch_size 1024 / lr 1e-4。

### 5. 待 SPEC 明确的遗留项
- G9 `*_ts` 语义（代码与文档均未定义）需在 SPEC 中明确或降级处理。
- P 组中 `open/high/low` 以 `close[t-1]` 为分母的统一性；`close[t]/close[t-1]-1` 等价 `return_1d`（已接受）。
- `docs/per_code_normalization_spec.md` 与 `data/AGENTS.md` 的 F 描述须同步。

## 附录 B：变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-09-13 | 首版：7 题访谈定稿（Q5 重问后以"实测派生为权威 + 导出 config 写列名"定案） |


