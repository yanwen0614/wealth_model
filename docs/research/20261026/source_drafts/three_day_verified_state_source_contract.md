# Verified State 来源契约（只读核查）

核查日期：2026-10-26。范围：不修改生产代码，不运行策略/绩效，不调用 API，不扩展数据扫描。SQLite 查询限定 `mode=ro` + `PRAGMA query_only=ON`；只检查指定源码、表级metadata、两个证券的有限行和事件邻近raw bars。

## 决策结论

**状态缺行目前不得解释为正常，执行放行 BLOCKED。** `history_status` 是稀疏状态/异常行数据且包含 `touch` 行；仅凭两只股票某个交易日没有事件行，不能证明对应代码、日期、字段均成功查询并完整落库。不得把缺失值填成 False，不得按数据库 `是否退市风险警示` 列名过滤退市风险。

### 已有三条源码线索

1. `D:/code/quant/src/core/data_reader/base.py` 的 `get_history_status` 文档明确称其读取“稀疏事件行（含 touch 确认行）”；并明确 touch 过滤需由消费端识别 `记录类型`，不能用四个状态标志作谓词。这说明普通无异常日可能不落行，但文档本身未证明逐 code/date 查询覆盖。
2. `D:/code/quant/src/core/data_fetcher/history_status.py` 映射 `IS_XR_SEC`、`IS_WD_SEC` 到中文列的语义存在已知手册冲突；Fetcher 只保留异常行且字段清洗可能把缺失变0。故这些列当前不能直接作为 `normal=False/True` 证据或退市过滤依据。
3. `D:/code/quant/src/core/data_storage/history_status_storage.py` 与 `history_status_update_pipeline.py` 是需要继续核实的实际写入/水位路径。现有 SQLite 有 metadata/touch 机制，但尚未证明 touch 保存按 code 的 requested start/end、接口成功、返回完整/空结果及首次查询2014覆盖边界；在证实前，不允许从缺行推正常。

## 目前可知状态与严格未知

- **可读原始状态**：`history_status` 可查询到的逐代码、逐交易日显式状态行；`记录类型='touch'` 属覆盖/刷新语义候选，必须从写入代码确认。原始0/1只保留原值，不沿用存在语义冲突的中文标签作业务解释。
- **不能推断**：某代码某日缺行=正常、未停牌、非ST、无除权、可交易；某个全表 metadata 更新时间=所有代码/区间已成功；某次 touch=从上市/2014起历史全覆盖；当前字段默认0=供应商明确返回0。
- **当前决策**：若没有能绑定 `code + requested interval + successful completion + source response coverage` 的证据，缺行仍是 `unknown`。不补默认状态，不改写市场历史。

## 必须确认的覆盖契约

继续只读审查 Fetcher→Storage→Pipeline/Watermark，确认是否保存：首次请求起点、结束点、代码、请求/返回日期范围、成功/失败、空结果成功与异常区别、touch 的精确定义、增量边界重叠/回填、metadata 粒度及提交时点。若存储只有稀疏异常行与全表/表级 `last_updated`，则无法逐代码证明无行是成功查询后的正常。

## 源码核实后的覆盖结论（2026-10-26）

Fetcher 中**实现意图**比单纯事件表更强：`history_status.py:30-34` 注释称 API 对每只在市股票每天返回完整状态行，无事件行由 `abnormal_mask` 过滤；`:174-180` 将“有原始返回、字段完整且异常过滤后为空”视为确认无事件，返回空DataFrame；`:194-211` 将被过滤窗口尾行涨跌停幅度放在 `attrs`。`:162-171` 的异常掩码包含ST、XR、WD、停牌、非标准涨幅。该契约若成立，可使**一次实际完整响应**中的窗口缺行代表未命中异常掩码。

但这只是代码注释/处理意图，不等于库中任何缺行都有该证书。单码 `fetch_single` 空输入或处理后为空返回 `None`（`:82-90`），不写touch；批量 `fetch_batch` 则只对明确返回的code运行处理，空 DataFrame 才能被保留。`BaseFetcher.retryable_batch_fetch` 对响应dict缺席的code静默丢弃（`:312-314, 344-354`），HistoryStatusPipeline把“缺key=真失败”写进自己的契约；因此**缺 key 与明确空结果不可混为一谈**。不调用供应商接口，本核查不能独立证明SDK空key/空DF的真实响应含义及服务端区间完整性。

Storage `history_status_storage.py:47-52` 只存异常行；touch行是`(证券代码,end_date,记录类型='touch')`，五标志置0、真实API尾行涨跌停幅度写入，旧touch按标记域每码仅留最新（`touch_confirm_mixin.py:65-80,105-150`）。**没有 begin_date、请求ID、成功状态、原始行数/日期范围或区间哈希**。普通事件行保留逐日异常日期，但事件行之外没有连续覆盖记录；`save_touch_rows` 对同日任意已有行跳过且只给本次确认无事件码写，故事件码即使查询成功也不会因此得到期末touch证明。

Watermark/增量路径也不补足证据：`HistoryStatusUpdatePipeline` 开启 `_use_per_stock_dates=True`、`_skip_tracker_record=True`，DB MAX(交易日期) 作逐码水位；`DBMetadataIncrementalStrategy` 有数据时返回MAX+1，无逐码日期时回退表metadata。`DataReader.get_metadata` 已把表级 `last_updated` 转为次日日期（`data_reader/base.py:794-825`），策略随后又对返回日期加一天（`db_metadata_strategy.py:78-88`）。所以无逐码历史行的新代码可能从近期表级墙上时钟附近开始，而不是2014；注册表虽配置default 20140101，但当metadata存在时该default不会用到。另批量 per-code 无水位分支使用基类 `DEFAULT_BEGIN_DATE=20130101`（管线 `base.py:682-688`），与Fetcher文档/单码默认20140101不一致；显式begin_date也能改变范围。实际请求起点未写入行或metadata，touch仅保留end_date。以上都使“表有最新metadata/touch→2014以来连续覆盖”不能成立。

此外，`HistoryStatusUpdatePipeline.run_now(code=...)` 走 `fetch_single` + `_execute_with_timing`，Fetcher空数据返回None，框架将空结果作success/0行但不调用`save_touch_rows`（`history_status_update_pipeline.py:120-130`; `base.py:404-408`）。单码查询的TaskResult成功也不是空区间覆盖持久证明。只有批量路径显式返回并收集空DataFrame，才进入touch机制；响应缺key不会成为no-event touch。

表级 `metadata` schema 只有 `table_name,last_updated,record_count`；更新仅刷新总行数/墙上时间，不记录 code 或日期区间。实库该表 `history_status` 记录为 `last_updated=2026-10-03 18:27:55.260017, record_count=703606`，不能据此推断任一码的H1覆盖。history_status增量路径跳过 update_tracker，不能用 tracker 的批任务状态回填该缺口。

## 两代码 2021H1 只读小样（Z盘dev库）

SQLite `mode=ro`/`query_only`，只查两代码和有限行。表结构确认记录类型、日期、四个状态、限幅；不查询/扫描全表事件：

|代码|全表逐码行数/含touch|逐码最早真实行|2021H1事件行|最新touch|
|---|---:|---|---|---|
|000001.SZ|13 / 1|2014-07-15|2021-05-14，状态(0,0,1,0)|2026-09-30，flags全0，涨跌幅0.1/0.1|
|600519.SH|13 / 1|2019-06-28|2021-06-25，状态(0,0,1,0)|2026-09-30，flags全0，涨跌幅0.1/0.1|

两条H1行恰与DB现金除息事件同日（000001 2021-05-14、600519 2021-06-25）；它们的 `是否退市风险警示=1` 因此再次证明不可按中文列名做退市风险过滤。表中打印的0/1是落库值，不证明0一定来自API原始显式0（Fetcher曾对NULL填0）。H1其余交易日无行，但touch在五年后，仅代表最新一次“确认无事件”写入候选；由于touch没有起点字段，不能给2021H1缺行补证。小样仅证明存储形态，不证明这两代码当时API请求完整。

### 明确允许与禁止的缺行推断

- **可条件性推正常**：只有取得该code、明确`begin_date/end_date`、成功响应且SDK原始响应确认该区间所有应有交易日均被枚举的不可变请求证据；有该请求的成功完成记录，并能证明原始每日行完整后通过已核验的字段/掩码规则。此时仅对被完整覆盖的交易日与被验证字段，事件表无真实异常行可解读为“查询返回未命中异常条件”，不能超出请求区间、市场交易日或API定义。
- **当前库不能条件满足**：metadata为表级；touch只有 code+end_date 且仅保留latest；水位无请求区间/响应成功载荷；正常日不落库；某些请求起点可能显式覆盖/增量边界不同；表没有“每日完整状态快照”。所以两个样本乃至其他无行日目前全部为 `unknown`，不得改市场历史或默认False。
- **touch窄义**：在可信执行日志另能证明该次调用所用begin/end和原始响应成功时，该touch可作“这个code在该次请求中窗口过滤结果为空”的完成证据；单独的DB touch行只能证明系统曾以某end_date写入空事件确认及其限幅payload，不能证明requested start、API所有日期覆盖或历史完整性。

## VerifiedState 最小适配边界

`CnnRawMarketDataProvider` (`backtest/cnn_adapter/raw_market_provider.py:60-76`) 对每个 `(code,date)` 独立读取状态：必须显式传 `market_state in {trading,suspended}`、`st_known is True`、`reference_known is True`、`limit_known is True`，缺字段就保持 unknown；`corporate_action_dates` 单独标记 `corporate_action_reference_required`。因此状态适配器不得把“未找到history_status行”转成False或自然常态。

raw parquet 的 `raw_market_inputs.py:18-19,130-141` 只将可选 `is_trading` 映射市场状态，原始记录的ST/reference默认unknown。Z盘两只源文件 schema 只含 `code,kline_time,OHLC,volume,amount`，没有 `is_trading`。可观察到同日存在、OHLC完整、真实股数>0的raw bar，可证明有成交记录并支撑当日“存在交易”；但无raw行/0成交/字段缺失不能单独区分停牌、无成交或行情缺漏。当前状态源并未形成可全区间验证的逐日 market_state。

### 日前收、reference 与 limit 能力

- 在**已证实为实际交易、日期非ex/除权日、raw前一有效交易日close可靠、且无跨日停牌/缺价不确定**时，前一实际交易日raw close是普通交易日参考价最小原始输入；还必须绑定该日有效板块、ST及交易规则版本，才可标 `reference_known=True`。代码缺口/长停牌恢复、公司行动、IPO上市特殊阶段不靠简单 `previous close` 兜底。
- 2021+规则假设范围可冻结为：普通主板10%，300创业板及688科创板20%，主板ST 5%；20%板块ST不自动降至5%。精确交易日的板块/上市状态/ST须有逐日可追溯来源；上市首日/前若干日、重新上市及特殊豁免规则不完整时，该日 `limit_known=False`、拒单。限价还需真实价格tick/交易所取整规则；不能只靠比例近似。
- `history_status` 真实异常行中非标准涨跌幅可提供该日事件值；正常行被过滤后标准10/20/5%不落真实行。touch只带本次窗口尾端的真实涨跌幅，不是历史逐日limit表。故不能用现存touch的0.1回填其余日期。须先有覆盖证书，再按规则推正常限幅；若历史行命中非标准幅度、除权或特殊上市规则，使用已验证当日幅度/官方reference，否则unknown拒单。
- Fetcher `COLUMN_MAPPING` 含 `LAST_CLOSE_PRICE`→`昨收价`（`history_status.py:36-48`），但ORM `HistoryStatus` 没有`昨收价`列（`database/models/factor.py:32-48`），且 `DatabaseStorage._prepare_data` 只保留ORM列（`database_storage.py:97-111`）；所以即使接口回了昨收，它也不会存进当前表。表中无官方除权参考价证据。
- ex-date/未识别公司行动：有独立、无前视的事件日输入时，将该日列为 `reference_unknown` 并拒该证券当日开盘所有新订单；既有仓位按raw bar盯市，已确认现金/股份权益照ledger记，不提前筛选未来日期。可将已验证的原始 `IS_XR_SEC` 或 backward factor 生效日跳变作为**当日事件候选**，但先核准原字段语义/时间戳与因子版本；候选误报只扩大该日拒单，应记录 coverage/容量影响。不可使用后续因子变化回填信号日。
- 配股固定不认购、不缴款：原持股数量不变、raw价格自然承受稀释；事件日reference不可确认时仅拒该日订单。配股权转让/注销/价值另列unknown，不强制实现主动认购或缴款流程，也不把权利价值当现金。

### 对0/1、touch与数据血缘的解释

Fetcher `_process_status_result` 将四标志 `numeric.fillna(0).astype(int)`（`history_status.py:157-160`）；DB无法区分原始API明确0与NULL/缺列后补0。`记录类型='touch'` 四标志更是storage明文硬编码0（`history_status_storage.py:12-23`），绝不可作为ST=false、未停牌或no-event字段。真实行上的某标志1可作为正向异常线索（字段语义仍需供应商核定）；同一行0不能作为权威否定。`是否暂停上市`是手工维护列，不来自API，当前也没有逐码完整历史证据。

历史ST最小可靠读法：仅在经验证真实API行、原始字段存在且语义确认时，把 `IS_ST_SEC=1` 作为正向ST；要确认非ST必须有同code/date完整状态查询证书，不能靠0或无行。历史风险警示不是本状态适配器可可靠提供的known字段；不从 `IS_WD_SEC` 映射列产生delisted/risk filter。

## 精确GO/NO-GO条件

- **可GO的窄场景**：逐日raw行具有正真实成交量与完整OHLC；状态适配输入对该code/date均可验证；市场板块及历史ST已知；前收来自最近有效raw交易且中间交易日/公司行动已排除；限价规则及tick适用且无IPO/重上市等例外；无事件时可据前收和规则算reference/limit。事件/除权日只有官方ref、限价可信且执行时点可用才放行，否则当日该代码订单拒绝而持仓保留。可对明确符合的稀疏子集或具体日期作mechanical replay验证，按coverage报告。
- **当前源整体 NO-GO**：`history_status`现存数据不保存逐code请求start/end、daily response completeness及每次成功状态；故H1稀疏缺行和最新touch不足以使 `st_known/market_state_known/reference_known/limit_state_known` 全字段known。当前不能将`verified_states={}`长期使用，也不能凭此源自动生成全面verified_states后宣称覆盖全样本。没有覆盖证据则unknown，执行层拒单，而非默认False。
- **不能扩大声明**：两只代码小样没有证明目标证券池覆盖；touch日期上的0.1/0.1仅限该touch日API payload。2021至今IPO/暂停上市/历史板块ST和全部reference限价例外没有在这次只读样本范围完整验证。

## 最小合成与两码实样验证

### 必需合成状态矩阵

1. 明确原始接口完整成功并枚举区间所有交易日，异常过滤空结果，且有请求区间/请求身份可回查：仅覆盖区间缺异常行→可给`no_abnormal_event`；区间外缺行仍unknown。
2. API缺code key、抛错、超时、日期列缺失、原始df为空，或无该code请求范围记录：缺行→unknown/failed，不能写normal。
3. touch只有`code,end_date`且start未知、或touch.flags全零：不可推状态否定；touch的high/low仅可绑定该touch end_date。
4. 真实状态行由缺列/NULL经fillna成为0：对应否定状态仍unknown；原字段1在映射语义可核前仅标`raw_positive_candidate`。
5. raw行有效且量>0、相邻有效raw收盘价可取、完整来源确认该日非事件，市场/ST/规则均known：验证reference=前收、普通板块limit按版本规则与tick取整；缺IPO/特殊上市规则或跨停牌参考语义→unknown/拒单。
6. ex-date命中dividend事件或经核验的factor变化，但官方reference缺失：只将该code/ex-date标`reference_unknown`并拒绝当日开盘订单；上一交易日信号与持仓不得回溯删除，资产按raw和已确认应收/股份权益记账。

### 两码实样事实与有限结论

|代码/事件|状态行|原始K线(事件前收→事件日OHLC)|因子事件|结论|
|---|---|---|---|---|
|000001.SZ，2021-05-14现金0.18元/股|record05-13/ex/pay05-14；状态`ST=0, XR=0, WD=1, suspension=0`|05-13 close23.07；05-14 O/H/L/C 23.14/23.43/22.60/23.32|因子ex行68.702731，前一因子日2020-05-28为68.166689|WD=1与现金除息同日，不可作退市标记；官方ref须unknown，拒当日订单|
|600519.SH，2021-06-25现金19.293元/股|record06-24/ex/pay06-25；状态`ST=0, XR=0, WD=1, suspension=0`|06-24 close2068.05；06-25 O/H/L/C 2049.96/2109.00/2042.60/2092.00|因子ex行7.473751，前一因子日2020-06-24为7.404039|同样WD=1与派息同日；factor变化可作事件候选，不证明完整覆盖或官方ref|

本轮SQL均只读取 `metadata` 单表指定行、两个code、窗口限定行或每码聚合/MAX TOUCH；没有全表扫描，也未调用API。raw parquet仅读两个代码的schema与指定事件附近少量行；尚未运行策略或市场模拟。

### known 状态及来源等级

|状态|目前可读取来源|何时可标known|当前库结论|
|---|---|---|---|
|market_state|raw行OHLC/volume；history_status异常停牌标志|正成交raw行可标当日有交易；停牌要可靠逐日显式标志或覆盖完备的停牌源；缺raw行不自动是停牌|部分raw交易日可观察；完整逐日状态仍unknown|
|st_state|Fetcher映射`IS_ST_SEC`→记录`是否ST`|该code/date有已核验真实状态行，或完整请求覆盖证书可证明未命中ST|稀疏H1无行不能推非ST；中文WD列禁用于退市筛选|
|reference|官方除权参考价；无公司行动时前一有效raw close|官方数据/版本明确，或已证非事件正常交易日且前收链完整|history_status未保留昨收；一般可从raw链重建，事件日不能|
|limit state|官方涨跌停价/参考价；或有效板块+ST+规则版本+tick推导|以上信息同日均verified，且排除IPO/暂停上市等例外|当前无历史逐日完整规则证据；非标准事件行部分有值，普通标准需条件推导|

`IS_XR_SEC`映射入`是否除权除息`、`IS_WD_SEC`映射入`是否退市风险警示`，但历史SDK文档冲突及样本与现金除息重合，后者不能称退市风险事实；禁止拿它做退市过滤。退市/风险警示如非本次验证目标，不补造字段。

## 最小 VerifiedState 记录格式与来源血缘

当前provider接受普通mapping，但它本身不会验证证据。适配侧至少须为每个 `(instrument_id,trading_date)` 输出以下值与证据，不允许只给裸boolean：

```text
VerifiedStateEvidence {
  instrument_id, trading_date,
  market_state, market_state_known, market_source, market_row_hash,
  st_state, st_known, st_source, st_row_id, field_semantics_version,
  reference_price, reference_known, reference_source, prior_raw_date,
  limit_up_price, limit_down_price, limit_known, rule_version, board, st_rate,
  corporate_action_candidate, action_source_ids, action_detection_method,
  coverage_certificate_id, confidence, unknown_reasons[]
}
```

`coverage_certificate_id`只有在可追溯的 `(code, requested_start, requested_end, request success, response coverage contract, pipeline path)` 真实证据存在时才填。当前SQLite `history_status` 表、单条touch行和metadata均不能生成此certificate；不通过人工默认或后来相邻日期行继承。真正需要新增/找到的最小证据是**每码每次查询的不可变覆盖清单**（不要求保留全量正常状态行），或数据源已持久化、可核验的逐日完整状态快照。至少包含requested区间、交易日数/响应日期覆盖、完整成功状态、query/source版本及空结果语义。没有它，不可追认历史空白为正常。

因子跳变适合作为保守事件候选而非公司行动事实真值：需要同代码两个相邻有效因子及因子快照版本；日期d有生效因子行且数值变化，则仅将d加入 `corporate_action_candidate`，无official reference时当天订单拒绝；不把候选事件扩展到d前日期。factor缺值/更新滞后也不能证明无行动，因此要和dividend事件表/数据覆盖比较；不确定的事件检测覆盖仍是NO-GO。

## 历史规则推导条件

若上述状态覆盖可证，对非事件普通交易日可以用最近的**实际交易raw close**作参考输入，并结合交易日d有效规则计算涨跌停。要求当前证券日有真实成交raw bar、昨日/最近成交raw close合法、交易日历和停牌链无缺、无除权/配股/派息或复牌参考价例外、板块和ST有效值已verified、适用规则版本/tick已核。普通主板10%、主板ST5%、300/688板块20%只在限定期间与类别内应用；上市初期/IPO/重新上市/特殊制度日期、历史板块规则缺证据时unknown拒单。前收只是输入，不自动证明limit_known。

公司行动识别优先用现有 `dividend.ex-date`/已校准XR原始值/`backward_factor`有效日变化形成执行日候选联合门；配股虽固定不参与，若无法识别除权日则仍有reference gate遗漏风险。使用ex-date时，事件资料只能在执行日启用，不允许信号日按未来事件过滤；事件版本只可用事前发布记录（当前历史修订版本缺失，限制事件相关绩效因果声明）。
