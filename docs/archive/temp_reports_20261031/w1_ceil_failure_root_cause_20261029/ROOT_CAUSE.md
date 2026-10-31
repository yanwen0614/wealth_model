# W1 300502.SZ ceil cutoff 失败：只读根因调查

## 结论与边界
根因已由调用栈、实现和单样本算术复现：**不是 binary float 回乘误差**。触发器是 `CorporateActionContext._validate_positive` 同时要求精确有理数乘积为整数；ceil 情景把目标事件专用 `effective_ratio` 转为有限精度 Decimal 字符串，作为 `raw_row["每股送转"]`，随后 Fraction 对这串有限小数作精确有理数运算。S1/S2/C70 得到的是略大于整数的有理数，故拒绝；core 的实际 float 乘积在这三个值上恰好表示为目标整数。

异常发生在**登记日 2021-06-07 的 `RecordPosition` 后观察者更新 hook**，不是 6/8除权、送转股登记或上市 hook。cutoff 恰止于登记日，prior to target ex 时间并未改变该状态。失败调用栈落在 observer `on_update` 的 `super()._validate_positive`。2021-06-08账户操作尚未应用。

这只确认条件分支的工程根因。floor/ceil 是假设分配，不构成真实获配证明；事件记录的非整数零碎股如何实际分配仍未知。未改源码、未跑大规模数据。

## 逐日及 hook 证据
- 原始截止日志 `outputs/W1_S1_ceil.stderr.log` 第 19–33 行：core `account_runner.py:1812` 调 `_notify_observer`，经 `corporate_action_context.py:108`、`fractional_scenarios.py:169` 到 context 第 91 行抛错。C70 ceil 日志相同调用链。异常事件为白名单 `dividend:27726:5fb635…`。
- core `src/backtest_core/engine/account_runner.py:1728–1753,1805–1817`：当日先处理开盘前操作、订单，再于 1751–1753 应用 `RecordPosition`；1812 的 observer 更新明确是当日 close snapshot。失败即发生在 **2021-06-07 登记后 close snapshot hook**。不得把它说成“6/8 ex hook”。
- `corporate_action_context.py:65–68` 从 `post_state.record_positions` 读登记数量；95–108 保存 update 并逐项验证正登记数量。
- `fractional_scenarios.py:24–27` 固定原比例、登记日、除权日、上市日；137–145 用 Decimal 对原比例计算取整，并算 effective ratio；165–169 仅替换白名单事件的情景比例及 raw row，再调用基类严格检查。
- core `account_runner.py:1735–1753` 应用 `RecordPosition`；`engine/account.py:128–132` 记录数量和成本快照。6/8 的 create entitlement 在 context `corporate_action_context.py:164–181`，不会先于 6/7登记。

## 数值复现（Python 默认 Decimal 精度 28）
`q = record_shares`，`n = ceil(q × 0.4002532)`。场景有效比例是 `Decimal(n)/Decimal(q)`，再由 `str(effective_ratio)` 保存到 raw row。

| 分支 | q | q×原比例 | n | effective ratio | `Fraction(q)×Fraction(str(ratio))` | float core `q*float(ratio)` |
|---|---:|---:|---:|---|---|---:|
| B1 ceil | 4000 | 1601.0128000 | 1602 | 0.4005 | 1602（整数） | 1602.0 |
| S1/S2 ceil | 1300 | 520.3291600 | 521 | 0.4007692307692307692307692308 | 521 + 1/25000000000000000000000000 | 521.0 |
| C70 ceil | 2800 | 1120.7089600 | 1121 | 0.4003571428571428571428571429 | 1121 + 3/25000000000000000000000000 | 1121.0 |

基类第 87–90 行的 `exact = Fraction(str(quantity))*Fraction(str(total))` 使用十进制字符串转成**精确有理数**；它不会采用 Decimal 乘法的 28 位舍入结果。S1/S2 残差为 `4e-26`，C70 为 `1.2e-25`。同一行的 `mechanical = quantity * event.share_ratio` 分别得到 Python float `521.0`、`1121.0`；失败由 `exact.denominator != 1` 单独触发，并非 `mechanical != exact.numerator`。

所有 floor 都得到 `effective_ratio=0.4`，乘登记数量精确整数（520、1120、1600）；B1 ceil 的 1602/4000 化简为十进制有限小数 0.4005，故也精确整数。错误代码同时涵盖其他不可表示情况，但此案有上述证据排除“浮点乘法误差”。

## 原始事件、白名单与成本 basis
- 事件固定身份见 `fractional_scenarios.py:20–27, 96–128`：event id、300502.SZ、登记 2021-06-07、ex/listing 2021-06-08、原始 Decimal `0.4002532`、原始行 SHA `5fb635…`、源快照 SHA `5ad5bf…`、官方 PDF SHA `c09dfd…`。descriptor 校验只对单一精确 event id 生效（81–86），核对文件、PDF、日期、证券、比例、row hash 和源快照哈希；context 仅针对目标替换比例（147–169、171–180）。这是边界窄的情景白名单，不能移除身份校验或覆盖别的公司行动。
- 本次可见的 stderr/JSONL 产物不含原始 source row 全列；故此报告依据代码中固定的 row/source SHA、原始比例与用户提供的事件事实，未声称独立重读了被哈希锁定的原始 parquet 行。官方公告确认的零碎股尾数分配/同尾随机规则以及账户实际获配，仍不能从这些情景日志推出。
- core 成本口径：`engine/account.py:128–132` 以 `quantity * state.cost` 冻结 `record_costs`；143–157 将 `record_costs * shares_per_share/(1+shares_per_share)` 作为 entitlement `cost_basis_total`，并以除权后总股数 `recorded_quantity*(1+ratio)` 更新持仓均价。最终上市 174–184 把权益成本并入现持仓成本。情景 ratio 来自 Decimal 除法的 28 位值，进入 float action；成本 basis 是 float 运算，精度并非 Decimal 账本。情景对象明示该 basis 分摊是假设（`fractional_scenarios.py:40–43`），不得据此宣称真实税务/成本证书。

## 最小修复建议（本次未实施）
只在 `W1FractionalScenarioContext` 的已锁定白名单事件上保留 `(record_shares, integer_shares)` 权威整数对；构造情景替代事件时仍保留官方原比例身份验证，并令仅供 core 的 effective float ratio 为 `integer_shares / record_shares`。在该白名单路径，基类整数判定应比较**精确 q×官方原始比例产生的目标 n**与已锁定情景 `integer_shares`，并核实 core 机械乘积 `q * float_ratio == float(n)`；不得再用舍入后的 effective Decimal 字符串要求一个本来是近似比例的数学有理数整数。基类默认生产路径的精确整数 fail-closed 不变；非目标事件照常走基类原比例验证；白名单身份/哈希/date/source校验不变。禁止全局 epsilon、floor/ceil 自动取整或改写权威原比例。

建议把该判定封装为目标事件的窄范围验证，而非临时绕过 `_validate_positive`：否则 6/7观察者 hook 和 6/8 `account_actions_for_day` 可能使用不一致规则。由于 core 始终用 float 数量，GREEN 还必须证明 6/8 entitlements shares 是整数并于 6/8 listing 成功，避免只让登记日通过。

## 真实隔离 core RED/GREEN 验证设计
使用隔离 core 源码树及真实 `run_account_backtest_from_orders`，固定真实 W1 前缀和单事件输入，不训练、不跑完整窗口。RED：冻结当前实现，证明 B1 ceil + S1/S2/C70 ceil 于 6/7 `RecordPosition` 后按上述错误失败，所有 floor 与 B1 ceil 原样对照；记录 core commit/tree SHA、source/PDF SHA、精确 exception 与 observer update 日期/序列。GREEN：仅应用上述白名单精确整数对验证；对 S1/S2/C70 ceil 及既有 floor/B1 ceil 运行相同真实 core 前缀，断言 6/7记录数仍为 q、6/8 share entitlement 数恰为 n、listing 后持仓增加 n、record cost 与 entitlement basis 满足既有分配公式，且没有任何全局容差放宽。

负例必须在真实 core 中 fail-closed：改变 event id、源行 SHA、源文件 SHA、官方 PDF SHA、证券代码、record/ex/listing 日期、原比例或多出第二条类似事件，均拒绝；另一非目标公司行动的非整数登记权益仍由默认精确规则拒绝。验证 `prior_to_target_ex` cutoff 的完整前缀事件序列/hash 与 RED 输入完全一致，并明确输出为条件情景、非实际分配证明。以上是测试设计，未执行。

## 可复现脚本与材料
运行 `python repro_decimal_float.py` 即输出八个分支的 Decimal、Fraction、float 结果；仅使用标准库、单样本运算。原始 stderr 在 `C:/Users/yanwen/AppData/Local/Temp/opencode/w1_real_prefix_exploration_20261029_v2/outputs/W1_{S1,S2,C70,B1}_{ceil,floor}.stderr.log`；状态矩阵为 `outputs/branch_status.json`。S1 ceil 堆栈列于本文。partial account JSONL 是单行状态序列，本次未把整份巨大 JSONL 导入报告。
