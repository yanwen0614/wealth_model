# 脚本索引

当前共同契约：训练数据来自 parquet，先过滤 `is_trading=False`；默认 per-code 输出 `F=45`
（39 个有效特征+6 个 G9 mask），`48` 是原始因子集合，`55` 不是当前默认模型输入。
序列长度 `T=60`，horizon=5，标签为 `open[t+1+horizon]/open[t+1]-1`；51 个 BINS 边界对应
`C=52`。scaler 由训练集 fit 并保存为 `logs/scaler_per_code.pkl`，验证集复用该统计。

| 脚本 | 用途 |
|------|------|
| `train.py` | 唯一训练入口 |
| `multi_seed_train.py` | 多 seed 串行训练 + λ 波动 + 汇总 |
| `eval_bins_mapping.py` | 52→11 类映射评估 |
| `build_ohlc_path.py` | 构建回测用 open 路径表 |
| `recompute_bins.py` | 全量 bins 分位离线重算 |
| `plot_topn_curve.py` | TopN 收益折线图（多模型对比） |
| `run_backtest.py` | 逐日回测 CLI |

---

## `train.py` — 训练入口

```
uv run --project . python train.py [选项]
```

| 选项 | 默认 | 说明 |
|------|------|------|
| `--smoke` | off | 冒烟：`max_codes=20, epochs=1` |
| `--max_codes N` | 全量 | 限 N 只股票（调试用） |
| `--epochs N` | 50 | 训练轮数 |
| `--batch_size N` | 256 | batch size |
| `--lr LR` | 1e-4 | 学习率 |
| `--patience N` | 10 | 早停耐心轮数 |
| `--num_workers N` | 4 | DataLoader worker 数 |
| `--seq_len N` | 60 | 序列长度 |
| `--horizon N` | 5 | 预测 horizon（日） |
| `--dual_head` | off | 双头回归 `EMD + λ·Huber` |
| `--pure_reg` | off | 纯回归消融（仅 Huber） |
| `--lambda_reg λ` | 0.2 | 回归损失权重 |
| `--huber_delta δ` | 1.0 | Huber delta |
| `--train_start / --train_end` | 2013-01-01 / 2025-06-30 | 训练时间范围 |
| `--val_start / --val_end` | 2025-07-01 / 2025-12-31 | 验证时间范围 |
| `--no_val` | off | 跳过验证集 |

示例：

```
# 冒烟测试（20 股 1 epoch，快速验证链路通断）
uv run --project . python train.py --smoke --num_workers 0

# 全量双头训练
uv run --project . python train.py --dual_head --lambda_reg 0.2 --epochs 50 --batch_size 256
```

---

## `scripts/multi_seed_train.py` — 多 seed 训练

```
uv run --project . python -m scripts.multi_seed_train [选项]
```

继承 `train.py` 全部数据/模型参数，额外：

| 选项 | 默认 | 说明 |
|------|------|------|
| `--seeds S` | `42,123,2024` | 逗号分隔的 seed 列表 |
| `--lambda_reg λ` | 0.2 | 回归权重基准值 |
| `--lambda_jitter δ` | 0.005 | λ 随机波动范围（±δ） |

每个 seed 的 λ = `lambda_reg + uniform(-jitter, +jitter)`，seed 内固定。完成后输出汇总 CSV 到 `logs/multi_seed_summary_*.csv`。

示例：

```
# 冒烟：2 seed，1 epoch
uv run --project . python -m scripts.multi_seed_train --smoke --seeds 42,123 --num_workers 0

# 全量：3 seed，50 epoch
uv run --project . python -m scripts.multi_seed_train --seeds 42,123,2024 --epochs 50 --dual_head

# 自定义 λ 基准和波动范围
uv run --project . python -m scripts.multi_seed_train --smoke --seeds 42,123 --lambda_reg 0.6 --lambda_jitter 0.01
```

---

## `scripts/eval_bins_mapping.py` — 52→11 类映射评估

```
uv run --project . python scripts/eval_bins_mapping.py [选项]
```

从训练好的 52 类模型做 softmax → 期望收益 → digitize 到 11 bins，评估 RankIC / 分位命中 / Top10%。

| 选项 | 默认 | 说明 |
|------|------|------|
| `--max_codes N` | 全量 | 限 N 只股票 |
| `--checkpoint PATH` | 自动找 | 指定 `best_model.pth` |
| `--preds_cache PATH` | 无 | 缓存推理结果 npz（供回测用） |

---

## `scripts/build_ohlc_path.py` — 构建回测路径表

```
uv run --project . python scripts/build_ohlc_path.py [选项]
```

为逐日回测生成 (code, 标签日) → 买入价 / 卖出价 / 持仓天数 的 npz 表。

| 选项 | 默认 | 说明 |
|------|------|------|
| `--val_start / --val_end` | 2025-07-01 / 2025-12-31 | 时间范围 |
| `--full` | off | 全量输出（含训练期） |
| `--out PATH` | 自动 | 输出 npz 路径 |

---

## `scripts/recompute_bins.py` — 全量 bins 分位重算

```
uv run --project . python scripts/recompute_bins.py [选项]
```

离线重算训练集 future_ret 的分位数 bins（不含验证集，防未来泄露）。

| 选项 | 默认 | 说明 |
|------|------|------|
| `--output PATH` | 控制台 | 输出 bins 到文件 |
| `--strategy` | 默认 | 分位策略（等宽/等频/自定义） |

> 口径注意：历史版本曾按 close-close 计算；该旧结果不可与当前 open-open 训练、评估或回测混用。
> 当前口径应使用 `open[t+1+horizon]/open[t+1]-1`（默认 horizon=5），并保留 51 个 BINS 边界。

---

## `scripts/plot_topn_curve.py` — TopN 收益折线图

```
uv run --project . python scripts/plot_topn_curve.py \
  --preds logs/preds_a.npz logs/preds_b.npz \
  --labels base dual --out logs/topn.png
```

从 `eval_bins_mapping.py` 缓存的 preds npz 读逐样本预测，按交易日截面统计各 TopN 档的真实收益均值，绘制折线图，支持多模型对比。

---

## `scripts/run_backtest.py` — 逐日回测

回测时序固定为 T 日决策、T+1 open 买入、T+6 open 卖出。输入预测缓存和 OHLC 路径表必须
来自同一 open-open 口径；旧 close-close 缓存不可混用。

```
uv run --project . python scripts/run_backtest.py \
  --preds logs/preds_a.npz logs/preds_b.npz \
  --ohlc logs/ohlc_path_val.npz
```

| 选项 | 说明 |
|------|------|
| `--preds` | 一个或多个 preds npz |
| `--ohlc` | `build_ohlc_path.py` 产出的 ohlc 路径表 |
| `--mode` | `topn`（默认）或 `target`（目标持仓数） |
| `--target_size N` | target 模式下的目标持仓数 |
| `--sell_buffer N` | target 模式的缓冲池大小 |

输出：`metrics.json`（各模型各档位指标）、持仓 CSV、净值 PNG。
