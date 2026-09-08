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
- 默认特征采用有序 39 列白名单和显式禁用黑名单；不在任一名单中的 parquet 列必须排除并发出 warning，提醒更新名单。
- 默认序列 `T=60`，horizon=5，标签为 `open[t+1+horizon] / open[t+1] - 1`。
- `BINS` 有 51 个边界，对应 `C=52` 类；窗口标签取窗口末日。
- scaler 只在训练集 fit；v3 scaler 缓存仅在训练 identity hash（数据快照、训练范围、特征顺序和处理配置）与 schema 匹配时复用，否则仅训练集重拟合。验证集必须提供并复用内存中的训练 scaler，禁止重拟合。
- 预测缓存必须包含 `exp_ret`、`true_ret`、`dates`、`codes`。
- 回测口径：T 日决策，T+1 open 买入，T+6 open 卖出。

## 运行验证
```bash
uv run --project . python -m unittest discover tests/unit
uv run ruff check .
uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
uv run --project . python train.py --smoke --num_workers 0
```

## 已知变更
- [2026-09-08 14:57] 精简 dependencies 从 30 到 7 个核心包，其余移入 optional-dependencies 分组
- [2026-09-08 14:57] 默认 parquet 路径按平台切换：win32 用 Z: 路径，Linux 用本地 data/test/train_data/
- [2026-09-08 16:02] per-code scaler 升级为 v3 identity/schema 校验；缺失值最终映射为 0，验证切分首日保留前一交易日仅作 relative context，未知 code 使用同一变换空间的全局 fallback。
