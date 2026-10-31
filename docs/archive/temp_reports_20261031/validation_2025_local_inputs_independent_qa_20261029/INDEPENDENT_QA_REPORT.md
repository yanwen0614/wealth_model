# 2025本地候选数据独立 QA

日期：2026-10-29。仅只读本地候选数据；未安装依赖、联网、运行真实年度回测，未触碰源码、数据库或 owner 工作树。详细机器证据：`independent_checks.json`；复核脚本：`qa_verify.py`。

## 结论

**P0：BLOCKED，不可作为2025 PIT完整证明、策略验收数据或收益证据。** 输入仅覆盖全榜 top 5 约4%，状态 `history_known_at=UNKNOWN`，源类别为本地 HDF 而非 SDK 响应；raw 缺 000040.SZ、000584.SZ，覆盖宇宙不完整。CA缺少可确认的时点可得性及实施/税务/整股分配证据。不得据此宣称实际可执行、税后达标、跑赢基准或持仓合规。

**P1：PARTIAL PASS，可用于隔离的条件探索输入。** 仅限明确保留缺失与未知、禁用 unknown 候选交易、完整排名顺序不删不补位的探索；正式 runner/策略验收需先补足全排名输入与 PIT/可执行状态证明。

## 独立检查及结果

| 检查 | 结果 | 级别 |
|---|---|---|
| `artifact_hashes.json` 所列交付物 | 284项全数复算；缺失0、哈希不符0；清单自身按原约定不纳入 | PASS |
| 状态 HDF 文件 | manifest 所列190路径逐一重算；190/190匹配 before/after SHA，缺失0 | PASS |
| 状态行字段与 row_hash | 固定22码；131行横跨2024-12-31、2025年多季度及2025-12-19；抽样均与 HDF 源值、大小写映射列、float/NULL/字符串保留规则及 row_hash 一致 | PASS（抽样） |
| 状态异常标志 | 抽中 ST=1、停牌=1、WD=1、XR=1 事件及0值；仅验证原值传递，不解释 WD/XR 业务含义 | PASS（字段级） |
| 状态日期缺口 | 268对，复核去重后仍268；标签均为 `no_local_hdf_row; cause_unknown`；未补行/补零 | PASS（保持未知） |
| Raw OHLCV 源值 | 10个可读异常/分散代码各抽最多8个边界/季度日期，80行相等；源/输出 SHA 均匹配各自清单；volume=int64、amount=double | PASS（抽样） |
| Raw 缺行情 | 000040.SZ、000584.SZ 的源与候选文件缺失；不解释为停牌、无成交或证券不存在 | BLOCKED |
| CA 导出 | 359条 dividend、0条 right_issue 导出逐条 loader 同款 row_hash 复核全通过；导出文件哈希匹配 manifest | PASS（内容完整性） |
| SQLite 只读性 | `mode=ro`、`query_only=1`；主动写入探针被拒；仅检查 schema/表名，未跑 integrity_check、未重算4.7GB整库 SHA | PASS（只读访问） |
| PIT/实施/税务与真实 runner | `history_known_at=UNKNOWN`、`pit_evidence=false`、`implementation_certified=false`；本次未执行 runner/回测 | BLOCKED |

## 字段与解释边界

- HDF 源哈希与候选 `source_sha256` 绑定本地 HDF 文件，不是原始 SDK 响应哈希；抽样验证 `row_hash` 按 `market_code,trade_date_str,preclose,high_limited,low_limited,high_lmt_rate,low_lmt_rate,is_st_sec,is_susp_sec,is_wd_sec,is_xr_sec` 顺序构造。标志维持字符串 `'0'/'1'`，不得把 UNKNOWN 转成 false/无风险。
- 268个缺码日的原因未知。即使字段为空或无行，也不能据此推断可交易、停牌、退市或无成交；原始排名不得因输入缺失而缩短并向下补位。
- 172个 raw 文件复制的列值未做单位换算；抽样源值等同可支持“未观察到重复换算”，但不能替代174码全量逐值独立比较。两个缺源代码仍是 runner 阻断项。
- CA 行 hash 证明导出内容与其自身封存值一致，不证明 SQLite 当前整库内容未变（本次未重算整库哈希），也不证明记录在当时已公开、方案已实施、股份获配/现金税正确。进度字段只保留原值，不赋予完成语义。
- 交付报告提到 backtest_core 接口缺失依赖；本次没有安装或运行 loader/runner。独立样本核验不能替代 owner 的适配器审查，也不证明 `known` 字段会安全传播或未知时严格拒单。

## 范围与复现

- 抽样：固定22个状态代码，多日/边界；131条状态记录；raw 10个存在文件代码、每码8个指定日期；缺行情两码单列。完整细节见 `independent_checks.json`。
- 全量清单复核耗时由 tmux 会话执行；交付文件哈希检查覆盖284项。CA源数据库未整库重哈希；HDF文件哈希检查覆盖190项。
- 主区 `.venv` Python `-B` 确认 PyArrow/Pandas 可用但无 PyTables，未安装依赖；HDF 复核由既有 `D:\code\quant\.venv` Python `-B` 显式使用 PyTables。Parquet/SQLite 复核使用既有 Python 环境只读执行。
- 本报告只评价候选输入的局部完整性与字段保持，不运行策略、不估计收益、不签发 PIT 或执行资格。
