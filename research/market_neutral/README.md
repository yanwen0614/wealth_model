# 市场中性纸面验证 market_neutral（2026-10-09）

> `run_backtest`仅long-only无空头已确认（`mode∈{rolling,target}`，全仓无short实现），
> 故只能纸面，不得写成回测收益；不计费；波动信号禁止reinterpret为方向。

## 脚本

- `scripts/s3_neutral.py`：`exp_ret`排序、`topN-bottomN`等权（N=10/100）、
  `true_ret`计价、`m_t`=当日截面均值剥离

## 结论

- IC恒等`IC(pred,true)≡IC(pred,true−m_t)` maxdiff 0复核通过。
- 2026图景LS日均（纸面非收益）：hgb N10 +3.13%/0.63、xgb +3.40%/0.66、
  A +2.15%、B +1.29%；N100 +1.3~2.4%。
- 开口验证：α在对冲m后仍有spread存在性，但纸面≠可交易。

## 产物

- `artifacts/{ls_spread,alpha_attr}.json`（已入库）
