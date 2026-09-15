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
