# 现有本地行情来源窄范围核查

核查范围：仅检查 `D:/code/quant/data/AmazingData_local_data/`、项目源码明确的日线/后复权相对目录、已知 `Z:/dev/kline/day` 与 `Z:/dev/kline_adj/day`，以及 `Z:/dev/quant_data_dev.db` 指定证券的只读SQLite查询。未扫整盘/训练parquet，未整载大文件，未调用API/服务，未读凭证，未改仓库、环境、数据库或缓存。

## 目录/样例可用性

|代码|SDK状态HDF|Z raw日线|Z adj日线|当前生命周期与W1关系|
|---|---|---|---|---|
|000005.SZ|有 `hist_stock_status/000005.SZ.h5`；未见行情字段|未找到|未找到|1990-12-10至2024-04-26；生命周期覆盖W1|
|000018.SZ|有 `hist_stock_status/000018.SZ.h5`；未见行情字段|有，1337行|有，1337行|1992-06-16至2020-01-07；在W1前已退市|
|002280.SZ|本次限定缓存目录未找到同码HDF|未找到|未找到|2009-08-21至2024-08-16；生命周期覆盖W1|
|600317.SH|本次限定缓存目录未找到同码HDF|未找到|未找到|2002-01-31至2021-01-29；W1前段生命周期相交|
|600687.SH|本次限定缓存目录未找到同码HDF|未找到|未找到|1993-11-08至2021-03-03；W1前段生命周期相交|
|600086.SH|本次限定缓存目录未找到同码HDF|未找到|未找到|1997-06-06至2021-03-17；W1前段生命周期相交|
|600677.SH|本次限定缓存目录未找到同码HDF|未找到|未找到|1993-09-28至2021-03-18；W1前段生命周期相交|

文件名查询仅覆盖本报告列出的目录。D盘SDK缓存的`basedata/`仅见`hist_stock_status/`（190个HDF）、`hist_code_list/20251231.pkl`及`industry_base_info/`；没有发现`hist_kline`/日线行情子目录。`Z:/shared/AmazingData_local_data`解析为`\\192.168.0.123\quant-data\shared\AmazingData_local_data`，同样仅有这三个子目录；000005/000018 HDF的大小、key与抽样行和D盘副本相同（未做字节级hash）。HDF文件大小：000005.SZ 1,258,736 bytes；000018.SZ 1,176,400 bytes。

### 小样元数据

- 两个HDF key分别为`/000005.SZ`、`/000018.SZ`，存储`FrameFixed`。抽取每个文件前2行只见状态信息：`MARKET_CODE,TRADE_DATE,PRECLOSE,HIGH_LIMITED,LOW_LIMITED,PRICE_HIGH_LMT_RATE,PRICE_LOW_LMT_RATE,IS_ST_SEC,IS_SUSP_SEC,IS_WD_SEC,IS_XR_SEC`；没有OHLC、volume、amount。限价参考值/昨收字段不能还原完整日K。
- 000018 raw/adj Parquet各1个row group、1337行，日期统计为2014-01-02至2020-01-06。raw schema含OHLC、int64 volume/amount、code；adj schema含OHLC、double volume、int64 amount、code。首3行小样可读，原/后复权OHLC不同；raw量额首行为2014-01-02：close=9.50、volume=28,502,000、amount=271,596,500,000；adj close=16.449193、volume≈16,460,929.12、amount相同。它提供退市前历史行情，但不覆盖2021 W1。
- 000005 HDF前样行日期为2024-04-25/24，标记ST及停牌；这只是状态HDF，不是对应交易K线。

## 来源契约与查询方式

- 项目`PathConfig.PARQUET_PATHS`将`kline_day`映射`kline/day`、`kline_day_adj`映射`kline_adj/day`。对已知`Z:/dev`根只检查上述两目录及七个精确文件名。
- quant源码`PathConfig.get_ad_local_data_path()`默认使用`get_data_root()/shared/AmazingData_local_data`，可由`AD_LOCAL_DATA_PATH`覆盖；`get_data_root()`要求`QUANT_DATA_ROOT`。白名单读取显示当前PowerShell进程的`QUANT_DATA_ROOT/AD_LOCAL_DATA_PATH/QUANT_ENV/QUANT_DB_ENV`均未设置；quant项目`.env`的安全键筛选仅发现`AD_LOCAL_DATA_PATH=./data/AmazingData_local_data`，这是相对`QUANT_DATA_ROOT`解析的覆盖值。`QUANT_DATA_ROOT`不在该`.env`安全键中；不读取其它`.env`字段。因而无法断言当前进程有效根，但静态规则的`shared/AmazingData_local_data`候选已在`Z:/shared`下找到；`Z:/data/AmazingData_local_data`（`.env`相对覆盖在该根下的派生候选）不存在。项目相对候选`D:/code/quant/data/shared/AmazingData_local_data`也不存在。
- SQLite以URI `mode=ro`打开并启用`PRAGMA query_only=ON`。`stock_basic`按`market_code`命中唯一索引，`code_list`按`code`索引查询；只取七码的证券名、`listdate/is_listed/delistdate`及`entry_date/remove_date/source/update_time`。两表这七码生命周期日期相同，code_list记录source=A、update_time为2026-05-03。
- HDF只读key/schema并各取2行；Parquet只读footer/schema、row-group日期统计及首3行。`hist_code_list/20251231.pkl`只查看文件名/文件元数据，未反序列化。

## W1 membership与导出筛选判断

- 对仍存在于当前`stock_basic`的代码，`listdate/delistdate`可构造一个粗粒度“在挂牌生命周期内”的候选区间；本次七码字段齐全，可判定哪些生命周期与W1相交。它不等于逐日PIT全部证券成员资格：当前基础表可能缺历史证券，日期不含盘中公告/实际可交易时点，也不覆盖停牌、ST、指数成分或逐日筛选状态。`code_list`的`entry_date/remove_date`是单条生命周期记录，不是按交易日版本化的membership序列。
- “训练从当前stock_basic全表起步”不必然排除退市股。`get_stock_code_list(filter_type='all')`明确包含仍在基础表中的已退市股，`get_a_stock_code_list()`再按A股证券类型筛选，不加`is_listed=1`条件。真正的前置遗漏是代码根本不在当前stock_basic；后续`export_training_data._export_code`若`get_kline_adj`为空则跳过该代码。故覆盖由基础表存留和逐股adj行情共同决定，不能把“起步全表”解释成完整保留。

## 最小恢复步骤（建议，未执行）

1. 先保存当前已发现000018 raw/adj两文件的只读路径、文件大小/时间、Parquet schema及日期范围；如需使用，按已核实的原始单位和公司行动口径再独立复核，不把它外推到其它代码。
2. W1若要恢复完整历史行情，先对每个缺口代码寻找经授权、带来源与版本身份的本地raw OHLCV/amount文件；状态HDF中的PRECLOSE/限价字段不能代替日K。没有证据就保留缺口，不用未来价格、复权因子点或状态价拼造完整bars。
3. membership候选可由现存stock_basic生命周期与可用code_list生命周期按沪深交易日历展开；同时列出当前基础表缺失的历史代码、日期语义不确定项和无行情区间。完成历史证券全集与缺失行情来源验证前，不称为完整W1 PIT membership。

## 证据限制

表中逐码记录本轮限定目录的命中情况：发现的`Z:/shared`是项目默认共享缓存后缀对应的旧/共享缓存位置，里面是状态HDF和代码清单，没有日线bars；D盘项目缓存根也没有新增行情目录。Z盘此次新确认的000018 raw/adj行情止于W1之前。当前有效`QUANT_DATA_ROOT`未设置，`.env`相对覆盖路径未解析；但默认共享缓存已实际检查。未命中仍严格限定于已列目录，不表示整机或所有SDK缓存不存在。现有生命周期字段支持部分历史挂牌区间近似，不能单独证明全市场PIT成员完整或绩效PASS。


## W1 2021H1 全量候选与 F4 覆盖对照（2026-10-26）

### 结论与口径

- W1 执行窗口按 2021-01-04 至 2021-06-30（沪深交易日）；候选挂牌生命周期用 `listdate <= 2021-06-30` 且 `delistdate` 为空或 `>= 2021-01-04`。
- A 股过滤严格调用已安装 SDK 的 `AmazingData.utils.security_type.is_security_type(code, "EXTRA_STOCK_A_SH_SZ")`：沪市 `60xxxx.SH/688xxx.SH/689xxx.SH`、深市 `00xxxx.SZ/30xxxx.SZ`。`stock_basic` 5415/5415 均命中该类型；对这些代码逐项以索引查询 `code_list` 的 `source="A"`，5415/5415 均有记录。来源标签只作交叉核对，不替代证券类型判断。
- 4385 个当前 `stock_basic` A 股代码的挂牌生命周期与 W1 相交；其中 4185 出现在 F4 `coverage_by_code.csv`，200 未出现。缺口中 187 个在本次核查的 raw/adj 日线目录均没有同名 parquet；另 13 个两目录都有同名文件。文件名命中不等于覆盖 W1 全期，也不证明 bars 完整。
- F4 有 1 个不属于当前 `stock_basic` W1 生命周期候选的代码：`600240.SH`（退市华业，listdate 2000-06-28，delistdate 2020-02-05）；它的 F4 coverage 表仍有记录。
- 候选的生命周期分布：W1 内退市 12；W1 全期前已上市且生命周期延伸到 W1 后 4129；W1 期间新上市 244。生命周期字段只形成挂牌区间近似，不是官方逐日 PIT membership。
- 当前 SDK A 股列表另有 1030 码不与 W1 生命周期相交：listdate 晚于 W1 的 1014 码、delistdate 早于 W1 的 16 码；这些也逐码保留在清单中。

### 原始逐码表与汇总

- `w1_2021h1_existing_coverage_manifest.csv`：当前 SDK A 股代码及 F4 额外代码逐码记录 stock_basic/code_list 日期、F4 输出天数/ready days、raw/adj 同名文件命中、状态 HDF 命中及分类。共 5415 个代码行（另有表头）。
- `w1_2021h1_existing_coverage_summary.json`：机器可读的汇总计数、生命周期与文件命中交叉表、输入 CSV SHA-256 和只读查询计划。
- F4 来源为既有 `W1_full_v1/coverage_by_code.csv`，SHA-256 记入 JSON。数据库以 `mode=ro` 与 `PRAGMA query_only=ON` 打开；`code_list` 查询计划命中 `idx_code_list_pk (code, source)`。

### 解读边界

- “raw/adj 未命中”严格限定于 `Z:/dev/kline/day`、`Z:/dev/kline_adj/day`；状态 HDF 目录为 `D:/code/quant/data/AmazingData_local_data/basedata/hist_stock_status` 与 `Z:/shared/AmazingData_local_data/hist_stock_status`。HDF 仅作为状态元数据命中单独标识，不当作 OHLCV。
- `stock_basic`/`code_list` 是当前可见代码表及生命周期日期，不证明历史证券全集、逐日可交易资格、ST/停牌或 PIT 指数成员完整。这里的 4385 是当前表可构造的 W1 生命周期候选数，不称“官方完整 A 股 PIT universe”。
- 200 个 F4 缺码只描述相对当前候选集的差异；有 13 个代码在行情目录有文件名但没进入 F4，187 个目录未命中。不能把这 200 个统称幸存者偏差。完整逐码名称和状态见 CSV。
- 本轮只读统计并写入本临时目录；未调用 API、未补采、未读取 4GB 训练 parquet，未修改 repo、环境、数据库或缓存。
