# 2025本地状态数据定向清点

日期：2026-10-29。范围仅为用户指定的 quant 项目、Z:/dev 已知路径和 opencode 临时研究材料；未联网、未调用 SDK、未读凭据、未写源库/共享环境/源码。

## 结论

- 找到一个实际可复用的本地历史状态缓存：`D:/code/quant/data/AmazingData_local_data/basedata/hist_stock_status/*.h5`，当前目录恰有 190 个按代码拆分的 HDF5 文件。
- 固定样本读取到完整字段：`MARKET_CODE, TRADE_DATE, PRECLOSE, HIGH_LIMITED, LOW_LIMITED, PRICE_HIGH_LMT_RATE, PRICE_LOW_LMT_RATE, IS_ST_SEC, IS_SUSP_SEC, IS_WD_SEC, IS_XR_SEC`。`HIGH_LIMITED/LOW_LIMITED` 是直接绝对价格字段，不由涨跌幅率推导。
- 样本 000001/000002/000030/000045/000100/000333 覆盖 2025-01-02 至 2025-12-31，各 243 行；000040 覆盖至 2025-04-29（77行）；000616 截至 2023-08-22（2025年0行）。仅为固定8码样本，不代表全目录日期覆盖。
- 190个文件远少于目标5,135码；既未证明覆盖5,135码，也未证明覆盖目标232个交易日或任意目标全集。未全扫，不声称全量行/日覆盖。
- 数据含历史日期值但无可见 `known_at`/发布时间；无法证明这些状态在对应交易日盘前可知，也无法证明当时股票宇宙的PIT成员关系。当前/年末代码清单不能代替2025每日PIT宇宙。
- 可将HDF转换为隔离候选缓存并生成文件级哈希，但不能直接传给现成 `build_execution_state_mapping`：其要求带 `code,date,row_hash,source_file_rel,source_sha256,sha_origin,window` 的canonical Parquet及匹配的source audit。HDF字段可映射其业务字段；来源身份、row hash、window和source audit需转换器生成且保持“本地缓存来源/来源时间未知”，不能伪称SDK响应证明或盘前已知。

## 其他本地源

- `Z:/dev/quant_data_dev.db` 的 `history_status` 为稀疏事件/状态表，字段为中文（代码、交易日期、ST、除权除息、退市风险警示、停牌、涨跌停幅度等），没有 `PRECLOSE/HIGH_LIMITED/LOW_LIMITED` 绝对界。只读统计：全表703,606行、2014-01-02至2026-10-03、5,415码；2025有46,995行、243个日期、3,957码，日期2025-01-02至2025-12-31。空缺不解释为0。
- `Z:/dev/kline/day/` 与 `kline_adj/day/` 有按代码拆分的日线 Parquet。抽查 `000001.SZ` schema 为 `code,kline_time,open,high,low,close,volume,amount`，没有直接绝对限价或状态字段；不得由涨跌幅重建限价。未统计该目录总码数/日期覆盖。
- `Z:/dev/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet` footer为12,254,385行，含日线及特征字段；没有本次要求的状态绝对界字段，不能代替状态快照。

## PIT/来源判断

- HDF字段结构与旧状态审计材料记录的AmazingData字段一致；这只说明字段形状兼容，不证明HDF由哪个原始响应生成、何时取得或当时可见。
- 每个样本HDF可计算当前文件SHA256（见 `SAMPLE_EVIDENCE.md`）；这不是原始来源哈希。旧全量研究清单只针对2026-10-27的另一批8,848个HDF导出文件，不绑定此190文件目录。
- 旧SDK审计统计（4,424码、1,007,108原始行、60,144缺日期、239空表、2,629缺字段）不能外推为2025全量数据覆盖。
- 当前证据不能形成可直接用于2025 A/B的全量、PIT、逐日可知状态快照。可复用的是190码的本地候选历史原料；其余目标缺口仍未解决。

## 已核对的既有材料

- SDK预检停止报告：`C:/Users/yanwen/AppData/Local/Temp/opencode/state_2025_probe_20261029/STOP_REPORT.md`，确认未调用SDK。
- 旧结构审计摘要：`C:/Users/yanwen/AppData/Local/Temp/opencode/state_acquisition_main_audit_20261027_v3/summary.json`。
- 回测构建器契约：`C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027/backtest/cnn_adapter/staged_production_inputs.py`，函数 `build_execution_state_mapping`。
- 输出文件仅写在本报告目录；没有转换或复制任何源数据。
