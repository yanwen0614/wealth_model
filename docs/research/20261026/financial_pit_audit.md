# F53 五个财务特征：时点（PIT）只读审计

核查范围：`gross_margin`、`net_margin`、`roe`、`roa`、`debt_to_equity`；检查F60 footer对应quant提交`26c3db036a266f5765d8cdee4ef352c56d6ee1e9`及当前源码。未查PE/PB/growth等未用列、未查询数据库、未扫大parquet、未改代码、未跑收益或API。结论为源码路径审计，不等于实际产物逐值重验。

## 结论

**五列整体不能给 PIT PASS。** 源码按公告日期前向填充，比按财报期末应用安全，但有三项未解除风险：

1. `实际公告日期` 缺失时回退到 `报告期`，可能把未来披露值提前到季度末。
2. 只有公告日期、无披露时分秒；当日披露直接进入同日因子，无法确认收盘决策时已可知。
3. 同报告期当前最新更正版先被选出，再跨报告期计算TTM；后来的历史更正可能进入更早报告事件的TTM。无逐行源版本时间线可供审计复核。

最小安全替代：当前研究基线先剔除五列。仅延迟公告日不能修复报告期回退或跨期更正；保留特征须按当时已披露的每期版本构造 PIT TTM，并对缺公告日记录拒绝/置空。

## 源码路径和计算语义

- F60源提交`26c3db...`的`src/core/factor/financial_preprocessor.py`已有`_dedupe_consolidated_report`、`_effective_report_date`、effect_date排序及reindex(ffill)逻辑；当前文件约`:192-233,:252-268,:348-380`。数据来自income、balance_sheet三表，预先落入per-code alpha factor parquet。
- 字段映射：`src/core/data_fetcher/income.py:34-50`与`balance_sheet.py:33-45`保留报告期、公告日期、实际公告日期；模型`src/core/database/models/financial.py:55-105`按代码/报告期/实际公告日期保存多版本。
- `_dedupe_consolidated_report`筛合并报表类型1（缺类型兜底），按实际公告日降序，每报告期留当前数据集合最新版本（`financial_preprocessor.py:192-209`）。这不是历史决策日的版本回放。
- `_effective_report_date`使用实际公告日期；缺列或单行缺失时退回报告期（`:212-233`）。同日多报告加纳秒只为排序唯一化，不提供盘中时点。
- 营收/成本/净利累计序列按report_date算标准TTM，映回effect_date后按交易日ffill（`:126-172,:290-327,:366-380`）。有实际公告日的值从该日向后持有；但当前版本选择与跨期TTM组合仍可能前视。

|特征|公式/来源|PIT判断|
|---|---|---|
|gross_margin|(revenue_TTM-cost_TTM)/revenue_TTM|公告日ffill；同日、缺公告日、TTM更正风险|
|net_margin|net_profit_TTM/revenue_TTM|同上；TTM版本交叉最直接|
|roe|net_profit_TTM/equity|分子有TTM版本风险；分母受公告日风险|
|roa|net_profit_TTM/assets|同上|
|debt_to_equity|liabilities/equity|不经TTM；仍受公告日和当前版本风险|

流通股本不参与五列公式；总股本用于市值及PE/PB等估值因子。不能以股本as-of已做当作五列PIT证明；ROE/ROA/debt_to_equity分母来自报表资产负债表。

## 风险、持久化及身份限制

- 公告仅有YYYYMMDD，无时间戳/盘前盘后标志；同日值进入因子，收盘后公告可能泄漏到当日收盘信号。保守处理是整日延迟。
- 公告日缺失数量未知；代码明示回退report_date，可能提前生效。多版本模型保留历史公告，但预处理选当前最新版再计算全局TTM，结构上可能将后来的旧期更正值带入更早effect_date；本次没有查DB判定哪些实际触发。
- `FactorStorage.save_stock_factors` 对非NaN新值覆盖，部分NaN以`combine_first`保留旧值；旧公告前填充值若被修正为NaN，可能残留。未检查F60各per-code文件，影响未知。
- exporter按kline_time left-merge已存日频值，不重新判断公告时点。footer有git hash/日期范围/export_time/K线与alpha factor最新日期和列名，但无财务源版本、财务哈希、factor parquet哈希或逐代码公告快照。历史训练值不能逐项证明PIT。
- 未见bfill/merge_asof；主要用`reindex(trade_dates, method='ffill')`。这不解决公告时间、缺公告日和多版本TTM问题。

|问题|判定|
|---|---|
|按季度末应用？|通常不是；有实际公告日则该日生效，缺失才回退报告期|
|同日公告收盘前可知？|未知；因子当天生效|
|是否把单个最新值回填全历史？|主路径不是；但当前版本用于全局TTM可能跨期泄漏|
|流通股本是否用于五列？|否|
|总体PIT结论|**五列整体暂不通过**；缺时分、公告日fallback与多版本TTM阻止PASS|

若保留研究分支，至少从实际公告日之后首个交易日使用，缺实际公告日期置空/排除；验收还需带披露版本的历史as-of TTM并重建/核验因子文件，不能只整体shift一天。此审计评估时点，不评价预测收益或因果推断。
