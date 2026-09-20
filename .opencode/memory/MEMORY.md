# Global User Memory

## User Profile
(none)

## Preferences
(none)

## Cross-Project Facts
- [2026-09-20] cnn 项目可用 `xgboost==3.4.1`（GPU 版，`device='cuda'` 可用，CUDA 13.3），后续 GBDT 实验改用 xgb GPU 加速替代 sklearn HistGradientBoosting（训练 90-200s/折 → 预期显著加速）。
- XGB-GPU 基线（2026-09-20）：16 rank 特征 H5 回归 X3（depth4/500树）val_IC 0.1146/test_IC 0.0749，与 GBDT 0.1126/0.0751 打平，训练 14-16s/配置（vs 90-200s）；涨停不可买占比 0.31%，跳涨停后 top10 test 0.4721。
- Torch DNN 对照（MLP 128-64-32）：val_IC 0.1093/test_IC 0.0763，test top10 0.4918，三模型 test IC≈0.075 收敛，未突破天花板。
- 空仓+绝对收益：strong_buy 空仓门限 thr=0.02 时 cash 35-98%，DNN ts10 thr0.02 cash90% 仍 nav1.058；目标持仓 test 绝对收益 XGB ts50 thr0 1.2629（年化+22.9%/Sharpe0.97），DNN ts20 thr0 1.2764（年化+24.1%），但池化胜率仅 47-51%。
- 拟合目标 H1/H20（XGB-GPU）：H1 test_IC 0.0413/top10 0.5007 更差；H20 val_IC 0.1596/test_IC 0.0880/spread+1.52% 但 test top10 0.4888，精度-幅度权衡依旧，75% 单票胜率不可达。
- 全市场截面扩展（2026-09-20）：73维=52rank+12z偏离+7市场状态+2板块，11.9M行构建643s；解耦后A_52rank val0.1140/test0.0689、B_52+12z test0.0658、C_+board test0.0643，均不如16维基线0.0749；市场状态进排序会导致同日恒定预测RankIC=NaN，只能做空仓门；regime与日top10精度相关|corr|≤0.11（m_n -0.112/m_amihud +0.112），空仓门提纯有限。
- [2026-09-21] 截面因子拓展 xs_factors（划分13-22/23-24/25-26）：xgb GPU复现基线16rank test0.0903与Ridge四位小数一致；S1_52rank 0.0876、+inter 0.0822、+mom 0.0748、full100 0.0717、+dist 0.0710、+mkt 0.0478崩塌，确认冗余有害且市场广播致体制过拟合；dist≡rank（单调恒等）、mom最强-0.032、市场时序IC最高vol_5+0.137；分年test 2025+0.098/2026+0.078，上涨日IC更高；未破0.10，最优即基线，DL建议只保留16rank旁路、市场因子仅作空仓门。
- [2026-09-21] 自主冲75%四路验证（划分13-24H1/24H2-25H1/25H2-26M8）：Ranker ndcg/map学反（val-0.069/test-0.047，首因验证标签传零+改真值后仍反，pointwise最优）；市场择时regime7维trainAUC0.68/val0.565/test0.424反转不可分；口袋挖掘val最优0.558/port0.653→test0.536/0.596，q0.99低波test0.557/0.597；breadth门因reg整体偏正tr恒1.0无效；结论75%单票不可达，最优仍为WF组合0.71口径，绝对收益XGB-ts50/DNN-ts20 nav1.26-1.27保持。
- [2026-09-21] xgb新目标滚动8折（expanding 13-22起/6月重训/test25-26，depth4/300轮/seed42）：R0复现IC0.0875；A大涨二分类IC≈-0.01/top1%win0 0.562/win3 0.425、B三分类IC≈-0.01/top1% 0.562/0.424、C加权IC0.070、D分位数IC-0.051方向反转；大涨分类器学到波动率（顶1%双尾富集P(<-3%)0.293>基线0.257）；最高win0仅B的P≥0.5档0.64（n=256），无≥75%且n≥50分档；不替换生产模型，A/B仅可作大涨富集辅助过滤。
