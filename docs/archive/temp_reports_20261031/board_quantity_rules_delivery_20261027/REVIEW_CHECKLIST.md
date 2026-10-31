# 审查清单

- [ ] 科创板 BUY 100拒绝，200/300接受，100001拒绝且 tranche 非 scheduled。
- [ ] BUY 拒绝进入 fail_tranche；无订单映射，不改变 commitment；其他候选仍可正常决策。
- [ ] SELL 100持仓可一次性卖100；300持仓不允许部分卖100。
- [ ] 普通主板缺省行为兼容既有 lot_size=100 测试。
- [ ] 规则区分 minimum、step、maximum；无200倍数误设。
- [ ] 缺失/占位来源、非法参数、生效区间或未知代码/日期被拒绝，不猜正常。
- [ ] 排序、预算、lot_size、core/runner、数据及共享环境未改。
- [ ] 定向 RED/GREEN、ruff、Pyright 有日志，冻结 hash 与工作区差异可复核。
