# 用户接口说明与当前 dev 数据差异核验

核查时间：2026-10-26。范围：`Z:/dev/quant_data_dev.db`、指定5个退市代码raw文件元数据、茅台指定除息事件、`history_status` PRAGMA列及quant接口/配置源码。SQLite `mode=ro` + `PRAGMA query_only=ON`；未实例化DataReader/DatabaseSchema、未迁移、未拉API、未全表读取、未修改quant。

## 当前数据库与默认路径边界

- DB `Z:/dev/quant_data_dev.db`，4,734,001,152 bytes，mtime 2026-10-20 05:36:45.645 UTC。相关表metadata：stock_basic 2026-10-04 05:25:25/5415行；code_list 2026-10-03 04:00:09/288068行；backward_factor 2026-09-30 17:14:27/62257行；dividend 2026-10-04 03:53:38/121033行；history_status 2026-10-03 18:27:55/703606行。文件mtime晚于这些业务表metadata，不单独证明业务表刷新。
- 源码默认环境为dev：`src/core/database/config.py:28-38`；dev相对路径按`PathConfig.get_data_root()`解析。该shell未设`QUANT_DATA_ROOT`，不能声称当前DataReader会自动连到Z盘；本核查按用户指定路径直接SQLite只读查询。
- `get_stock_code_list`、`get_stock_basic`、`get_code_list_df`、`get_kline`、`get_kline_adj`、`get_history_status`、`get_metadata`接口存在，不代表表内有对应证券/日期数据，更不生成缺失覆盖。

## 核验矩阵

|对象|实际抽样证据|仍缺/判断|
|---|---|---|
|stock_basic/code_list|五码退市样本均有记录与上市/退市日期|无每日membership快照，不能证明全历史证券池完整|
|get_stock_basic|五码均`is_listed=0`且有delistdate|基础行不代表行情/因子存在|
|raw get_kline/provider|五个指定`Z:/dev/kline/day/{code}.parquet`均不存在|这些代码的raw执行行情缺失|
|get_kline_adj|本次Z盘及quant仓内五码adj候选均无；上一轮F60按码投影均0行|无证据有同日HFQ可供反推；本轮未重扫F60|
|get_history_status|600519.SH 2026-06-26事件行存在：是否除权除息=0、是否退市风险警示=1、是否停牌=0|只有稀疏标志及幅度，无昨收或绝对涨跌停价|
|get_metadata|返回metadata日期/行数；函数存在|是更新时间和增量起点信息，不是逐证券完整性证明|

|代码|stock_basic|raw parquet|raw行数|
|---|---|---|---:|
|002280.SZ|2009-08-21上市/2024-08-16退市|不存在|无|
|600317.SH|2002-01-31上市/2021-01-29退市|不存在|无|
|600687.SH|1993-11-08上市/2021-03-03退市|不存在|无|
|600086.SH|1997-06-06上市/2021-03-17退市|不存在|无|
|600677.SH|1993-09-28上市/2021-03-18退市|不存在|无|

仅复查raw路径存在性及Parquet footer（缺文件则无行），未重扫5215个文件。不能以接口存在推断这些文件有内容。

## 2026因子日期更正与公司行动证据

- `dividend`存在600519.SH事件：公告2026-06-22、进度3、税前每股28.02423元、登记2026-06-25、除息/派息2026-06-26。
- 该股`backward_factor`最新行仍为2025-12-19、因子8.446992；2026-06-26精确日期0行。因此该大额事件在抽查股因子中未覆盖，不能因接口存在称事件已处理。
- **范围纠正：2025-12-19是600519.SH等抽查股的因子截止日，不是全表最大日期。既有年度聚合证据记录 backward_factor 全表 max=2026-09-29（62257行/5415码）；请勿把样本股缺口外推为全表日期上限。**
- 其它代码2026事件覆盖未全查，不外推。派息事件存在不证明派息税务、交易限制或完整成交可行性。

## history_status字段与参考价

当前表列：`id,证券代码,交易日期,是否ST,是否除权除息,是否退市风险警示,是否停牌,涨停幅度,跌停幅度,记录类型,是否暂停上市`。有停牌flag，无昨收/涨停价/跌停价/PRICE_HIGH_LMT/PRICE_LOW_LMT绝对价。Fetcher临时映射`LAST_CLOSE_PRICE→昨收价`，但输出白名单及ORM不保存该字段。

history_status代码把`IS_XR_SEC`映射到“是否除权除息”、`IS_WD_SEC`映射到“是否退市风险警示”；本地手册对`IS_WD_SEC`描述为除息，另一SDK码表又不同。除息日`是否退市风险警示=1`的年度统计强烈支持实际列承载现金除息，但供应商原始定义尚未核准；不得按列面义过滤退市风险。

## 采集身份、限制与结论

- 复核入口为原报告及已有脚本：`C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_user_data_claims_check.md`。Z盘DB由用户指定直接只读；未实例化可能受环境路径影响的ORM/DataReader。
- 抽样确认五个退市代码基础表有记录但raw文件不存在；茅台事件有记录但同日因子缺失；history_status有停牌幅度字段但无参考价/绝对限制价。未证实全市场数据完整性、逐日PIT股票池、退市结算规则或策略绩效。
- “因果特征”在原证据中只指输入特征的时点可用性简称，不是因果推断模块；逐特征发布时间/构造时点仍需审计。
- 本文只核对接口与指定抽样数据，不构成交可行、全表覆盖或绩效PASS。
