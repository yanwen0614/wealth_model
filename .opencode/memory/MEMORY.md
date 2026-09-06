# Project Memory

## 当前架构
- 唯一训练入口：`train.py`。
- 默认配置：`config/defaults.py`；模型、损失、优化器和调度器工厂：`training/factory.py`。
- 数据：`data/dataset.py` 保留 `ParquetDataConfig`/`ParquetDataset`；schema 在 `data/schema.py`；标签在 `data/labels.py`；归一化在 `data/scaler.py`。
- 模型：`models/cnn_transformer/`；训练：`training/`；损失：`criterion/`；回测：`backtest/`。
- `scripts/` 只负责评估、回测和实验 CLI。

## 不可变契约
- 数据源为 parquet，必须过滤 `is_trading=False`，按 `code,kline_time` 排序。
- 默认 per-code 输入：`F=45`，即 39 个有效特征加 6 个 G9 mask；原始因子集合为 48 列，不能直接当模型维度。
- 默认序列 `T=60`，horizon=5，标签为 `open[t+1+horizon] / open[t+1] - 1`。
- `BINS` 有 51 个边界，对应 `C=52` 类；窗口标签取窗口末日。
- scaler 只在训练集 fit，验证集和正式评估复用 `logs/scaler_per_code.pkl`，禁止验证集重新拟合。
- 模型输出为 `(logits[B,52], ret_pred[B])`；旧 checkpoint 不在当前支持范围。
- 预测缓存必须包含 `exp_ret`、`true_ret`、`dates`、`codes`。
- 回测口径：T 日决策，T+1 open 买入，T+6 open 卖出。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
uv run --project . python train.py --smoke --num_workers 0
```

当前整理结果：69 项单测、Ruff、py_compile 和 smoke 通过；Pyright 仍有 34 个既有类型标注错误。训练产物、parquet、日志和 `.opencode/` 均不提交。
