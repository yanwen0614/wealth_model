# 分批候选最小整合实施计划（2026-10-27）

## Goal

- 将已有 A 数量规则、B 账户 runner、C 公司行动 context 接成真实 core 闭环，固定 B1/S1/S2/C70 × W1/W2 共八个独立研究窗。
- 原目标保持：每窗成本后收益 >=0 且严格超过同期沪深300，逐日实际正持股 <=10；资金100万元、固定槽20万元、最多5槽。
- 本交付仅只读分析与规划；未编码、测试、训练、运行绩效、提交、创建工作树或派发会话。执行由主会话另建独立整合树。
- 不调参、不重训、不重生信号、不把八窗拼接连续净值；机械结果与实际税后目标资格分别报告。

## Architecture

- 复用 `load_frozen_signal_parquet → RankingSnapshot → StagedOrderStrategy → core → observer → registry`；新建一个输入接线模块，不另建账户或策略架构。
- 只读准备一次两窗输入；同窗四候选复用冻结信号、完整排名、行情缓存、状态映射、费用表和公司行动 snapshot；每次新建账户、registry、bridge、recorder、context。
- 真实 observer 链必须为 `core → ctx → recorder → bridge`：ctx 先保存完整 post_state，recorder 原样记录并送 bridge；不能把 ctx 与 recorder 并排调用或跳过 recorder。
- `account_actions_provider=ctx.account_actions_for_day`；任何退出路径 finally 保存 `ctx.evidence()`、窗口身份、最后回调与错误，不伪造完成的账户结果。

## KeyDecisions

- 探索明确配置 `strict_tax=False, tax_policy='cash_dividend_20pct_stress'`，真实税始终 unknown；严格模式继续按实际暴露阻断，禁止把全市场未知变成全局拒跑。
- `known` 是临时适配层对某个来源字段的可用性判定，不是原始数据的认证列；原始 canonical 与 JSON 只读，不新增 known/verified。
- 完整榜仅按 ready、finite 和冻结排序规则形成；buy_eligible 保留文件值，执行缺数不删榜、不补位到第6名、不重新排名。
- anchor 用于空仓基准，不是成交日；费用冻结必须避开 W1 的2020-12-31，否则现有 historical_costs 会抛错。
- 数量模块只校验申报量，保留现有按100股保守取量；科创规则 min200/step1 不要求把策略改成200倍数或启用新的取量优化。

## Impact：最少文件

|文件（相对整合树）|动作与具体边界|
|---|---|
|backtest/cnn_adapter/staged_production_inputs.py|唯一新增接线模块：输入校验、派生状态、准备缓存、来源配置、四候选循环、基准与汇总；不复制账户逻辑|
|backtest/cnn_adapter/staged_candidate_runner.py|移入B冻结文件后修改：接收准备输入、quantity resolver、CA snapshot；接线observer/hook；开放CLI；补finally与分层审计|
|backtest/cnn_adapter/raw_market_provider.py|保留原转换；构造增加 history_bars、allow_empty_window 并传给读取器，允许已解释的整窗无行情返回None|
|backtest/cnn_adapter/raw_market_inputs.py|读取入口增加 allow_empty_window=False；仅此显式模式允许空signal返回空窗口；严格校验、重复键、单位逻辑保留|
|backtest/cnn_adapter/corporate_action_context.py、corporate_action_snapshot_loader.py|精确移入C两文件，首轮不改内部语义；QA若发现真实接线缺陷另记修复轮|
|backtest/cnn_adapter/quantity_rules.py、staged_order_strategy.py|精确移入A当前版本；仅在必须增强结构化决策拒绝审计时小改strategy，不重写规则或策略|
|tests/unit/backtest/test_staged_candidate_runner.py、test_staged_production_inputs.py、test_raw_market_inputs.py、test_raw_market_provider.py|移入B测试并新增或扩展接线边界测试；执行阶段才运行|
|tests/unit/backtest/test_quantity_rules.py、test_staged_order_strategy.py、test_corporate_action_context.py、test_corporate_action_snapshot_loader.py|移入A/C对应冻结测试并检查共存；不能用B旧strategy测试覆盖A新版本|
- 主区 `runner.py`、`historical_costs.py`、`scripts/audit_walkforward_execution.py` 仅作复用契约与输出参考，首轮无需修改；后者是用户WIP，禁止执行其大源hash/标签检查/旧费用路径。
- `../backtest-core` 不修改；依赖必须核实实际 import 文件位置、版本和源码hash，不能因 editable 路径改变意外切回旧core。

## 冻结来源与证据路径

- 下面 `T=C:/Users/yanwen/AppData/Local/Temp/opencode`，`M=D:/code/cnn_full_20260905/cnn`；所有相对临时路径都以T为根。
- B源树：`C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/staged-runner-v2-20261027`；runner文件SHA256=`939a3cc63740cac7bf686441d22e40de13978183fafc1f7fc13b201b682ec084`，这是文件摘要，不是Git提交。
- B物证：`staged_runner_independent_qa_20261027/reverify1/VERDICT.json`、`verification.json`、`REVERIFY_REPORT.md`；87项是既有定向结果，production仍BLOCKED，不等于整合通过。
- A四文件取M当前未提交版本；物证 `quantity_rules_main_integration_20261027/INTEGRATION_REPORT.md`；移入前后逐文件hash，禁止把主区整体未提交变更打包。
- C源树：`T/corporate-action-fix-20261027`；只取 `corporate_action_context_delivery_20261027/fix1/SOURCE_SHA256.json` 的四文件，API见同目录INTEGRATION.md。
- C独立QA尚不能据本轮读取宣布PASS；不读取旧 corporate-action-context-20261027 树。若冻结hash变化先停移植，由主会话确认新交付身份。
- 官方数量来源：`board_exposure_audit_20261027_v1/official_rule_source.json`、科创2019 PDF、2023废止清单；`historical_order_rules_20261027_v1/manifest.json`；深交所修正以 `evidence_closure_review_20261027/CORRECTIONS.md` 为准。

## 输入身份与加载路径

|输入|明确路径、摘要与消费方式|
|---|---|
|预注册|T/staged_candidate_prereg_20261027_v1/preregistration.json；SHA256 `1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae`|
|日历基准|同目录calendar_and_benchmark.csv，列date/benchmark_close，247行；SHA256 `01f8462550e31af5088e933ac1931a6b313956a6caf355a0f82db2760ac70187`|
|W1信号|T/three_day_signals/W1_F4_full_CPU_v1/signals.parquet；SHA256 `99198e069157e570ffc2fa83818d1738a4abe468a5d39c76fca30dfba5d762e9`；478369行/4720201字节/118日|
|W2信号|T/three_day_signals/W2_F4_full_CPU_v1/signals.parquet；SHA256 `dc39dd8c0287d8ed4c3fb2313961518969534c633de451303dad7b9fd8178d9c`；538599行/5405801字节/125日|
|SDK规范状态|T/staged_execution_input_snapshot_20261027_v1/task1_v3/data/canonical_state_v3.parquet；SHA256 `36f7ea0e085bcdd03b58dca2a11e5494574f3a55e6625b781b132d876058b755`；1033541行/80416258字节/89组|
|缺口索引|同目录gap_index_v1.parquet单独读取，60144条缺口；绝不能把data目录整体当一个dataset|
|公司行动|T/staged_execution_input_snapshot_20261027_v1/task2_v2/{dividend_range_rows,right_issue_range_rows,metadata_snapshot}.json；使用现有loader逐文件校验与逐行hash|
|公司行动manifest|根delivery_manifest_v4.json；外部预期SHA256 `e7b1a533a6853a1b995d4a84c713acbb62943cc55f785c472020d2d492b86bcf` 来自C交付，执行时须实测匹配；不信任manifest中列出的自身旧hash|
|原行情|Z:/dev/kline/day/{code}.parquet；逐代码八列 code/kline_time/open/high/low/close/volume/amount；显式原价，volume÷100还原股、amount÷100000还原元|
|指数|Z:/dev/kline_index/day/000300.SH.parquet；预注册SHA256 `97a99b8ec472299960f56c3cc38c8e69adc8358482dda53eba1d722c210fe599`；准备时核小文件并比CSV对应close|
|数据库|Z:/dev/quant_data_dev.db，如确需补元数据只允许mode=ro+query_only；常规接线优先冻结JSON，不重扫DB或稀疏history_status|
- 信号实际schema为code/date/exp_ret/true_ret/status/label_availability/buy_eligible；date是timestamp，现有loader转纯date。true_ret为空，只保留原文件，不读取标签或训练大源。
- W1 checkpoint：`M/logs/relative/run_20261026_100509/best_model.pth`，SHA256 `a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde`。
- W2 checkpoint：`C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/w2-f4-training-20261026/logs/relative/run_20261026_212052/best_model.pth`，SHA256 `03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4`。
- checkpoint物证：两信号目录metadata.json；T/checkpoint_main_verification_results_20261027.md、checkpoint_main_verification_20261027.py、w2_ckpt_verify.json。准备阶段只hash权重并核冻结报告/config，不重复训练或推理。
- metadata记录W1 config SHA `6c5a2b7f67a520d84e7ae66843b595644a312fde6f6fdb4ff7b471c500ae164f`，W2为 `b21097978dd4c5ec8bbc8259b997d62907c2ea7ccb99793911db3c9612a39840`；从checkpoint同run配置定位，缺失则保留报告级证据，不能自动补证。
- 两窗均F4 OHLC/relative/excess/seq60/H10；W1训练止20200630验证止20201231，W2训练止20201231验证止20210630。训练源仅引用metadata已有大小/schema/历史摘要，不重hash4279965200字节源。
- W1执行日历=anchor2020-12-31+118信号日+2021-07-01/02/05，共122日；W2=anchor2021-06-30+125信号日+2022-01-04/05/06，共129日。
- CSV按各窗anchor≤date≤buffer末日切片，生成纯日期calendar_W1.txt/calendar_W2.txt给现有CLI；不把CSV表头直接传_parse_calendar。
- 同时记录CSV文件SHA与顺序ISO日期紧凑JSON的日历SHA；ctx.window_end用buffer末日，E另存。核实际core参数一致后，runner另出身份验证结果，不篡改ctx的pending_runner_validation原证据。

## 临时状态映射：来源绑定而非写回认证

- 新接口 `build_execution_state_mapping(state_path, *, expected_sha256, calendar, raw_records, source_audit) -> (states, evidence)`；states只给provider消费，evidence外置JSONL保存每字段判定与unknown。
- 先校验canonical文件摘要、(code,date)唯一、market_code/code及trade_date_str/date一致；按assemble_state_v3.py同序11字段紧凑JSON重算row_hash，不能换成新hash算法。
- 每条派生证据携带 canonical文件SHA、row_hash、source_file_rel、source_sha256、sha_origin、window、映射版本、字段语义来源，以及原始值；来源SHA必须追到scope_manifest/probe_result，不用当前重算值替代来源记录。
- 原始文件根为T/state_acquisition_20261027/full_state_v1；绑定既有8848文件核验报告 T/state_snapshot_main_verification_20261027_v1.json 与 state_acquisition_main_audit_20261027_v3；执行前核报告对应同一canonical摘要，不无条件照搬“已验证”。
- `is_susp_sec=='1' → market_state='suspended'`，`'0' → 'trading'`仅限真实显式成功SDK日记录及身份/hash通过；原行情与状态冲突另报，不能用成交行掩盖冲突。缺行、null、非0/1保持unknown。
- `is_st_sec in {'0','1'}`且字段原始保留、语义与来源核对通过才给`st_known=True`；同时在evidence保留is_st值，不能用known当作“非ST”。
- `preclose`正有限且来源字段含义已绑定 → `reference_known=True`；该值是SDK当日参考输入，不要求等于昨raw close，公司行动日也不重建或用旧close覆盖。
- `high_limited/low_limited`均正有限且顺序有效 → 透传absolute_limit_up_price/down；执行开盘open正有限后，以整数分比较open>=upper、open<=lower生成limit_up/down，再置limit_known=True。
- 不以close/high/low判断开盘封板；不从板别比例重建绝对限价；0/缺失/异常界（尤其IPO五日和恢复上市日）保持limit_known=False并解释，不能把无上限改成巨大数值。
- `IS_WD/IS_XR`原值保留，WD样本支持除息、XR支持除权；不推退市/风险警示、不生成CA权益，也不凭flags==0宣布无公司行动。
- 402暂停缺日仅用已核官方两码区间作独立状态来源；上市前59491/退市后251为生命周期解释，无交易bar就返回None，不能补假OHLC。全宇宙这些缺口不能把所有候选窗标成不可运行。
- corporate_action_dates由snapshot明确ex日期作参考需求标记；缺ex的descriptor另留coverage问题，不能凭此集合宣称CA完整。历史20/21根raw输入可供流动性计算，即使其SDK状态未知也不补known；core统计消费数值与执行授权分开记录。
- provider实际消费键必须使用下列拼写（各值均按上述条件派生，不能整表无条件True）：
```python
states[code, day] = {
    'market_state': market_state,
    'st_known': st_known,
    'reference_known': reference_known,
    'limit_known': limit_known,
    'limit_up': limit_up,
    'limit_down': limit_down,
    'absolute_limit_up_price': upper,
    'absolute_limit_down_price': lower,
}
```

## TaskDecomposition：生成器最小执行任务

### T01 冻结移植与依赖身份（无前置）

- files：上述A四文件、B两文件、C四文件；操作仅在主会话新建整合树。记录M的base HEAD及选定WIP文件hash；整合树从该base起步，显式叠加所需WIP，不用stash/reset影响其他会话。
- 验收：逐文件移入前后摘要相同；C的context=`8c88683136972e032dc37c11d96c3eff4d04c34c508fe9a2545c823a1aa22510`、loader=`31f72bec1f2adecd7e7914c191e2f442515544dd9eda802df928fb77c405dd49`；记录core import实际路径/版本/hash。C独立QA状态按实际报告列明。
### T02 准备冻结输入与状态适配（依赖T01）

- files：新增staged_production_inputs.py及其测试；raw_market_provider.py/raw_market_inputs.py及已有两套测试。
- 接口：`prepare_staged_inputs(config_path, output_dir) -> prepared_manifest_path`，配置固定两窗、四候选及全量绝对路径和预期SHA；输出目录必须不存在。
- 复用load_frozen_signal_parquet、build_signal_ranking、load_corporate_action_snapshot和CnnRawMarketDataProvider；不能另写一套Parquet信号解释、费用公式或CA loader。
- 为run_staged_window增加可选`prepared_inputs`；其中信号行、实际文件SHA、内容SHA、ranking、coverage、fee_table来自一次准备。使用前核窗口/来源/信号SHA一致，无prepared参数时保留现有直接读取路径。
- provider增加`history_bars=max(adv_window,sigma_window+1)`，默认兼容；执行配置这里明确21。allow_empty_window仅用于经来源覆盖解释的无行情窗口；源文件不存在或坏schema独立记问题，不能广泛吞掉ValueError。
- 验收：错SHA/重复键/跨窗输入/伪布尔均失败；缺SDK日只影响该键授权；停牌与全窗空行情可披露后继续；raw价格范围/量额单位原校验保持。准备缓存落本地不可变Parquet及摘要，允许新进程复用而不重读Z。
### T03 显式费用与历史数量来源（依赖T02）

- files：staged_production_inputs.py、staged_candidate_runner.py及接线测试；quantity_rules.py/historical_costs.py保持复用。
- 配置CostConfig：commission_rate_buy/sell=.0002、min_commission=5、stamp_tax_rate=.001、transfer_fee_rate=.00002、impact_coefficient=1、adv_window=20、sigma_window=20、sigma_clip=[.005,.08]、p_cap=.10、spread_floor=.0002、slip_max=.05、missing_volume_policy='warn'。
- resolver实际签名`(execution_date, code)->CostConfig`，用`resolve_historical_costs(execution_date=day, market='SSE_A'或'SZSE_A', commission=cost)`；按.SH/.SZ且经证券类型核查配置，未知不猜。
- 修正_freeze_fees：只冻结anchor之后可能实际执行的日历日；anchor无订单不调用历史函数；若core意外在anchor请求费用，明确契约错误，不填2021费率冒充2020来源。
- quantity配置每个显式代码归入已核历史板别：科创(200,1,100000)、沪深主板(100,100,1000000)、创业板限价(100,100,300000)。用MappingQuantityRuleResolver的逐完整代码键，避免宽前缀重叠；未知代码不默认主板。
- 研究配置支持区间明确冻结为2021-01-01至2022-01-06，作为本次已核适用范围而非声称制度初始生效日；source_id关联官方URL、文件hash、条文/版本、更正文件。创业板精确首次起效日未闭合不影响2021已施行证据的窄范围使用。
- runner新增`quantity_rule_resolver: Callable[[date,str],QuantityRule]`并透传strategy；策略当前传信号日，runner适配为下一执行日查询，并记录两日，anchor不会虚假查询。无下一执行日的BUY应已被边界拦截。
- 验收：科创100拒/200及201规则合法，主板122整余额卖出合法、创业30万上限、未知代码拒绝；真实申报量逐单绑定规则。部分成交可少于min，不把合法部分成交误判为非法新申报；core全局lot100保守取量另披露，不宣称逐板最优取量。
### T04 CA与真实observer闭环（依赖T02、T03）

- files：staged_candidate_runner.py及其接线测试；C内部两文件首轮保持冻结。
- 新增参数`corporate_action_snapshot: CorporateActionSnapshot | None`；旧corporate_action_provider直接调用仍拒绝。整合输入必须给snapshot与period_id，严格标志由显式exploration/strict模式确定。
- 构造`ctx(snapshot, period_id=window_id, reset_anchor=window.anchor_date, empty_reset=True, strict_tax=False, tax_policy=config.tax_policy, delegate=recorder, window_end=window.execution_calendar[-1], calendar_sha256=calendar_sha)`。
- core只接`observer=ctx, account_actions_provider=ctx.account_actions_for_day`；recorder内部继续送bridge。ctx的delegate协议允许recorder，不必把它改成只能接bridge。
- try/finally必须包住core及后续结果写盘；保存evidence、运行状态、异常类/原因、最后core事件、已收到的updates/registry轨迹、实际日历身份；失败窗mechanical_status=INCOMPLETE，不能沿用PASS默认。
- `StagedWindowOutcome.mechanical_status`由当前Literal['PASS']扩为PASS/INCOMPLETE/FAILED；真实中断可写失败manifest而不构造不存在的EvaluationResult。ctx.evidence中的descriptor未知与实际_issues都入审计，不能只看ctx.status判断完整。
- 验收：登记后卖光仍付现、零登记无幽灵、送转T只用一次、未知税探索继续且资格false、严格税仅正暴露阻断；缺阶段/非整数/同日record-ex保留中断，不补日期/不floor/不伪造账。
### T05 CLI与八窗调度（依赖T04）

- files：staged_production_inputs.py、staged_candidate_runner.py；新增输入模块只提供准备/批量运行两个模式，不新增另一套runner。
- 新接口`run_prepared_windows(prepared_manifest_path, run_root) -> summary_path`；外循环W1/W2、内循环固定四策略，各次新建可变对象，共享只读输入。单窗异常保存后继续其余七窗，汇总不隐藏失败窗。
- runner.main新增`--input-config`和`--research-mode exploration|strict`，从配置绑定market/CA/quantity/historical fees后调用run_staged_window；保留现有参数并逐项核对配置，冲突直接拒绝，不能默默覆盖。
- 验收：旧CLI最后NotImplementedError被真实接线替代；空输出目录独占；四候选的信号/日历/行情/费用/规则输入hash相同而策略hash不同，W1/W2资金与record权益不跨窗。
### T06 审计闭环与独立验收（依赖T05）

- files：runner的输出函数、新输入模块汇总及接线测试；仅当现有rejection_log不足以解释机会缺失时，小增strategy结构化decision_log，不改决策条件。
- 原有manifest/daily_account/decisions_orders_fills/execution_updates/registry_transitions/daily_registry/order_results/strategy_rejections/market_coverage/actual_fee_usage/rank_summary/episode_summary全部保留。
- 新增sources_manifest、state_mapping_evidence、quantity_rule_usage、corporate_action_evidence、opportunity_coverage、summary；记录所有输出文件SHA到独立产物清单，不自hash循环。
- 验收：每日完整Top5原排名/买资格、持仓退出需求、缺单原因、拒单原因、未用槽、锁仓及buffer残留可追溯；没有交易不能自动算覆盖通过。每个回调后及每日检查正持股<=10、active_slots<=5和资金/权益一致性。
- 主收益使用anchor资金至E净值，沪深300用anchor close至E close；buffer独立。汇总每窗数值比较与资格分别列，主比较S2-B1、次比较S1-S2/C70-B1，不依结果挑选或调参。

## CLI：已存在与拟新增必须分清

- B现有参数：`--signal-parquet --expected-sha256 --source-id --checkpoint-sha256 --anchor-date --evaluation-end --execution-calendar --policy --output-dir --initial-capital --tax-policy --tick-size --lot-size`。现有CLI读完信号/日历后抛NotImplementedError，目前直接执行不能产生研究结果。
- T02须生成外部`integration_inputs.json`，不是修改预注册。顶层字段固定：schema_version、preregistration_path/sha256、calendar_csv_path/sha256、raw_market_root、index_path/sha256、state_path/sha256、gap_index_path、state_source_root、state_audit_path、ca_root/manifest_path/manifest_sha256、quantity_sources、cost_config、windows、policies、initial_capital、strict_tax、tax_policy。
- `windows.W1/W2`各含source_id、signal_path/sha256、signal_metadata_path、checkpoint_path/sha256、config_sha256、anchor、evaluation_end、buffer_dates；值逐项取上文明确常量。source_id分别固定W1_F4_full_CPU_v1/W2_F4_full_CPU_v1，不能运行时随意命名掩盖来源。
- `quantity_sources`逐板包含minimum/step/maximum、supported_from/supported_through、source_id、official_url、artifact_path/sha256、corrections_path/sha256和显式code列表；列表从已验证证券类型元数据形成，不能把未知类型默认为主板。
- `cost_config`采用T03全部显式值；policies固定四项；initial_capital=1000000；strict_tax=false；tax_policy=cash_dividend_20pct_stress。运行manifest同时保存完整配置和实测SHA。
- 以下是T05完成后才成立的真实调用设计，本轮没有执行；`D:/code/cnn_full_20260905/cnn-staged-integration-20261027`是主会话未来整合树约定路径，当前未创建。若主会话选择其他目录，仅调整I变量。
```powershell
$T = 'C:/Users/yanwen/AppData/Local/Temp/opencode'
$I = 'D:/code/cnn_full_20260905/cnn-staged-integration-20261027'
$P = "$T/staged_production_integration_plan_20261027"
$PY = 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe'
# 在I工作目录执行；只读复用解释器，不uv sync、不改共享依赖。
& $PY -m backtest.cnn_adapter.staged_production_inputs --config "$P/integration_inputs.json" --prepare-dir "$T/staged_prepared_inputs_20261027_v1" --prepare-only
& $PY -m backtest.cnn_adapter.staged_production_inputs --prepared-manifest "$T/staged_prepared_inputs_20261027_v1/manifest.json" --run-root "$T/staged_mechanical_results_20261027_v1" --research-mode exploration
```
- 单窗复现CLI示例（同样仅为接线完成后的命令，输出目录须不存在）：
```powershell
& $PY -m backtest.cnn_adapter.staged_candidate_runner --input-config "$P/integration_inputs.json" --research-mode exploration --signal-parquet "$T/three_day_signals/W1_F4_full_CPU_v1/signals.parquet" --expected-sha256 99198e069157e570ffc2fa83818d1738a4abe468a5d39c76fca30dfba5d762e9 --source-id W1_F4_full_CPU_v1 --checkpoint-sha256 a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde --anchor-date 2020-12-31 --evaluation-end 2021-06-30 --execution-calendar "$T/staged_prepared_inputs_20261027_v1/calendar_W1.txt" --policy B1 --output-dir "$T/staged_mechanical_single_W1_B1_20261027_v1" --initial-capital 1000000 --tax-policy cash_dividend_20pct_stress --tick-size .01 --lot-size 100
```
- 不加checkpoint模型加载到回测热路径；预检从metadata路径核实际权重字节SHA，并绑定已存在严格加载物证。权重不存在不能只接受CLI手填hash；该门保留未核实，严格放行仍失败。

## 哪些未知逐暴露INCOMPLETE，哪些必须中断

|情形|机械研究处理与声明边界|
|---|---|
|现金/送转实际税、公告known_at、实施进度含义未核|保留原始进度与unknown；可在显式探索模式下按loader机械事件运行，实际暴露逐项列出，禁止说官方已实施或实际税后已达标|
|未持有、零登记的无关CA缺税/日期|全市场coverage仍披露；不因无关事件全局拒单，零权益不创建幽灵|
|持有现金额None、探索strict_tax=False|C原行为记cash_amount_unknown且不补零，机械账可继续但现金权益不完整；结果标INCOMPLETE，不能把净值当完整经济收益|
|配股不认购、权利价值与注销未知|保留coverage及持仓相关暴露；不创建认购现金，不宣称权益完整|
|实际正登记缺record/ex/pay/listing、同日record/ex、非整数送转、登记后股数变化不支持|保留C中断；finally落证，当前窗INCOMPLETE，继续其余独立窗。不能为了八个完整净值编造日期、舍入或现金；八个尝试都有审计结果不等于八个都完成|
|某键ST/参考/限价未知或实际订单缺行情|仅该键/订单拒绝或锁定，保留未成交/退出需求与机会分母；原榜不变，实际需求受影响则窗口INCOMPLETE|
|已解释的上市前/退市后/暂停缺口|宇宙覆盖报告分类，不能按所有codes×日期的missing总数把production一律BLOCKED；若真实持仓或意图命中，升级为暴露问题|
|历史短样本/ADV或sigma缺失|沿冻结warn路径机械spread-only可继续，警告与实际fill绑定，滑点完整性INCOMPLETE；不能换参数让其“通过”|
|文件摘要不符、重复身份、来源冲突、账户/registry不一致、持仓>10、槽>5|当前输入/窗硬失败，停止该窗并保存证据；不能按普通未知忽略。共享输入完整性失败则不启动八窗|
- 调整现有_market_coverage与acceptance：全宇宙覆盖只做输入报告；另以完整Top5机会、实际意图、真实持仓/登记权益建立exposure层。机械完成、输入覆盖、生产资格分别计算，禁止因全表缺口全局封死或因为跑完就写生产PASS。
- 现有固定failures列表改为证据驱动：数量/CA接入/日历/权重/来源门仅在对应核验物证满足后撤销；share_tax_unknown和actual_after_tax_target_eligible=false仍保留，不能为去掉BLOCKED一键清空全部门。
- 即使数值满足>=0且>沪深300，实际税未知、CA实施与PIT未知、权利/舍入完整性、执行来源时间可得性未证、真实滑点/容量降级、残留锁仓/权益未对账任一未闭合，都不能声称原实际税后目标已达成。
- 2021仅历史探索；2026-01至08是已使用样本，不作新规则验收。干净前瞻证据仍须2026-09之后；不得把本轮八窗改称前瞻成功。

## 真实读取规模与四策略复用

- 本轮实读限制：源码/小型证据；canonical和两信号仅footer/schema与2行batch；Z盘只检查000001.SZ一个文件footer和2行，未遍历Z、未读指数/SQLite、未跑账户或收益。
- 实测000001.SZ源文件128947字节、3336行、1个row group、无is_trading列。按4424码同体积粗外推约544MiB压缩输入，仅作量级，不能代替全目录实测。
- 现有raw读取只下推code和execution_end上界，无日期下界；单row-group源即便只保留21条历史也可能读取此前多年。W1/W2各自重复准备会读两遍；四策略各自新provider会进一步重复。
- T02一次按代码读到2022-01-06，保留W1所需21条历史至W2 buffer末日；对每窗生成独立provider视图、按截止日返回历史。W1绝不能看到W2未来bar；prepare拥有未来数据不等于运行接口可泄露未来。
- 外推读取前2022历史约数百万至近千万行八列，实际受上市时间、row-group裁剪和代码覆盖影响；不提供未经测量的分钟级工时承诺。准备manifest记录真实文件数/读字节/row-group/扫描行/保留行/耗时。
- 两信号合计1016968行、10126002字节（约9.66MiB）只加载/hash一次；当前Python逐行dict展开显著大于压缩体积，四策略共享排名和信号，不做四份深拷贝。
- 状态80.4MB压缩、1033541行一次核hash并流式筛选；CA约7.8MB/8740分红+12配股一次加载；gap独立小表。来源审计大文件的完整重验可引用同冻结版本现有报告，新增或不符来源才定向重验。
- 两窗codes×execution_days上界4424×251=1110424键，四候选重复全覆盖达4441696条；只保存一份共同coverage及其SHA，各候选另保存实际暴露子集和共同文件引用。
- 合并日历247天加最早窗口21根历史，raw保留上界约1185632行，数值列通常百MB量级；若全展开dict/MarketBar/状态证据，可能达数百MB至数GB。按窗顺序运行、批次写证据、共享不可变缓存，不能把“9.66MiB信号”当作总内存估计。
- 不为了省读只加载事后成交代码。首次可完整读固定宇宙一次；若后续优化为按需缓存，仍须逐日记录完整Top5买机会和全部实际退出/权益需求，且不能改冻结排名。

## 重复检测结论与执行验证边界

- 已找到可复用：raw_market_inputs严格单位/价格校验、raw_market_provider状态透传、historical_costs日期费率、runner.py真实core调用与主/buffer分段、B的账/订单/registry输出、C的权益/observer链。
- 旧audit_walkforward_execution.py的账户序列化/差分思想可参考，但其入口旧参数、硬编码费用、标签端点检查与4GB源hash不适合本任务；不复制或调用该WIP入口。
- 后续整合测试最小反例：anchor不查2020费用；21根σ输入；CSV派生日历；单键未知不全局封死；core→ctx→recorder→bridge事件不重不漏；CA中断finally；八窗独立reset；E-1在E合法与E后BUY全禁。
- 数量反例与C自身用例直接复用已移植测试；新增只覆盖真实接线，不镜像实现。独立审查须针对整合冻结hash，既有307/18/87及C owner结果不能冒充本轮整合测试。
- 计划完成状态为PLANNED。整合执行、测试及八窗数值结果均未产生；任何资格结论必须来自后续实际物证，不能从本计划推导。
