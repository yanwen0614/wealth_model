# W1 History Status 字段语义跟进

## 范围与裁定

- 只读检查现有 SDK 1.1.8、本地手册/字段映射、Fetcher/Storage、000001.SZ HDF/raw K 线及 `Z:/dev/quant_data_dev.db`；未调用 API、未写数据库、未改仓库或 DS 盘点产物。
- **修正前报告的解读**：20982 条是通过语法/完整性检查的候选，不是“状态未知”；两个限价率冲突都落在 `IS_SUSP_SEC='1'` 且无 raw K 线的股票日。它们只使该停牌日的 rate↔absolute 对应关系 unknown，不应否定其它 20982 行。
- **日线模型：GO（000001.SZ、2020-12-31~2021-07-05）**。HDF 和 raw K 线各 122/122 日期；ST/SUSP flag 非空且均为 0；直接价格栏与 raw 日价同量纲、OHLC 全部被绝对限价包住。按日期作为日线状态/价格特征可用；不要把没有发布时间戳的当日字段自动当作前收盘时已知输入。
- **预先固定订单的机械回放 + core 现金/NAV 核验：条件 GO**。使用原始 `HIGH_LIMITED/LOW_LIMITED`，不从 rate 重建/覆盖；订单信号、方向、股数、费用、有效期和撮合假设须先冻结；公司行动现金按已固定账务时点处理。结果只验证确定性机械账本，不是候选绩效或实际成交证明。
- **9:30 实际排队/实际成交结论：NO-GO**。日线 SDK/HDF 无队列、盘口、订单到达时刻及逐笔成交；这是成交证据边界，不是否定 ST/SUSP/价格字段作为日线模型数据。

## 字段定义、来源和映射

- SDK 开发手册称 `get_history_stock_status` 为日频历史状态（`D:/code/quant/docs/AmazingData开发手册.md:785-803`）；字段表给 `PRECLOSE` 前收、`HIGH_LIMITED/LOW_LIMITED` 涨/跌停价、rates、ST/SUSP 的字符串枚举 1/0，且手册把 `IS_WD_SEC` 释为除息、`IS_XR_SEC` 释为除权（`:805-819`）。手册没有注明价格单位、盘中更新时间或9:30可用时间。
- 本地安装为 AmazingData **1.1.8**，仅反汇编本地 `.pyc`，未调用 SDK 查询：`D:/code/quant/.venv/Lib/site-packages/AmazingData/download_data/download_info_data.pyc` 内 `download_hist_stock_status` 的 bytecode 常量/嵌入行显示先请求 `A010060002`（约1589行），再请求 `A010060005`（约1608行），按 `TRD_DATE`→`TRADE_DATE` 左连接（约1630-1634行）。输出列含三个绝对价格及 rates/flags。绝对价格应作为直接值优先消费；rates 仅辅助校验。
- SDK `info_spi.pyc` 的 `HistStockStatusSpi.OnResponse`（嵌入行307-319）：非空 data 按 code 保存；只有非 `kSuccess`/`kDataEmpty` 状态记 error。SDK 没有在此解码/验证 flag enum，也未给出缺行代表正常的保证。
- ST/SUSP 可按字符串 `"1"`/`"0"`解码：手册明确；Fetcher 再 `to_numeric` 转整数（`D:/code/quant/src/core/data_fetcher/history_status.py:157-160`）。状态列适合作为日状态；Fetcher 输出映射见 `:36-48`。
- **WD/XR 命名存在真实冲突**：项目 API 表把 WD 写为“退市整理”、XR 写“除权除息”（`D:/code/quant/docs/amazing_data_api_codes.md:406-423`）；Fetcher 又将 WD 映射为“退市风险警示”、XR 映射为“是否除权除息”（`history_status.py:44-46`）。SDK 开发手册的 WD=除息、XR=除权与该两处不一致。原始位先保留，不从该 SQL 中文列名推断风险/退市。
- 价格 rates 在现有数据中是比例小数：`.10` 表示 10%、`.05` 表示 5%；Fetcher 的 `STANDARD_LIMIT={0.1,0.2,0.05}`（`history_status.py:12`）与 core 的百分比乘法（`D:/code/quant/src/core/backtesting/adapters/common.py:156-170,224-244`）相符。文档没有独立写“百分比按比例存储”，这是源码+raw 样例确认的口径。
- `PRECLOSE/HIGH_LIMITED/LOW_LIMITED` 没有在 SDK 手册明确标单位；它们是价格 float。000001.SZ 与 raw K 线 OHLC 同数量级，且 122/122 日满足 `raw high <= HIGH_LIMITED`、`raw low >= LOW_LIMITED`。结合 raw 行情的 `元/股` 口径（`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_corporate_actions_contract.md:26-29`），可按元/股消费。这里证明日线价位语义和比例尺，不证明成交队列。

## 000001.SZ 完整窗口实证

- W1 交易日历、HDF 与 raw K 线均 122 日；HDF `MARKET_CODE` 与请求代码一致；raw K 线窗口 122 行，缺 bar=0。HDF SHA256 `f44140938d77d70d8215ad87a5db61276b4e51fbb79424e7e6431004644b72a7`；raw K 线 SHA256 `945a652db2352362e94515a41dc1a495eee84cd5fb4a14d7351efe91a29bb027`。逐日细节见本目录 `semantic_probe_evidence.json`。
- 122 日 `IS_ST_SEC` 全为字符串 `"0"`，`IS_SUSP_SEC` 全为 `"0"`；二者没有 null/异常值。它们可用于该代码的 daily state；该结果不外推到其余 4185 代码。
- 绝对限价对 122/122 raw bars 均成立。Rates 与绝对价格逐日算术相合（原独立扫描为 122/122）；不是靠百分比替代绝对价。
- 唯一 `PRECLOSE` 与前一 raw close 不同的日期是 2021-05-14：前收字段 `22.89`，raw 05-13 close=`23.07`，差 `0.18`。SQLite `dividend` 行为登记日 2021-05-13、每股税前/税后派息 `0.18`、除权除息日/派息日 2021-05-14、公告日 2021-05-07（证据 JSON 的 `dividend_rows`）。故该 `PRECLOSE` 是除息调整参考，不是可被前一未调整 close 覆盖的错误值。
- 同日 HDF `HIGH_LIMITED=25.18`、`LOW_LIMITED=20.60`；按 `22.89×1.1=25.179→25.18`、`22.89×0.9=20.601→20.60` 到分，吻合。raw OHLC 为 `23.14/23.43/22.60/23.32`，处在绝对限价之间。HDF flags `IS_WD_SEC="1"`,`IS_XR_SEC="0"`；这条除息样例支持开发手册的 WD=除息语义，与项目 API 表/Fetcher 映射冲突。
- W1 SQL sparse `history_status` 仅有 000001.SZ 的 `20210514` 一行；其 `是否退市风险警示=1`、`是否除权除息=0`、`是否停牌=0`、rate 为 NULL、`记录类型=NULL`。该行来自 WD 错映射的证据，不是退市风险证据。`semantic_probe_evidence.json` 同时记录该代码全表13行、最新 `20260930 touch` 及表级 metadata `last_updated=2026-10-03 18:27:55.260017, record_count=703606`。

## 两个暂停日异常：缩小到日，不否定全表

- `000017.SZ 2021-06-21`：前两条交易状态为 ST=1/rate=.05；暂停日 SUSP=1、无 raw K bar，绝对限价 `3.72/3.36` 正好是 `PRECLOSE=3.54` 的约 ±5%，但 rate 字段仍为 `.10`；6-22 复牌后 rate=.10 且绝对限价 `3.89/3.19` 为 ±10%。
- `000422.SZ 2021-06-10`：6-8/6-9 ST=1/rate=.05；暂停日 SUSP=1、无 raw K bar，绝对限价 `6.56/5.94` 为 `PRECLOSE=6.25` 的约 ±5%，rate 却为 `.10`；6-11 复牌后 rate=.10 且绝对限价 `6.88/5.63` 为 ±10%。上下文和空 K 线列表见 `semantic_probe_evidence.json` 的 `anomaly_context`。
- 证据最支持“暂停日 rate 未随暂停前 ST 状态及时更新/各字段更新时间不一致”；不能证明哪一组代表假设复牌当天的法定限价。机械订单裁决在 `IS_SUSP=1` 日应直接不撮合、保留持仓；不需用 rate 反推，不需把其它行变 unknown。若研究暂停日的假想限价，则仅该两个证券日 `rate_vs_absolute_limit=unknown`。

## SQL 稀疏表：何时无行可解释为正常，例外在哪里

- 表设计明确只存 ST/除权除息/风险/停牌/非标准幅度事件；昨收从 kline 取，标准幅度不存（`D:/code/quant/src/core/database/models/factor.py:7-22,36-45`）。Fetcher 对成功返回的日线行应用异常 mask；标准 5/10/20% rate 会过滤，全部无异常时返回按 code 保留的空 DataFrame（`history_status.py:162-190,194-212`）。所以：**若确认该 code 的查询完整成功且 SDK 确实返回了完整日行，事件表无逐日记录可解释为没有被该 mask 保留的异常**；绝不等于数据库本身含逐日正常标签。
- 增量流程把有 code key 的确认空 DataFrame 收集起来（`D:/code/quant/src/core/data_pipeline/data_update_pipeline/base.py:723-742`）；Storage 只为这些 code 写一条 `记录类型='touch'` 的 `end_date` 水位行，标志硬编码0（`D:/code/quant/src/core/data_storage/touch_confirm_mixin.py:65-80,96-150`）。touch 证明一次更新管道将该 code 作为确认无异常推进到截止水位；不是每天的状态快照，也不提供历史逐日请求日志。
- **不能单凭 SQL 无行推断正常的例外已在当前源码中存在**：SDK callback 将 `kDataEmpty` 当作非 error（`AmazingData/.../info_spi.pyc` 嵌入行307-319）；SDK 的两接口合并只对请求结果字典两边都存在的 code 继续处理（`download_info_data.pyc` 嵌入行1623-1634）。generic `BaseFetcher` 明文规定缺席 code 静默丢弃、不重试（`D:/code/quant/src/core/data_fetcher/base.py:344-354,400-411`），这与 HistoryStatusFetcher 注释“缺 key=真失败”（`history_status.py:30-34`）不一致。
- 还有批次全缺口：`run_batch_by_date_groups` 的 `all_no_event` 对 `{}` 使用 `all(data.values())`，因此 `all([])=True`；注释明确该分支会被当作整批无事件豁免（`D:/code/quant/src/core/data_pipeline/data_update_pipeline/base.py:783-815`）。但空 dict 没有 per-code empty DataFrame，故不会进入 `_last_no_event_results`，批尾也不会为这些 code 写 touch（`base.py:119-137,733-742`）。API 缺码/空数据可能因此留下无事件表行、无水位且无逐码失败证据。
- 数据库没有逐 code×date 请求状态账；`metadata` 只有表名、全表更新时间、全表计数。本次只读值为 `2026-10-03 18:27:55.260017 / 703606`。故查询范围未能从源响应或逐日全覆盖快照独立证实时，SQL 无行必须保留 unknown；“touch 存在”也不能替代缺失的历史响应审计。
- 本例 W1 SQL 只在 `20210514` 有一条事件行且语义映射错误；但 000001 的 SDK HDF 与 raw 行情都逐日 122/122 完整，故该代码窗的 ST/SUSP 正常状态由逐日源行支持，而非由 SQL 空行推断。
- 状态/限价消费者另有同类缺口：`D:/code/quant/src/core/backtesting/adapters/limit.py:57-88` 对稀疏表无事件返回 `None`，core 再按代码/板块和 prior close 推百分比价（`market_data.py:281-305`; `common.py:178-244`），没有直接接入 SDK 的绝对 `HIGH_LIMITED/LOW_LIMITED`。故本次机械回放须明确走绝对价格数据门；不能把当前 sparse limit provider 的“无记录→默认”说成已由完整历史覆盖证明。

## 逐项放行条件与结论

- **000001 日线模型字段：GO**：以 HDF 日期行使用 `IS_ST_SEC`/`IS_SUSP_SEC` 和 direct price fields；保留原始 dtype/值/文件 SHA。若模型决策时点早于该日期可知性，按 PIT 再查有效时间；SDK 手册没有9:30发布时间承诺。
- **000001 订单机械回放、core 现金/NAV：条件 GO**，限单代码、该完整日期窗、预先冻结订单和会计核对；不是策略收益验收。Source gate 使用 HDF 当日 absolute limit 和 `PRECLOSE`，rate 只保留诊断。订单日 `IS_SUSP=1` 则不撮合并保留仓位。
- 执行前固定：①订单在前一收盘生成的时间、方向/股数/限价/期限、最坏现金预算、费用与容量/滑点假设；②12/31 作 warmup、决策日按完整交易日历、最后三日不新开仓；③raw Open/Close 与状态输入的文件路径/SHA、逐日拒因、cash/receivable/positions/NAV 守恒；④core 账本采用的公司行动和红利税政策。绝不在观察执行日 open 后改订单股数。
- **2021-05-14 必须单列**：HDF reference `22.89` 有分红算术和 absolute-limit 交叉支持，公告日 `2021-05-07` 早于 ex-date 但只有日期、无时分。若订单限价需执行日更新 reference，只有预先声明“把该存档 reference 作为开盘前可用输入”的机械假设才可回放；要主张真实 pre-open 可见，仍缺公告/行情发布时刻。若不接受该假设，仅拒绝该证券日订单、保留持仓和权益，别剔除整窗。
- 该日股权登记日 `2021-05-13`、税前/税后字段均 `0.18`、ex/pay date=`2021-05-14`。按项目既定保守时点，符合登记条件的应收计NAV，派息现金只在 pay-date EOD 转为可用现金；9:30订单现金预算不能先花这笔股息。core 必须对齐公司行动记录、selected tax policy 和“一次扣税/一次入账”，再断言扩展 NAV。
- `HIGH_LIMITED/LOW_LIMITED` 直接数据路径接入当前 core 是尚未验证的接口缺口：现有 `LimitOverride` 只表达 ST 和 pct（`market_data.py:294-300`），没有传绝对上下限字段。因此该复盘需由外部确定性门控按 absolute prices 预裁决后，将固定成交/拒单记录交 core 核账；如果要求 core 内部自行裁绝对限价，则需要先证明或提供相应接口，不能用现有百分比推价冒充直连验证。
- **9:30实际成交：NO-GO**；这是盘口/排队和时间戳证据缺失，不阻断前两项。0.045带等订单约束只能称受限开盘机械模型；“raw open 价内”不等同真实排队成交。

## 本次固定证据

- 主要明细：`semantic_probe_evidence.json`（HDF/raw hashes、122日对齐、raw限价包含、前收差异、公司行动行、SQL 行及两暂停日上下文）。
- 原逐码审计：`audit_report.md`、`qa_summary.json`、`candidate_day_assessment.jsonl`、`per_code_coverage.csv`。两条率/价冲突计为局部暂停日 unknown；20982 条完整性候选仍保留，不把它们升级为绝对的真实成交证明。
- 本次唯一失败探针是首轮对 SQLite `metadata` 错假定列名 `name`；查 `PRAGMA table_info(metadata)` 后按实际 `table_name,last_updated,record_count` 读取成功。数据库全程 `mode=ro` 并设置 `PRAGMA query_only=ON`。
