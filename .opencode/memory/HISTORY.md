[2026-09-03 11:13] 归一化总基调定为 per-code（推翻全局z-score）；剔除 G6估值/G7成长 入训特征为 39+6mask=45；标签沿用 close[t+5]/close[t]-1 原逻辑
[2026-09-08 17:20] Hardened per-code feature pipeline with v3 scaler identity and feature lists
[2026-09-12 23:18] E1-E4 对照实验在 RTX3070 以 psmux 会话 cnn_e1e4 后台串行启动，实测 ~12.8 it/s
