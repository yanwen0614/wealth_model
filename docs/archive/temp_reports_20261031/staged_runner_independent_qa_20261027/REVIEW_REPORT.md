# 冻结单窗 reset 运行器独立只读审查

日期：2026-10-27。任务：staged_runner_independent_qa_20261027。模式：review_verify。

**VERDICT：FAIL。合成机械测试 PASS；生产／研究验收 BLOCKED。未发现需定为 P0 的证据，存在以下 P1。**

源码树：`C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/staged-runner-v2-20261027`。
审查仅覆盖新增 runner、其单测和必要的 staged/core/公司行动/市场依赖；未修改源码、提交、派发会话、装包或运行训练／真实绩效。
应用 quant-model SKILL.md 的 review_only 质量门；用户的只读、解释器、临时目录和不询问约束优先。
已读根 AGENTS.md；backtest、cnn_adapter、tests、unit/backtest 无模块 AGENTS.md。读取了已安装 core 的 engine/contracts 规范。
参考清单为 `docs/agent/task/20261027_staged-order-strategy/REVIEW_CHECKLIST.md`；其 scope B 及真实绩效项目仍未勾选，非本 runner 的已签收证书。

## P1 实际问题

1. **逐日落盘账本不足以复核真实账户与决策。** runner:303–322、360–379、604–678。
   daily_account 的 cash、available_cash、NAV、持仓、应收合计及未上市权益确实来自 core，但未保存 locked 股数、pending_cash、逐事件应收／登记股数和状态血缘。
   `blocked_cash=cash-available_cash` 不是锁定股票。真实 observer 的 locked 与账户行动状态可用，却被丢弃。
   decisions_orders_fills 仅序列化 result.trades；未保存 result.order_results 的请求股数／限价／订单终态、attempt/sequence、slippage_cost、participation。
   core 产生的失败成交事件有保留 status/reason；但无法凭它还原请求量／DAY 剩余量，策略在提交前拒绝的原因也未导出。
   episode_summary 只有最终状态；没有逐日 slots/commitments/free_cash/occupied codes 或 tranche 状态迁移。`bridge` 形参未使用。
   建议导出真实 ExecutionUpdate、OrderResult、策略 rejection_log 与逐日 registry 快照，保留原始身份，提供持仓并集及守恒校验。

2. **缺少验收状态的显式传播，unknown 被成功返回掩盖。** runner:241、500、582–600、640–648。
   quantity_rule_status 正确写 not_accepted，没有伪造 accepted；但 outcome 和 manifest 的 validation_failures 恒为空，缺少 mechanical/production acceptance 状态。
   独立 probe 使用空行情 provider：0 orders、0 trades、warnings=[]、validation_failures=[]，仍返回 outcome 并写 manifest。
   本实现没有 complete 字段；不能指控其显式写了 complete。但下游只看空 failures 会误判完成，且缺行情／规则验证状态无法区分。
   建议机械运行与生产签收分别标识；将缺失数量验证、公司行动验证、市场覆盖／unknown 状态显式列为未验收，不能将空失败列表当生产通过。

3. **公司行动接口含静默无效参数。** runner:135、278–289、389、440–445、567–581。
   require_known_share_tax 仅声明，从未消费；设 True 仍可无 provider 成功返回，配置哈希与默认相同。
   provider 存在而 period_id=None 时每日 hook 返回空操作；manifest 却记录 provider fingerprint。独立 probe 证实与无行动的交易结果相同。
   当前接口实际只把 period_id/tax_policy 转交 account_operations_for_day；不提供持仓／登记权益过滤，不接 CorporateActionLedger，不传播 tax_metadata、rights/送转税未知状态。
   建议拒绝无效组合；实现或显式拒绝 require_known_share_tax；记录实际行动范围和 unknown，不把“传入 provider”视为已集成验证。

4. **无关未持有公司行动会全局终止。** runner:285–288、440–470 → corporate_actions.py:189–219。
   每天对 provider 全部事件转换操作，缺 record/pay/listing 等字段的检查发生在 core 确认登记持仓之前。
   probe 对从未入榜／持有的 999999.SZ 设置缺 record_date 的现金分红；真实 runner 在该 ex_date 抛 ValueError，终止全窗。
   原因在既有 provider 的无条件检查，runner 集成直接继承；不能因为依赖代码既存就认为此次集成路径可验收。
   建议以真实登记权益及相关代码判定是否需要严格结算；无关未知事件留审计记录，持有权益未知则显式阻断相关验收。

5. **实际费用／公司行动配置不能可靠复现。** runner:430–474、503–506、567–581、618–649。
   静态 CostConfig 同时交给策略和 core，路径正确；但 resolver 可改变实际费用，manifest 只记录 argument/default，配置哈希不绑定 resolver 或执行日／代码实际费率。
   probe 在同样文件／窗口／config 下添加 commission_rate=0.01 resolver：main_nav_end 从 999312.2853999999 变为 993757.33，config_hash 相同。
   config_hash 还缺 period_id、provider fingerprint、require_known_share_tax；manifest 没有可还原的完整成本数值、执行默认值、core 版本／指标口径／warnings。
   建议固定并记录实际费用表及来源哈希，绑定实际行动输入和所有有效参数；不能以这一个 config_hash 作为完整研究配置身份。

6. **窗口日历只有自洽校验，零 buffer 时 E 退出逻辑缺失。** runner:178–203、428–438。
   日期严格递增、anchor/E 在日历、信号文件日期集合相等、buffer 不超过 3 日均有检查；没有权威交易日历绑定，无法发现日历和信号同时缺日。
   接口允许 0/1/2/3 个 buffer，而非保证完整 3 日。零 buffer 时 buffer_start=None，策略不会走 E 退出分支。
   probe 去除所有 buffer：成功返回、E 信号 SELL=0、最后仍持有 3 股代码、validation_failures=()。
   零 buffer 的盯市本身不应被冒称现金清算；此处问题是完整终端维护未实现却无状态声明。建议生产冻结权威日历，并明确支持或拒绝不完整 buffer。
   E 边界实际语义为“E 收盘不提交 BUY，buffer 不执行 BUY”；E 日仍可执行 E-1 的 BUY。现有政策裁决第34行也是此语义，不能称“E 日执行完全禁买”。

7. **指定解释器下类型门失败。** runner:221、287、590、599；测试:244、318、327、354、362、371、380。
   定向 Pyright 12 errors：runner 5 条（日期联合类型迭代、TaxPolicy、out_path 可能未绑定），测试 7 条（SyntheticMarketProvider 与具体 market 注解不符，以及故意非法参数缺类型抑制）。
   这些静态诊断不都意味着运行时故障，但质量门要求零错误，不能因单测成功忽略。
   全仓 Pyright 863 errors；范围外错误未逐项归因，未与基线比较，不声称由本增量引入。新增两文件本身的 12 errors 已独立定位。
   建议修正接口类型／控制流，并对故意非法调用作局部明确的测试类型声明。

8. **E 日执行仍可 BUY，不满足本次“E及buffer禁全部BUY”的严格字面要求。** runner:438、461–479 → staged_order_strategy.py:324–329。
   补充 probe 只在 E-1 开启 buy_eligible，真实 core 在 E（2021-01-11）开盘成交5笔 BUY，validation_failures 仍为空；见 probe_e_execution.json。
   已有政策文件定义的是“E收盘不提交进入buffer的BUY”，现实现遵循该较窄语义；本次文字要求若包含 E 执行日，则当前行为不合格。
   建议验收记录直接标出决策日／执行日边界；严格 E 执行禁买需向前门控 E-1 买单。不能以现有 test_e_day_and_buffer_no_buy 证明该严格要求。

## 已确认正确的机械路径

- runner:461 直接调用主区 .venv 已安装真实 run_account_backtest_from_orders，传真实 StagedOrderStrategy、StagedExecutionBridge、完整传入日历、signal/maintenance/anchor/E。
- core 路径：`D:/code/cnn_full_20260905/cnn/.venv/Lib/site-packages/backtest_core/engine/account_runner.py`；文件 SHA-256 为 `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。
- core 自己维护现金、T+1 locked、成交、DAY 终态、权益、逐日 mark；bridge 使用 pre/post 实际现金差，不自行构造账户盈利。独立探针观察到 36 个真实 ExecutionUpdate。
- registry 预算恒为 initial_cash/5，最多 5 个非 CLOSED 周期；策略将持仓、锁仓、权益、活动订单并入 occupied，10 名额边界存在。
- 全 ready+finite 按 score 降序／代码升序排名；buy_eligible 不删排名，只门控新 BUY 和加仓；普通退出 rank>10 与 buy_eligible 无关。buffer 行政退出另行成立。
- 每次 run 创建新 registry/bridge/strategy/core 账户；连续两次 reset 的逐日账户快照相同。continuous 明确 NotImplementedError，符合本次许可。
- 真实文件原始字节 SHA 绑定读取的同一份 bytes，支持 F4 date/code 映射；拒绝非 64hex／全0、文件篡改、删行改分值、外传 Mapping／自报未匹配 SHA。
- 文件日期集合必须与 window.signal_dates 完全相等；缺列、重复代码、无效资格由 loader/ranking 层拒绝；不按行情执行可买性预删排名。
- output_dir 使用 exist_ok=False 排他创建，既有目录拒绝覆盖；子文件写 w 以新目录独占为前提。未发现普通调用路径覆写既有输出。
- daily_account 的日期覆盖传入全部 9 日，包括 anchor；合成逐日现金+持仓+应收+权益守恒测试通过。实际最大正持仓 3、locked 代码最大 3，不能把这个夹具称成真实持仓上限已实证。
- 主区间收益与 buffer 分别从 core 快照计算；结果是资金盯市账户收益。缺基准和真实行情验收，不能据此声称严格跑赢基准。
- quantity_rule_status 始终 not_accepted，税务明确 stress 非实际个人税制；pretax 为税前口径，送转税未知没有被本审查认作已知。

## 三项验证及 TDD

统一工作目录为冻结树，Python 为 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`。
所有回测测试设置 CNN_ALLOW_LEGACY=1，禁写 bytecode；测试临时文件重定向审查目录。无安装／lock 变更。

| 验证 | 结果 | 实际范围与证据 |
|---|---|---|
| Ruff | PASS | `-m ruff check --no-cache .`，全仓，退出0；ruff.log |
| Pyright 定向 | FAIL | `-m pyright --pythonpath <主区解释器> <新增两文件>`，12 errors；pyright.log |
| Pyright 全仓 | FAIL | `-m pyright --pythonpath <主区解释器>`，863 errors / 0 warnings；pyright_full.log |
| unittest | PASS | runner 20 + allocation 38 + strategy 11 + bridge 5 = 74，通过74，失败0，错误0，skip0，0.352秒；tests.log |
| 独立合成探针 | 已执行 | probes.json / probes_extra.json；所有数值仅为机械示例，非研究绩效 |
| TDD 历史证明 | FAIL／证据缺失 | 未提供 runner 的 red_passed/green_passed 记录；测试文件自称 TDD 不等于 RED 证据 |

按质量门，新公共运行入口属于 need_test=true；缺 tdd_verification 不能给 TDD PASS。
上述 unittest 是用户明确要求的独立实跑证据，不能补认历史 RED，也不能让正式 TDD 门由 FAIL 转 PASS；默认“TDD FAIL 不进 test”的流程被用户显式实跑要求覆盖。

## 七关卡

| gate | 结果 | 依据 |
|---|---|---|
| 规范一致性 HIGH | FAIL | snake_case/PascalCase 命名正常；runner:413、480、508、617–670 大量注释描述“做什么”，不符合“只写为什么”；测试:69、201、207 有英文说明注释。作为规范项列 P2，不与账户 P1 混淆 |
| 模块边界 HIGH | PASS | adapter→core contracts/engine/evaluation、adapter 内部依赖；未发现冻结 research import 或反向依赖 |
| 数据安全 HIGH | PASS | 新增两文件无硬编码凭证；只记录信号／checkpoint SHA，不产生假数量证书 |
| 导入合规 MEDIUM | PASS | 无通配符，Ruff I 通过 |
| 错误处理 MEDIUM | FAIL | provider 缺 period 静默返回空行动；策略拒绝／unknown 在产物中丢失，见 P1-1/2/3 |
| 过度防御 MEDIUM | FAIL | getattr(market, verified_states, {}) 把无覆盖证据折成0而无未验收状态；require_known_share_tax 是无效接口保护，见 P1-2/3 |
| 性能风险 MEDIUM | PASS（限审查范围） | 未发现必须阻断单窗运行的性能故障；全文件 bytes+Arrow+逐行 dict+全榜 JSON 多次物化无规模上界，未作全市场内存压测，不声称已验证容量 |

## 范围外门槛与明确未验证项

- 生产数量 resolver 尚未接入，科创最低200股／零股整余额卖出不能靠全局 lot_size=100/200 证明；保持 not_accepted，本次不构造证书。
- 公司行动生产快照、登记日前历史权益、配股未知处理、缺失结算规则与送转税需独立集成验收；目前只预留按日操作转换，不能称已完成账户行动上下文验证。
- 信任 market provider 提供 SDK 直接价格界／状态。runner 没有重建价格界；已读 CnnRawMarketDataProvider 确认其直接透传 absolute_limit_*，未知为 None。尚未验收真实快照血缘、覆盖和实际 SDK 数据。
- CLI 明确抛 NotImplementedError，尚不是可直接运行的生产命令；API 可供合成／注入 provider 调用，CLI 未接入不等于 core 调用是假的。
- 未做真实 F4 大文件或真实绩效运行，仅用真实 Parquet 格式的 F4 date/code 合成数据验证读取；checkpoint SHA 仅是记录值，没有核验 checkpoint 实物。
- 74项包括既有 staged 回归，runner 自身20项。部分测试仅检查存在／末态；例如 max_five_slots 只看末态，buffer_sell 若无成交会空循环通过，不能据其证明全路径／所有政策。
- 成本后非负、严格跑赢同口径基准、真实每日持仓<=10的研究目标仍未证明；未运行数据、无基准比较，状态 BLOCKED。机械 PASS 不代表研究验收。

## 冻结文件哈希及交付

审查前、三项验证后、最后探针后均一致：

- `backtest/cnn_adapter/staged_candidate_runner.py`：`2faa9e1196732d875d4fe9674086869c894cc76c965a18310dd7dd976983a931`
- `tests/unit/backtest/test_staged_candidate_runner.py`：`39c8d8af6a2f4b399cd5c36baa2e01b05208d87dbc87cbc3c04b731750652c6d`

日志：verification.json、ruff.log、pyright.log、pyright_full.log、pyright_full_exit.txt、tests.log。
探针：probes.py/json、probes_extra.py/json、probe_e_execution.py/json；合成产物 probe_outputs/、unknown_outputs/。verify.py/typecheck_full.py 保留命令和执行环境。
所有交付位于用户指定临时目录；修复轮数0，无源码补丁，无 git 提交。
