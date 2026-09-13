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
