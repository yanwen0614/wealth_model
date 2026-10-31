# 修复轮1独立复验

日期：2026-10-27。mode=re_verify；task_id=staged_runner_independent_qa_20261027；retry_count=1。

**模块质量门：PASS（本轮约定的机械模块功能复验＋定向三项验证）。生产验收：BLOCKED／未验收。研究收益目标：未证明。**

本轮采用 re_verify 流程：直接执行三项验证，再逐条对照前轮真实问题；不重新执行全仓七关卡审查或全仓类型基线。
主会话明确接受旧 CA provider 拒绝执行及生产未接线作为阶段门槛；未将这些门槛当作机械模块实现缺陷。
本结论不是生产 accepted，也不表示既有全部注释均已符合完整 review_verify 的风格门。
未修改源码、安装依赖、改 lock、Git提交或创建会话；无训练、无真实F4绩效运行。日志及合成探针只写本目录。

## 冻结范围与输入证据

源码树仍为 `C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/staged-runner-v2-20261027`。
已读 Generator 的 `staged_runner_fix1_20261027/DELIVERY.md`、`evidence.json`、`red.log`、`green.log`；未仅依据交付声明判定。
沿用本会话已读的根／模块规范和 quant-model 技能；本轮用户限定的定向验证范围优先。

| 冻结文件 | 审查前、验证后、最终复核 SHA-256 |
|---|---|
| backtest/cnn_adapter/staged_candidate_runner.py | `939a3cc63740cac7bf686441d22e40de13978183fafc1f7fc13b201b682ec084` |
| tests/unit/backtest/test_staged_candidate_runner.py | `f8468d13624955021a8034dafc407e9b81f49016168ebcac8d650dc3ff2115af` |

## 三项验证

所有命令使用 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`，cwd 明确为冻结树。
回测测试 CNN_ALLOW_LEGACY=1；PYTHONDONTWRITEBYTECODE=1，测试临时目录指向本交付目录。

| 项目 | 本轮独立实跑 |
|---|---|
| 定向 Ruff | `-m ruff check --no-cache <新增两文件>`：PASS，退出0 |
| 定向 Pyright | `-m pyright --pythonpath <主区解释器> <新增两文件>`：0 errors、0 warnings，退出0 |
| 四套件 unittest | runner33＋allocation38＋strategy11＋bridge5＝87；全部通过、0失败、0错误、0 skip，1.324秒 |
| 全仓类型基线 | 按要求未重跑；旧863项不参与本轮模块判定 |

完整命令、工作目录、解释器、退出状态及前后哈希见 verification.json；输出见 ruff.log、pyright.log、tests.log。

## 逐项收敛

| 上轮问题 | 本轮结论 | 复验依据 |
|---|---|---|
| 1. 输出缺真实账户／订单／registry | 已修复 | runner:317–352、737–820；独立对比36条真实bridge回调、9日账户／registry、6笔OrderResult，身份与数据一致 |
| 2. 空failures掩盖unknown／not_accepted | 已修复 | runner:674–683、787–793；空市场机械PASS但生产BLOCKED，failures非空；覆盖完整零成交仅INCOMPLETE，仍非accepted |
| 3. 税务参数及provider缺period静默 | 已修复为显式拒绝 | runner:507–513；缺period抛ValueError，严格送转税抛NotImplementedError，旧provider明确拒绝 |
| 4. 无关未持有CA缺日全局爆炸 | 当前接口已以守卫封闭；生产CA仍待集成 | 未进入旧provider操作转换；无关999999.SZ缺record事件得到明确集成门槛错误。未宣称底层provider已修复 |
| 5. 费用改变结果却身份不变 | 已修复 | runner:297–314、684–712；真实费率表先冻结，策略与core共用；成本及有效配置纳入SHA256身份 |
| 6. 不足3buffer／日历未认证 | buffer缺陷已修；日历认证转显式阶段门槛 | runner:202–204要求恰好3日；独立拒绝0/1/2/4日；authoritative_calendar_not_accepted仍保留 |
| 7. 两文件12项类型错误 | 已清零 | 正确主区解释器定向Pyright实跑0错误，测试非法参数仅局部豁免 |
| 8. 严格E执行禁买 | **撤回，不是缺陷** | 主会话裁定：E-1订单在E执行合法；既定边界为E收盘不能提交进入buffer的BUY |

前轮报告／VERDICT原件保留作审计历史；本报告对原第8条作正式更正，后续不得继续引用其为缺陷或要求前移E-1门控。
旧“注释只写为什么”P2观察仍有描述性注释残留（如runner:559、756、800）；不报告为已修复。测试原有英文说明已改中文。
该P2观察单列为非功能规范遗留，本轮PASS仅表示re_verify三项验证和所指定真实缺陷通过，不冒充完整七关卡重新签收。

## 独立核验真实产物

探针 probes.py 通过包装真实 StagedExecutionBridge.on_update 捕获原始对象，并先执行真实bridge；未替换core、未构造模拟ExecutionUpdate。

- execution_updates.jsonl：36条，event_id和sequence与真实回调一致；逐条核对pre/post cash、available_cash、positions、locked、pending_cash、record_positions。
- daily_account.jsonl：9日精确覆盖传入日历；逐日core_state等于同日最后一条真实事件post_state，state_lineage对应真实event_id；NAV/现金/可用现金与core AccountSnapshot相同。
- daily_registry.jsonl：9日，与同日真实core_state一致；registry_transitions.jsonl有44条，含收盘决策后状态和后续core事件状态，保留episode/tranche详细字段。
- 持仓、锁仓、应收、未上市权益、pending_cash保存在core契约状态中；blocked_cash仍仅为现金差，不当作锁定股票。当前CA禁用，权益项为空是真实空值，不是生产CA测试证明。
- order_results.jsonl：6条与真实OrderResult一一对应；核对order_id、请求shares、limit_price、filled_shares、remaining_shares和终态。execution_updates另保留attempt/terminal身份。
- 本轮回归还覆盖真实partial/DAY唯一终态／剩余量、非空策略提交前拒绝日志、成交滑点及参与率导出，均通过。
- 逐日现金＋持仓市值＋应收＋未上市权益与NAV一致；槽位<=5、occupied并集<=10。合成默认夹具实际持仓3、locked代码最大3；不称真实研究期上限已证明。
- 每次run重新创建registry/bridge/strategy/core账户；重复reset逐日快照相同。原始文件SHA/日期集合/拒绝外传Mapping/排他输出回归均通过。

费用探针复现：静态成本NAV=999312.2853999999，改高佣金后NAV=993757.33；结果仅是合成机械数值。
静态身份：`89d723369b7c2ae4ef7ac79630a6e0fe2d52691e3efd8cb9a1ae3798fbe0c502`。
高佣金身份：`16c314c3f089374f31d6b09a0e28cb143789ce5e00b90b0fa0a16b6352a27e7f`。
不同resolver对象返回相同费率时身份相同；回归确认每个日期／代码只调用原resolver一次，actual_fee_usage披露实际查表使用。

公司行动探针：无关未持有事件缺record、provider缺period、require_known_share_tax=True分别被明确拒绝，无静默通过或虚称税制已知。
空市场探针：mechanical_status=PASS，production_acceptance=BLOCKED，包含market_data_missing和market_state_coverage_unknown。
不能把这里的mechanical PASS解释成市场数据有效或生产完成；outcome和manifest均保留独立生产状态与失败／缺项列表。

## 本轮TDD与历史限制

原版本缺历史RED证明的事实不变，不追溯补认。仅验收本轮7项修复行为的RED/GREEN。
Generator red.log 的命令是指定解释器单runner套件；27项运行，7个失败、2个错误（buffer的0/1/2各一个subTest失败），退出1。
错误分别是缺mechanical_status和缺execution_updates文件，属于待实现行为的RED；其他失败对应费用身份、provider门槛、缺period、严格税务与buffer守卫。
Generator green.log 最终87项全通过；本轮独立重跑同样87项全通过。故这7类修复的red_passed=true、green_passed=true可接受。
新增其余回归为补充覆盖／边界澄清，未伪称13项新增测试全都有独立RED轨迹；类型门0错误亦由本轮独立实跑确认。

## 生产验收与模块结论分离

模块机械实现已通过本轮复验；**生产未验收，仍不可称accepted**。以下门槛没有被修复或单测“抹平”：

- quantity_rule_status=not_accepted；真实板别数量resolver尚未接入，不能用统一lot_size替代科创最低200股或整余额卖出校验。
- corporate_action_context/snapshot_loader尚未接入；旧provider当前拒绝，登记日历史持仓、相关事件范围、配股及缺失日期处理仍需后续集成验收。
- share_tax_unknown保留；pretax为税前、cash_dividend_20pct_stress为压力口径；无公司行动实际入账时不冒称已施加实际税制。
- 真实市场快照血缘、权威交易日历及checkpoint实物未验收；代码有逐格行情／状态覆盖检查，但source_known恒false，调用方表不能自证官方来源。
- 数据／状态有缺项时BLOCKED；逐格覆盖完整时最多INCOMPLETE；生产accepted路径当前不存在。这是明确阶段限制，不是本轮模块FAIL理由。
- CLI仍明确拒绝生产执行；continuous仍明确未实现；均未冒充可用生产入口。
- 尚未做真实F4大规模容量、真实成本后收益、同口径基准和真实逐日持仓验收。最终成本后非负且严格跑赢基准、持仓<=10的研究目标仍未证明。

本次未发现仍开放的P0/P1机械实现缺陷。旧第1/2/5/6/7问题已通过；第3/4通过显式拒绝封闭当前接口；第8正式撤回。
交付文件：VERDICT.json、verification.json、ruff.log、pyright.log、tests.log、probes.py、probes.json及artifacts/、empty_market/。
本轮源码修复操作0次；复验结束再次核对两文件SHA，与本报告冻结值一致。
