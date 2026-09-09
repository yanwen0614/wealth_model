# 审查清单 — rolling-normalization-cnn

> 生成时间：2026-09-09 16:25

## 需求理解

本任务只在当前 CNN 项目实现 rolling normalization 实验：`parquet -> ParquetDataset -> CNNTransformer`。默认 `normalize="per_code"` 继续使用 frozen `PerCodeGroupedScaler`；rolling 必须显式 opt-in。quant 项目、quant exporter、rolling parquet 导出均不在范围内。

显式假设：当前代码事实优先，默认输入是 51 raw + 18 G9 mask = `F=69`；`close` 只读作 relative/rolling 辅助列，不进入模型输入；rolling 采用 `[t-251,t]`、含 t、`min_periods=120`，历史不足按约定 frozen fallback；validation 可使用 split 前 context，但不得把 context 用于标签、窗口或 index。若 close 必须成为输入，状态应为 blocked，等待用户确认。

## 影响范围

| 模块 | 文件 | 操作 | 审查重点 |
|---|---|---|---|
| data | `data/rolling_scaler.py` | 新增 | kernel、前视、fallback、独立 transform digest |
| data | `data/dataset.py` | 修改 | rolling opt-in、过滤/排序/标签/窗口和 context 不变 |
| data | `data/scaler.py`, `data/schema.py` | 修改 | frozen 不回归；schema/identity/输出列隔离 |
| training/config | `train.py`, `config/defaults.py` | 修改 | 默认 frozen、显式参数、run metadata |
| model | `models/cnn_transformer/*` | 兼容检查 | `ModelConfig` 与 `F=69,T=60,C=52` 对齐 |
| eval | `scripts/eval_bins_mapping.py` | 修改 | checkpoint mode/schema/identity 校验 |
| tests | `tests/unit/data/*` | 新增/修改 | 数值、时序、维度和回归契约 |
| docs | README/AGENTS/spec | 修改 | F=45 历史文案与 F=69 事实分离 |

## 重复检测

| 搜索关键词 | 结果 | 位置/结论 |
|---|---|---|
| `rolling normalization` | 未发现实现 | issue 有设计口径；仅规划 |
| `rolling` | 已存在但无关 | `scripts/run_backtest.py` 是回测模式，不能复用为预处理 |
| `PerCodeGroupedScaler` | 已存在 | `data/scaler.py`；frozen 唯一基线，rolling 不得二次调用 |
| `identity_hash/schema_manifest` | 已存在 | `data/scaler.py` v3；rolling 应采用独立 version/mode/digest |
| `ParquetDataset` | 已存在 | `data/dataset.py`；已有 context、fit/reuse 和窗口契约 |
| `F=69` | 已存在 | `data/dataset.py`, `config/defaults.py` 当前工作树事实 |
| `F=45` | 大量旧文档/测试描述 | README、AGENTS、spec、旧测试需文档漂移处理 |
| `CNNTransformer` | 已存在 | `models/cnn_transformer/model.py`；不新增模型 |

## 核心审查项

### 默认 frozen 回归

- [ ] 未传 rolling 参数时仍走 `normalize="per_code"`，默认命令和已有 scaler 路径不变。
- [ ] `is_trading=False` 过滤、`code,kline_time` 排序、open-open 标签和 `max_s` 窗口索引逐项回归。
- [ ] 训练 scaler 只 fit；validation 只复用训练对象，未见 code fallback 语义不变。
- [ ] frozen 产物、旧 `scaler_per_code.pkl` 和默认 checkpoint 不被 rolling 覆盖。

### Rolling kernel 前视与边界

- [ ] 每个 code 独立排序；统计窗口为 `[t-251,t]`，包含当前 t，不使用 t+1。
- [ ] 对 t+1 及之后数据扰动，t 的 rolling 输出和 mask 不变化。
- [ ] `min_periods=120`、expanding fallback、缺失不参与统计均有精确 synthetic case。
- [ ] G1/relative、G3/G4/macd winsor、G5 其他/G8 透传、G9 value+mask 与 manifest 一致。
- [ ] close 可用于 relative/rolling 辅助，但不出现在模型输入列或输出 schema。

### Split context 与标签

- [ ] validation/test 起点前每 code 的历史 context 可用于 rolling 统计。
- [ ] context 行在变换后被移除，不进入 label、group、window、index 或样本计数。
- [ ] 未来标签仍为 `open[t+1+horizon]/open[t+1]-1`，不因 rolling 改变。
- [ ] split 边界和窗口数量与 frozen 相同样本对照可解释。

### Schema / checkpoint 隔离

- [ ] frozen/rolling 的 mode、version、window、min_periods、feature order、辅助列、transform digest、identity hash 均独立。
- [ ] rolling 不能加载 frozen scaler；frozen 不能加载 rolling scaler；不匹配必须显式报错。
- [ ] checkpoint metadata 记录 preprocessing identity 和 `F=69,T=60,C=52`；F=45 旧 checkpoint 不复用。
- [ ] 评估脚本按 checkpoint metadata 选择同 mode preprocessing，不在模型侧重复归一化。

### Model forward shape

- [ ] `ModelConfig(featurenum=69, seq_len=60, num_classes=52)` 与 dataset 输出一致。
- [ ] `CNNTransformer(torch.randn(B,69,60))` 返回双头 tuple；`logits.shape == [B,52]`、`ret_pred.shape == [B]`。
- [ ] trainer/criterion 对双头输出无新增分支耦合；rolling 只改变输入 preprocessing。

## Full Quality Gate

| # | 关卡 | 检查项 | 优先级 |
|---|---|---|---|
| 1 | 规范一致性 | 命名、日志、注释、行宽；不写 quant 导出逻辑 | HIGH |
| 2 | 模块边界 | data 负责 preprocessing；train 只编排；model 不复制 scaler | HIGH |
| 3 | 数据安全 | 无凭证；无跨 split 前视；不读取 quant 项目 | HIGH |
| 4 | 导入合规 | 无未使用/通配符 import；新增模块可独立导入 | MEDIUM |
| 5 | 错误处理 | identity/schema mismatch 不静默 fallback；统计失败可见 | HIGH |
| 6 | 性能 | 不做全量 O(N²)；关注 252 窗口、内存、耗时和样本损失 | MEDIUM |
| 7 | 测试 | focused unittest、py_compile、ruff、frozen smoke、rolling smoke | HIGH |
| 8 | 产物隔离 | rolling/frozen scaler、checkpoint、config 和评估输入不可混用 | HIGH |

本阶段只生成文档，不执行上述命令；后续编码阶段由 Quality Gate 执行。
