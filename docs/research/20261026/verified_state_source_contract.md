# Verified State 来源契约（只读研究归档）

日期：2026-10-26。未改生产代码、未调用API、未跑策略/绩效。数据库检查限定SQLite `mode=ro`+`query_only`，磁盘范围仅已知quant日志/cache、CNN日志目录、指定W1 HDF5与少量raw行。

## 决策摘要

- `history_status` SQL表本身是稀疏异常行+每码最新touch；缺行不可默认正常，触摸日与metadata不能证明历史区间覆盖。现表不能生成通用覆盖证书，且WD中文列不能用于退市筛选。
- 新发现：quant SDK本地缓存 `data/AmazingData_local_data/basedata/hist_stock_status/*.h5` 保存原始每日状态行（包括昨收、绝对涨跌停、限幅、原始状态码）。目录有190个代码H5，非W1全部4186码。可逐码比对预期交易日历；仅对日期完全匹配且字段有效的(code,date)生成窄域verified state。HDF5无请求起止/请求成功元数据，不能仅凭它宣称供应商调用完整成功。
- 实测 `000001.SZ.h5`：1,291,128字节，2919×11，日期2014-01-02至2025-12-31；2021H1含118日，与本地交易日历118日完全相等（无缺无多）。2021-05-14行含 `PRECLOSE=22.89`、`HIGH_LIMITED=25.18`、`LOW_LIMITED=20.60`、上下限幅0.1、`IS_WD_SEC=1`。该行是现金除息日；字段WD不可直接译作退市风险。
- `600519.SH.h5`不存在；目录内H5只有190个代码。已知五只退市股的status H5均不存在。现有本地HDF5因此可支持部分代码研究/交叉校验，不支持全W1 4186码覆盖。
- W1全窗执行仍需缺失代码的状态响应与逐码coverage manifest；持仓/参考价unknown日拒单而保留资产，不把缺行映射False。

## 源码语义与覆盖证据

`quant/src/core/data_fetcher/history_status.py:30-34,162-180,194-211`注释描述API对在市证券按交易日给完整状态行；Fetcher按ST/XR/WD/停牌/非标准限幅筛异常，空结果携带末日限幅attrs。此为代码意图，单独不足以证明库行完整。

`history_status.py:157-160`对状态值`fillna(0)`；`IS_XR_SEC`映射“是否除权除息”、`IS_WD_SEC`映射“是否退市风险警示”与历史SDK文档冲突。数据库无法区分显式0与NULL后填0；touch标志也是硬编码0。只允许保留raw原码，禁止按WD中文名过滤退市风险。

`history_status_storage.py:47-52`仅存异常行；`TouchConfirmMixin`只写(code,end_date,type=touch)，按码留最新，不存begin_date/请求ID/行数/成功状态。`metadata`只有表名、更新时间、记录数。Watermark基于事件行或touch的MAX日期，不能表示请求覆盖范围；新代码还可能回退表级metadata日期。单码fetch空结果不写touch，批量缺key不会自动成为确认空结果。

已知日志 `D:/code/quant/logs/quant.log` 有2026-05单码请求参数/Fetcher原始行数与过滤后行数示例，但不是W1，且不含全部raw响应/逐日日期集合/请求身份。`pipeline.log`为空；`data/api_cache`中未见history_status响应；`data/execution_log`仅kline/snapshot。无已发现的W1请求区间+成功+逐码完整响应清单。

## 现存HDF5窄域证据

缓存路径：`D:/code/quant/data/AmazingData_local_data/basedata/hist_stock_status/`。目录只统计文件元数据，共190个H5、约244,455,616字节；未逐文件读取。选读000001.SZ一文件，因HDF为Pandas Fixed格式不能where下推，故仅读其约1.29MB文件，并仅输出H1日期行。HDF存储属性仅Pandas格式/版本，无query start/end、请求时刻或成功状态。

对000001.SZ的2021-01-01至2021-06-30：HDF日期118个，与SQLite本地交易日历沪深交易日118个完全一致（首日2021-01-04，末日06-30）。这证明此缓存文件在此码/窗口含逐日记录，可支持该窄窗口的字段复核；不证明其它代码、日期或供应商返回成功元数据。05-14原始 `IS_WD_SEC=1` 且 `IS_ST_SEC=0, IS_SUSP_SEC=0`，仍须保持字段原语义，不得把WD当退市。

2021H1 SQL小样：SQL稀疏表中000001.SZ仅05-14一行、600519.SH仅06-25一行；两者正好为现金除息日且落库WD=1。二者touch均为2026-09-30，限幅0.1；不能回证H1。600519缺HDF文件。SQLite metadata `history_status`=2026-10-03更新/703606行，为表级统计而非代码覆盖证书。

## VerifiedState来源及规则

`CnnRawMarketDataProvider`要求每个(code,date)显式给`market_state/st_known/reference_known/limit_known`；空映射会维持unknown/拒单。可用HDF原始日行作窄域来源，须逐代码检查日期唯一、字段非空/合理、与交易日历完全匹配，并保留HDF文件hash、行hash、来源路径/字段名。

正成交raw OHLC可证明该日有成交；raw无行、零量、缺OHLC不能区分停牌/无成交/行情缺漏。完整覆盖且普通非事件日可用最近真实raw交易日close；要求前收链完整、无公司行动/长停牌例外。HDF若有原始`PRECLOSE`、`HIGH_LIMITED/LOW_LIMITED`，它优先作为该日直接报价证据，不能被训练复权价替代。

2021+常见规则仅可在已核类别/状态/规则版本下使用：普通主板10%，主板ST5%，300/688板块20%；IPO/重新上市等初期规则、停牌复牌和特殊交易例外缺证据则unknown/拒单。非标准百分比和价格tick须来自当日raw响应或权威规则，不用最新touch回填历史。

公司行动日：用现存dividend ex-date、已校验raw XR字段、可用的因子生效日变化形成当日候选；无可验证官方reference/限价则拒绝该code当日开盘订单，已持仓及已确认应收/股份权益按raw账本盯市，不提前筛未来日期。因子缺行不证明无事件。固定不认购配股可保持原股数、raw盯市；权利价值/注销单列unknown。

## 明确缺行推断与GO边界

- 只有某代码某窗的原始每日响应完整，且响应日期集合逐日等于该证券预期在市交易日历、响应/文件字段schema有效，才可把该窗HDF行当覆盖；若某日没有HDF行则该日unknown，不能因表稀疏而标正常。
- 目前可验证：000001.SZ H1 HDF日期完整匹配；不可外推到600519或其它4185码。HDF行匹配提供内容覆盖，但没有请求身份/成功时间，完整采集身份仍不完整。
- 总体执行仍NO-GO：无全W1代码覆盖、未核全字段SDK语义/版本、未核所有IPO/限价规则。仅窄域code/date可以按其HDF逐日证据构建状态；缺状态的证券日拒单并报告覆盖率/容量影响。
