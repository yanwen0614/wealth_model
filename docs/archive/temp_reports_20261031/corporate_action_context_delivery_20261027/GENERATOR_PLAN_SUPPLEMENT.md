# Generator 实施补充（2026-10-27）

## 实际边界

- 目标树：`corporate-action-context-20261027`，独立于 runner owner；仅新增 context、snapshot loader 与对应测试。
- 复用 `CorporateActionEvent` / `CorporateActionProvider` 和冻结 backtest-core 的 `account_actions_provider` / `ExecutionObserver` 契约；core 继续唯一维护现金、应收、登记股数、成本和上市股数。
- 不修改 `runner.py`、staged runner、bridge、registry 或 backtest-core。runner owner 后续只接入 `ctx.account_actions_provider` 与 observer wrapper。

## 冻结数据映射

- 每行 `_row_hash` 重算规则：移除全部 `_` 元字段后，`json.dumps(..., ensure_ascii=False, sort_keys=True)` UTF-8 SHA256。metadata 的 `_snapshot_sha256` 在存在时用相同排序规则、移除自身字段后核验。
- manifest 对 JSON 文件计算字节 SHA256；每一行保留原始字段和进度码原值。进度码不作为实施状态证书。
- 8740 dividend 行完整保留；3500 行生成有除权日的规范事件，5240 行生成未决描述；配股 12 行仅保留覆盖证据。
- 总股权仅采用 `每股送转=T`。B/C 原始值保留在 source row；缺 T 时不回退 C。现金与 T 在一个复合事件中只生成一次股权成本分配。

## core 上下文与失败边界

- 登记日无条件输出 `RecordPosition`，登记数量只从 observer 收到的 core `post_state.record_positions` 读取；开盘买单已由 core 在登记动作前执行。
- Ex/Pay/List 以 core 登记 operation 与登记股数为准；数量为零不产生后续权益；登记后仓位归零不消除现金应收。
- reset anchor 前事件仅在声明空账户时可跳过缺登记；其他缺登记、正登记缺 ex/pay/list、未知税严格模式、非整数或浮点不可精确的送转均输出 `INCOMPLETE` 并终止。
- 显式探索模式允许机械入账，仍输出未知股税和非实际税后状态；20% 只作用于现金 stress。精确整股不构成发行人舍入规则证明。
- observer 在保存只读 core 状态后顺序转发原 update；delegate 异常原样传播。操作 ID 稳定，依赖 core 账本幂等。

## 验收与状态

- 新增 14 个 context/core 行为测试、5 个 loader 契约测试；既有公司行动 runner E2E 4 项通过。
- Ruff、Pyright 针对本次四文件验证通过；冻结 JSON 全量行 hash、文件 hash 和进度码统计通过。
- 交付文件：`GENERATOR_TDD.log`、`GENERATOR_VALIDATION.log`、`GENERATOR_SOURCE_SHA256.json`、`GENERATOR_DELIVERY.json`。
- 本文档及日志只反映本 Generator 文件版本；交付目录中已有 `final/` 内容与此工作树 API / 文件 hash 不同，保留原文件不覆盖。
