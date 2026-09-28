# 大产物清单（未入库索引，源路径 `~/code/goal`，HEAD `88d851c`）

> 本目录仅收录 `artifacts/README.md` + 小指标 JSON；以下二进制/大文件**均未入库**，
> 需复现时回源目录按路径取用。状态定义见 `../docs/experiments.md`。

## 数据（7.5G）

| 路径 | 体积 | 说明 |
|---|---|---|
| `data/train_data.parquet` | ~3.5G | 源表拷贝（58列/1141万行/5166股，2013-01-04~2025-12-31） |
| `data/new/train_data_20260831.parquet` | ~4G | 预拼接全集（含 2026-01~08） |
| `data/sample_100.parquet` | 小 | 100股全历史采样 |

## 产物（6.9G，按体积）

| 路径 | 体积 | 状态 | 说明 |
|---|---|---|---|
| `artifacts/exec_cache/` | 2.5G | 缓存 | 执行缓存 4 份 parquet（t1open/close/mid/dayclose） |
| `artifacts/new_split/` | 2.0G | experimental | 新切分 5d/20d/40d horizon 实验 |
| `artifacts/opt_roll/` | 1.6G | historical | H1 滚动归一化实验 |
| `artifacts/opt_mag/` | 202M | historical | 幅度加权 W1-W4 |
| `artifacts/opt_feat/` | 202M | historical | 特征剪枝/G6回补/seqstats |
| `artifacts/opt_model/` | 167M | historical | 架构实验 |
| `artifacts/opt_joint/` | 87M | historical | 多任务联合+融合 |
| `artifacts/opt_extend/` | 78M | historical | 延长段 top100/seg2026/full range |
| `artifacts/opt_ltr_hgb/` | 45M | historical | HGB pairwise |
| `artifacts/baseline/` | 43M | historical | 主基线：`pred_test.parquet` 33M + `scaler.pkl` 8M + `model_hgb.pkl` 1.2M（JSON 已入库本存档） |
| `artifacts/opt_ltr/` | 42M | historical | MLP-RankNet |
| `artifacts/opt_lambda/` | 42M | historical | LambdaRank |
| `artifacts/opt_2026/` | 23M | experimental | 2026 前瞻（冻结模型） |
| `artifacts/opt_exec/` | 13M | historical | 执行参数网格 |
| `artifacts/joint_e2e/` | 5.4M | **INVALID** | 40日 stride 重叠失效，禁引用 |
| `artifacts/opt_final/` | 小 | historical | 最完整可交易证据（`account.json` 已入库；`trades.csv` 332K 回源取） |
| `artifacts/joint_e2e_gate_off/` | 小 | current/experimental | 修正版（JSON 已入库本存档） |
| `artifacts/daily_continuous_runs/` | 小 | current/experimental | stride1 完整产物（TEST account.json 167K 已入库 `daily_stride1/`） |
| `artifacts/opt_trigger/` | 小 | negative | 触发式判负 |
| `artifacts/opt_trigger_top100/` | 小 | negative | H4/H5 2026 全败判负 |

## 已入库小指标（本存档可直接读）

`artifacts/baseline/{backtest,data_check,metrics,metrics_torch}.json`、
`artifacts/opt_final/account.json`、
`artifacts/joint_e2e_gate_off/{build_stats,selection,test_once_guard}.json`、
`artifacts/daily_stride1/{account,test_once_guard,selection}.json`。
