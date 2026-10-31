# 2025 本地输入与生产桥接：Sol 独立只读诊断

结论：现装 core 可用；local_hdf 并非 builder 的类型障碍。当前全年度 A/B 入口只有预检和桥接，尚无生产账户调用；稀疏状态、来源时点和公司行动亦未闭合。建议只实施一个“全榜保留、受限本地状态条件执行”的研究分支，先交付小样本接线与明确 INCOMPLETE 契约，不能承诺 22:00 前获得用户目标达标账本。

本次所有主动文件写入位于本目录。未写 candidate、主区、整合树、quant 或 Z 源库；未安装依赖、调用 SDK、控制 Luna 会话或运行年度回测。主区 Python 使用 -B；只读导入整合树。四日测试使用真实行情与人工订单，分红为人工夹具，不是2025模型绩效。

## 证据身份与活跃目录

- 观察到 `delivery_summary.json` 内容更新：首次读取 completed_utc=01:04，诊断执行时为03:45:20 UTC。旧 REPORT 的“未导出”已经落后。未将活跃目录判成冻结交付、未据瞬态差异判 owner QA 失败。
- diagnose.py 第二次执行前后，五个 manifest 的 size/mtime/SHA 一致；这仅为观察区间稳定性，不是排他冻结。具体值见 diagnostic.jsonl 最后一项。
- full190 manifest：190源文件、174码、40,796行、236日、268个缺代码日、candidate_only=true、qa_accepted=false、history_known_at=UNKNOWN。174×236−40,796=268；16个文件目标区间无行。summary 报 anchor_missing=0，未在本次全扫独立复核。
- raw_v2：172/174码、44,116行、complete=false；000040.SZ、000584.SZ 在候选和 `Z:/dev/kline/day/{code}.parquet` 指定路径均不存在。本次仅检查这两个源路径，不声称其他目录没有备份。
- CA manifest：359条 dividend、right_issue空列表、174码元数据。summary 报登记/除权/实施公告日期各缺229，派息缺231、红股上市缺355；不是359个已确认实施事件。源数据库哈希沿用导出材料，未重读/重算 Z 数据库。
- 本次实测 candidate_state SHA 与清单一致：53acb4976d50fbc17a4b518f0ef7451daece04e0c03c26d0937bb03878cc8498；000001.SZ raw SHA 亦匹配清单。读取状态12行，全部 row hash 通过，逐行 HDF hash 与 manifest 绑定一致；未重读HDF，未核SDK响应真实性。

## 真实解释器与 API

- 解释器 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe`，3.12.13；cwd主区，脚本显式将整合树置于 sys.path[0]，未改环境。
- core 从主区 `.venv/Lib/site-packages/backtest_core` 导入；`contracts/account_actions.py` 实际 import 成功。没有证据支持在该解释器中“模块缺失”；原报错的解释器/完整 traceback 未取得，不能断言它当时的具体原因。
- `engine/account_runner.py` SHA=aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00，与v12绑定一致。完整函数签名、导入路径和sys.path记录在 diagnostic.jsonl。
- `run_account_backtest_from_orders` 接收 execution_calendar、signal_dates、maintenance_dates、anchor_date、evaluation_end、strategy、market、observer、cost_config_resolver、account_actions_provider；没有 data_snapshot 参数。实际快照入口是 provider 的 verified_states 和 runner 的 corporate_action_snapshot，不应传一个未经定义的 data_snapshot 关键字。
- `MarketDataProvider.get_bar(code,date)->MarketBar|None`；get_history 返回截止日及之前的升序序列。MarketView 批量键需覆盖请求代码，无数据为空序列，禁止未来日期查询（contracts/protocols.py:36、152）。

## 状态与价格精确契约

- staged_production_inputs.py:100 要求11个小写业务字段，另需code/date/row_hash/source_file_rel/source_sha256/sha_origin/window。日期为date，market_code==code，trade_date_str==YYYYMMDD，键全表唯一；额外原始大写列可以保留。
- :71 canonical_row_hash：按 `_FIELDS` 固定插入序构建JSON，五个数值非NULL转float，None保留；ensure_ascii=False、allow_nan=False、separators=(',',':')，UTF-8后SHA256。四flag保留原字符串'0'/'1'/None；不能用 or ''、bool('0') 或把None变0。NaN不可哈希。
- :124 只检查 `source_audit[relative]==(sha,origin)`，不设origin白名单。本次直接传入local_hdf审计，真实builder成功；:220 `_source_lookup` 才只支持scope缓存/probe结果。诊断中的audit取样本行构造，再与独立manifest相互核对，不能当成独立源证书。
- :137 输出仍写 sdk_absolute_v1 和SDK语义；研究适配必须使用 local_hdf_absolute_v1 或另加完整来源说明，保留SDK形状原字段但不伪称取得SDK响应。无需改row hash算法。
- derive_execution_state :78：IS_SUSP_SEC 0/1→trading/suspended，其余unknown；IS_ST_SEC仅派生st_known，不返回ST值；reference_known仅检查PRECLOSE正有限。WD/XR原值留证，不推退市或分红。
- HIGH_LIMITED/LOW_LIMITED 是当日绝对价；需正有限且lower≤upper。limit_known另需同日raw.open正有限；limit_up/down按开盘与绝对边界比较并以Decimal分为单位。涨跌幅比例只留原值，不能重建绝对价；无涨跌幅限制日的0/NULL不能套10%默认值。
- raw_market_inputs.py:106：OHLC必须全有或全缺、为正有限且高低自洽；volume原始整数可被100整除，除100为股；amount除100000为元，VWAP需落在OHLC±0.01。原is_trading可NULL，不能靠有bar推可交易。
- raw_market_provider.py:84：按(code,当日)读取mapping，四known字段必须是实际bool True；market_state独立决定交易/停牌。absolute边界允许None，bool和非数拒绝、core再检正有限与顺序。未知mapping不授权执行；缺整个raw文件却在:65抛异常，不返回None。
- core contracts/market.py:74：缺任一OHLC拒绝可交易；reference_unknown在CA参考必需时才直接形成拒单。st_state_known只表达是否掌握ST状态，MarketBar不携带st_flag；策略若排除ST，必须另在收盘资格层明确判断st_flag=True并拒买。

## v12 能复用和不能复用的内容

- v12 states 样本包含market_state/st_known/reference_known/limit_known/limit_up/limit_down/绝对上下界；没有st_flag、listing_known、quantity_rule_known、corporate_action_known，更没有历史known_at证明。不能直接给新桥接器补这些true。
- v12 coverage汇总包含expected_count/missing_bar_count/unknown_count/rows/source_known/source_status；:378全代码×全日遍历，rows可保留需求子集，shared_path/shared_sha256绑定外置证据。W2计数570696/15620/16605是2021窗口，绝不能当2025覆盖。
- prepared manifest包含artifacts、core路径/hash、benchmark、config、actual_after_tax_target_eligible=false；manifest.sha256钉住manifest字节。:617 `_verify_prepared` 会重核每个artifact与core真实路径/hash。
- canonical源hash来自scope/probe实际输出，不能用canonical自己的hash冒充源；HDF分支应绑定实际HDF文件hash和提取器版本/字段映射/输出hash，分别保存manifest与canonical的字节hash。当前文件完整性和历史时点真实性必须为两个维度。
- :412准备器硬编码W1/W2、四policy和旧协议，:559固定历史成本基数；不能只替换日期复用整个prepare_staged_inputs。可复用builder/provider/PreparedWindow/quantity resolver和单窗run_staged_window。

## 已复现的接线缺口与最短修改位置

| 位置 | 观察到的行为 | 最短研究分支调整 |
|---|---|---|
| staged_production_inputs.py:220、502 | 自动源审计仅scope/probe | 由独立local_hdf manifest loader构造audit；检查逐文件SHA、映射、输出SHA并显式标UNKNOWN |
| 同文件:137 | evidence仍声称sdk_absolute_v1 | 接受明确source_kind/研究证据版本，保留原值与known_at UNKNOWN |
| validation_2025_bridge.py:163–165；run_2025_ab_execution.py:191–217 | 缺任何完整排名状态键抛异常 | 每个排名行产生明确ineligible决策与原因；实测缺键异常，不删榜、不补位 |
| validation_2025_bridge.py:178 | st_flag只校类型 | 本次st_flag=True仍buy_eligible=True；若协议排除ST必须显式拒买 |
| 同函数 | history_known_at=UNKNOWN未参与判断 | 严格模式拒；研究模式单列假设准许，不能悄悄继承“已验证”含义 |
| raw_market_provider.py:58–65；runner:652–654 | coverage扫描全榜会因缺raw文件抛异常 | 仅对明确缺文件列表用研究包装器返回None/空history并记录missing；其他异常继续抛；已持仓缺估值不能静默跳过 |
| run_2025_ab_execution.py:105–117 | missing_raw/state/CA非零全局阻断 | 保留严格预检；另设条件探索入口允许稀疏输入、状态持续INCOMPLETE，schema必须有逐行拒绝原因 |
| 同文件:221–297、300–335 | 只输出bridge，固定NOT_STARTED | 新增小型调度函数分别构造A/B StagedWindowConfig和provider，调用run_staged_window；不新写撮合引擎 |
| staged_candidate_runner.py:866–890 | exposure仅汇总实际需求，未把全部被阻断机会纳入mechanical_status | 外层结果永久保留全机会缺口和scope资格，禁止因未成交导致暴露为0就升级为目标PASS |

上述行号是本轮读取版本定位，不是owner冻结版本证书；Luna仍拥有这些文件，后续owner实施时应重新定位。未改任何一行生产源码。

## 两层状态时间与研究假设

- 收盘信号日t：完整排名只按exp_ret降序、code升序；不读true_ret作决策。用于资格的ST、交易状态、板别/上市和已知事件必须属于t；不能用t+1状态预先挑选t的买单。收盘触板资格如需要应使用t收盘与t当日边界，不能误用builder开盘触板布尔量称为收盘触板。
- 实际执行日t+1：provider取t+1的ST知识、停牌、参考和绝对边界以及t+1开盘；core执行裁决不能沿用t状态。持仓期间每日估值、CA和退出仍需每日数据，不能只保证买入日。
- 严格PIT：known_at UNKNOWN→拒单、目标INCOMPLETE。当前HDF全局known_at未知，此路径可能全拒，必须标NO_EXECUTABLE_OPPORTUNITY，不能当作模型无效或达标。
- 唯一建议的条件分支：显式采用“本地SDK形状原字段在其标注交易日适用”的回溯假设；structural_valid与execution_usable_under_assumption单列，historical_known_at仍UNKNOWN、pit_verified=false。允许结构完整的当日记录在该假设下执行，缺字段/缺日/缺文件仍拒单。
- 限制为190个源文件中实际有2025状态的174码，并进一步受raw缺两码限制；原5135码全榜保留，绝不把174/172码重排成新的Top5。rank6不会因前五未知而变rank5。缺状态与ST/停牌等已知不可买分开计数。
- 既有Toprank报告的A/B Top5结构有效54/41、排除ST/SUSP后17/10只是旧清单与下一执行日联结的诊断结果；本次未全读NPZ重算，不能当最终收盘资格或成交数。稀疏覆盖很可能主导研究结果，应同时公布两模型机会分母和被拒比例，不挑模型赢家。

## 来源报告和A/B身份处理

- 本次只读NPZ四数组头部和各前6项，A/B各1180872行，dates datetime64[us]、codes U9、exp_ret/true_ret float64；未全扫、未重算70MB NPZ及权重hash。全数组唯一性/对齐与NPZ/权重hash沿用既有DATA_IDENTITY及QA报告，并明确证据层级。
- A/B eval JSON实际SHA与旧清单一致；checkpoint路径存在；两个config实际SHA与旧清单一致、均HORIZON=10，训练终点2024-12-31、验证期2025。配置和旧评估JSON不证明NPZ由该权重生成，也不证明历史冻结或独立验收。
- `_validate_source_report` :214只核JSON绑定字段及实际字节SHA，没有签名/公钥/外部时间戳校验。可以用2026-10-29编制的local_retrospective_identity报告引用实测hash，标identity_evidence=local_bytes、checkpoint_link=local_evaluation_report_claim、historical_generation_time=UNKNOWN、independent_certificate=false。
- produced_at不能伪填2025。最短改为保留 signal_original_produced_at=null，并另设identity_observed_at/bridge_created_at；若旧接口必须非空时间，只能定义为本次桥接时间并修正字段语义。独立QA重算hash证明可复现身份即可，不要求发明签名门，也不把自报报告升级成历史来源认证。

## 明确的数据和结果契约

机器可读字段清单见 CONTRACTS.json；下列规则是必需语义，不是可选展示字段。

- local_hdf source audit逐文件保存relative、absolute路径、size、SHA、提取前后SHA一致性、HDF key、字段类型/NULL统计、原始及保留行数、窗口、提取器SHA、canonical SHA；独立验证者重读文件hash及固定样本映射后才能标byte_integrity_verified。该标志永远不等于source_response_verified或pit_verified。
- scope分开列190文件、174状态码、172 raw码、5135信号码；日历来自共同benchmark。全排名逐日行数与keys/score指纹不变；Top5分母应有1160/模型，并另列E日不可新买的机会，避免把统计机会误称可入场机会。
- opportunity逐原rank保存信号/执行日状态是否存在、结构质量、ST/SUSP值、known_at、raw/history、板别/数量、CA未知、资格和各拒绝原因、订单/成交及剩余槽/预算。缺输入必须有行，拒绝本身也有证据；不能只留实际成交曝光。
- raw_missing清单保存期望路径、检查时间、影响日期、原rank/已有持仓、是否只阻止新开仓或同时阻断估值。明确缺码仅让未持仓缺数据查询返回None，不制造bar、不把None视为停牌；持仓缺mark/权益调整必须停止或标不完整，禁止用0估值。
- CA保留所有原始阶段与NULL，不把无日期提案当已实施、不因缺ex_date就删除未知。逐事件输出source hash、raw row hash、税/碎股/上市/支付/实施/known_at未知和持仓暴露。仅有cash事件可按20%压力情景核账；送转非整股不默认floor/ceil，遇实际暴露暂停并留完整前缀。未知未暴露也必须在全scope计数。
- 不能将corporate_action_known统一置true。如果研究分支允许携带CA不确定性，改为ca_input_present/ca_assessment_status，不用一个true掩盖未知；ctx仍按实际暴露处理并保留INCOMPLETE。
- R&D结果必须含research_class=retrospective_validation_exploration、CONDITIONAL_RND、INCOMPLETE、pit_verified=false、actual_after_tax_target_eligible=false。零买入/零曝光另加NO_EXECUTABLE_OPPORTUNITY；异常中断为ABORTED_AT_UNKNOWN_EVENT，不能把截至中断日收益当完整区间。
- 主期只比2024-12-31 close至2025-12-16 close；buffer另列。基准旧报告端点3934.9109→4497.5545，仅作为已引用身份数据；未来runner须逐日核验实值。数值即使收益≥0且超基准，也只能记conditional_numeric_criteria_met，目标总判定仍NOT_EVALUABLE。A/B两行同协议并列保留。

## 本次真实小样本验证

- diagnose.py：真实import、core签名/hash、manifest观察、12行canonical及4日state/provider、缺raw报错、ST=True且known_at UNKNOWN仍可买反例、缺state抛错反例、v12状态样本。后两项是缺口复现，不是合格行为断言。
- core_sample.py：真实000001.SZ raw及12条HDF候选状态，执行12/16–19四日；100股人工订单。正常在12/17买、12/19卖；最低佣金各5元、过户万0.1、卖出印花万5、滑点内含于成交价，所有快照NAV守恒、持仓峰值1。
- 删除12/17执行日mapping：买入零成交、reason=limit_boundary_unknown，warnings为空；不允许仅依赖warnings判断完整。买入限价1元：reason=limit_price_exceeded，零成交。两个零仓测试只验证拒单API。
- 人工分红夹具：12/17登记100股，12/18每股税前0.1、压力扣缴0.02，应收8元；12/19到账。gross_cash_dividends_paid=10、NAV守恒。该事件不是真实000001公司行动，明确不用于绩效。
- 本次未验证5槽极值、10只极值、真实A/B排名策略全链或真实2025CA覆盖；它们属于下述owner小样本与独立QA门。不能把“峰值1≤10”当作一般上限证明。
- verify_small.py：两个config/eval实际hash，NPZ头部及前6项、candidate与单码raw输出hash、样本来源绑定；完整原NPZ及权重hash没有本次独立重算。全部原始结果见JSON/JSONL。

## 独立 QA 设计（owner完成并冻结后执行）

1. owner停写并发布完成token、代码/输入manifest SHA和排他输出目录；审查者重新核hash，执行前后相同。活跃文件不能提前判PASS。审查使用同一主区.venv -B，记录sys.path和core实际路径/hash，不修改共享环境。
2. 固定mini：七个真实交易日、五个有输入码加至少一个全榜unknown首名；完整排行保持unknown=rank1、已知码rank2–6，验证rank6不补位。另置ST、停牌、缺绝对界和缺执行日状态，逐项检查拒绝原因；正常支路至少有一笔成交，防止全拒假通过。
3. 单独构造能同时占五槽的接口夹具、卖出受阻/部分成交/T+1锁仓/红股未上市夹具；逐个execution_update和registry_transition重建正持仓、锁仓、权益/活动订单占用并检查actual_positions≤10、active_slots≤5。拒单/部分成交不提前释放槽；每笔成交后也检查，不只检查日终。
4. 对真实provider小样本独立核原量价单位、21条历史、当日绝对上下界、买卖限价和执行日；验证不读取t+1来决定t资格。卖出缺数据保留仓位/锁定记录；缺估值和CA参考异常不能补零。
5. 费用逐笔重算，分红登记/应收/到账与现金冻结核守恒；送转非整股、未知上市日和配股暴露需中断留证。至少包含一个正常cash压力事件和一个unknown权益事件，严禁统一known=true。
6. A/B逐日keys/score/rank与NPZ一致，true_ret从交易决策隔离；端点、日历、完整基准和buffer禁买核对。分别检查条件数值与目标资格字段，零成交/低覆盖/中断不得PASS；保留失败日志与退出码。

此处是可执行QA用例设计，不声称独立代理已经验收owner待实现分支。既有桥接QA报告只能引用其当时版本，不能替当前活跃修改担保。

## 唯一推荐的最小实施顺序与截止预算

本机核时2026-10-29 11:55 +08:00，距离22:00约10小时。下列为owner恢复后的一名编码者工作预算，不派新编码者覆盖其树，不等待或中断Luna；若仍被额度阻断，主编排只能在自己的隔离副本实施，后续由owner合并，不能并写现有树。

| 时间预算 | 最小交付 | 停止/继续依据 |
|---|---|---|
| 12:00–13:00，1小时 | owner确认现有数据导出完成；生成独立local_hdf审计和scope，检查两个缺raw路径，锁A/B本地身份/研究假设 | 不再全扫HDF/重提SDK；输入仍变化则只做接口样本 |
| 13:00–15:00，2小时 | 最小研究适配：来源audit、缺状态逐行拒买、ST策略、缺raw显式None、研究标签和零仓标签 | 不改变core/wheel，不改排行，不新写引擎 |
| 15:00–17:00，2小时 | A/B单窗调度接到run_staged_window，复用ctx/recorder/bridge/数量resolver/费用；七日mini至少一笔成交 | 首先证明完整榜unknown首名不补位；禁止用删榜小宇宙取代 |
| 17:00–19:00，2小时 | mini正常/未知/费用/CA/限价/五槽与持仓上限矩阵，固定失败输出和finally审计 | 正常支路仍全拒就修接口，不以空仓通过 |
| 19:00–21:00，2小时 | owner冻结之后独立QA，核代码与数据hash、逐事件账与排名、研究资格 | QA失败只修最小问题；不启动年度绩效来替代QA |
| 21:00–22:00，1小时 | 交付可复跑的mini、prepared候选manifest、完整scope/机会清单和阻断清单 | 有真实未解CA/估值则明确剩余API或输入缺口，保留INCOMPLETE |

预算约7小时实现/样本、2小时独立QA、1小时缓冲；可能交付“可执行研究分支＋小样本证据”。不保证此时能完成全scope输入审计，也不保证全年度两次回放及目标达标。最短输入处理顺序为既有manifest→局部hash/样本→local_hdf审计→两层状态→完整排名资格→缺raw包装→ctx/数量/费用→mini→独立QA；不先扫描全市场raw。

生产安全结论：原样调用现有2025入口不能完成该方案，真实缺口在上表所列具体行；core本身不缺account_actions API。最短新增是一层研究适配/调度，而非新基础设施。即使此分支安全跑完，来源PIT和实际税后未知仍使用户最高目标无法验收；2025只能探索，最终考场仍是事前冻结的干净数据。

## 复跑与诊断边界

命令以主区为cwd，统一使用主区解释器（不uv sync，不安装）：

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B 'C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_sol_diagnostic_20261029/diagnose.py'
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B 'C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_sol_diagnostic_20261029/core_sample.py'
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B 'C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_sol_diagnostic_20261029/verify_small.py'
```

diagnose.py重跑会追加观察日志并重写本目录样本；它只作观察，不冻结其他会话。core_sample.py写本目录四份账户测试JSON；verify_small.py写小文件验证JSON。所有测试极小，无年度循环。命令、退出码、失败和修正见 COMMANDS.md；原始import与异常traceback见 diagnostic.jsonl。
