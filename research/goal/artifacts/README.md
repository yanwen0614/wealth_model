# artifacts/

实验产物归档目录。每组实验可能包含 `account.json`（绩效指标）、`trades.csv`（成交明细）、`figs/account_equity.png`（净值曲线）；daily/joint 产物的文件结构不同，不能仅凭目录存在判定结果有效。

项目级入口和状态索引见 [`../README.md`](../README.md)、[`../docs/architecture.md`](../docs/architecture.md) 和 [`../docs/experiments.md`](../docs/experiments.md)。

## 目录结构

### 基线
| 目录 | 内容 |
|---|---|
| `baseline/` | 主流水线基线产物：HGB/torch 预测、回测指标、scaler、模型pkl |

### 模型实验
| 目录 | 内容 |
|---|---|
| `opt_model/` | 模型架构实验（v2、leaf参数、baseline repro） |
| `opt_feat/` | 特征工程（G1剪枝、G6/G7回补、seqstats时序统计） |
| `opt_roll/` | 滚动归一化 H1；历史模型/执行实验，指标不得脱离对应执行口径单独称为冠军 |

### 执行实验
| 目录 | 内容 |
|---|---|
| `opt_exec/` | 执行参数网格（close/t1open、freq、buffer） |
| `opt_exec2/` | 执行第二版（挑战版配置；历史年化结果约 51.20%，须结合具体模型和引擎口径） |
| `opt_edge/` | 缓冲区/最小边敏感性 |
| `opt_trigger/` | 触发式退出规则 |
| `opt_trigger_top100/` | Top100触发式（H4/H5 — 2026全败判负） |
| `opt_focus/` | 集中度实验（Top10~Top30） |
| `opt_liquid/` | 流动性过滤（min50M/min100M、参与率） |
| `opt_weight/` | 加权方案（等权/线性/二次/v5） |
| `opt_combo/` | 特征×执行联合实验 |

### 排序（LTR）实验
| 目录 | 内容 |
|---|---|
| `opt_ltr/` | MLP-RankNet |
| `opt_ltr_hgb/` | HGB pairwise（中位数参照） |
| `opt_lambda/` | LambdaRank（ΔNDCG加权） |
| `opt_mag/` | 幅度加权（W1-W4） |
| `opt_joint/` | 多任务联合+融合（λ=0.3） |

### 端到端实验
| 目录 | 内容 |
|---|---|
| `joint_e2e/` | 端到端联合训练 |
| `joint_e2e_gate_off/` | 修正版（门控关闭） |

### 其他
| 目录 | 内容 |
|---|---|
| `account/` | v1基线真实账户回测 |
| `exec_cache/` | 执行缓存（4份~630MB parquet） |
| `new_split/` | 新时段切分实验（5d/20d/40d horizon、opt_exec网格） |
| `opt_2026/` | 2026前瞻（v5引擎B配置，模型冻结） |
| `opt_extend/` | 延伸实验（top100、seg2026、full range） |
| `opt_final/` | 历史上最完整的可交易账户验证：200万、Top100、T+1 open、20日调仓 |
| `figs/` | 汇总图表 |

## 状态说明

- **当前实验**：`daily_continuous_runs/20260906_gpu_stride1_full` 和 `joint_e2e_gate_off`。daily TEST 只有 155 个可用信号日，并有 8 个 locked/unpriced holdings；joint TEST 只有 2 个 episode，均不构成稳定 2026 业绩结论。
- **历史有效账户证据**：`opt_final`、`opt_extend/top100`、`opt_edge/B_extend`。详细数字和口径以根 [`REPORT.md`](../REPORT.md) 为准。
- **失效结果**：`joint_e2e/` 因 40 日 stride 时序重叠而 INVALID，不能作为验证或 TEST 结果；其 README 已说明原因。
- **负面结果**：`opt_trigger/` 的每日触发式方案因高频噪声和成本判负，见 [`../STRATEGY.md`](../STRATEGY.md)。
- **smoke**：daily synthetic smoke 只验证状态传递、延迟奖励和执行器链路，不提供真实收益证据。

不要在本索引中使用“冠军”作为脱离口径的总称。HGB 纸面、历史账户和当前 daily/joint 实验属于不同代码链，优先级见 [`../docs/experiments.md`](../docs/experiments.md)。
