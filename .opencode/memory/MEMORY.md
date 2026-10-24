# Global User Memory

## User Profile
(none)

## Preferences
- 子 agent 返回空结果时，不要自己重做，用 `task_id` 重新给该子 agent 发消息（`resume` 同一会话），让它交出结果报告即可
- 链式跟踪定义：``sleep <秒数> && <观察命令>`` 循环（禁止 while 循环），例如 ``sleep 300 && tmux capture-pane -t <session> -p | tail -40``，用于长时间任务监控；等待时长根据任务实际调整（常用 300/600/900），禁止用 tmux 后台起观察任务

## Cross-Project Facts

### 数据与特征
- cnn 项目可用 `xgboost==3.4.1`（GPU 版，`device='cuda'` 可用，CUDA 13.3），后续 GBDT 实验改用 xgb GPU 加速替代 sklearn HistGradientBoosting（训练 90-200s/折 → 预期显著加速）。
- XGB-GPU 基线：16 rank 特征 H5 回归 X3（depth4/500树）val_IC 0.1146/test_IC 0.0749，与 GBDT 0.1126/0.0751 打平，训练 14-16s/配置（vs 90-200s）；涨停不可买占比 0.31%，跳涨停后 top10 test 0.4721。
- Torch DNN 对照（MLP 128-64-32）：val_IC 0.1093/test_IC 0.0763，test top10 0.4918，三模型 test IC≈0.075 收敛，未突破天花板。
- 全市场截面扩展 73维解耦验证：16维基线最优（test 0.0749），52rank 掉到 0.0689；市场状态进排序会导致同日恒定预测 RankIC=NaN，只能做空仓门。
- 截面因子拓展 xs_factors：16基线 xgb test 0.0903 最优，52/dist/mom/mkt/inter 全败，未破 0.10。

### 建模核心结论
- **75% 单票胜率不可达**（天花板 52-59.6%）。根本原因：5 日收益 SNR≈0.1，75% 需 SNR≈0.67（IC≈0.35），实际最强 IC 仅 0.075。七路独立研究全部收敛于此。
- **ASL 损失数学不可用**：ASL(γ_neg=2) 全局最小值在 p≈0.575，梯度偏移使所有样本被统一推向同一预测值。
- **引擎隐性杠杆 bug**：`backtest/engine.py:384` target 模式 `budget` 未约束可用现金，导致负仓位（最低 -13.9%）。已修复。
- **滚动重训诚实口径**：8 折 expanding window，单期严重高估（+40.61%→真相+10.77%）；分散化决定性（size=200→+28.61%/Sharpe0.99）；动态退出年化翻倍。
- **CNN-Transformer A/B**：B 截面指标胜出（2025 RankIC 0.078 vs 0.055），但 2026 target ann −7.0%/MDD 18.0%，跑输基准 −1.86%。
- **JKX I30-color 停止**：RGB 全链路实现+分片缓存解决 HDD 瓶颈，但排序提升换不到绝对收益，成本远高（17min/epoch+313GB 缓存）。
- **α vs 市场项**：信号 α 主导（方差 83-86%），CE 早停错，截面目标提 IC 不提 topN，均值门控不减亏，仅 RankIC 能选对轮次。
- **损失对照（k=32/6ep/seed0-2）**：C/D/E 截面损失 RankIC 显著优于 CE（C-A +0.0264 p<1e-4），但 top10/top200 绝对收益全部不显著；早停改 RankIC 对 CE 变体仅 +0.0002。
- **树模型同口径验证**：IC 全面优于主模型（2025 0.105 vs A 0.055），但 target 净值 1.002~1.015 属噪声区，判排序更优基线不建议替换生产。
- **归因+精确+择时+双塔收敛**：树模型 2026 唯一守住正 α；精确 VAL 提至 0.60-0.64 但 2026 全塌；m_t 方向/幅度不可行（门控 -35pp），仅波动可作风控候选；完全分离双塔方向门证伪。

### H10 系列
- 指数口径审计：ew 等权收益指数唯一合格；方案 A（双账户 50/50）唯一通过预注册验收；冻结 A 2026 V1 NAV 1.1448/V2 1.1174（跑输裸奔）；选项二 REJECT；选项一固化前校验 PASS（需 engine 改动 60-90 行）。

### 工程纪律
- 禁用 `git add -A`，每次提交只点名显式文件/目录。`paper_jkx` 隔离纪律已解除（2026-09-28）。
- remote 已改 SSH（`git@github.com:yanwen0614/wealth_model.git`），原 HTTPS 因 SSL 不可用。

### 工具
- `scripts/decile_diagnosis.py`：十分位收益诊断+驼峰检测，16 单测全 PASS + ruff 零告警。
