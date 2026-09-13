# 审查清单 — rolling-normalization-redesign

> 生成时间：2026-09-13 23:31
> 依据：`grouped_scaler_DESIGN_SPEC.md` v1.0 / `grouped_scaler_INTERVIEW_LOG.md`（Q1–Q7）

## 需求理解

实现归一化层与滚动归一化重构（DESIGN_SPEC v1.0），全面替换旧默认 schema：
- 列分组 P/R/N/G；`APPROVED_RAW_FEATURES` 51→52（`close` 解禁进 P）；1 个 shared `g9_observed_mask`；`F_out=52+1=53`。
- 新增 `normalize="relative"` + `RelativeScaler`（E0，无 fit）；`rolling_scope ∈ {e0..e5}`；`--feature_cols` 子集入口。
- `ColumnRule` Registry 集中注册列→变换；修复 rolling 入 scope 的 G9 列短路 mask；`featurenum` 实测派生为权威。
- 导出 `config.json` 含 `feature_cols`/`feature_cols_out`（含 mask）；三处版本 bump；文档同步。
- 实验矩阵 E0=relative+e0；E1=per_code+e1；E2–E5=rolling+e2..e5。

### 显式假设（实现时需确认）

1. `relative` 模式**无持久化 state**（纯确定性变换），验证/评估按同规则重算，缓存 identity 用 rules digest；因无 fit，
   不违反「禁止验证集重 fit」红线（该红线针对需要统计量的 per_code/rolling）。
2. `--feature_cols` 收窄时，shared mask 仅对**子集中出现的 G9 列**求 OR；若子集不含任何 G9 列则不追加 mask，
   `F_out = len(feature_cols_out)`；默认全列时为 53。
3. `e1` 仅作 `rolling_scope` 名称占位；E1 走 `normalize=per_code`，其「P 静态」由 per_code 策略对 P 组应用鲁棒统计实现，
   `rolling_scope` 在 per_code 下被忽略（与现状 `test_per_code_ignores_rolling_scope` 一致）。
4. 非 scope 列在 rolling 模式下也按 `COLUMN_RULES` 变换（R asinh / N clip01 / G 固定 clip），
   以保证 E 臂间仅「滚动列集」单变量差异。
5. 评估脚本 `featurenum` 缺省 45 改为「从 checkpoint metadata 实测 / 默认 53」；旧 ckpt 不静默按 45 继续。
6. 根 `AGENTS.md` 一并同步（用户列表外补充，因多处 F=69）。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|---|---|---|---|
| schema | data/schema.py | 新增/修改 | FEATURE_GROUPS P/R/N/G；52 raw；shared mask；close 解禁 |
| scaler | data/scaler.py | 新增/修改 | ColumnRule Registry；RelativeScaler；PerCodeGroupedScaler 重构；版本 bump |
| rolling | data/rolling_scaler.py | 新增/修改 | scope e0..e5；G9 mask 修复；非 scope 规则；close 解禁；版本 bump |
| dataset | data/dataset.py | 修改 | relative 分支；num_features 实测；cache key；`_RollingDatasetState` payload version |
| cache | data/feature_cache.py | 修改 | `CACHE_FORMAT_VERSION` bump；`feature_cols_out` 落盘 |
| train/CLI | train.py, config/defaults.py | 修改 | --feature_cols/--featurenum；删 69 断言；feature_cols_out 落盘 |
| 评估脚本 | scripts/eval_bins_mapping.py, run_eval_pipeline.py, run_eval_full.sh, multi_seed_train.py | 修改 | mode relative；scope e0..e5；featurenum 实测 |
| 测试 | tests/unit/** | 新增/修改 | 53 维度契约；新 schema/规则/relative/scope 覆盖 |
| 文档 | docs/per_code_normalization_spec.md, README_TRAINING_CHAIN.md, data/AGENTS.md, models/AGENTS.md, AGENTS.md | 修改 | F=53 与新分组 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 处置 |
|---|---|---|---|
| 分组逻辑 `GROUP_DEFS_PER_CODE`/`PER_CODE_CONFIG` | 是 | data/scaler.py:37-64 | 用 `FEATURE_GROUPS`+`COLUMN_RULES` 替换并删除 |
| `asinh` 变换 | 是（仅 G6 不可达分支） | data/scaler.py:67-68,159-172,317-331 | 提取为 `ColumnRule("R")`，rolling 侧新增 |
| `winsor` 逻辑 | 是（per-code 与 rolling 各一份） | data/scaler.py:55-64,179-212；data/rolling_scaler.py:304-307 | 统一命名常量；per_code 不再 winsor |
| `relative` 逻辑 | 是（两份实现） | data/scaler.py:253-261；data/rolling_scaler.py:190-200 | 统一 `x/close[t-1]-1`，尽量共用 |
| `scope` 预设 | 是 | data/rolling_scaler.py:43-47 | 扩为 e0..e5 |
| G9 mask | 是（18 逐列） | data/scaler.py:217,284-291；data/rolling_scaler.py:129,240-243 | 改 1 个 shared OR mask，修短路 |
| `close` 禁令 | 是 | data/schema.py:52；data/rolling_scaler.py:158-161 | 移除 |
| `featurenum` 硬编码 | 是 | train.py:90；config/defaults.py:37；eval_bins_mapping.py:250；run_eval_pipeline.py:203 | 实测派生 |
| `RelativeScaler` / `ColumnRule` | 否 | — | 新增，无重复实现 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名/日志/注释风格；命名常量（`ASINH_CLIP`/`AMIHUD_SCALE`/`P_CLIP`）；docstring 与类型注解；`line-length 120` | HIGH |
| 2 | 模块边界 | `data/*` 不 import 具体 `models/*`，`models/*` 不 import `data/*`，仅 `featurenum` 数值契约；`feature_cols_out` 单一事实源；新增策略未侵入 data 外 | HIGH |
| 3 | 数据安全 | 无硬编码凭证；scaler 只在训练集 fit；验证/评估复用不重 fit；relative 无 fit 语义明确 | HIGH |
| 4 | 导入合规 | 无通配符 import；无未使用 import；删除旧 `GROUP_DEFS_PER_CODE`/`PER_CODE_CONFIG`/`_asinh` 残留 | MEDIUM |
| 5 | 错误处理 | 未知列/未知组 raise；未知 normalize raise；缓存写失败有日志不静默；rolling 维度不匹配警告而非静默；`g9_observed_mask` OR 语义明确 | MEDIUM |
| 6 | 性能风险 | `_rolling_column` 保持向量化（不退化逐行）；pandas rolling 不变；featurenum 69→53 减少首层通道（无参数量突增）；无 O(N²) 全量扫描 / 无 parquet 全量重复加载 | MEDIUM |

## 通用模型接口校验（F=featurenum 随 53 变）

| 校验项 | 断言 |
|---|---|
| 前向形状 | `CNNTransformer(ModelConfig(featurenum=53,seq_len=60,num_classes=52))(torch.randn(2,53,60))` → `logits.shape==(2,52)`，`ret_pred.shape==(2,)` |
| `out[0]` 旧契约 | `out[0].shape==(B,52)`（双头恒返 tuple，兼容旧调用） |
| 维度一致性 | `model_cfg.featurenum == ds.num_features == len(ds.feature_cols_out) == 53`（默认全列） |
| 单样本契约 | `ds[0][0].shape==(53, seq_len)`；`y∈[0,52)`；`y_ret∈[-0.5,0.5]` |
| 列序契约 | `feature_cols_out == [P:18]→[R:16]→[N:12]→[G:6]→["g9_observed_mask"]` |
| 评估/推理 | 从 checkpoint `config.json` 读 `featurenum`/`feature_cols_out`，模型 `strict=True` 加载；异 scope/identity 拒绝 |
| ModelConfig 对齐 | `config/defaults.py` 占位 `featurenum=53`，训练以实测覆盖；`--featurenum` 显式冲突报错 |
