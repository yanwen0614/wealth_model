# Z盘数据源只读审计

审计日期：2026-10-28。目标范围：2026-09-01 以后。操作限于文件名/大小/mtime、少量 Parquet footer 与单列日期投影、SQLite 只读 schema 及少量聚合/行样本。未读私密配置，未写源库，未训练或回测，未改 CNN 源码。

## 结论摘要

- 可确认近期执行行情候选：`Z:\dev\kline\day\000001.SZ.parquet` 样本业务日期 2013-01-04 至 2026-09-30，3336 行，2026-09-01 起21行。指数候选 `Z:\dev\kline_index\day\000001.SH.parquet` 同样止于 2026-09-30，3338 行，9月起21行。
- `Z:\dev\alpha_factor\000001.SZ.parquet` 样本日期 2013-01-04 至 2026-09-30（3338行）。同目录枚举 5,215 个 parquet、约4.15GB；只读其中一个小样本，不代表全目录覆盖。未触碰 CNN 4GB 训练 parquet。
- `Z:\dev\model_features\996515042bf2\000001.SZ.parquet` 188行，日期 2025-11-04 至 2026-08-11，未覆盖目标起始日。目录枚举约5,100个 parquet、79.7MB；只抽查一个 footer/日期列。
- `Z:\prd\quant_data_prd.db` 4,869,562,368字节，以 SQLite `mode=ro`、`query_only=ON` 读取。日历表 57,468 行、日期整数范围 19901012–20270115。`metadata` 记录：history_status 705,983行/更新 2026-10-23；dividend 121,231/2026-10-19；right_issue 5,516/2026-10-03；trade_calendar 57,468/2026-10-18；forward/backward_factor 各62,260/2026-10-19。业务日期范围：history_status 20140102–20261023，dividend 除权除息日 20130208–20261026，right_issue 公告日 20130108–20261003。
- dividend 在2026-09-01后存在记录；抽取的最新三行除权除息日均为2026-10-26，登记日2026-10-23。right_issue 最新公告日2026-10-03，但抽取三行方案进度、比例等字段为空，不能据此判断有可执行配股。
- 发现 `Z:\dev\execution_log\kline_day.jsonl`（9,470字节）和 `snapshot.jsonl`（315字节），mtime均为2026-05-24；未读取日志正文。`Z:\dev\trade_calendar` 只有这两类清单未列出文件，目录为空。SQLite主库未发现表名匹配 execution/order/signal/model。
- `Z:\dev\backtest\experiments` 共30份 JSON，文件名日期及mtime均为2026-08-09，未见2026-09后信号或执行产物。没有据此读取 JSON 内容。

## 样本 schema 与证据

- 股票行情样本：列 `code, kline_time, open, high, low, close, volume, amount`；日期列 timestamp[us]。指数样本：`kline_time, open, high, low, close, volume, amount, code`。
- alpha_factor 样本：`kline_time`、多类收益/波动/均线/估值/财务/两融字段及`code`；日期为 timestamp[us]。schema footer 显示单 row group，3,338行。
- model_features 样本：`kline_time, O_rel, H_rel, L_rel, C_rel, V_rel, turnover`；日期为 timestamp[us]。
- history_status schema 含代码、交易日期、ST、除权除息、退市风险警示、停牌、涨跌幅及暂停上市字段；数据库存在状态表，但未发现独立执行状态/订单表。
- 抽查 Parquet：`kline/day/000001.SZ`、`kline_index/day/000001.SH`、`alpha_factor/000001.SZ`、`model_features/996515042bf2/000001.SZ`。日期是抽样文件精确范围，不是目录级完整覆盖声明。

## mtime、哈希与局限

- 文件/目录 mtime 表示文件系统最后修改时间，不等于行情业务日期。例：样本股票日线mtime 2026-10-03，但业务末日2026-09-30；模型特征mtime 2026-08-12，业务末日2026-08-11。
- 未计算 SHA-256：需要完整读取文件内容，对大型源库/全目录计算不符合本次最小读取约束。Parquet footer 未提供可信内容 SHA。
- 文件枚举结果只做目录级数量/大小统计，未逐文件读内容。未独立证明日期覆盖、缺失率、样本间一致性或信号可用性。Parquet 样本不证明全市场数据同范围。
- SQLite 主库仅查询 schema、日历聚合、metadata 与少量日期聚合/业务行；未对主库所有表做行数或日期扫描。日历最大日 2027-01-15 是库中记录，不代表未来实际开市安排。
- execution_log 正文、信号 JSON、全部 Parquet footer、私有配置与共享目录大批归档内容均未检查。故“未找到”仅限已枚举路径/schema 范围，不能推断其他位置绝对不存在。
