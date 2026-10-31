# 八窗机械回测独立审计

- tmux：`cnn_eight_windows_v1`；自然结束 `pane_dead=1` / `pane_dead_status=0`；原始 stdout：`EXITCODE=0`；stderr 为空。
- 原始汇总：`C:\Users\yanwen\AppData\Local\Temp\opencode\staged_mechanical_results_20261028_v1\summary.json`；SHA256 记录在 `audit.json`。
- 结论：8/8 的机械状态均为 `INCOMPLETE`，0/8 实际税后目标资格；W2 数值只可称主区间机械 NAV 变化，不能称完整收益或生产结果。

| 窗/策略 | 机械状态 | 主区间机械变化 | 同期沪深300 | buffer | 完整日持仓 | 拒因 |
|---|---|---:|---:|---:|---:|---|
| W1/B1 | INCOMPLETE | 无（异常中断） | 无 | 无 | 部分日志最高4 | CA数量表示异常 |
| W1/S1 | INCOMPLETE | 无（异常中断） | 无 | 无 | 部分日志最高5 | CA数量表示异常 |
| W1/S2 | INCOMPLETE | 无（异常中断） | 无 | 无 | 部分日志最高5 | CA数量表示异常 |
| W1/C70 | INCOMPLETE | 无（异常中断） | 无 | 无 | 部分日志最高4 | CA数量表示异常 |
| W2/B1 | INCOMPLETE | +23.6794% | -5.4350% | -1.2208% | 5 | 无 |
| W2/S1 | INCOMPLETE | +7.8805% | -5.4350% | -0.0098% | 5 | 688686.SH 买单数量规则 |
| W2/S2 | INCOMPLETE | +7.2273% | -5.4350% | -0.0098% | 5 | 688686.SH、688390.SH 买单数量规则 |
| W2/C70 | INCOMPLETE | +16.9639% | -5.4350% | -0.9640% | 5 | 无 |

## 口径与发现

- W1 四策略均在同一事件失败：`dividend:27726`，`300502.SZ`，每股送转 0.4002532，登记日持仓 4,000 股，乘积 5,601.0128 股。整数表示校验在 `corporate_action_context.py:86-91` 按设计 fail-closed；没有 W1 主区间终值，未将中间账面状态计作收益。
- W2 四策略各有 129 条逐日账户记录（锚点、125 个主期交易日、3 个 buffer 日），最大持仓均为 5，低于 10；buffer 三日峰值残留持仓：B1=1、C70=1、S1=0、S2=0；四窗到 2022-01-06 均已清仓，期末活动持仓、订单、承诺均为 0。buffer NAV 变化单列如上。
- W2 相对沪深300的主区间机械差：B1 +29.1144pp、S1 +13.3156pp、S2 +12.6624pp、C70 +22.3990pp。均为 INCOMPLETE，不能据此宣称完整收益。
- W2 限制均包括 `share_tax_unknown`、`market_data_missing`、`market_state_coverage_unknown`、`corporate_action_exposure_incomplete`、`execution_source_known_at_unknown`、`ca_implementation_and_pit_unknown`。覆盖统计 570,696 条预期中 15,620 缺失、16,605 未知；真实快照血缘未独立验收，公司行动 provider 为 none。
- 税务参数是现金股息 20% 压力测试，不是实际个人税制；送转税务未知，故实际税后目标资格为 0/8。
- 手续费配置：双边佣金 0.02%（最低 5 元）、卖出印花税 0.1%、过户费 0.002%、冲击模型系数 1、spread floor 0.02%、滑点上限 5%、缺失成交量 warn。执行记录费用累计（佣金/印花税/过户费/滑点）：B1 11,618.82/29,176.51/1,161.88/104,446 元；S1 4,055.62/10,184.96/405.56/27,601 元；S2 3,910.19/9,817.87/391.02/26,768 元；C70 8,133.56/20,426.13/813.36/64,528 元。详细未舍入值在 `audit.json`。
- W2 数量规则拒因：S1 于 2021-07-06 拒 `688686.SH` 买单；S2 同日同因，并于 2021-12-30 拒 `688390.SH`。B1/C70 无策略拒因。
- 逐窗 artifacts/hash、原始 JSONL、公司行动证据及来源清单保留在原始结果目录；未修改源码、未重跑。