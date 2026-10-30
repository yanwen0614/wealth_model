# F53 五个财务特征：时点（PIT）只读审计

核查范围：仅 `gross_margin`、`net_margin`、`roe`、`roa`、`debt_to_equity`；检查 F60 导出 footer 对应 quant commit `26c3db036a266f5765d8cdee4ef352c56d6ee1e9` 及当前 quant 源码。未查 PE/PB/growth 未用列、未查询数据库、未扫大 parquet、未改代码、未跑收益或 API。结论是源码路径审计，不等于实际产物逐值重验。

## 先给结论

**五列整体不能给 PIT PASS。** 源码已采用公告日期前向填充，比按财报期末应用更安全；但仍有三类未解除风险：

1. `实际公告日期` 缺失时回退到 `报告期`，可能将未来披露值提前到季度末。
2. 只有公告日期、无披露时分秒；当日披露值直接落在同一交易日因子上，无法确认收盘决策时已可知。
3. 同报告期更正版本先取当前数据中最新版本，再跨所有报告期计算 TTM；后来的历史报告更正值可能进入更早报告事件的 TTM。现有数据/快照没有可供本审计复核的逐行来源版本时间线。

**最小安全替代**：若需要当前即可确认无前视，先从模型输入剔除这五列。仅把公告日期滞后一交易日，可规避日期粒度的同日时点不明，但**不能**修复报告期回退及跨期更正版本问题；要保留五列，需逐报表版本按其当时披露日构造 PIT TTM，并对无实际公告日期记录拒绝/置空。

## 源码路径和计算语义

- F60 导出源提交：`26c3db...` 的 `src/core/factor/financial_preprocessor.py` 已有 `_dedupe_consolidated_report`、`_effective_report_date`、按 effect_date 排序及 reindex(ffill) 逻辑；当前文件对应约 `:192-233, :252-268, :348-380`。数据来自 income、balance_sheet 三表；计算值预先落入 per-code alpha factor parquet。
- 利润表字段映射：`src/core/data_fetcher/income.py:34-50` 将 `REPORTING_PERIOD→报告期`、`ANN_DATE→公告日期`、`ACTUAL_ANN_DATE→实际公告日期`，以及营业收入、营业成本、净利润入库。`src/core/database/models/financial.py:83-105` 按 `(证券代码,报告期,实际公告日期)` 保存多版本。
- 资产负债表字段映射：`src/core/data_fetcher/balance_sheet.py:33-45` 同样保留报告期/公告日/实际公告日，并映射资产总计、负债合计、股东权益；模型 `financial.py:55-80` 以报告期+实际公告日期为唯一键保留版本。
- `_dedupe_consolidated_report` 先筛合并报表类型 `1`（缺类型兜底），按实际公告日降序，每个报告期只留当前记录集合中最新公告版本（当前源码 `financial_preprocessor.py:192-209`）。这解决同报告期多行及更正覆盖，但不是“每个历史决策日看到当时版本”的完整 PIT 版本回放。
- `_effective_report_date` 用 `实际公告日期`；缺列时全退化到报告期，单行值缺失时 `.fillna(report_date)`。同日多报告加纳秒仅用于排序唯一化，不改变交易日级别生效日（`:212-233`）。因此主链不是按季度末应用，但缺实际公告日期会按季度末提前生效。

## 五列逐一追踪

|特征|值来源与时序|PIT判断|
|---|---|---|
|`gross_margin`|`(revenue_TTM-cost_TTM)/revenue_TTM`，income 营业收入/营业成本；`:398-416`|使用披露序列 ffill；有同日、缺实际公告日和 TTM 更正版本风险|
|`net_margin`|`net_profit_TTM/revenue_TTM`，income 净利润/营业收入；`:398-416`|同上；TTM 版本交叉最直接|
|`roe`|`net_profit_TTM/equity`，income + balance_sheet 股东权益；`:398-416`|分子有 TTM 版本风险；分母单报表 as-of ffill，仍受公告日期缺失/同日风险|
|`roa`|`net_profit_TTM/assets`，income + balance_sheet 资产总计；`:398-416`|分子有 TTM 版本风险；分母同上|
|`debt_to_equity`|`liabilities/equity`，balance_sheet 负债合计/股东权益；`:348-360, :412-416`|不经 TTM；按表行时间前向填充，但仍受公告日 fallback、同日可用性及当前最新更正版时间线风险|

收入/成本/净利累计序列以 `report_date` 作 key 后算标准 TTM（`_col_to_report_cum`/`_ttm_standard`：`:126-172`）；单季 TTM 算完映回以 effect_date 为索引的序列（`:290-327`），再在交易日 `reindex(..., method='ffill')`（`:366-380`）。这不是简单把某个“最新值”铺满整段历史：有实际公告日的报表值从其生效日向后持有；但当前版本选择与跨期 TTM 的组合仍可能把后来的更正值带入更早的事件日。

**流通股本不参与这五列。** `_shares_as_of_series`/总股本用于市场资本及 PE/PB 等估值因子（`:285-286, :393-403`），并非五列公式中的分子/分母；不能把“股本 as-of 已做”当作这五列 PIT 证明。ROE/ROA/debt_to_equity 用的是报告资产负债表 equity/assets/liabilities，而非市场流通股本。

## 公告同日及更正版本风险

- **公告时点**：源码只有 `实际公告日期`（YYYYMMDD 日期），没有时间戳/盘前盘后标志。面板在与同一 `trade_date` 对齐时已经包含该日期的财报值。因此对“当日收盘后形成信号”而言，公告当天是否已公布不可确认；收盘后公告会泄漏到当日收盘信号。整日延迟到下一个交易日可保守解决此项。
- **缺失公告日期**：落库字段 nullable；Fetcher 映射存在不证明每条行都填有实际日期。代码明确缺失即退回 report_date，季度末早于真实公告日的记录会提前可见。未查 DB（本任务禁止），缺失数量未知。
- **修订版本**：模型唯一键允许一个报告期按多个实际公告日留版本；源码在每次预计算时按最新公告取一版并丢弃旧版。然后 TTM 在 report_date 序列上全局计算，再映回各报告事件：若某个被引用的旧期报表后来才更正，其更新值可能已被用于更早 effect_date 的 TTM。结构性路径由源码确认；本次没有读取数据来判定哪些 code/date 实际触发，故影响范围未知。
- **资产负债分母的版本**：选中的最新 balance 版本单独按自身 effect_date 前向填充，通常不会在该修订公告日前单独生效；但若实际公告日缺失会回退报告期。并且 ROE/ROA 的 TTM 分子仍有上述跨期版本耦合。

## 因子持久化、导出 merge 与 footer 可追溯性

- `FinancialFactorPreprocessor.run` 计算整段 `trade_dates` 的序列并写入 per-stock 因子文件（当前 `financial_preprocessor.py:539-545,590-620`）；F60 exporter 的 `_export_code` 读 `FactorStorage.load_stock_factors(code)` 后按 `kline_time` left-merge 到行情主表（`scripts/export_training_data.py:322-324,352-360`）。Export merge 不重新判断公告时点，直接消费已存日频值。
- `FactorStorage.save_stock_factors` 对同名非 NaN 新值覆盖旧值，但对**部分 NaN 单元格** `combine_first` 保留旧值（`src/core/factor/storage.py:115-126,161-176`）。若旧因子文件曾有公告前填值，而修正后这些日期变 NaN，局部 NaN 可能留住旧值；全列 NaN 才有显式清旧行为。未检查 F60 所用 per-code 文件，故该风险是否发生未知。
- 该 F60 footer（提交 `26c3db...`）有 git hash、日期范围、export_time、K线/alpha-factor 最新日期和 alpha 列名；不含财务三表行版本、财务数据哈希、factor parquet 内容哈希或逐代码公告日期快照。`export_training_data.py` 当前 `_capture_data_snapshot`（`:340-358`）记录 K线/alpha 最大日期、margin 最大日期、列名，同样没有逐财务源版本身份。`alpha_factor_max_date` 只能证明文件有日期，不能证明每个值所用报告版本。
- **历史训练值能否逐项证明 PIT：不能。** 源码设计支持按公告日期 ffill，但实际产物没有足够来源版本证据，本审计也未逐值扫描大文件。`26c3db` 提交代码已确认同样包含公告日期生效逻辑和财务列 merge，不是当前才新增；这只能证明程序定义，不能证明特定导出时每条源记录实际公告日齐全或旧 parquet 无残留。

## 判定与最小可行处置

|问题|判断|
|---|---|
|按季度末应用吗？|通常不是；有实际公告日则该日期生效，缺失才回退报告期。|
|同日公告收盘前可知吗？|未知；数据只到日，因子当天即生效。|
|五列是否把单个最新财务值直接回填全历史？|代码主路径不是；按报告 effect_date 前向填充。但每报告期当前最新更正版用于全局 TTM，可能有跨期 PIT 泄漏。|
|流通股本是否用于这五列？|否。|
|bfill/merge_asof？|未见 bfill 或 merge_asof；主要为日期索引 `reindex(trade_dates, method='ffill')`。这不自动解决公告时间戳、缺公告日和多版本 TTM。|
|结论|**五列整体暂不通过 PIT 审计。** 对当日收盘决策，缺时分公告和 report_date fallback 已足以阻止 PASS；多版本 TTM 是额外结构性风险。|

无需等待新数据的保守基线：CNN F53 配置先停用这五列；保留它们的研究分支则至少从实际公告日之后第一个交易日才允许使用，并将 `实际公告日期` 缺失值置空/排除。若要恢复成可验收特征，还须构造带披露版本的报告期 as-of TTM（每个历史日期只使用当时已披露的每期版本），明确公告日之后生效时点，并重建/核验历史因子文件，不可只对现有值整体 shift 一天。

注：这里评的是特征信息时点，不是因果推断模块，也不评价这五列的预测收益。
