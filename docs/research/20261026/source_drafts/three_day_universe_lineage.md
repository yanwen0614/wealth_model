# 历史股票池 / 幸存者偏差：只读数据血缘核查

核查范围：只读 quant 源码、`Z:/dev/quant_data_dev.db` 基础表、训练 parquet footer/row-group 元数据及少数退市代码投影。未全表读取、未重新拉取数据、未训练或跑收益，也未修改上游 quant。SQL 使用 `mode=ro`、`PRAGMA query_only=ON`。

## 最小结论（供主会话先读）

- **训练宇宙不是 PIT 历史股票池。** `export_training_data.py` 无 `codes` 时调用 `DataReader.get_a_stock_code_list()`；其定义从当前 `stock_basic` 获取代码并按股票类型过滤，不按历史每个交易日的全市场成分重建。之后用当前 `stock_basic.listdate/delistdate` 在训练区间画每股日历网格。没有逐日 point-in-time 宇宙或 membership 快照。
- **源码并非明文“只选当前存续股”。** `stock_basic` 模型保存 `is_listed/listdate/delistdate`，get_stock_code_list 默认 `filter_type='all'` 会返回所有基础表代码（含其登记的退市股票）；导出仅在 `kline_adj` 有数据时产出。实际退市覆盖因此取决于当前基础表是否仍有该代码及历史复权K线是否保留。
- **日线增量采集明确偏向当前存续股。** `KlineDayUpdatePipeline._get_code_list()` 显式传 `active`（is_listed=1 且 delistdate 为空或未来）。该采集路径不再请求已退市股；当前 raw 文件缺失与此一致。但没有证据证明所有历史文件曾被删除；找到的源代码只证明当前增量池及保留边界，不证明早期初始拉取策略或定期清理历史。
- **少量实测确认有退市遗漏，不足以量化全市场偏差。** 002280.SZ 在当前 stock_basic 仍有上市/退市日期（20090821/20240816，is_listed=0），但 raw 文件缺失，训练 parquet 0 行。另抽查 600317.SH、600687.SH、600086.SH、600677.SH（2021年退市）均有基础表退市记录，但 raw 文件缺失、训练 parquet 0 行。说明存在历史退市样本被排除，不能仅归因“002280 一个坏文件”。
- `stock_basic` 当前有 5415 行，5191 `is_listed=1`、224 `is_listed=0`；224 个有 delistdate 的股票时间范围 2020-01-07 至 2026-07-17。这个表本身并非覆盖所有历史退市证券：代码列表表中有 601299.SH、600832.SH、000033.SZ 的历史记录，但三者当前 stock_basic 均无记录，训练/已查 raw 也无文件；该观察说明历史基础证券全集可能缺口，不能据 224 估计历史退市覆盖率。
- **训练 footer 没有股票池版本证据。** footer 有 git hash、范围、导出时刻及 K线/因子/两融的最新日期，不含 stock_basic/code_list 的 hash、更新时间、证券代码清单或 universe 日期快照。训练文件 5199 代码（既有库存清点），无法由 footer 证明纳入规则或数据源股票池版本。

## 可复核代码路径与行号

1. `D:/code/quant/scripts/export_training_data.py:241-260`：`codes is None` 时 `self._reader.get_a_stock_code_list()`，再逐代码导出。
2. `D:/code/quant/src/core/data_reader/base.py:522-580`：`get_stock_code_list(filter_type='all')` 从 StockBasic 查市场代码；仅 `active/margin` 条件才按 `is_listed==1`、`delistdate IS NULL OR > today` 过滤。`get_a_stock_code_list` 同文件 :582-598 调默认 all 后按 `EXTRA_STOCK_A_SH_SZ` 股票类型筛选，不带历史日期参数。
3. `D:/code/quant/src/core/database/models/stock_basic.py:5-23`：`stock_basic` 只存单份当前信息（market_code、listdate、is_listed、delistdate 等）；无历史有效期/版本表。
4. `D:/code/quant/scripts/export_training_data.py:101-120`：导出初始化时一次性读当前完整 `stock_basic`；:298-337 要求每 code 有 `kline_adj`，再按这份当前基础信息构造整个 train_start—train_end 的 calendar grid。缺复权K线直接返回空，:305-308。
5. `D:/code/quant/src/core/data_pipeline/data_update_pipeline/kline_day_update_pipeline.py:36-39`：日线更新 `_get_code_list` 明确 active-only；增量默认起点 2020-01-01 在同文件 :24-27。源码不能证明当前 raw 目录是从何时开始 active-only，也没找到删除历史 raw 文件的逻辑。
6. `D:/code/quant/src/core/data_fetcher/stock_basic.py:96-127`：stock_basic 全量 fetch 从 `get_code_list()` 的证券类型列表获取，再调用 `get_stock_basic`。`docs/AmazingData开发手册.md:741-767` 声明 SDK stock_basic 可返回所有股票（含退市）及 LISTDATE/DELISTDATE；实际 DB 覆盖与 SDK 理论能力不等同。
7. `D:/code/quant/src/core/database/models/extended.py:284-307`：code_list 有 code、entry_date、remove_date、source、单个 update_time；没有按观察日保存历史 membership。`D:/code/quant/src/utils/code_list.py:85-129` 查询 distinct code；`is_valid` 参数没有被用于 SQL 过滤。此历史代码辅助表也不是 PIT 证券池。

8. `D:/code/quant/src/core/data_pipeline/data_update_pipeline/a_stock_code_list_update_pipeline.py:69-80`：代码列表 API 的 `date` 参数语义是“当日仍上市的全量股票”；:141-160 每交易日查询后存储。但 `D:/code/quant/src/core/data_storage/code_list_storage.py:107-151` 对 A 股仅保存首次出现代码，:142 以下丢弃已存在代码；因此历史逐日返回没有按日期保留为 membership 面板。之后 :165-204 再从当前 stock_basic 回填单一 listdate/delistdate。
9. `D:/code/quant/src/core/data_storage/parquet_storage.py:40-81`：单码 parquet 默认 overwrite，merge 是读旧行、同日去重保留新行、写回；该保存函数没有退市时删文件的逻辑。故 raw 缺失可由“采集未纳入/源数据无文件”导致，不能反推其曾被删除。

## 低 IO 实际核验

核验脚本：`C:/Users/yanwen/AppData/Local/Temp/opencode/universe_lineage_probe.py`；样本结果：`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_universe_sample.json`。只投影 stock_basic/code_list 的数个代码和 Parquet 的 code/kline_time/is_trading，使用 row-group code min/max 定位；检查了 `Z:/dev` 与 `D:/code/quant` 下的样本 adj 文件名。训练文件 12 个 row group，每组约 1,048,576 行；footer 范围按 code 排序。既有 inventory 记录 5199 个 code、日期至 2026-08-31；footer fingerprint `v1_20130101-20260831_26c3db036a26`、git hash `26c3db036a266f5765d8cdee4ef352c56d6ee1e9`、export_time `2026-09-05T15:15:42`。

|代码|可核实身份|当前 stock_basic|Z:/dev/kline/day 文件|训练 parquet 命中|
|---|---|---|---|---|
|002280.SZ|ST联络(退市)|2009-08-21 上市；2024-08-16 退市；is_listed=0|无|0 行|
|600317.SH|营口港(退市)|2002-01-31 上市；2021-01-29 退市；is_listed=0|无|0 行|
|600687.SH|退市刚泰|1993-11-08 上市；2021-03-03 退市；is_listed=0|无|0 行|
|600086.SH|退市金钰|1997-06-06 上市；2021-03-17 退市；is_listed=0|无|0 行|
|600677.SH|*ST航通(退市)|1993-09-28 上市；2021-03-18 退市；is_listed=0|无|0 行|

同代码 `backward_factor` SQLite 事件记录也作了只读计数：002280.SZ 9 行，日期止于 2017-07-13；600317.SH 18 行，止于 2020-07-31；600687.SH 15 行，止于 2018-08-29；600086.SH 9 行，止于 2017-08-01；600677.SH 21 行，止于 2019-08-23。五个代码在本次查找的 Z:/dev 与 D:/code/quant adj parquet 候选路径都无文件，训练 F60 code 小投影均 0 行。因此它们**不能从当前 F60 用 `raw=HFQ/F` 反推 OHLC**；数据库中零散因子点本身没有 OHLC，且日期早于终止上市。曾有的因子记录只证明因子表留有部分事件，不证明同期原始或调整行情仍保留。

另：stock_basic 查询没有 601299.SH（中国北车并入中国中车后终止上市）、600832.SH、000033.SZ；code_list 中有这些代码的单记录（部分 `remove_date=NULL` 且 entry_date=20130104），但 parquet/raw 对这些被抽查代码均无命中。因 DB 无权威退市日期，此处只把它们作为历史证券曾存在但当前基础表缺行的线索，不据此断言具体公司行动日期。

## 必须分开的两项故障：训练覆盖 vs 执行价源

|问题|本次证据|结论|
|---|---|---|
|训练宇宙是否漏股|五只 stock_basic 明确退市股票在 train parquet 均 0 行；另有代码列表线索但基础表缺行|这些证券的历史样本确实没有进入当前 F60。源码的 all-code 起点不等于最终训练覆盖，缺 adj 行会静默跳过。对其交易日历史全市场截面/标签存在遗漏；全市场偏差比例未知。|
|CNN 执行 provider 是否缺价|上述同五只 `Z:/dev/kline/day/{code}.parquet` 都不存在；Cnn raw provider 依赖该 per-code parquet|若策略产生这类历史代码的持仓/退出订单，当前 raw provider 无可交割行情，执行路径不能回放。当前 F60 也没有其价格预测行，故不是仅 provider 问题。|
|能否反推缺失 OHLC|需同代码、同日期、同版本的 HFQ OHLC 和非零 F；公式 raw=HFQ/F 已对两只存量活跃股票逐日验证|当前样本无 F60 HFQ 行、无查到的 adj parquet 文件；factor DB 只有零星且早于退市的因子日期。现有证据下无同日 HFQ 可除，不能恢复这些缺失行。|
|即使未来找回 HFQ，是否足以执行|还需要因子版本、准确量额、公司行动与 raw 限价规则|只反推价格不能反推原成交 volume/amount、除息参考价或可成交队列。它只能成为 OHLC 恢复候选，不自动恢复真实执行数据。|

因此，用户提出的“若保留训练/HFQ 行且有已知 F，则 raw=训练OHLC/F 可数值重建”是正确的条件路径；本次五个已退市样本恰恰不满足关键前提（无训练行/已查 adj 文件）。活跃股票上的公式验证不能外推成这些退市样本的恢复证据。

**限制**：以上退市证券是定向小样，不是全量 224 个当前标注退市代码的覆盖率抽样；无全表 code 投影或 224 码的历史行情批量统计。它证明已有实际遗漏样例，但不能估计损失多少历史股票/样本。某退市代码缺 raw 文件也不能单独区分“从未抓到”与“历史上曾存在后被外部清理”。

## 对历史回放、excess 标签和恢复能力的影响

- **真实历史回放**：按 2013–2025 当日可交易证券池回放，目前不能声称完整。当前 Parquet 码集含幸存者偏差的直接证据已存在；原始价格、成交量和退市终止/现金清算路径可能缺失，尾部失败股票被排除会抬高可见历史样本的生存质量。具体绩效偏差大小未知，不能量化成固定百分点。
- **横截面 excess 标签**：若标签为个股未来收益减同一未来区间基准收益，减去 benchmark 只消除共同市场项，并不会补回被漏掉的退市股票或其停牌、退市收益。训练截面少了失败/消失证券，标签尾部分布、每日日截面规模和横截面排序均可能偏乐观；若标签再按截面标准化/分箱，分布影响会进一步传入标签定义。模型对当前训练码集的技术诊断仍可做，但不能把该样本集合外推为历史全市场可交易表现。
- **长期停牌证券**：导出按上市至退市日期生成交易日网格，并将无行情日期记 `is_trading=False`（export_training_data.py:339-345）；CNN reader 对 `is_trading=False` 行过滤。代码没有因“长期停牌”本身从最终证券池剔除股票，但停牌期不能作为正常成交日标签；重新上市后的样本是否保留取决于 raw/adj 行情存在。持有期锁仓、退市整理/转板和清算现金收益不能由该训练 parquet 还原。
- **能否用现有数据恢复 PIT 宇宙**：**不能完整恢复**。`code_list` 更新器虽曾逐历史交易日请求当日上市名单，但 `CodeList` 唯一键是 `(code, source)`，A股保存策略只保留首次出现代码；随后用当前 stock_basic 覆写 entry/remove dates。数据库没有每日 universe membership 快照，也没有生成时版本化的股票清单。对 002280 这类仍在 stock_basic 的代码，可从上市/退市日期画生命周期近似区间；对缺失的 601299/600832/000033 等，无权威 remove_date，且行情也缺。仅靠现有 parquet + 现有 SQLite 无法补齐所有历史成员与退市价格。

## 已确认 / 未知 / 不可用于验收

|状态|结论|
|---|---|
|已确认|训练导出以当前 stock_basic 股票类型列表为入口，非逐日 PIT universe；行日期用当前基础表 list/delist date；raw 日线增量代码池 active-only；code_list 并非历史逐日快照；训练 footer 未记录 universe 身份；至少 5 个 2020–2024 退市样本 raw 与训练均缺失。|
|未知|当前 5199 码里退市代码实际总数；各年每交易日横截面缺失比例；缺失历史股原始数据是否曾抓取后由外部删除；退市证券完整终止收益/现金清算；合并吸收证券的全量 code mapping；较早年份和长期停牌的真实覆盖率。|
|不可用于历史全市场绩效验收|当前 F60 作为无幸存者偏差的 2013–2025 全市场训练集；当前股票池下的 excess 横截面标签可代表当日全市场分布；基于 current/raw 5215 文件数宣称历史池完整。|

建议工程最小动作（不属于本次执行）：将 PIT 成员清单纳入数据生成快照并 hash；对历史正式验收区间以交易日级清单比对每股原始行情覆盖，退市证券必须有可执行终止/锁仓/现金清算规则；对历史退市证券缺失的区间明确 NO-GO，不能通过当前 `stock_basic` 的生命周期字段静默补成完整池。此项是回测验收硬门，不阻止当前固定历史模型的代码/数值技术诊断。
