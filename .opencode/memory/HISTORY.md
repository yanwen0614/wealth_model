[2026-09-03~09-13] 归一化基调 per-code，E1-E4 对照实验完成，context warmup 修复（标签日 95→154）
[2026-09-14] redesign: FEATURE_GROUPS(P/R/N/G)+52列+shared mask、ColumnRule registry、PerCodeGroupedScaler v4、rolling scope e0..e5、train/CLI 适配；E0-E5 六臂训练 E3 最优(RankIC 0.0441)
[2026-09-14~15] 回测口径升级(A股费用/指数基准/小TopN/avg_cash_ratio)；E0 relative 设为 baseline
[2026-09-20] 建立三分评估规范(eval_three_way)，新增 cs_rank 截面rank特征；GBDT 截面 rank 生产模型 test RankIC 0.075，确认 75% 单票胜率不可达(天花板 52-58%)
[2026-09-20] 特征工程/滚动重训/风险 overlay/空仓/XGB-GPU+DNN 研究完成；集成共识天花板 0.544；指数 MA40~80 趋势过滤近乎免费降 MDD
[2026-09-21] 全市场截面扩展/截面因子拓展/自主冲75%/xgb新目标全部失败，75%不可达收敛。引擎杠杆 bug 修复。ASL 证伪(p*=0.575梯度偏移)。提交纪律确立。
[2026-09-22~23] H10 全链路：指数口径审计(ew等权唯一合格)、冻结A 2026 样本外(V1/V2 NAV 1.1448/1.1174)、预注册方案A唯一通过、选项二 REJECT、选项一固化前验证 PASS
[2026-09-28] 主仓整理：merge origin/main(a8866a7)、backtest-core 克隆、logs 大扫除(340→76)、paper_jkx 源码入库、adapter 为唯一回测路径
[2026-09-30~10-01] 三组建模完整评估(B截面最优)、JKX I30-color 实验定论(排序有信号但绝对收益不如主模型)、α vs 市场项 H1-H6(信号α主导)
[2026-10-02~03] 损失对照(C/D/E截面损失RankIC显著优于CE，top10/200绝对收益均不显著)、早停改RankIC(对CE变体+0.0002近乎无效)、JKX图像线停止、主模型A补跑2026、树模型同口径验证(IC全面优但target净值属噪声区)
[2026-10-05~08] 全模型α归因(树模型2026唯一守住正α)、精确优先(VAL提至0.60-0.64,2026全塌)、m_t可预测性系统研究(方向/幅度不可行,仅波动可作风控候选)、完全分离双塔(方向门证伪,波动定仓不显著)
[2026-10-23] 创建 decile_diagnosis.py(十分位收益诊断+驼峰检测), 16单测PASS+ruff零告警