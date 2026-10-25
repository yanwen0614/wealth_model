# Project Memory

## Architecture & Decisions

### CNN-Transformer Training Pipeline
- `train.py` 唯一入口；F=53（no cs_rank/mkt_factors）+ excess 标签为最优训练配置。
- **最优配置消融链**：excess+F53 (0.0480) > absolute+F53 (0.0520) > excess+F80 (0.0487) > absolute+F80 (0.0611)。
- **训练加速**：数据放本地 NVMe（GPU 7%→83%）；batch_size 1024；patience=3；epoch 14min。

### 2026 策略研究结论（2026-10-25 深度迭代）
- **真实引擎回测**（scripts/run_backtest.py）：target size20/buf10 无止损年化 +10.57%/Sharpe 0.519；止损-3%/-6% 过激（收益→+0.16%）；rolling top5/-0.61%, top10/+0.78%, top20/+2.54%, top30/-2.18%。
- **归因**：target vs rolling 优势主要来自换手节省(+2.96pp)而非选股(+1.03pp)。
- **指数择时证伪**：趋势/大跌信号全部跑输基线（年化 -8%~-18%），滞后错过反弹。与 docs「择时样本外无效」结论一致。
- **exp_ret 校准**：全局分位映射最稳（RankIC 0.0767 几乎无损，P0→P100 单调 -1.17%→+0.89%），但高分组均值<成本门槛，不能直接做买入阈值。逐日分位/滚动线性校准会摧毁排序。
- **⭐ 自信号择时（核心发现）**：当日 top5 的 exp_ret 均值 < 过去60天滚动 q20 分位 → 空仓。稳健性 15/15 网格全胜（q10-30×w40-90 全部改善），无前视，规避的正是下跌段（空仓日 top5 平均收益 -0.30%/日 vs 持仓日 +0.24%）。
- **波动率目标仓位无效**（组合波动 1.2-1.5% 很少触限）；持仓数 5/8/10 无降回撤效果；行业集中度可控（单行业>60% 天数仅 5.4%）。

### 🏆 最终策略方案（待 2026-09 后新数据验证）
- **配置**：target size=8 + buffer=8 + 自信号择时（top5 exp_ret 均值 < 60日q20 → 空仓）
- **2026-01~08 业绩**：年化 +40.0%（vs 沪深300 -1.85%，超额 +41.9%），Sharpe 2.956，最大回撤 13.37%，空仓 20.8% 交易日
- **执行规则**：每日收盘后算排名与信号；持仓 8 只等权，候选池 top16；跌出池或择时触发次日开盘卖出；数据异常默认空仓；成本双边 0.1%
- **备选**：target5+择时（年化 45.4% 更高、回撤 11.7% 更小、但 Sharpe 2.86 略低）
- 脚本：D:/tmp/opencode/bt_final_strategy.py；结果 JSON 同目录
- **⚠️ 谨慎**：仅 149 天样本，空仓段只有 2 段主下跌（2月、5-6月），转产前必须用 2026-09 后新数据验证

### Key Facts
- 数据：Z:\dev\train_data\train_data_v1_F60_*.parquet (4.28GB)，本地副本 C:\train_data\
- 指数：Z:\dev\kline_index\day\000300.SH.parquet
- 预测缓存：D:/tmp/opencode/r4_excess_F53_preds_2026.npz（2026-01~08, 768549样本）
- H5/H10 疑虑已排除：adapter PREDICTED_HORIZON=5 仅是 provenance 标签，实际预测/回测全 H10
- gate_loss.py 缺失已修复（commit 286a6a7）

## Key Facts

- Luna 分析会话 ses_e8e5f2e98ffeRjZnmmVtcQENOI（magpie/codex/gpt-6-luna）：方向分析、行动方案、择时陷阱提醒，全程指导本次迭代。

## [2026-10-25 12:56] 3070 训练任务完成
- 5 轮迭代，最佳 Round 4 (excess+F53, Val Loss 0.0480)

## [2026-10-25 13:15] 2026 回测
- Round 4 模型 rolling top20 年化 +2.54%，RankIC 0.086（baseline 2x）
