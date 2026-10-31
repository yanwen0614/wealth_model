# 证据清单

边界：本轮只读；没有生成绩效结果、重算哈希或读取大行情全量内容。

| 项目 | 已核验事实 | 来源 | 未证明事项 |
|---|---|---|---|
| A预测 | 4键；1,180,872行；2025-01-02至12-16；232日；5,135码；无重复、NaN/Inf | `logs/preds_fullA_2025.npz`；`logs/eval_fullA_2025.json` | 权重存在且路径对应，但应冻结文件身份 |
| B预测 | 与A日期、代码、标签逐元素相同；分数数组为各模型输出 | `logs/preds_fullB_2025.npz`；`logs/eval_fullB_2025.json` | 权重存在且路径对应，但应冻结文件身份 |
| 信号语义 | exp_ret为softmax概率乘52类中心的期望收益；配置HORIZON=10 | `backtest/cnn_adapter/predictions.py`；A/B config.json | adapter provenance常量标HORIZON=5，需修正研究报告谱系 |
| 训练截止 | A/B configs分别对应2024-12-31训练截止、2025验证覆盖 | `logs/relative/run_20260929_162734/config.json`；`.../174047/config.json` | 2025属于已观察验证期，非独立测试/前瞻冻结 |
| 代码/标签同资产 | A/B dates、codes、true_ret完全相同；每日截面5,041–5,128 | 只读NPZ摘要 | codes是否存在不同市场别/生命周期状态须按原始逐日状态表核对 |
| 预测日历 | 232个信号日均包含于243日指数日历；缺的11日全为12-17至12-31 | NPZ dates与指数 `kline_time` | 期末执行与清算需额外calendar/raw行情覆盖 |
| 指数 | 000300.SH覆盖2013-01-04至2026-09-30；2025有243行 | `Z:/dev/kline_index/day/000300.SH.parquet`，仅读日期/收盘列 | 2025每日值、缺值、端点/价格指数分红口径须冻结并逐日校验 |
| 行情parquet | 本地训练parquet footer覆盖至2025-12-31，11,413,377行；OHLC注明后复权 | `data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet` footer | 不能证明真实成交价、PIT状态/因子；rowgroup日期统计跨多年，不适合直接拿来证明窗口覆盖 |
| 原始股票行情 | `Z:/dev/kline/day` 存在 | 文件系统存在性 | 2025全市场代码/日期、开盘价、缺bar与单位尚未盘点 |
| 既有绩效 | A/B 2025评估含排序指标；汇总注明2025账户回测为null | `logs/eval_fullA_summary.json` | 任何2026结果属于已烧样本，本计划不引用作验收 |
| CLI/账户核心 | `--mode target --target_size 10`可调用adapter；费用参数可显式设置 | `scripts/run_backtest.py` | CLI不导出逐日snapshot/订单全量审计，不接原始状态/CA |
| 市场限制 | missing bar与suspended分开计数；limit unknown只计数并以False占位；ST名单默认空 | `backtest/cnn_adapter/market.py` | 不可把unknown当可成交；OHLC不能恢复队列/触板顺序 |
| 终端审计 | audit可校验逐日持仓<=10、NAV恒等式、订单时序、locked及未解决订单 | `backtest/cnn_adapter/execution_audit.py` | CLI没有调用；需要隔离集成和完整日历/逐日收盘价 |
| 现有工作区 | 本区已有多处未提交用户WIP，保持未改 | `git status --short`只读查看 | 未来改动必须从冻结HEAD创建独立worktree，避免共享目录 |

NPZ摘要由本地Python只读载入；Parquet仅读footer，沪深300仅读 `kline_time,close`。未遍历4GB源、未重训、未安装依赖。
