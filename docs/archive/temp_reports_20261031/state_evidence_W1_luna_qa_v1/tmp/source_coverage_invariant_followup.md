# History Status 覆盖不变量跟进

## 源码核查

- 默认范围起点为 `20140101`：History Status 注册的 `DBMetadataIncrementalStrategy("history_status", 20140101)`；Fetcher 默认同为 `20140101`。基类通用 `DEFAULT_BEGIN_DATE=20130101` 不适用于该注册。
- 增量批量路径按每码 `MAX(交易日期)` 分组；没有该码行时回退注册默认起点。History Status 不写 `update_tracker`，运行时的表级 `metadata.last_updated` 不参与这个决策。
- 成功返回的非空事件行会保存；明确返回且被过滤为 0 行的 DataFrame 会被收集，批尾写入当次 `end_date` touch 推进水位。已有同日任意行时 touch guard 跳过。
- SDK 响应缺失 code 不会进入 Fetcher 的失败重试池。整批变空会由 pipeline 计失败；部分缺码时其余码仍可保存，缺席码无 touch、无逐码失败计数，TaskResult 仍可能成功。其 DB 水位不变，后续运行按旧 MAX 再查；故单次成功不证明每码覆盖。本机制只能证明重查机会，不能证明供应商下一次会返回缺失码。
- 若传入 None/空 dict、获取抛错或保存失败，不写 touch；批次失败/异常也不改变 DB MAX。逐码 MAX 因而会让后续运行重查旧窗口。若合法响应被持续缺码，则会持续静默停留旧水位，须靠供应商完整响应契约或逐码覆盖日志发现。
- 批尾 touch 仅证明该码被明确归类为“本次确认无事件”，并把水位跳到 end_date；它不是逐日行证据。未来日期组 `begin > end` 会跳过且不请求。

## 实测统计（只读）

- 窗口 2020-12-31 至 2021-07-05；F4 信号代码 4186，HDF 190，交集 172（4.11%），交集外 HDF 18。172 个 HDF 均覆盖 122/122 个交易日；该覆盖结论来自前序 QA，状态语义仍未知。
- 按“SQL 无行暂作 normal 假设”计算 172×122=20,984 格：ST TP=1370、FP=9、FN=0、TN=19605；停牌 TP=64、FP=0、FN=0、TN=20920。HDF 两字段均无 unknown。该矩阵是对照假设，不是正常状态完整性的证明；9 个 ST FP 集中在 7 码，见 JSON 逐码矩阵。
- 4186 信号码的 SQL 每码 MAX：4185 码 `>=20210705`，1 码早于截点（`600240.SH`，MAX=`20200204`）；无信号码缺 SQL 水位。Master 生命周期字段：4177 当前 listed、8 条有 delistdate、1 条其他/非 listed；逐码日期在 JSON。不能由当前上市状态反推历史窗口状态。
- SQL `history_status` metadata=`2026-10-03 18:27:55.260017`、record_count=703606；当前源码的逐码增量不以这个表级时间戳替代 MAX。全表有 4994 条 touch，但审计窗口内 0 条；窗口内查询到 28,810 条状态行，status 字段无 NULL。HDF 无行按 normal 计算的 FN=0 不足以证明缺失 HDF 的 4014 码正常。

## 结论与限制

- 源码路径支持“失败或无 touch 时旧 MAX 留存，后续增量仍会重查”；不支持“部分缺码已自动逐码重试”。完整覆盖结论依赖供应商批量响应完整、缺码不会被静默丢弃或会在后续成功补齐的契约，目前源码不能独立证明该契约。
- 表级 metadata 只能描述表更新时间/行数，不能证明某一代码覆盖到某日。F4 的 4186 个 SQL MAX 只能说明至少有历史行，不等于窗口完整。
- SQL 无行映射为 normal 是用户指定的比较假设。Sparse event 行仅能证实被记录的异常；缺 HDF、缺逐日确认、缺请求身份/响应日志时仍属 coverage unknown，不发布为 verified normal。
- 统计脚本及逐码/逐日数据：`coverage_stats.py`、`source_coverage_stats.json`；输入 HDF、SQL 与信号清单路径及具体逐码事实记录在 JSON 中。未修改仓库、数据库或环境，未调用 API。
