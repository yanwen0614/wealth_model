# 历史股票池 / 幸存者偏差：只读数据血缘核查

核查范围：只读 quant 源码、`Z:/dev/quant_data_dev.db` 基础表、训练 parquet footer/row-group 元数据及少数退市代码投影。未全表读取、未重新拉取数据、未训练或跑收益，也未修改上游 quant。SQL 使用 `mode=ro`、`PRAGMA query_only=ON`。

## 最小结论

- **训练宇宙不是 PIT 历史股票池。** `export_training_data.py` 无 `codes` 时调用 `DataReader.get_a_stock_code_list()`；其定义从当前 `stock_basic` 获取代码并按股票类型过滤，不按历史每个交易日的全市场成分重建。之后用当前 `stock_basic.listdate/delistdate` 在训练区间画每股日历网格。没有逐日 point-in-time 宇宙或 membership 快照。
- 源码并非明文“只选当前存续股”。`stock_basic` 保存 `is_listed/listdate/delistdate`，`get_stock_code_list(filter_type='all')` 会返回基础表登记的全部代码；导出只在 `kline_adj` 有数据时产出。实际退市覆盖取决于当前基础表是否仍有该代码及历史复权K线是否保留。
- **日线增量采集偏向当前存续股。** `KlineDayUpdatePipeline._get_code_list()` 显式传 `active`（is_listed=1 且 delistdate 为空或未来）。这证明当前增量池不请求已退市股；不能证明早期初始拉取策略或所有历史文件曾否被删除。
- **定向实测确认退市遗漏，但不量化全市场偏差。** 002280.SZ（2009-08-21上市、2024-08-16退市）、600317.SH、600687.SH、600086.SH、600677.SH（2021退市）当前基础表均有退市记录，但 raw 文件缺失、训练F60均0行。
- `stock_basic` 当前5415行，5191 `is_listed=1`、224 `is_listed=0`；224个带delistdate代码日期为2020-01-07至2026-07-17。该表不覆盖所有历史退市证券：code_list含601299.SH、600832.SH、000033.SZ线索，但当前stock_basic无记录，训练/raw也无文件。不可据224估计历史退市覆盖率。
- **训练 footer 没有股票池身份。** footer 有 git hash、范围、导出时刻及K线/因子/两融最新日期；不含 stock_basic/code_list hash、更新时间、证券清单或 universe 日期快照。训练文件既有清点为5199代码，footer不能证明其纳入规则或股票池版本。

## 可复核代码路径

1. `D:/code/quant/scripts/export_training_data.py:241-260`：`codes is None` 时取 `get_a_stock_code_list()`。
2. `D:/code/quant/src/core/data_reader/base.py:522-598`：`all` 按股票类型过滤；仅 active/margin 按当前上市状态过滤；`get_a_stock_code_list` 不带历史日期参数。
3. `D:/code/quant/src/core/database/models/stock_basic.py:5-23`：当前信息表，无历史有效期/版本表。
4. `D:/code/quant/scripts/export_training_data.py:101-120,298-337`：一次性读当前基础表；每股必须有 kline_adj，否则返回空；用现有上市/退市信息构造区间网格。
5. `D:/code/quant/src/core/data_pipeline/data_update_pipeline/kline_day_update_pipeline.py:24-39`：日线更新明确 active-only；这不能证明更早历史采集行为。
6. `D:/code/quant/src/core/data_fetcher/stock_basic.py:96-127`：全量 fetch 基于证券类型列表。SDK理论可返回退市股，不等于当前 DB 覆盖完整。
7. `D:/code/quant/src/core/database/models/extended.py:284-307`、`src/utils/code_list.py:85-129`：code_list 是单条状态记录，不是 PIT universe。
8. `D:/code/quant/src/core/data_pipeline/data_update_pipeline/a_stock_code_list_update_pipeline.py:69-80,141-160`：逐日请求当日列表；`data_storage/code_list_storage.py:107-151,165-204` 对A股只留首次出现代码，之后以当前 stock_basic 回填单一生命周期。
9. `D:/code/quant/src/core/data_storage/parquet_storage.py:40-81`：单码 parquet overwrite/merge 实现未显示退市时删除文件；raw 缺失不证明历史文件被删。

## 低 IO 核验及采集身份

复核脚本：`C:/Users/yanwen/AppData/Local/Temp/opencode/universe_lineage_probe.py`；样本结果：`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_universe_sample.json`。仅投影基础表少数代码及parquet的 code/kline_time/is_trading，利用 row-group code min/max 定位；检查 Z:/dev 和 quant 仓内样本 adj 文件名。未全量扫描大文件。

训练文件既有 inventory 为5199代码、日期至2026-08-31；footer fingerprint `v1_20130101-20260831_26c3db036a26`，git hash `26c3db036a266f5765d8cdee4ef352c56d6ee1e9`，export_time `2026-09-05T15:15:42`；12个 row group，每组约1,048,576行。

|代码|可核实身份|当前 stock_basic|Z:/dev/kline/day 文件|训练 parquet|
|---|---|---|---|---|
|002280.SZ|ST联络（退市）|2009-08-21上市；2024-08-16退市；is_listed=0|无|0行|
|600317.SH|营口港（退市）|2002-01-31上市；2021-01-29退市；is_listed=0|无|0行|
|600687.SH|退市刚泰|1993-11-08上市；2021-03-03退市；is_listed=0|无|0行|
|600086.SH|退市金钰|1997-06-06上市；2021-03-17退市；is_listed=0|无|0行|
|600677.SH|*ST航通（退市）|1993-09-28上市；2021-03-18退市；is_listed=0|无|0行|

同代码 backward_factor 事件行数/末日：002280.SZ 9行/2017-07-13；600317.SH 18行/2020-07-31；600687.SH 15行/2018-08-29；600086.SH 9行/2017-08-01；600677.SH 21行/2019-08-23。五码在本次查询的 Z:/dev 与 D:/code/quant adj parquet 候选路径均无文件，F60按码小投影也均0行。零散因子点没有 OHLC，且日期早于退市；不能从当前F60用 `raw=HFQ/F` 反推这些证券的OHLC。

另：stock_basic 无601299.SH、600832.SH、000033.SZ；code_list 有单记录（部分 remove_date=NULL、entry_date=20130104），但 parquet/raw 无命中。DB无权威退市日期，故仅作历史证券曾存在但当前基础表缺行的线索，不断言具体公司行动日期。

## 必须分开的两项故障：训练覆盖 vs 执行价源

|问题|证据|结论|
|---|---|---|
|训练宇宙是否漏股|五只明确退市股票训练parquet均0行；另有 code_list 线索但基础表缺行|这些历史样本没有进入当前F60；截面/标签有遗漏，全市场偏差比例未知|
|CNN执行provider是否缺价|上述五只 `Z:/dev/kline/day/{code}.parquet` 均不存在|若策略产生这类历史代码的持仓/退出订单，当前raw provider无行情可回放；F60也无预测行|
|能否反推OHLC|需要同代码、同日期、同版本HFQ OHLC及非零F；活跃两股上公式逐日验证|当前样本无F60 HFQ行、无查到的adj文件；无法恢复这些缺失行|
|即使找回HFQ是否足以执行|还需要因子版本、准确量额、公司行动与raw限价规则|反推价格不能恢复成交量额、除息参考价或成交队列|

用户提出“若保留训练/HFQ行且有已知F，则 raw=训练OHLC/F 可数值重建”是正确的条件路径；本次五个退市样本不满足关键前提。活跃股票公式不能外推为退市样本恢复证据。

限制：以上是定向小样，不是当前224个退市代码的覆盖率抽样；未做全量 code 投影或逐日全市场统计。缺raw文件不能区分“从未抓到”与“历史上曾存在后由外部清理”。

## 对历史回放、标签和恢复能力的影响

- 按2013–2025当日可交易证券池回放，目前不能声称完整。缺失失败/消失证券可能抬高可见样本生存质量，绩效偏差大小未知，不能量化成固定百分点。
- excess 标签减去共同基准项不会补回退市股票、停牌或退市收益。训练截面遗漏会改变标签尾部分布、每日截面规模和排序；对现有训练码集的技术诊断不能外推为全市场可交易表现。
- 导出按上市至退市日期生成日历网格，无行情日标 `is_trading=False`；CNN reader 过滤此类行。停牌锁仓、退市整理/转板及清算现金收益不能由训练parquet还原。
- 现有数据不能完整恢复 PIT universe：没有每日 membership 快照和生成时版本化清单；对缺失的601299/600832/000033等也缺权威 remove_date 与行情。

## 已确认 / 未知 / 不可用于验收

|状态|结论|
|---|---|
|已确认|导出以当前stock_basic类型列表为入口，非逐日PIT universe；raw增量池active-only；code_list非历史逐日快照；footer无universe身份；至少5个退市样本raw与训练均缺失|
|未知|当前5199码退市代码总数；逐日截面缺失率；raw历史文件是否被外部删除；完整退市终止收益/清算；合并代码映射；早期与长期停牌覆盖率|
|不可用于验收|当前F60不能作为无幸存者偏差的2013–2025全市场训练集；当前excess截面不能代表逐日全市场；不能凭文件数宣称历史股票池完整|

建议工程动作（非本次执行）：将PIT成员清单纳入数据生成快照并hash；以交易日级清单核对正式验收宇宙行情；退市证券必须有终止/锁仓/现金清算规则；缺失区间明确 NO-GO。该项不阻止固定历史模型的代码/数值技术诊断。
