# F53 两融特征时点与生成来源审计

## 范围与证据等级

只读检查了 quant 两融预处理器、导出脚本配置、CNN schema/scaler，以及 W1 两代码小投影。源码事实与小投影现象分开记录；未查询供应商接口、未计算模型表现。

## 源码支持的结论

- 两融源数据表为 `margin_detail`，按证券代码、交易日期存储；管道文档说明交易所于 T+1 早间公布 T 日两融数据，日更 16:30 因而通常读取 T-1。见 `D:/code/quant/src/core/data_pipeline/AGENTS.md:68-73`。供应商/交易所数据的具体发布时间及个别日期可用时点仍未由本次接口核验。
- `MarginFactorPreprocessor` 的六项 raw 公式（`margin_preprocessor.py:272-311`）：余额比例=(融资余额+融券余额)/(close×as-of流通A股)；融资买入比例=融资买入金额/成交额；净买入比例=(买入−非负偿还)/成交额（两项均零时置 NaN）；5日融资余额变化=余额/5个 margin 行前余额−1；融券余额比例=融券余量/市值；融券卖出量比例=融券卖出数量/(成交额/close)。流通股与 close 使用 as-of/ffill；成交额不 ffill。
- 六个无 `_raw` 后缀列是逐交易日横截面 `rank(axis=1,pct=True)`，不是绝对值变换；部分更新截面整日置 NaN（`margin_preprocessor.py:313-335`）。
- 六个 `_ts` 列是各股 raw 序列 trailing 20 个 margin 行 rolling rank，`min_periods=5`（`margin_preprocessor.py:64-68,337-356`）。不是全历史 rank，也不是 expanding rank。
- 保存时将两融源日期整体映射至下一上海交易日，末日截断；只有落盘日期 shift，`run()` 返回的结果仍使用原 margin 日期（`margin_preprocessor.py:382-412,514-546`）。因此落盘 kline_time 对应下一交易日，契约是保守 T+1 对齐。
- CNN 将 18 个两融列全部列为 G9 observation source（`cnn/data/schema.py:107-116`）。mask 对输入列逐行 finite 后 OR；`RelativeScaler` 也在逐列变换前按输入 finite 状态累积 mask，随后缺失值填 0（`cnn/data/schema.py:181-189`、`cnn/data/scaler.py:379-397`）。故 mask 不由未来日期的 eligibility 单独推导；具体 mask 会随上游输入 parquet 的 18 列 finite 状态而定。
- quant 导出器按上市日期与交易日历构造行网格，K 线日及合成日都 left-merge 因子；缺少的因子列/值保持 NaN，注释明确导出侧不填充因子（`scripts/export_training_data.py:602-642`）。`bfill` 出现在 `TOT_SHARE` 股本序列（754-758），不作用于两融特征。故该导出路径未发现对两融列的未来可用性回填或 eligibility 截断。

## 小投影核验

- `signal_probe_W1_two_codes/input.parquet` 为 4,132 行、55 列，包含 000001.SZ 和 600519.SH，日期 2013-01-04 至 2021-07-05，含 6 raw、6 横截面列及 6 `_ts` 列。
- 对 6 个 `_ts` 列按每股 raw 重算 trailing 20/min_periods=5 rank；各列所有有效重叠样本均吻合（每列约 3,662–4,120 个有效点），与源码定义一致。
- 两股票投影不足以独立复核“全市场”横截面 rank：横截面排名由完整市场参与者决定。不能据两股票数值声称复算验证了 rank 列。
- 本次未用现存输入重新计算 6 个 raw 公式；公式依据为源码，尚无对源表/原始 K 线的数值复算证据。

## 缺口与结论边界

- 两融列的实际输入值来自 per-stock 因子文件，导出器按 kline_time 左连接并保留 NaN；代码层没有用当前标的池/最新 eligibility 改写历史两融值。仍未将具体 F60 parquet footer commit 与其生成 manifest/运行记录绑定，因此只能对照当前导出源码契约，不能证明该特定产物确由这份源码生成。
- 导出配置 `scripts/export_training_data.py:68-77` 列有 18 个两融特征；本次没有建立其对应源文件 footer commit 与扩展生成入口之间的版本绑定，故该血缘关系仍未核实。
- 交易所常规发布时间与 T+1 shift 源码契约相符，但这不证明每个历史日期、每个证券的实际可获得时刻。精确时点仍需数据供应方记录或原始采集时间戳。

## 审计结论

源码定义显示，6 个横截面列来自逐日全市场 percentile rank，6 个 `_ts` 列来自逐股 trailing 20 行 rank；T 日两融截面落盘到下一交易日。CNN mask 是当前行 18 个输入值 finite 的 OR，不会自行读取未来日或 eligibility 表；当前 quant 导出源码保留两融因子缺失值，未发现对两融列的 bfill 或 eligibility 截断。两代码投影支持 `_ts` 计算方式，但不足以验证全市场 rank。特定 F60 产物与源码版本的绑定、以及逐日供应商发布时间，仍未证实。

## 追加：2021H1 真实 artifact 窄范围对齐探针

- 读取 `Z:/dev/quant_data_dev.db` 使用 SQLite URI `mode=ro` 并设 `PRAGMA query_only=ON`。只查 `margin_detail` 两个代码和 `交易日期 BETWEEN 20201201 AND 20210705`，查询计划确认使用 `idx_margin_detail_code_date (证券代码,交易日期)` 范围索引；未扫描全表。
- 源字段已由 SQLite `PRAGMA table_info` 确认：`融资余额`。每只股票按源交易日排序，以 `融资余额[T]/融资余额[第5个更早的实际 margin 观测日]-1` 重算。两代码 2021H1 各有 118/118 个沪深300交易日记录，无源日期缺失；同日移位窗口的前史也包含在窄查询中。
- 对 2021-01-04 至 2021-06-30 的 236 个 code-date 对，候选落在同一日 T：0/236 在绝对误差≤1e-12 下吻合，最大绝对误差 0.12341740781562605，中位误差 0.014505739607212076。
- 候选落在下一实际沪深300交易日 T+1：236/236 吻合，最大及中位绝对误差均为 0；重算值和 artifact 值缺失均为 0。春节边界示例：源 2021-02-10 映射至 2021-02-18（000001.SZ 为 0.05611508640212959，600519.SH 为 0.09365474206415025），证明用的是交易日历而非自然日 +1。
- 这项结果支持两代码、该窗口、该 raw 列在现存投影中的 T+1 实际对齐；不外推到全市场、其它两融列或 F60 全部生成血缘。当前 DB 与 artifact 数值完全一致，但不能据此证明 DB 历史上从未修订，也不能替代 artifact 的生成 commit 绑定。机器可读明细原存 `../margin_artifact_probe_2021h1.json`（2026-10-31 精简删除，可从 git 历史取回）。

## float_shares as-of 口径补充

- `MarginFactorPreprocessor._load_float_shares` 读取 `equity_structure` 的证券代码、变动日期、公告日期、是否有效、流通A股；`_build_as_of_series` 过滤有效且非空行，按 `(变动日期, 公告日期)` 排序，同一变动日期保留公告日期最新行，再把序列索引设为**变动日期**。margin 计算侧按 margin 日期前向填充（`margin_preprocessor.py:112-140,234-259`；`_shared_utils.py:10-73`）。公告日期不是生效日，只用作同变动日期多版本的 tie-break。
- 因为后公告版本仍被回填到原变动日期，若历史更正公告晚于变动日，当前实现可能把更正值追溯应用到公告前日期；源码没有按公告日期设置生效门槛。这构成潜在 PIT 前视风险。当前任务未查询股本记录或量化其覆盖面，不能判断风险发生频率/幅度。
