# 2026-10-26 研究证据索引

本目录归档既有只读研究证据，供主会话审阅与后续工程判断。未重新扫描数据或DB，未复制parquet/SQLite等大型数据，未改业务代码。各报告保留原始采集日期、可复现路径、提交/footer身份及限制；路径指向原始研究环境，当前可用性未重新验证。

|归档文件|主题|核心结论与边界|
|---|---|---|
|[price_lineage.md](price_lineage.md)|价格、量额、复权因子与公司行动|两股逐日支持单位变换；原混合口径只能作研究代理；事件/执行缺口未解除，NO-GO仍在|
|[universe_lineage.md](universe_lineage.md)|PIT股票池与幸存者偏差|定向五只退市股训练/raw均无行；当前F60不是已证明完整的历史全市场股票池，偏差比例未知|
|[financial_pit_audit.md](financial_pit_audit.md)|五个财务特征时点|公告日缺失回退、同日时分未知、TTM更正版本导致结构风险；五列整体不能PIT PASS|
|[margin_time_audit.md](margin_time_audit.md)|两融特征、mask与日期对齐|源码为CS rank、trailing20/min5及落盘T+1；小样与导出代码有明确边界|
|[margin_artifact_probe_2021h1.json](margin_artifact_probe_2021h1.json)|两代码真实artifact窄范围对齐|只读DB范围查询；raw变动列T+1为236/236精确匹配，同日0/236；不外推F60全链|
|[user_data_claims_check.md](user_data_claims_check.md)|用户接口说明与指定dev抽样差异|五退市码raw缺失；history_status无绝对限价；逐项区分接口、表和实际数据|
|[verified_state_source_contract.md](verified_state_source_contract.md)|逐日状态来源契约与本地缓存证据|000001.SZ HDF5 的W1 H1日期118/118匹配；仅支持逐码窄域判断，缺全市场请求成功清单|
|[state_data_acquisition_plan.md](state_data_acquisition_plan.md)|W1状态数据补采方案|复用现有接口，100码/批串行；待授权/额度确认；不写Z库，退市raw与PIT股票池另行补证|

## 身份与范围纠正

- 训练F60 footer身份：git hash `26c3db036a266f5765d8cdee4ef352c56d6ee1e9`，export_time `2026-09-05T15:15:42`，fingerprint `v1_20130101-20260831_26c3db036a26`。这些标识不能证明扩展F60入口与同一不可变构建完全绑定。
- 价格/公司行动抽查的数据库为`Z:/dev/quant_data_dev.db`，SQLite只读；两股行情文件与两代码投影见各报告精确路径。用户数据差异报告也记录显式DB路径及环境变量限制。
- **因子日期：全表 backward_factor 最大日为2026-09-29（既有年度聚合，62257行/5415码）；2025-12-19仅为600519.SH等抽查股的最新日。** 不把单股截止日写成全表覆盖上限。
- 所有证据均为限定样本/源码审查；不能升级为全市场覆盖、完整PIT、成交可行性、税务完整或绩效PASS。尚未证明最终成本后非负且跑赢大盘目标已实现。
- 主会话此前提交95e3443、4ff2e2b、970d9d0；本归档未提交/推送。`ENGINEERING_STATUS.md`及同目录公司行动文档未修改。
