# 市场中性纸面验证 market_neutral（2026-10-09）

> `run_backtest`仅long-only无空头已确认（`mode∈{rolling,target}`，全仓无short实现），
> 故只能纸面，不得写成回测收益；不计费；波动信号禁止reinterpret为方向。

## 脚本

- `scripts/s3_neutral.py`：`exp_ret`排序、`topN-bottomN`等权（N=10/100）、
  `true_ret`计价、`m_t`=当日截面均值剥离

## 结论

> 见 `research/README.md` 总表（结论只写注册表一份，此处不重复）。
> 一句话：IC恒等复核通过，LS存在性成立但纸面≠可交易。

## 产物

- `artifacts/{ls_spread,alpha_attr}.json`（已入库）
