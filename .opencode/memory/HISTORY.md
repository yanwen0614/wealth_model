[2026-09-03 11:13] 归一化总基调定为 per-code（推翻全局z-score）；剔除 G6估值/G7成长 入训特征为 39+6mask=45；标签沿用 close[t+5]/close[t]-1 原逻辑
[2026-09-08 17:20] Hardened per-code feature pipeline with v3 scaler identity and feature lists
[2026-09-12 23:18] E1-E4 对照实验在 RTX3070 以 psmux 会话 cnn_e1e4 后台串行启动，实测 ~12.8 it/s
[2026-09-13 10:18] T05 修复 _FeatureView 重复 mmap(1455) 并启动 E1-E4 实验链(num_workers=2, patience=5)
[2026-09-13 10:31] 诊断 GPU 未打满：每步 ~868 kernel launch 造成 ~62ms 固定 CPU 开销，放大 batch 线性加速；torch.compile 因缺 functorch/triton 不可用
[2026-09-13 10:39] 采用 batch=1024 加速（GPU 91%、epoch 12:40、≈3.4x），重启 E1-E4 链；compile/channels_last/batch_first 均判定不可用或无收益
[2026-09-13 14:04] 向量化 rolling _rolling_column（commit 0a22d1f，69-72x）；E2 建缓存从估算 4.4h 降到 ~15min，多进程不需要
[2026-09-13 18:39] E1-E4 全部完成：per_code vs rolling e2/e3/e4，val loss E4 最低(0.0563)，所有臂均在 epoch1 达最优并早停
[2026-09-13 19:14] E1-E4 截面分析与 rolling 回测完成：截面 IC E2/E4 弱正，回测仅 E1 Top5 正超额
[2026-09-13 20:52] 实现 context warmup（标签日 95→154）；重跑 E1-E4 评估与回测，E1 Top5 由 +18% 翻转为 -43%，全部跑输基准
[2026-09-14 00:05] T01 redsign: data/schema.py 引入 FEATURE_GROUPS(P/R/N/G)+52列+shared g9_observed_mask，新增 test_schema_groups.py 并同步旧测试为 52/1
[2026-09-14 00:14] T02 redesign: ColumnRule registry + RelativeScaler (E0) 纯增量落地 data/scaler.py，16 项单测绿
[2026-09-14 00:27] T03 完成：PerCodeGroupedScaler 重构为 v4（ColumnRule 路由 + P 静态 robust + 1 shared mask + 未知列 raise），18+6 测试绿，dataset/rolling 未动
[2026-09-14 00:51] T04（redesign）rolling 重构：scope e0..e5 + G9 shared mask 修复 + close 解禁，39 单测全绿
[2026-09-14 01:17] T06（redesign）train/CLI+metadata 落地：scope e0..e5、relative 分支、feature_cols/featurenum 实测派生、config.json 含 feature_cols_out；config/defaults e5/53；测试全绿
[2026-09-14 02:01] T07 评估脚本层适配完成（relative / scope e0..e5 / featurenum 实测派生），test_eval_preprocessing 28 项全绿
[2026-09-14 02:41] 整体 review 修复：dataset 默认 parquet 改 F60、relative digest 纳入 mask、_relative_transform inf 边界、默认 LR 3e-4
[2026-09-14 21:54] redesign T01-T09 + 整体 review 完成并提交 178f24e；E0/E1/E2 训练与评估完成（E2 RankIC 0.0415 最优），E3-E5 后台训练中
[2026-09-14 21:56] E0-E5 redesign 六臂训练+评估完成：E3 最优（RankIC 0.0441, top100 +16.61%）；提交 475391c
[2026-09-14 22:46] 完成三种评估口径（rolling/target/逐日TopN）对账，确认无bug，根因为涨停不可买样本+尾部未到期样本污染直接法
[2026-09-14 23:49] 回测口径三项修订：benchmark_index_nav 大盘指数基准、avg_cash_ratio 平均现金仓位、--topn 默认 [5,10,20]（TDD 57 tests OK）
[2026-09-14 23:58] 文档+记忆同步：回测口径升级（A股费用模型/指数基准/小TopN/avg_cash_ratio），commit 4073bad
[2026-09-15 00:59] add-strong-buy-gate 完成（强买门槛）+ E0-E5 综合结论：E0 relative 最稳
[2026-09-16 01:46] E0 (relative) 设为 baseline：config.defaults NORMALIZE=relative, SCALER_PATH=None; dataset.py 默认 normalize=relative
[2026-09-20 15:31] 建立 scripts/eval_three_way.py 严格三分评估规范：val/test 对比 + 阈值样本外校准，发现 val 达不到 75% precision（顶格 57.8%）
[2026-09-20 15:34] 新增 label_mode=excess 截面超额收益标签选项（默认 absolute 不变），含纯函数、dataset 应用、缓存 key 隔离与单测
[2026-09-20 16:04] 特征/截面特征研究：单特征 IC、冗余簇、截面 rank 原型（Ridge/GBDT RankIC 0.08-0.09 vs DL 0.025-0.046），报告 logs/ic_analysis/REPORT.md
[2026-09-20 16:30] 新增 cs_rank 逐日全市场截面 rank 特征（可选默认关，旁路归一化追加 F=69）
[2026-09-20 17:09] 完成 GBDT 截面 rank 生产模型（logs/gbdt_cs）：严格三分 test RankIC 0.075、阈值样本外 precision 0.547，确认 75% 胜率不可达
[2026-09-20 17:47] 市场择时研究：test top10 股票级胜率诚实上限 ~0.47，无法达 75%；市场方向不可预测（AUC≈0.5），val→test 过滤器不可迁移
[2026-09-20 19:24] 完成散户模型全链路研究：GBDT截面rank+target动态退出回测(test +40.6%/Sharpe1.45, val +58.5%)，修复引擎隐性杠杆bug，确定"75%单票胜率"不可达(天花板52-58%)
[2026-09-20 20:18] 集成/共识/组合策略研究（logs/ensemble/）：集成与 stacking 不如 clf 单信号，单纯共识天花板 0.544；clf 共识+宽度过滤(test)单票胜率 0.5904，四段稳定 0.55-0.61；DL 无 val 覆盖且 2026 失效，不可用
- [2026-09-20] 多周期×多标签扫描（logs/horizon_target/）：H20/H5 rank 目标把 test 单票 top10 胜率做到 ~0.55（超额 +6~7pp，两半年稳定）；H60 表面 0.58 系重叠窗口假象不可信；75% 仍不可达（样本外最高 0.6557）。
[2026-09-20 22:06] 特征工程实验复现并新增胜率发现：base16+7动量 GBDT 集成冻结阈值 test 胜率 0.5688（基线 0.5473），RankIC 天花板仍 ~0.076
[2026-09-20 23:30] 滚动重训多模型对比（logs/rolling_models/）：GBDT+Ridge 截面 rank 集成全面最优（size=20 年化 +45.4%/Sharpe 1.416/MDD 34.8%），单模型 Ridge 风险调整最优（+27.4%/1.106），分类器 RankIC 最高 0.098；三路集成反而降到 +32.8%
[2026-09-20 22:15] 风险 overlay 研究：指数 MA40~80 趋势过滤把滚动 GBDT 策略 MDD 55.4%/37.8% 降到 24.2%/21.8% 且年化升至 35.5%/34.7%，近乎免费；回撤控制/止损/波动率目标无效或有害（logs/risk_overlay/）
[2026-09-20 22:23] 空仓专项：清仓能把 size200 MDD 压到 ~20% 但收益腰斩且 2023/2026 转负；size20 清仓不如 hold；高频信号二级清仓换手 204-244x；结论「降暴露优于清仓成空仓」
[2026-09-20 22:54] 确认 xgboost 3.4.1 GPU 可用(device=cuda OK)，后续 GBDT 实验改用 xgb GPU 加速；派子代理做逐笔订单深度分析
