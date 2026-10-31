# 最小源行与账本证据

## 候选CA原始行

源：`validation_2025_local_inputs_20261029/ca_full174/task2_v2/dividend_range_rows.json`，只摘000601.SZ三行，字段值按源记录；未改源文件。

| id | hash | 方案进度 | 预案/公告/股东大会/实施 | 登记/除权/派息 | 税前/税后/送转 | 年度 |
|---|---|---:|---|---|---|---|
|17916|4ea22242c9a926e684adaa8a0d1baf1c7b5c71778d6333f45bd2c4438e91c0bc|"1"|20250805 / 20250805 / null / null|null / null / null|0.0 / 0.0 / 0.0|20250630|
|17917|8f7e2f3e1075391d2b6d5775aaefc97e08eb591d8d4248f5942cd0f79d422479|"2"|20250428 / 20250624 / 20250624 / null|null / null / null|0.0 / 0.0 / 0.0|20241231|
|17918|b971e207ca38b2bd9d408dfc25d4c806e63129efc1c6a32caecd2038afc82385|"3"|20250211 / 20250306 / 20250227 / 20250306|20250312 / 20250313 / 20250313|0.2 / 0.2 / 0.0|20240930|

17916、17917其他源字段：基准日期/股本、转增比例、送股比例、红股上市日、预披露日均null；17916、17917对象及备注均null；三行货币均CNY，方案是否变更均0。

## A core证据

- `annual/A/summary.json:9-16,24-27,37-50`：不可评估、3买入标的、5 fills、成本、错误、中断持仓与NAV空。
- `annual/A/core/manifest.json:2-16`、`attempt_audit.json:2-16`：异常及最后core快照327、日期2025-08-22、现金802419.79268。
- `annual/A/core/daily_registry.jsonl:157`：execution:327，持仓/锁定000601.SZ各33600；core状态持仓成本5.76、最后标记5.76。
- `annual/A/ca_observed_checks.json:375-403`：17916被标记 inspect_now=true、publication_following_date，公告字段20250805，但官方文件、历史known-at及实施证据均UNKNOWN。
- `annual/A/core/corporate_action_evidence.json:9-20,198-200`：本地SQLite候选导出，query_only=true，但history_known_at UNKNOWN、pit_evidence=false、implementation_certified=false。
- `annual/A/order_policy_guards.json:2-15`：8/22是已验证买入请求，文件明确为意图而非core成交。
