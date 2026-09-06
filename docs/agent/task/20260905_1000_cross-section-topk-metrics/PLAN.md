# PLAN: 日截面 TopK / RankIC 指标（eval_bins_mapping.py）

## Goal
eval 输出从"全池混合排序"扩展为"按交易日截面排序"，覆盖 Top1%/Top5%/Top10% + 截面 RankIC + 多空 spread。解决用户指出的口径问题：5000 股全池 Top10%≈500 只，对个人操作无意义；日截面 Top1%≈每日 50 只才是实盘口径。

## 设计决策
1. 日期来源：`ds.groups[code]["kline_time"][label_pos]`（dataset.py:312 已存，行序与 features/future_ret 对齐），推理循环内按 offset 同步取，零数据层改动。
2. 截面口径：每交易日独立截面，样本数 <100 的日期跳过（防止稀疏截面噪声）。
3. 指标：每截面 Spearman RankIC（复用脚本内 spearman）、TopK% 均值/为正率（K=1,5,10）、Top10%−Bot10% spread；跨日聚合 mean/median/>0 天占比。
4. 兼容：不改动现有全池指标输出（对照保留）；`--checkpoint` 等参数不变。

## 影响范围
- 仅 `scripts/eval_bins_mapping.py`（modify，约 +40 行）
- 不动 data/models/training/criterion（无重复实现，低风险）
- 验证：真实跑 eval（200 股验证集）检查新输出合理性

## 测试决策
need_test=false：eval 脚本无既有单测先例，纯输出扩展；验证方式为实际运行检查。
