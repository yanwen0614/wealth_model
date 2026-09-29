# CNN 训练项目

> 口径声明：本文档默认契约已按 `docs/archive/data_contract_F53_H10_adapter.md`（代码实情裁决）对齐（`F53/H10/relative/adapter`）；历史数值（旧 `F69`/`horizon=5` 等）仅在标注处作历史记录。
> 当前权威以 `docs/archive/data_contract_F53_H10_adapter.md`（代码实情裁决）为准。

本项目以 parquet 为训练数据主入口，唯一训练入口是 `train.py`。

当前默认契约（与 `config/defaults.py` + `data/schema.py` 一致，权威裁决见 `docs/archive/data_contract_F53_H10_adapter.md`）：

- 读取 parquet（默认 `train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`），并过滤 `is_trading=False` 的合成行。
- 默认 **relative 归一化**（`NORMALIZE=relative`，`RelativeScaler` 无状态/无 fit；`per_code`/`rolling` 需显式 `--normalize` opt-in，rolling 默认 scope `e5`）。
- 默认模型输入为 `F=53`：52 个 raw feature（`P18+R16+N12+G6`，列序 `P→R→N→G`）+ 1 个共享 `g9_observed_mask`；`close` 已解禁进 P 组（relative 分母 `close[t-1]`）。**注意一号两用**：`F=69` 仅在 `--cs_rank` 开启时成立（`52+1+16`，16 个 `cs_*` 截面 rank 列旁路归一化追加末尾），与历史 `F=69`（旧 51 raw + 18 逐列 mask）同数不同义；`--mkt_factors` 全开时再 `+11=F=80`。默认双关，`F=53`。`F=45`（39+6 mask）、`F=55` 为历史 schema。
- 序列长度 `T=60`，预测 horizon=10；标签收益为 `open[t+1+horizon]/open[t+1]-1`（即 T+1 open 到 T+11 open）。
- `BINS` 含 51 个边界（`linspace(-0.38,0.38,51)`），对应 `C=52` 个类别。
- 时序切分默认：训练 `2013-01-01~2025-06-30` / 验证 `2025-07-01~2025-12-31` / 测试 `2026-01-01~`。
- scaler 只在训练集 fit（`per_code` 模式落盘 `logs/scaler_per_code.pkl`，验证集复用；`relative` 默认无 scaler/state）。
- 回测唯一入口 `backtest/cnn_adapter/*`（`backtest/legacy.py` 为历史）；回测按 T 日决策、T+1 open 买入、T+11 open 卖出；费用=买佣 0.025%(最低5元)/卖佣 0.025%+印花税 0.025%，基准=大盘指数（默认沪深300 `000300.SH`）。
- `scripts/frozen/*` 为冻结归档（自 `scripts/h10_rolling/*` + `scripts/wf_xgb_cs.py` 迁入，READ ONLY）：生产代码禁 import，复现命令见 `scripts/frozen/README.md`。

运行、数据处理和归一化细节见 [README_TRAINING_CHAIN.md](README_TRAINING_CHAIN.md) 与
[per-code 归一化规范](docs/per_code_normalization_spec.md)。
