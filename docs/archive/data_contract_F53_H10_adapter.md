# 数据契约实情裁决（以代码为准，2026-09-27）

仲裁源：`config/defaults.py:20,42` + `data/schema.py:33-60` + `585a533`。

## 当前默认值

* `SEQ_LEN=60 / HORIZON=10 / BINS=linspace(-0.38,0.38,51) / C=52`
* `NORMALIZE=relative / ROLLING_SCOPE=e5`
* `52 raw（P18+R16+N12+G6）+ 1 共享 g9_observed_mask = F53`，列序 `P→R→N→G→mask`
* `cs_rank`开则 `+16=F69`，`mkt_factors`全开则 `+11=F80`，默认双关
* 切分：训练 `2013-01-01~2025-06-30`，验证 `2025-07-01~2025-12-31`，测试 `2026-01-01~None`
* 默认 parquet：`train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`
* 回测入口：`backtest/cnn_adapter/*`唯一路径（N01/N02），`legacy.py`为历史

## 历史快照（不再是默认值）

* `README.md`的 `F69/H5`、`scripts/README.md`的 `F45/H5`、
  `README_TRAINING_CHAIN.md`的旧切分 `13-23/24-25`：均为历史，头已挂横幅。
* `F69（51+18mask）/F45（39+6mask）/F55`：历史 schema。
* 标签口径统一 `open[t+1+h]/open[t+1]-1`，旧 close-close 结果不可混用。
