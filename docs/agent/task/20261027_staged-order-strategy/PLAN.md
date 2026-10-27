# 分批策略模块收口计划

- 原分析依据：临时根staged_policy_strategy_plan_20261026/PLAN.md、three_day_candidate_registry.md及15条独立oracle；本文件收口，不重新声称分析或TDD发生时间。
- 目标：B1/S1/S2/C70单窗策略、tranche计划与真实core反馈，保持完整预算/时钟/终端身份契约。
- 实现：原Luna owner在独立树按RED/GREEN编码，冻结后独立Luna审查；主会话负责提交合入。
- 首轮唯一真实FAIL为来源占位可BUY；原owner最小修复后同QA复审，不放宽BUY门。
- 生产来源绑定、3buffer日历和连续年度编排由后续运行器完成，不在本模块冒充通过。
