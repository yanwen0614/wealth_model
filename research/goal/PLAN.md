# goal 实施计划：端到端盈利验证闭环（20小时自足冲刺）

> **历史文档**：这是项目初始脚手架计划，不代表当前任务状态。当前架构、实验状态和推荐入口请以根目录 `README.md`、`docs/architecture.md` 和 `docs/experiments.md` 为准。原计划中的 Streamlit 展示页已删除。

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task.

**Goal:** 证明基于 quant 因子 + cnn 方法论的预测信号在样本外（2024–2025）有超额收益（IC / 五分位多空利差 / Sharpe），并沉淀为可一键运行的训练+回测+服务三件套。

**Architecture:** 复用 cnn 的 per-code 分组归一化思想但重做标签（52类→截面五分位，专治坍缩）；sklearn HGB 基线先行证信号、小 torch 模型跟进；独立轻量回测器（5日调仓、双边费率）出盈利证据；FastAPI 提供基线产物接口；REPORT.md 诚实记录。

**Tech Stack:** python3.12（`/home/starcyan/code/cnn/.venv/bin/python`，含 pandas/pyarrow/sklearn/torch/fastapi），pyarrow 列投影，cosmetic matplotlib。

---

## 全局契约（所有 agent 必须严格遵守，不得自行其是）

- 工作根目录：`/home/starcyan/code/goal`
- 源数据（只读，绝不写入）：`/home/starcyan/code/cnn/data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`（58列，1141万行，5166股，2013-01-04~2025-12-31）
- 目标拷贝：`data/train_data.parquet`（`cp` 一次，3.5G）
- 特征列：照抄 cnn `data/dataset.py:88-100` 的 `_default_feature_cols` 排除逻辑 → 45维输出（39特征+6两融mask），scaler 逻辑拷贝 `cnn/data/scaler.py` 为 `data/vendor_scaler.py`（文件头注明来源），fit 只许在 TRAIN 段上做
- 时段划分（硬约束，防泄露）：TRAIN 2013-01-01~2021-12-31 / VAL 2022-01-01~2023-12-31 / TEST 2024-01-01~2025-12-31
- 标签：`future_ret_5d[t] = close[t+5]/close[t]-1`（按每股交易日索引，跳过 `is_trading=False` 行）；`q5` = 每个 `kline_time` 截面 `pd.qcut(future_ret_5d, 5)`（每个 split 内各自 qcut，不跨 split）；回归分 `score` 即对 `future_ret_5d` 本身建模
- 窗口：`SEQ_LEN=60`，`X = 过去60日特征 [45,60]`，`y/score` 取窗口末日 `t` 的 `future_ret_5d[t]`（`t+5` 必须在同股序列内且 `is_trading` 均为真，否则丢弃该窗口）
- 产物目录 `artifacts/`：`scaler.pkl model_hgb.pkl model_torch.pt pred_test.parquet backtest.json metrics.json`
- 预测文件 schema：`[code:str, kline_time:datetime64, score:float, future_ret_5d:float, q_true:int]`
- 回测口径：TEST 段、每5个交易日调仓、等权；组合：Q5多头 / Q1多头 / 全市场等权基准；费率 买入0.03% / 卖出0.13%；指标：总收益、年化、Sharpe(rf=0.02)、最大回撤、换手率、IC均值/IR（Spearman，逐日截面）
- 成功线（诚实口径）：TEST 上 IC>0.02 且 Q5−Q1 年化利差>5% 且 Q5 Sharpe>0.8 → “盈利证据成立”；否则如实报告负结果 + 归因
- 解释器：统一用 `/home/starcyan/code/cnn/.venv/bin/python`；不许各自建 venv；不许写 cnn/quant 目录；不许 `pip install`

## 文件结构

```
goal/
  PLAN.md               # 本文件
  data/
    vendor_scaler.py    # 拷贝改编自 cnn/data/scaler.py（A负责）
    prep.py             # 拷贝+采样+scaler fit+窗口检查+quintile标签（A负责）
    sample_100.parquet  # 100股全历史（A产出）
  models/
    baseline_hgb.py     # HGB 回归 future_ret_5d + 输出 pred_test.parquet（B负责，依赖A的prep产出）
    torch_small.py      # 小CNN/MLP smoke（B2负责，依赖A，可选）
  backtest/
    engine.py           # 独立回测器：读 pred_test.parquet → backtest.json + figs/*.png（C负责，可先造合成数据开发）
    make_synthetic.py   # 合成 pred 数据供引擎自测（C负责）
  service/
    api.py              # FastAPI: /health /backtest /predict（D负责，可先读合成/占位产物开发）
  REPORT.md             # 方法+表格+图表+诚实局限（E负责，先搭框架，末尾填数）
  run_all.sh            # 一键：prep→train→backtest→api自检（集成阶段由主agent拼装）
```

## 任务分解

### Task 1（A: data）— 数据地基
- [ ] Step 1: `cp` 源 parquet → `data/train_data.parquet`，校验行数/列数与源一致
- [ ] Step 2: 拷贝 `cnn/data/scaler.py` → `data/vendor_scaler.py`（头注来源+改动点），拷贝特征排除逻辑
- [ ] Step 3: 写 `data/prep.py`：列投影读取 → TRAIN/VAL/TEST 切分 → TRAIN拟合scaler → 全量transform → 100股采样 `sample_100.parquet` → 窗口合法性检查脚本 `--check`（输出窗口数/类平衡/NaN率）
- [ ] Step 4: 运行 `--check`，产出数据体检报告（各段行数/窗口数/q5分布/NaN率），保存 `artifacts/data_check.json`
- [ ] 验收：`pred` 所需列齐全、scaler只在TRAIN拟合、q5每类占比18~22%、无NaN泄漏到特征

### Task 2（B: baseline）— HGB基线（依赖Task1产出）
- [ ] Step 1: 写 `models/baseline_hgb.py`：窗口末日45维+4个手工统计（mean_5/mean_20/vol_20/ret_20）→ HistGradientBoostingRegressor 拟合 future_ret_5d（TRAIN，sample_weight按|y|分位反比抑制极端）
- [ ] Step 2: VAL调参（max_iter/max_leaf_nodes 两档即可），TEST输出 `pred_test.parquet`（契约schema）+ `metrics.json`（IC/IR、分位单调性）
- [ ] 验收：VAL IC>0 为最低线；TEST IC/IR如实记录；单次训练<30分钟CPU

### Task 3（C: backtest）— 独立回测器（可立即并行，先用合成数据）
- [ ] Step 1: 写 `backtest/make_synthetic.py` 生成合成 pred（3种 regime：有信号IC≈0.05 / 无信号 / 反信号）
- [ ] Step 2: 写 `backtest/engine.py`：5日调仓等权、Q5/Q1/基准、双边费率、产出 `backtest.json`（契约指标）+ `figs/equity.png figs/quintile.png`
- [ ] Step 3: 三种合成数据自测：有信号必须 Q5>基准>Q1 且利差为正；无信号利差≈0；反信号反转
- [ ] 验收：合成三测全过；真实 pred 接入时零改动（只换输入路径参数）

### Task 4（D: service）— 服务演示（可立即并行）
- [ ] Step 1: 写 `service/api.py`：`GET /health` `GET /backtest`（读backtest.json，不存在返回503+说明）`POST /predict`（读model_hgb.pkl打分，不存在返回503）
- [x] Step 2: Streamlit 展示页已移除；当前服务只保留 FastAPI API
- [x] Step 3: `uvicorn` API 自检由 `run_all.sh` 负责（curl /health 200）
- [ ] 验收：无产物时优雅降级、有产物时全展示

### Task 5（E: report）— 报告框架（可立即并行，数字留空待填）
- [ ] Step 1: 写 `REPORT.md`：背景/数据/方法/回测口径/结果表位/图表位/局限与下一步（表格留空位，注明由backtest.json填充）
- [ ] 验收：结构完整、口径与契约一致、不预写结论

### Task 6（集成，主agent执行）— 串线+验收
- [ ] 真实 pred 接入回测 → figures → 服务展示 → REPORT填数 → `run_all.sh` → 20小时复盘结论

## 自检（spec覆盖/占位符/类型一致）
- 覆盖：盈利证明→B+C；训练链→A+B；服务+演示→D；报告→E；一键→Task6。cnn坍缩根因（52类不均衡）由q5截面分位+回归建模正面回应。
- 占位符：无TBD；合成数据/503降级均为显式可运行行为，非占位。
- 类型：pred_test.parquet schema 全链一致；backtest.json 键名由C定义、D/E只读。
