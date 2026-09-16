# CNN rolling 归一化实验与导出回迁（rolling-normalization-export）

> 创建日期：2026-09-08
> 级别：P1
> 状态：CNN 内实验进行中；quant 回迁待后续阶段
> 来源：与其他建模链路对照 rolling normalization 时发现
> 关联：`docs/per_code_normalization_spec.md`

---

## 一、背景

当前 CNN 主链路在 Dataset 中执行 per-code/frozen 归一化。rolling normalization 依赖每只股票按时间排序的历史窗口；
若直接放入完整导出 pipeline，需要同时解决计算成本、切分 context、有效性和产物版本问题。

本 issue 先在当前 CNN 项目中完成 rolling 特征方案和模型训练验证，不立即回接 quant 的完整导出链路。只有确认模型效果、
样本损失和时序口径均可接受后，才把稳定实现迁移到 quant，在导出阶段一次性生成 rolling-normalized parquet。

## 二、目标口径

| 项目 | 定义 |
|---|---|
| 分组 | 每只股票独立，按 `code,kline_time` 排序 |
| rolling 窗口 | `[t-251, t]`，最多 252 个交易日，包含当天 `t` |
| expanding | 上市不足 252 天时使用 expanding |
| 最小历史 | 至少 120 个有效历史观测 |
| 前视边界 | 统计右端为当前信号日 `t`，不使用 `t+1` 及之后数据 |
| G1 | `open/high/low` 等模型价格特征先 relative，再 rolling median/IQR robust，clip `[-5,5]` |
| G3/G4/macd | rolling 1%/99% winsor，不做 robust z-score |
| G5 其他/G8 | 透传，缺失填 0 |
| G9 | 缺失填 0、clip `[0,1]`、增加 observation mask |

`close` 仅作为 relative/rolling 的辅助列，不能进入模型输入或输出 schema；原始 `close` 仍用于标签和回测。

当前默认 schema 为 51 个 raw feature + 18 个 G9 observation mask = `F=69`；`F=45`（39+6）是历史 schema，不能复用旧 checkpoint。

## 三、建议处理范围

第一阶段只对以下特征做 rolling：

```text
G1: open, high, low, ma_5, ma_10, ma_20, ma_60, ema_12, ema_26
G5: macd
G3: volatility_5d, volatility_10d, volatility_20d
G4: volume_ratio_5d, volume_ratio_10d, amihud
```

第一阶段暂不对以下特征做 rolling：

```text
sar, trend_duokong, trend_shortline,
std_5, std_10, std_20, boll, kelch, dmi, adx,
G8 质量指标, G9 两融指标
```

原因：`trend_*` warmup 较长；`std_*` 是价格绝对尺度；`boll/kelch` 与波动率重复；G8 为低频财务数据；G9 已是截面 rank。

## 四、有效性和缺失处理

rolling 统计不足时，不因一个特征无效而默认丢弃整行：

1. rolling 特征有足够历史时使用 rolling 统计。
2. 历史不足时优先使用 frozen per-code fallback，避免 warmup 造成大量样本损失。
3. 特征自身缺失按原有分组规则处理；缺失不得参与 median/IQR 或 quantile 统计。
4. G9 始终保留原值和缺失 mask。
5. 额外记录 rolling fallback 比例、各组有效率和最终窗口数量。

rolling 计算前应过滤 `is_trading=False` 并按有效交易日排序。验证集和测试集可以使用 split 前最多 251 个有效交易日的历史 context，
但 context 不进入 labels、windows 或 index；窗口末日和未来标签必须遵守当前 split 边界。

## 五、实验阶段

在 CNN 项目中按以下顺序训练，固定相同样本、标签、模型、随机种子和训练预算：

1. frozen per-code baseline。
2. rolling 只处理 G1 + macd。
3. rolling G1 + macd + G3。
4. rolling G1 + macd + G3 + G4。

每个版本记录：

- 年度和 split 级 IC/ICIR、分类指标、top-bottom 收益；
- 换手和成本后收益；
- rolling fallback 比例和样本窗口损失；
- 每组 winsor 比例及边界漂移；
- 与 `return_20d`、`volatility_20d` 等既有因子的相关性；
- 收盘后生成信号、次日开盘交易的时序一致性。

只有 rolling 版本在验证集和测试集均改善或至少不恶化，且样本损失与计算成本可接受，才进入完整导出 pipeline。
frozen 与 rolling 的 state、schema、transform digest 和 checkpoint identity 必须隔离，禁止互用。

## 六、回迁 quant 导出链路的目标设计

验证通过后，在 quant 导出阶段按股票一次性生成独立 rolling 产物：

```text
train_data_roll_v1/
  code=000001.SZ/part.parquet
  code=000002.SZ/part.parquet
  manifest.json
```

推荐逐股票处理而不是全量 `groupby.rolling`：

1. 读取单股完整时间序列。
2. 过滤非交易行并排序。
3. 计算指定特征的 rolling 变换。
4. 单股完成后立即写 parquet shard，不把所有 DataFrame 返回主进程。
5. 全部 shard 校验通过后生成 manifest。

manifest 至少记录输入快照、git hash、输入/输出列顺序、`window=252`、`min_periods=120`、
`include_current_t=true`、缺失策略、transform digest、行数、股票数、fallback 比例和失败股票。

原始因子产物不得被覆盖。rolling 产物必须使用独立 schema/checkpoint identity，禁止模型侧再次调用 frozen scaler
或重复计算 rolling。

## 七、验收标准

- [ ] CNN rolling 实验实现并通过 smoke training。
- [ ] rolling 特征统计右端为 `t`，`t+1` 扰动不影响 `t` 输出。
- [ ] 抽样暴力重算 median/IQR/winsor，数值误差在约定阈值内。
- [ ] 验证/测试 split 起点正确使用历史 context，标签不跨 split。
- [ ] 记录不同方案的样本损失、fallback 比例、训练耗时和磁盘占用。
- [ ] 完成 frozen vs rolling 的相同样本对照实验。
- [ ] 实验确认后再在 quant 导出阶段实现一次性 rolling parquet。
- [ ] quant 产物具备独立 schema、manifest、前视审计和失败可见性。

---

## 阶段边界

> 当前只做 CNN 模型训练验证，不立即修改 quant exporter 或完整导出 pipeline。实验结论通过后，quant 回迁仍需单独创建或恢复后续任务。
