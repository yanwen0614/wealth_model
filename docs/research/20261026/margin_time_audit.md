# F53 两融特征时点与生成来源审计

核查范围：只读 quant 两融预处理器、导出脚本配置、CNN schema/scaler及W1两代码投影；未查询供应商API、未算模型表现、未改业务代码。SQLite时间探针另见本目录`margin_artifact_probe_2021h1.json`。

## 源码结论

- 两融源数据表`margin_detail`按证券代码、交易日期存储。quant管道文档记载交易所T+1早间公布T日数据，日更16:30通常只能取T-1；供应商/交易所逐日实际可用时刻未独立核验。
- 六个raw公式见`D:/code/quant/src/core/factor/margin_preprocessor.py:272-311`：余额比例=(融资+融券余额)/(close×as-of流通A股)；买入比例=融资买入/成交额；净买入=(买入−非负偿还)/成交额（买入与偿还均零时NaN）；5日变化=融资余额/第5个更早margin观测值−1；融券余额比例=融券余量/市值；融券卖出量比例=卖出数量/(成交额/close)。close与流通股as-of/ffill，成交额不ffill。
- 六个无`_raw`后缀列为逐日横截面`rank(axis=1,pct=True)`；部分更新日整行NaN（`:313-335`）。六个`_ts`列为逐股trailing 20个margin观测行rolling rank，`min_periods=5`（`:64-68,:337-356`），不是expanding或全历史rank。
- 计算源日期整体映射到下一上海交易日落盘，末日截断；`run()`结果仍保留原margin日期（`:382-412,:514-546`）。这是源T到落盘T+1的设计契约。
- CNN将18个两融列作为G9 observation source；mask是当前行18列finite值的OR，变换前按输入finite累计，之后缺失填0（`cnn/data/schema.py:107-116,181-189`；`cnn/data/scaler.py:379-397`）。mask自身不读未来日或eligibility表。
- quant exporter按上市日期/交易日历建行网格，再left-merge因子；因子缺失保留NaN，`bfill`仅用于TOT_SHARE，不作用于两融因子（`scripts/export_training_data.py:602-642,752-758`）。当前源码路径未发现两融值未来回填或按当前eligibility截断；该特定F60产物的生成版本仍未绑定。

## 小投影与真实 artifact 对齐

- W1两代码投影`C:/Users/yanwen/AppData/Local/Temp/opencode/signal_probe_W1_two_codes/input.parquet`：4,132行、55列，000001.SZ/600519.SH，2013-01-04至2021-07-05，含18列两融数据。六个`_ts`列按raw重算trailing20/min5，各列有效重叠点均吻合（约3,662–4,120点）。两股票不能独立复核全市场CS rank。
- 低IO实际artifact探针：SQLite URI `mode=ro`、`PRAGMA query_only=ON`，只查`margin_detail`中两代码`20201201..20210705`；查询计划确认索引`idx_margin_detail_code_date(证券代码,交易日期)`范围搜索。按每股融资余额T/前第5个实际margin观测值−1重算。
- 比较2021-01-04至2021-06-30共236对：同日T对齐0/236吻合（误差≤1e-12），最大误差0.12341740781562605，中位0.014505739607212076；下一个实际沪深300交易日T+1对齐236/236吻合，最大误差0，重算值/投影值缺失均0。
- 春节例：源T=2021-02-10映射到2021-02-18；000001.SZ raw=0.05611508640212959，600519.SH raw=0.09365474206415025。两代码各覆盖118/118个H1沪深300交易日。
- 该结果支持两代码、该窗口、该raw列在现存投影中的T+1对齐；不外推全市场或其它列。当前DB与投影数值吻合，不证明DB从未修订或F60整体构建版本。详细样本、缺失和指标在JSON中。

## float_shares as-of边界

- `MarginFactorPreprocessor._load_float_shares`读取`equity_structure`的流通A股、变动日期、公告日期、是否有效；`_build_as_of_series`过滤有效行，按(变动日期,公告日期)排序并对同一变动日期保留公告日最新版本，随后**以变动日期作为生效索引**，计算侧按日期ffill（`margin_preprocessor.py:112-140,234-259`; `_shared_utils.py:10-73`）。
- 公告日只用于同变动日期版本tie-break，不作为可用日。若晚公告更正历史变动，最新更正值可能追溯用于公告前日期，存在潜在PIT前视；本次未查股本记录、未量化影响范围。

## 限制

横截面rank不能用两只股票投影单独复算；raw公式本轮未从源表与原始K线独立逐值复算。供应商实际发布时间、F60 footer/扩展入口版本绑定、DB历史不可变性均未知。**这是特征时点证据，不是成交可行、模型绩效或PIT整体PASS。**
