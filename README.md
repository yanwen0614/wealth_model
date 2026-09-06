# CNN 训练项目

本项目以 parquet 为训练数据主入口，唯一训练入口是 `train.py`。

当前默认契约：

- 读取 parquet，并过滤 `is_trading=False` 的合成行。
- per-code 归一化后默认模型输入为 `F=45`：39 个有效特征加 6 个 G9 缺失 mask。
- `48` 仅表示原始因子集合；`55` 是原始基础列与因子的历史组合，不是当前默认模型输入。
- 序列长度 `T=60`，预测 horizon=5；标签收益为 `open[t+1+horizon]/open[t+1]-1`。
- `BINS` 含 51 个边界，对应 `C=52` 个类别。
- scaler 只在训练集 fit，验证集复用 `logs/scaler_per_code.pkl`。
- 回测按 T 日决策、T+1 open 买入、T+6 open 卖出。

运行、数据处理和归一化细节见 [README_TRAINING_CHAIN.md](README_TRAINING_CHAIN.md) 与
[per-code 归一化规范](docs/per_code_normalization_spec.md)。
