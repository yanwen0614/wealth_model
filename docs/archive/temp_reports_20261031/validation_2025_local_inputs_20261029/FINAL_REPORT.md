# 2025本地候选输入快照报告

**状态：候选数据已生成；完整回测输入 BLOCKED；未运行A/B回测。** 本次只读本地源，输出仅写在本目录。`candidate_only=true`、`qa_accepted=false`；所有历史 `known_at` 均为 UNKNOWN，不构成PIT或真实可执行证明。

## 状态 HDF 候选快照

- 输入 `D:\code\quant\data\AmazingData_local_data\basedata\hist_stock_status\*.h5`：190文件、542,907源行；每文件路径、SHA读前/后、HDF key、列名、代码、行数、文件创建UTC、读取起止UTC见 `full190/source_manifest.json`。190文件均单key、同一11列schema、读前后SHA相同；16个文件在目标日期无行。
- 窗口含首尾 `2024-12-31..2025-12-19`，日历取沪深300本地日线文件，SHA `97a99b8ec472299960f56c3cc38c8e69adc8358482dda53eba1d722c210fe599`。236日；174码有40,796行；anchor 174/174有行；268个缺失代码日都标 `no_local_hdf_row; cause_unknown`，其中000040.SZ缺158日、000584.SZ缺110日。缺日不删行、不补0。
- HDF候选 [candidate_state.parquet](full190/candidate_state.parquet) 同时保留11个HDF原列与builder小写映射列；每行附 `row_hash/source_file_rel/source_sha256/source_kind=local_hdf/sha_origin=local_hdf/window=candidate_2025/history_known_at=UNKNOWN`。原SHA是当前本地HDF文件SHA，不是SDK响应哈希。没有生成任何 `known=True` 或认证字段。
- `row_hash` 使用builder字段次序 `market_code,trade_date_str,preclose,high_limited,low_limited,high_lmt_rate,low_lmt_rate,is_st_sec,is_susp_sec,is_wd_sec,is_xr_sec`，数值字段以Python float、NULL原样保留、flag保留字符串，紧凑UTF-8 JSON（`ensure_ascii=False, allow_nan=False`）后SHA256。全40,796行复核通过；原值/映射列差异0、重复键/冲突0、读错误0、11字段NULL均为0。flag仅保留原值：ST 0/1=38,643/2,153；停牌=40,615/181；WD=40,675/121；XR=40,794/2。

## 原始未复权日线候选输入

- 输入 `Z:\dev\kline\day\{code}.parquet`，目标代码来自174个有HDF目标期行的代码。使用冻结 `read_raw_market_inputs` 逐代码校验日期顺序/唯一性、OHLC一致性和量额单位；输出不做单位换算，保留源 `code,kline_time,open,high,low,close,volume,amount`。每码取窗口起点前21根有效暖窗bar及窗口数据；状态未从行情合成，保持unknown。
- 174个目标文件中172个成功，44,116行；所有172码均有21根有效暖窗。**000040.SZ、000584.SZ在raw与adjusted日线目录均无对应文件**，原因未知，未当作无行情。172个输出逐行与源重读精确相等，输出SHA全匹配；日期重复/排序错误、单位/OHLC/VWAP检查错误均未发现。源行组及列块数据页偏移/大小/编码记录在 `raw_ohlcv_full174_v2/raw_page_value_audit.json`。
- 因缺两码，行情集 `complete=false`，没有“已准备完成”标记。逐码输入SHA、文件大小/row group/schema/读批统计、21根历史日期、输出SHA见 `raw_ohlcv_full174_v2/source_manifest.json` 与 `candidate_manifest.json`。

## 公司行动候选快照

- SQLite输入 `Z:\dev\quant_data_dev.db` 以 `mode=ro` 打开并设置 `query_only=ON`；4,734,001,152字节，读前/读后完整SHA相同：`bb1372c362e8a9b085af4984eb522f9a4b243e0d07f5c1b9777c532d94b7b14b`。174码范围内按2024-12-31至2025-12-19日期字段筛选，原字段保留；源库未复制或写入。
- loader形状导出包含359条 dividend、0条公告日在窗口的 right_issue、174条 stock_basic原行及2条上市/退市日期落窗记录。方案进度原值计数 `{1:151,2:77,3:130,4:1}`，不解释其语义；359条中登记日229空、除权日229空、派息日231空、实施公告日229空、红股上市日355空。缺日期不补、不视为已实施、不加税务/整股规则。
- [delivery_manifest_v4.json](ca_full174/delivery_manifest_v4.json) 按现有loader格式钉住三份导出完整SHA；原始数据库SHA、SQL范围、PIT未知标记见 `ca_full174/task2_v2/metadata_snapshot.json`。全359行的loader同款 `_row_hash` 复核0差异。

## 精确接口差异与owner适配契约

- `build_execution_state_mapping` 要求11个小写业务列及 `code,date,row_hash,source_file_rel,source_sha256,sha_origin,window`；本候选已提供这些列，但以 `source_kind=local_hdf` 独立标识，来源审计需绑定逐HDF文件SHA。函数本身没有 `sha_origin` 白名单；现有 `_source_lookup` 仅构造 `cache_manifest/probe_result` 来源元组，未读取本地HDF manifest。
- builder的hash规范可对齐且本次全行验证一致；但其证据固定写 `mapping_version=sdk_absolute_v1`，并从状态/执行raw派生known状态。不可将此SDK语义用于本地HDF，也不可把本地值升级成已知盘前状态。
- 建议owner审查的隔离适配器契约：①接受显式 `source_kind=local_hdf` 并从HDF源manifest验证路径、key及文件SHA；②按本报告row hash及NULL/flag原值复核；③把 `history_known_at=UNKNOWN` 传播到执行状态，相关known字段不设true；④unknown候选严格拒单，原始完整排名顺序不删、不向下补位；⑤缺行情文件是输入缺口/runner阻断，不能解释成停牌、无bar或证券不存在；⑥adapter输出仍标候选，不签发SDK/PIT认证。
- 当前 `CnnRawMarketDataProvider._load` 对被请求的任意排名代码缺少 `{code}.parquet` 会抛 `FileNotFoundError`；174码也远小于A/B完整排名宇宙。因此不能把这批行情当完整runner输入。现有loader在当前quant环境实际导入还失败：已安装 `backtest_core` 缺 `backtest_core.contracts.account_actions`；未安装/改环境，故公司行动导出按原loader JSON、manifest和row hash契约独立核对，未声称loader运行通过。

## 交付与边界

- 汇总与UTC完成时间：[delivery_summary.json](delivery_summary.json)；全目录逐产物SHA清单：[artifact_hashes.json](artifact_hashes.json)，清单不含自身SHA。运行日志：[full190_run.log](full190_run.log)、[raw_ohlcv_full174_run.log](raw_ohlcv_full174_run.log)、[raw_value_audit_run.log](raw_value_audit_run.log)、[ca_full174_run.log](ca_full174_run.log)，各成功进程退出码0；源/逐文件输出SHA也见相应manifest。
- 不运行回测，没有证明扣成本跑赢沪深300、持仓始终不超过10只或税后资格；也未证明2025 A/B任何策略表现。2025 A/B仍是已观察验证期历史回放，不能作为干净验收。缺状态不补位，空仓或低成交不能解释为模型无效或达标。
- 外部依赖补齐、适配器经owner审查、缺失行情代码问题有证据处理，并完成独立QA前，这些材料只供隔离验证研究，不可接入策略验收。
