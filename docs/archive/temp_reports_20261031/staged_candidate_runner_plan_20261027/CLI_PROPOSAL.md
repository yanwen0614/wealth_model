# CLI 提案（设计稿）

建议独立入口：`python -m scripts.run_staged_candidate_account`。以下参数是实现提案，不代表已存在 CLI，也不授权启动绩效。

```text
--mode {reset,continuous}                 required
--window {W1,W2,annual}                   reset 必填；continuous 固定 annual
--policy {B1,S1,S2,C70,B0}               可重复；默认 B1,S1,S2,C70
--capital 1000000                         主表默认锁定；仅可用显式敏感性参数加跑
--capital-sensitivity 100000              可选预登记并完整报告
--signals <prediction-cache>              必须身份匹配 checkpoint
--checkpoint <path>                       W1 run_20261026_100509；W2 QA 通过后指定
--raw-market <path> --state-evidence <path> --corporate-actions <path>
--calendar <path> --benchmark <path>      含沪深300价格指数的真实日历及端点
--window-plan <frozen-json>               anchor/E/buffer/禁买执行日集合和跨窗规则
--execution-profile <frozen-json>         成本/滑点/容量/限价/税务政策身份
--coverage-policy {fail,restricted}       fail 为完整性不符即停；restricted 逐项拒单并标 INCOMPLETE
--review-only                             只验证身份、日期、覆盖；不得写回测结果
--out <new-output-directory>              新目录，拒绝覆盖任何既有证据目录
```

实施界线：W1/W2 reset 需分别执行、分别输出，不接受合并净值；continuous annual 只调用一次 core runner，并把各半年端点作为同一结果内的 NAV 截面。所有政策臂必须共享输入 hash 和冻结 execution profile。B0 未冻结 min_edge 时拒绝参数生成；W2 checkpoint loader QA 未 PASS 时禁止生成信号及任何回测。`--coverage-policy restricted` 不是盈利验收开关，任何 unknown 拒单都要进入覆盖分母和原因表。

窗口日集合、策略参数、buffer禁买范围、benchmark端点、主/敏感性资本在生成 run manifest 后只读；修改其中任一项必须创建新 run identity，禁止看结果后改参数重跑并覆盖旧目录。
