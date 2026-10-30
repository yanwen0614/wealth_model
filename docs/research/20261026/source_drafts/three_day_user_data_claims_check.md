# 用户接口说明与当前 dev 数据差异核验

核查时间：2026-10-26。范围限定为当前 `Z:/dev/quant_data_dev.db`、指定 5 个退市代码 raw 文件元数据、茅台指定除息事件、`history_status` PRAGMA 列，以及 quant 接口/配置源码。SQLite 以 `mode=ro` + `PRAGMA query_only=ON` 打开；未实例化 DataReader/DatabaseSchema、未执行迁移、未拉 API、未全表读取、未修改 quant。

## 当前数据库是否变化

|证据|当前值|
|---|---|
|DB 文件|`Z:/dev/quant_data_dev.db`，4,734,001,152 bytes|
|文件 mtime|2026-10-20 05:36:45.645 UTC|
|stock_basic metadata|2026-10-04 05:25:25，5415 行|
|code_list metadata|2026-10-03 04:00:09，288068 行|
|backward_factor metadata|2026-09-30 17:14:27，62257 行|
|dividend metadata|2026-10-04 03:53:38，121033 行|
|history_status metadata|2026-10-03 18:27:55，703606 行|

文件 mtime 晚于上述相关表 metadata，但这些表的 `last_updated/record_count` 与此前所见一致。SQLite 文件 mtime 可能由其它表/数据库操作更新，不能单独证明上述业务表刷新过；以下均以本次直接查询结果为准。

## 默认 dev 路径的源码核验边界

- **源码确认默认环境为 dev**：`src/core/database/config.py:28-38` 缺省 `default_env=dev`，当前进程未设 `QUANT_DB_ENV`。`src/utils/path_config.py:51-64,80-85` 映射 dev→`quant_data_dev.db`，默认当前环境也是 dev。
- **路径仍受数据根目录影响**：config.yaml 中 dev `db_path=dev/quant_data_dev.db`；`DatabaseConfig._resolve_yaml_path` 用 `PathConfig.get_data_root()/raw_path`（config.py:75-99）。本次 shell 的 `QUANT_DATA_ROOT` 未设置，而 `PathConfig.get_data_root()` 缺该变量会报错（path_config.py:119-129），故不能声称该进程中实例化 DataReader 会解析到 Z 盘。为满足本次核验要求，直接以用户指定的 `Z:/dev/quant_data_dev.db` 做只读查询。没有实例化会加载配置/可能引发路径副作用的 ORM/DataReader。
- **接口存在不等于有 PIT 历史**：`get_stock_code_list`、`get_stock_basic`、`get_code_list_df`、`get_kline`、`get_kline_adj`、`get_history_status`、`get_metadata` 均可在 `src/core/data_reader/base.py` 找到；它们只提供读取入口，不为表中缺失的证券/日期生成数据。

## 四层核验矩阵

说明：每项分别标【接口有 / 表有 / 具体数据有 / 仍缺】。接口文档、ORM 模型或 Reader 方法都不能替代当前 dev DB 的具体行。

|声明/对象|接口有|表有|具体数据有（当前抽样）|仍缺/判断|
|---|---|---|---|---|
|股票清单 `get_stock_code_list(all)`|有，默认 all 查 `stock_basic`：`data_reader/base.py:672-733`|stock_basic、code_list 都有|metadata 分别5415/288068行；五退市码均在两表，上市/退市日期一致|只能确认抽样历史代码被保留；表没有每日 membership 快照和完整性证明，不能推出全历史证券池完整|
|`get_stock_basic()`|有：`base.py:414-428`，无 code 读全表|stock_basic 有|五退市码均有 `is_listed=0` 和有效 `delistdate`|具体行存在，不代表对应 K 线/因子行存在|
|`get_code_list_df()`|有：`base.py:509-522`|code_list 有|五码均有 source=A、entry/remove date、update_time|每码单行状态表，不是逐日历史股票池；无法还原每个交易日完整成员资格|
|`get_kline(code)` / 当前 raw provider|有：`base.py:307+`，路由 `kline_day`|共享 per-code parquet 目录在代码中配置|五个指定文件 `Z:/dev/kline/day/{code}.parquet` 均不存在|对这五码具体 raw 执行价仍缺；接口存在不补数据|
|`get_kline_adj(code)`|有：`base.py:894-914`|`kline_day_adj` 存储类型有|本次检查的 Z:/dev、quant 仓内五码 adj 文件候选均无；上一轮 F60 按码小投影五码均0行|这轮未再扫/读整份 F60；没有证据有同日 HFQ 行可供反推 |
|`get_history_status(code)`|有：`base.py:617-625`|history_status 有|指定 600519/20260626 行存在：是否除权除息=0、是否退市风险警示=1、是否停牌=0|有的是稀疏事件标志与涨跌幅“幅度”，没有昨收价或绝对涨/跌停价列|
|`get_metadata(table_name)`|有：`base.py:794-826`|metadata 有|五表更新时间/行数如上|函数返回“metadata日期+1天”的增量起点，不是数据逐行完整性或逐证券覆盖证明|

## 五退市 raw 文件复核

|代码|当前 stock_basic 日期/状态|raw parquet|raw 行数|
|---|---|---|---:|
|002280.SZ|2009-08-21 / 2024-08-16，is_listed=0|不存在|无|
|600317.SH|2002-01-31 / 2021-01-29，is_listed=0|不存在|无|
|600687.SH|1993-11-08 / 2021-03-03，is_listed=0|不存在|无|
|600086.SH|1997-06-06 / 2021-03-17，is_listed=0|不存在|无|
|600677.SH|1993-09-28 / 2021-03-18，is_listed=0|不存在|无|

这里仅复查 raw 路径存在性与 Parquet footer 行数（文件不存在故无行数），没有重扫 5215 个文件。不能以接口可以 `get_kline(code)` 推断这五个文件当前有内容。

## 茅台 2026-06-26 事件与因子

- **具体事件行存在**：`dividend` 有 600519.SH，公告日 2026-06-22、方案进度`3`、税前每股派息 28.02423 元、登记日 2026-06-25、除息/派息日 2026-06-26。
- **对应因子行缺失**：`backward_factor` 对 600519.SH 最新行仍为 2025-12-19、因子 8.446992；指定 2026-06-26 exact-date 查询 0 行。全表日期聚合仍为 max=2026-09-29、2026年 2601 行/2496 代码，metadata 更新戳仍为 2026-09-30；不是“有调用接口”就代表该事件已覆盖。
- 因此用户关于“因子日更覆盖到 2026”的陈述在这个具体大额事件上**未成立**。其他代码事件的 2026 完整度本次未全查，不外推。

## history_status 能否提供参考价/绝对限价

当前 `PRAGMA table_info(history_status)` 真实列为：`id,证券代码,交易日期,是否ST,是否除权除息,是否退市风险警示,是否停牌,涨停幅度,跌停幅度,记录类型,是否暂停上市`。

- **有停牌 flag**：`是否停牌` 列确实存在；源码 fetcher 映射 `IS_SUSP_SEC`（`data_fetcher/history_status.py:36-48`）。
- **没有昨收/绝对涨跌停价格列**：没有 `昨收价`、`涨停价`、`跌停价`、`PRICE_HIGH_LMT`、`PRICE_LOW_LMT` 等绝对价格列。当前表只存 `涨停幅度/跌停幅度` 比率或非标准幅度。
- Fetcher 虽把 SDK `LAST_CLOSE_PRICE` 临时映射成 `昨收价`（同文件 :39），但 `_process_status_result` 输出列白名单在 :188-191 不含昨收价，ORM `HistoryStatus` 也无该列，最终落库不保存参考价。绝对限价也未见落库字段。因此接口临时收到了昨收字段，不等于历史库可用它还原真实除权参考价或限价。

## 接口/源码引用与后续最小路径

- 当前配置默认 env=dev：`src/core/database/config.py:28-38`；DB 相对路径由 `PathConfig.get_data_root()` 拼接：`config.py:75-99`、`src/utils/path_config.py:51-64,119-129`。当前 shell 缺 `QUANT_DATA_ROOT`，所以本报告不声称它自动连到 Z 盘；Z 盘数据库按用户指定直接只读核验。
- API：`get_stock_code_list(all)` `data_reader/base.py:672-733`；`get_stock_basic` :414-428；`get_code_list_df` :509-522；`get_kline` :307 起；`get_history_status` :617-625；`get_metadata` :794-826；`get_kline_adj` :894-914。
- 当前证据确认“表有数据”的边界：五退市码基础表/代码表有记录，但 raw 五文件不存在；茅台 dividend 有事件但同日 factor 无记录；history_status 有停牌 flag 但没有参考价或绝对限价字段。后续若要提升历史回放覆盖，最小下一步是只对这五码检查是否能从获授权的历史供应商缓存补齐 raw bars（以及按日确认量额单位）；独立核验退市/合并现金结算规则。若无来源，则这些证券历史区间继续标记缺失，不可用 API 声明替代。

## “因果特征”一词

这里的“因果特征”只指当前 F53 模型输入在每个决策时点使用截至当日可知的特征/避免前视，是对特征时间可用性的简称；没有新增因果推断、处理效应估计或新的因果建模模块。是否真正无前视仍需逐特征核验数据发布时间与构造时点，不能仅凭这个简称认定。
