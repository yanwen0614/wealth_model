冻结 runner 修复交付（2026-10-27）

status: complete（本轮修复完成；生产集成仍未验收）
task_id: staged_runner_fix1_20261027

changed_files:
- backtest/cnn_adapter/staged_candidate_runner.py：修改；组合真实 observer、状态/订单/费用/registry 导出、验收状态、费用冻结及配置身份、公司行动显式集成门槛、三日 buffer、类型修复。
- tests/unit/backtest/test_staged_candidate_runner.py：修改；原20项保留并增加13项回归，E日测试命名明确区分决策与执行，非法参数仅局部类型豁免。

test_files:
- tests/unit/backtest/test_staged_candidate_runner.py

实际根因与处理：
- 旧导出只遍历 result.trades；bridge 收到的不可变 pre/post_state 及订单结果被丢弃。现在原始 ExecutionUpdate 先逐条交付 bridge，再按契约字段序列化；额外保存 post_state 的 locked/pending_cash/record_positions/应收/未上市权益、真实 OrderResult、三项现金成本/滑点/参与率、策略 rejection_log、逐事件及收盘 registry/episode/tranche 状态。没有重算账户账本。
- validation_failures 旧值恒空。现在 outcome/manifest 均显式 mechanical_status=PASS，production_acceptance=INCOMPLETE/BLOCKED，并列出数量规则、CA上下文、送转税、市场血缘、权威日历、checkpoint实物及真实 core warnings 的门槛。
- 旧 provider 缺 period 静默跳过；require_known_share_tax 未执行。现在缺 period 立即 ValueError，严格税务要求立即 NotImplementedError；所有旧 provider 直接运行均明确拒绝，等待独立 corporate_action_context/snapshot_loader 接入。
- 旧 provider 对全市场事件转换时先检查 record_date，尚未进入 core 登记持仓判断。evidence.json 直接重现无关 999999.SZ 缺 record_date 异常；runner 在调用转换前拒绝，未复制独立树模块。
- 旧 config_hash 只绑定静态成本。现在在窗口全部日期和候选代码上按真实 CostConfig resolver 接口预先 resolve，每键一次；策略与 core 仅查冻结表。完整成本表、执行/组合配置、period/tax/require_known、行动输入、core版本/runner文件SHA、实际warnings、方法口径及市场输入摘要进入SHA256身份；实际调用费用表另行导出。不使用函数 repr。
- 同样合成信号：默认主区间末NAV=999312.2853999999，高佣金NAV=993757.33；旧代码两者身份相同，修复后不同。两个不同 resolver 对象返回相同费率时身份和账户序列相同。
- 日历现要求恰好3个buffer，0/1/2和超过3均拒绝。E-1买单在E执行合法；E收盘与buffer不提交BUY，真实成交边界回归通过。
- 日期联合迭代、TaxPolicy及out_path控制流问题修复；行情参数改用core MarketDataProvider协议，保留正常合成/真实provider接口。

真实 TDD（不是补认历史证明）：
- baseline.log：修改前原20项通过；baseline_types.log：重现指定解释器下12项Pyright错误。
- red.log：先加入7项行为回归，运行27项；7个失败、2个错误（含buffer三个subTest失败），退出1。
- green_initial.log：首轮实现后仅剩测试字段拼写错误，已改为core真实字段record_positions；该中间失败未隐藏。
- green.log：最终87项全部通过，退出0；runner33 + allocation38 + strategy11 + bridge5。
- lint.log：限定两文件 Ruff PASS，退出0。
- types.log：指定主区解释器 Pyright，两文件0 errors/0 warnings，退出0；未跑全仓类型检查。
- 新增补充守卫覆盖E-1→E、resolver对象确定性/每键一次、真实partial/DAY终态/剩余、非空拒绝日志、全表计数不能证明窗口覆盖、有数据零交易不误判缺行情。

tdd_verification（以下各项 red_passed=true，green_passed=true）：
- 费用改变结果必须改变身份。
- 缺 period 不得静默跳过。
- require_known_share_tax 不得成为无效参数。
- 不完整 buffer 必须拒绝。
- 旧公司行动 provider 必须明确阻断等待新上下文。
- 空市场不得生产通过。
- 原始执行状态及订单血缘必须导出。

源码 SHA256（最终内容，见 evidence.json）：
- runner：939a3cc63740cac7bf686441d22e40de13978183fafc1f7fc13b201b682ec084
- tests：f8468d13624955021a8034dafc407e9b81f49016168ebcac8d650dc3ff2115af

交付物：evidence.json、synthetic_artifacts/、verify.py、evidence.py及上述日志。测试临时目录已由TemporaryDirectory清理；这些交付证据保留。

blocked_reason（仅生产集成）：
- 数量校验resolver尚未接入，不能把lot_size=100作为科创最低200股/零股整余额卖出证书。
- 独立树的corporate_action_context/snapshot_loader未合入；需要登记日历史权益、事件范围、税务未知与快照血缘集成验收。本轮不支持生产CA执行。
- verified_states按(代码,日期)逐格检查market_state/st_known/reference_known/limit_known，实际bar状态与绝对价格界也逐字段检查；缺失/unknown导出到market_coverage.jsonl。即使覆盖完整，source_known仍明确false，不能将调用方表视为真实来源证书。
- 市场原始快照与官方状态血缘、权威交易日历及checkpoint实物尚未验收；有覆盖且无交易可为INCOMPLETE，空行情必为BLOCKED。
- CLI仍显式拒绝未接入的生产运行。未做真实F4大文件容量验证、实际研究绩效或基准收益验收。

范围核对：
- 只有用户指定两个源码文件发生改动，git状态仍为原有两个未跟踪文件；未stage/commit/push、未装包、未改core或其他owner的上下文模块、未派会话。
- 单测仅运行指定runner和三个直接相关staged模块，没有运行全量测试套件。
- 读取独立QA的REVIEW_REPORT.md；用户所述probes/pyright.log路径不存在，实际原始类型日志在同一QA临时根的pyright.log，已读取并实际重现12项错误。
- 每次apply_patch新增/替换写入均不超过50行。真实F4原始字节SHA、精确日期集合、拒绝外传mapping、排他输出、reset新账户、五槽预算及完整榜规则保留。
