# 技术29公式与有限合成因果验证

日期：2026-10-26。原报告位于`D:/code/quant/docs/research/20261026/technical29_time_audit.md`；本归档核对该报告及配套JSON，不重跑数据或训练。

## 源码和样本身份

- 本次quant源码HEAD：`cdee171b35c69edcaa638928cd57297636355045`。
- 训练footer提交：`26c3db036a266f5765d8cdee4ef352c56d6ee1e9`；与当前测试源码不同。
- 探针：`C:/Users/yanwen/AppData/Local/Temp/opencode/technical29_prefix_probe.py`及同名JSON。
- JSON保留7个因子/算子源文件SHA256与逐特征比较结果。
- 环境：Python3.12.13、NumPy2.4.6、pandas3.0.3、TA-Lib0.6.8。

## 有限验证结果

人工确定性OHLCV共301行，prefix为271行，再追加30行未来数据。
按原因子compute路径验证P18+R11，OHLC直接透传，其余25列调用因子实现。
在成熟索引250/260/270比较，容差rtol=1e-9、atol=1e-10。
常规后端29/29列通过，各成熟点最大绝对差为0。
单独强制SAR源码fallback亦通过；扰动首5行后这三个成熟点仍一致。

所见MA/BOLL/STD/波动率为trailing rolling，EMA/ATR等为当前及历史递推。
volume_ratio当日分子配此前5/10日均量；未见负向shift、居中窗口、bfill或整样本fit。
T收盘后形成信号、T+1开盘执行已满足本次时点关系，无需额外机械shift一天。

## 严格边界

该有限样本支持当前函数定义的因果候选性质，不证明所有异常/缺失序列均正确。
历史F60完整生成快照、当时backend、供应商复权版本及实际逐值对照仍未闭合。
不能据此宣称F60整体PIT通过、真实成交可行或策略已经实现最终收益目标。
