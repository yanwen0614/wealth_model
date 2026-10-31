# 独立合成闭环设计

## 目标与强制边界
状态：设计完成，真实候选实验 NO-GO；仅新增接口与合成测试，不接入实际 runner/engine。
冻结原日期标签7文件及原三件套；不改 runner、core、已有审计脚本、__init__.py、记忆或其他已有文件。
实施白名单恰为 backtest/cnn_adapter/{historical_costs,execution_audit,run_identity}.py，以及 tests/unit/backtest/test_{historical_costs,execution_audit,run_identity}.py。
本轮只创建 SYNTHETIC 三件套，不写上述源码，不跑测试、训练、GPU；每次文件写入<=50行，中文，不提交推送删除。

## 已核实协议与重复检测
core policies/cost.py:16：calculate(side, amount)→(commission, stamp_tax, transfer_fee)，无日期参数。
core contracts/config.py:150：CostConfig 支持双边佣金、最低佣金、stamp_tax_rate、transfer_fee_rate。
core engine/account_runner.py:1351-1357：内部硬编码 AShareCostModel(resolved_cost)，无费用模型注入点；cnn runner.py:173-178 只传静态 CostConfig。
core contracts/protocols.py:182：OrderStrategy.orders_for(*, trading_date, signal_time, account, market)→Sequence[OrderIntent]。
core account_runner.py:1371-1409：开盘先执行已排程单，再收盘调用策略；尾日清算发生在收盘信号之后。
core contracts/account.py:149-175：快照校验 cash+已知MV=NAV，但允许缺价持仓不计入；新增审计必须更严格。
现有 target_strategy.py:206、233 可复用订单协议/OrderIntent；禁止复制选股、撮合、T+1、成本公式。
现有 runner 测试覆盖静态费率参数，未发现历史费率模块、独立执行审计模块或逐分支身份模块；三个新模块名均不存在。
cnn 根及适用技能约束沿用已读版本；新增读 core 根/ contracts AGENTS，core 只读且依赖不可反向引用 cnn。

## A：历史费用最小 API（historical_costs.py）
`resolve_historical_costs(*, execution_date: date, market: str, commission: CostConfig) -> CostConfig`
market 仅精确接受 SSE_A、SZSE_A；调用者须显式提供A股市场类型，不凭.SH/.SZ后缀把基金/B股认作A股。
execution_date 仅纯 date（拒绝 datetime/字符串），且>=2021-01-01；北京/未知市场及更早日期 ValueError。
以传入成交日判断生效断点，不用 signal_date：卖出stamp在2023-08-28前0.001、当日起0.0005；买入由core保持0。
transfer双边在2022-04-29前0.00002、当日起0.00001；commission的佣金及其他配置保持原值，仅替换上述两字段后重新构造CostConfig校验。
`calculate_historical_costs(*, execution_date, market, side, amount, commission: CostConfig) -> tuple[float,float,float]`
内部仅 resolve→AShareCostModel(resolved).calculate(side, amount)，不复制费用公式，不修改NAV；金额/side沿用core校验。
commission为必填的调用者券商假设，文档必须称可配置佣金，不声称法定费率/最低额；不改core的零金额语义。
来源一：https://shanghai.chinatax.gov.cn/zcfw/zcfgk/yhs/202308/t468451.html ，公告2023年第39号确认2023-08-28起减半。
来源二：https://jrj.wuhan.gov.cn/ynzx_57/xwzx/202204/t20220429_1964160.shtml ，确认沪深0.02‰→0.01‰双边、生效2022-04-29。
两页已读取；来源一只声明减半，2021起基准0.001为本任务明确输入，不将该公告夸称覆盖全部历史。

## B：终端包装与核验最小 API（execution_audit.py）
`build_terminal_plan(calendar: Sequence[date], evaluation_end: date, *, buffer_days: int=1) -> TerminalPlan`
交易日历必须严格递增唯一；buffer_days>=1；E=max(d<=evaluation_end)，X=max(d<evaluation_end)，B为E后连续buffer_days个日历交易日。
明确采用保守解释：X为evaluation_end严格之前最后一个交易日；X收盘起退出-only，E仍保留普通考核期末MTM截点，B仅为退出清算缓冲。
要求X存在、B足够；不自动补自然日，不假装日历完整；计划返回exit_signal_date=X、evaluation_date=E、buffer_dates=B、settlement_end=B[-1]及完整日历。
`ExitOnlyStrategy(inner: OrderStrategy, plan: TerminalPlan)` 实现同签名 orders_for，并提供只读 suppressed_orders 记录。
trading_date<X时调用inner；任何BUY若下一交易日>X即抑制并记录(signal_date, execution_date, order, reason)，SELL原样保留。
trading_date>=X时不调用inner，按account.positions排序为正持仓发全股SELL；不扣locked猜成交，交core裁决，下一交易日重试剩余股数。
最末日无下一交易日则不发无效单，报告残仓；计划区间外日期、信号日期/时区不符直接拒绝。
包装器只读账户，不维护影子持仓/现金、不伪造OrderResult；抑制记录属于包装决策，区别于core成交/拒单回报。
`validate_terminal_execution(execution_config: ExecutionConfig, portfolio_config: PortfolioConfig) -> None`
要求execution_mode=t1_open、final_liquidation='mark'、rebalance_frequency=1；force/skip/非逐日均拒绝，避免错过退出回调。
`audit_execution(result: EvaluationResult, plan: TerminalPlan, *, daily_closes: Mapping[date,Mapping[str,float]], max_positions: int=10) -> ExecutionAuditReport`
只核验，不重算撮合或修改NAV；快照日期须逐日完整覆盖计划运行日期且唯一递增，E/B[-1]都存在。
每日正股数持仓计数<=10（max_positions只能1..10）；价格/MV/cash/NAV须有限，每个正持仓必须有当天显式正close。
对照daily_closes逐项核验shares×close=position.market_value及sum(MV)+cash=NAV，容差abs=1e-6、rel=1e-9；不接受last_marks替代缺失当天价。
核验所有成交execution_time>signal_time；X之后执行的BUY、forced_exit事件均判失败，不能靠期末现金掩盖违规。
报告分列evaluation_mtm（E的现金/MV/NAV/持仓）与post_buffer（B[-1]同字段），不得把后者当作原考核期净值。
报告保留filled成交、locked事件、partial/rejected订单及reason，并列最终每只残仓shares/MV；locked事件数量不冒充实时锁定股数。
cleared仅最终正持仓为空时true；存在合法locked残仓可审计通过但cleared=false，绝不声称buffer保证卖得掉。
契约缺失/恒等式/时序/持仓/缺价失败均ValueError并指明日期标的；残仓本身是透明结果，不能静默抹零。

## C：逐分支身份最小 API（run_identity.py）
`capture_run_identity(*, branch_label: str, repositories: Mapping[str,Path], modules: Mapping[str,Path], artifacts: Mapping[str,Path], distributions: Sequence[str]) -> RunIdentity`
repositories必须包含cnn/core两个git根；modules必须含historical_costs/execution_audit/run_identity/cnn_runner/core_runner/core_cost/core_account的实际源文件。
artifacts必须含data/cache/checkpoint三个非空常规文件路径；没有真实文件时使用明确标记synthetic的合成文件，缺失不得unknown或跳过。
distributions至少backtest-core、numpy、pandas、pydantic、torch、pyarrow；importlib.metadata查询版本，缺失即失败；另记录Python版本。
各次调用独立运行git rev-parse HEAD、git status --porcelain=v1 -z --untracked-files=all，记录实际分支名/HEAD与dirty明细；detached只记录真实状态。
git错误、非仓库、缺文件/不可读/空角色/重复label为空值均ValueError；不以unknown占位，不使用全局上次分支缓存。
每个模块/产物记录resolve绝对路径、size、SHA-256；流式读并比较读取前后stat，文件采集中变化即失败；git采集前后不一致也失败。
modules中的core路径须与本进程实际import的core模块__file__一致；cnn三个新模块同理，拒绝给另一checkout文件冒充执行身份。
输出含schema_version、branch_label、仓库证据、文件证据、依赖版本；规范JSON排序派生identity_hash，函数不写文件。
`validate_branch_identities(identities: Sequence[RunIdentity]) -> None`：非空且label唯一、必需证据齐全；不同label允许相同SHA，但不能复用一份未重新采集的记录。
不同label复用相同仓库内容不算造假；调用者须每条实际执行路径单独capture，执行前后身份对比变化则该路径证据失效。

## 合成闭环与接入声明
费用闭环：手算有限笔成交notional→按成交日费用→合成现金流水/持仓→core快照→audit；只在测试中构造，不在生产模块实现运行循环。
终端闭环：合成MarketDataProvider+core现有run_account_backtest_from_orders直接验证wrapper，配置mark/逐日，用静态费用且避免跨费率断点。
两个闭环分开标注：费用日期测试覆盖断点，core终端测试覆盖实际T+1/拒单/残仓；不存在“动态费用已接入core”的集成测试结论。
身份闭环：每个合成branch_label独立采集三个新模块与core、合成data/cache/checkpoint文件证据，附在测试输出断言中。
这三个模块不导入cnn.runner来启动任务；不猴补core私有上下文、不按日期拆跑后拼NAV、不对已生成NAV补扣费。
真实候选NO-GO保持：日期感知费用尚未接入实际engine；复权notional、完整无标签半年信号、同时间基准等也未由本任务证明。

## 任务分解与验收
|任务|新增文件|依赖|验收|
|---|---|---|---|
| S01 历史费用纯接口 | historical_costs.py / test_historical_costs.py | 无 | 两断点前/当日/后、两市场双边、佣金假设保留、拒绝非法输入 |
| S02 终端包装与审计 | execution_audit.py / test_execution_audit.py | 无 | mark/T+1顺序、末正常买单挡住、buffer卖单、锁定/部分/缺价/11股失败、双截点分列 |
| S03 逐路径身份 | run_identity.py / test_run_identity.py | 无 | 两label独立采集、dirty/hash变化、依赖与路径缺失失败、实际core路径核验 |
| S04 独立合成闭环 | 仅在上述三个新测试内组合 | S01/S02/S03 | 不改既有文件，无真实候选比较，所有NO-GO边界仍明示 |
现有冻结七文件仅由主会话Luna门审查；本任务与其并列，不读取其测试结果冒充本任务验收。
