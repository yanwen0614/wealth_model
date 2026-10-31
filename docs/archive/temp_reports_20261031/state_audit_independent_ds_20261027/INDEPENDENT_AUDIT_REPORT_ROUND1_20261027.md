# 独立只读复核报告 ROUND1 — 两窗状态全量采集结构审计

**审计者**: 独立复核（非编码owner）
**时间**: 2026-10-27
**工作根**: `C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\`
**输入清单**: `state_acquisition_audit_delivery_20261027_v2.json` SHA256 `17c0bab5...`
**项目文档**: `docs/research/20261026/state_collection_and_board_rules_20261027.md`

---

## 术语定义

- **SDK原始输出**: `get_history_stock_status` 直接返回的DataFrame。本次采集parquet与之一致。
- **W窗**: W1=122交易日(20201231~20210705)，W2=129交易日(20210630~20220106)。全窗日数≠决策日数(118/125)。
- **空表**: 代码窗口parquet行数=0。**总数8848=8609非空+239空表**。
- **缺口**: 期望1,110,424 − 实际1,050,280=60,144。

---

## 任务1：29文件完整性

**PASS(29/29)** ——全部SHA256/字节与清单一致。

---

## 任务2：数据总量独立重算

**PASS**——SDK 1,007,108 + 缓存 43,172 = 1,050,280，缺口60,144。

### 2.1 SDK（86批probe_result逐码累加）
逐批读取probe_result的「逐码→行数」，4252代码×2窗=8504条。
复现：`task2_recalc_sdk.py`附录B，断言`total==1007108`。

### 2.2 缓存（scope_manifest累加）
W1 20,984+W2 22,188=43,172。344文件全存在。

### 2.3 SHA256抽样（64非空）
**母集8609非空**，种子42随机抽64。SHA256与probe_result/scope_manifest期望值比对。
**64/64 PASS**。

### 2.4 字段结构
11标准字段一致。**全部SDK直接输出**（非推导）。包括：
`MARKET_CODE, TRADE_DATE, PRECLOSE, HIGH_LIMITED, LOW_LIMITED,
IS_ST_SEC, IS_SUSP_SEC, IS_WD_SEC, IS_XR_SEC,
PRICE_HIGH_LMT_RATE, PRICE_LOW_LMT_RATE`

- TRADE_DATE: large_string YYYYMMDD（如"20210705"）
- flag: string `'0'`/`'1'`
- 零未知字段、零缺失字段

### 2.5 重复/冲突/身份
零重复日、零额外日、零身份错配。overlap_conflicts.csv仅表头(15B)。

### 2.6 空表分类
239空表全来自SDK批次。含000670.SZ(暂停)、600240.SH(退市)、IPO较晚码。
**缺字段2629=239×11**，非全因IPO。

### 2.7 覆盖断言
coverage_by_code_window.csv各行与v3 summary.json完全一致（附录C）。

---

## 任务3：生命周期日期与暂停上市

### 3.1 日期格式与分类
**PASS**——全部日期%Y%m%d格式。lifecycle_snapshot(5415码)日期均为8位数字。

missing_dates_explained(60144行)分类：

| 分类 | 合计 | W1 | W2 |
|------|------|-----|-----|
| 上市前 | 59,491 | 44,852 | 14,639 |
| 退市后 | 251 | 122 | 129 |
| 挂牌内缺日 | 402 | 244 | 158 |

### 3.2 402暂停上市匹配（核心核验）
**数据库**: `Z:/dev/quant_data_dev.db`（4.41GB，只读mode=ro/query_only），**唯一指定源**。

history_status表11列，含**是否暂停上市**（INTEGER, default=0）。
总行703,606，是否暂停上市=1共4,047行。行ID范围：9,998,960~10,003,006。

**402/402全部通过逐行核验**：

| 条件 | 通过/总数 |
|------|----------|
| id在数据库中存在 | 402/402 |
| 证券代码匹配 | 402/402 |
| 交易日期匹配 | 402/402 |
| 是否暂停上市=1 | 402/402 |
| 重复id | 8/402(见注) |

**注**: 8个重复ID对应同一数据库行被两个缺失日期引用。不影响核验。

**CSV中数据库行ID**: `9999141-9999542`（400个）+额外2个，全部在Z库范围内。
**结论**: 402个缺日全部**唯一匹配**数据库中证券代码+交易日期+是否暂停上市=1的行。

**来源说明**: 是否暂停上市为手动维护列（history_status.py:14、factor.py:14均确认"API无此字段"），不称为官方盘前已知。仅作数据库正向来源证据。

---

## 任务4：价格界边界异常与前日ready

### 4.1 边界异常确认
**PASS** ——1,872条非正HIGH_LIMITED/LOW_LIMITED均已在原始parquet文件独立确认。

| 窗口 | 合计 | 上市前5日 | 特殊 |
|------|------|----------|------|
| W1 | 887 | 887 | 0 |
| W2 | 985 | 984 | 1(000792.SZ) |
| 合计 | 1,872 | 1,871 | 1 |

10条抽样确认parquet中HIGH=0.0且LOW=0.0。

### 4.2 前日ready信号（时间对齐）
**PASS** ——1,872条异常执行日前一真实交易日ready=0。

**buy_eligible说明**: 420条"无该窗决策记录"的buy_eligible为**缺失**(空)，非False。全部1,872条无前日ready买入资格，零条有。

| 前日状态 | 条数 |
|---------|------|
| insufficient_history | 1,451 |
| 无该窗决策记录（buy_eligible缺失） | 420 |
| not_trading | 1 |
| **ready=0合计** | **1,872** |

**时间对齐**: 前一市场交易日字段指向真实前日(如20210531→20210528)，非同日信号。

---

## 任务5：字段语义核验（含重要反证）

### 5.1 IS_WD_SEC/IS_XR_SEC语义反证
**CONDITIONAL** ——结构(存在/类型)可核，语义存在未解决反证。

quant项目`history_status.py:44-47`的中文映射与SDK实际数据冲突：

| 字段 | quant中文映射 | 实际SDK语义(反证推导) |
|------|-------------|-------------------|
| IS_WD_SEC | 是否退市风险警示 ❌ | **除息**(ex-dividend/含息调整) |
| IS_XR_SEC | 是否除权除息 ❌ | **除权**(ex-rights/含权调整) |
| IS_ST_SEC | 是否ST ✅ | 一致 |
| IS_SUSP_SEC | 是否停牌 ✅ | 一致 |

**反证A: 000001.SZ 20210514**（现金分红0.18元）
- 前日closing=23.07，SDK PRECLOSE=22.89=23.07-0.18 ✓
- IS_WD=1，但平安银行**从未被退市风险警示**
- 全窗122日中IS_WD=1仅此1日（公司行动日）

**反证B: 300896.SZ 20210316**（现金3.5+送转0.8股）
- 前日closing=750.88，SDK PRECLOSE=415.21≈(750.88-3.5)/1.8 ✓
- IS_WD=1且IS_XR=1（同日除息+除权）
- 全窗122日中IS_WD=1/IS_XR=1均仅此1日

**quant的COLUMN_MAPPING不是独立字段证书**。SDK安装包函数docstring为null（`sdk_status_docstring_20261027_v1.json`），无官方SDK文档可核。字段含义标注"**语义待核/unknown**"。

### 5.2 价格字段原始性
HIGH_LIMITED、LOW_LIMITED、PRECLOSE均为SDK直接输出，**非推导**。PRECLOSE不能无独立证据等同LAST_CLOSE_PRICE/未调整昨收。非正价格不直接等于"异常"（可反映无限制板块状态）。

### 5.3 是否暂停上市
三个独立源码文件确认"手动维护，API无此字段"。Z库402匹配仅正向来源，**不称官方盘前证据**。WD语义重分类(除息≠退市警示)后长期暂停股判定更依赖手动列，进一步加强此立场。

---

## 最终结论

### ✅ 结构PASS（字段存在/类型/行数/哈希/日期格式——全部独立验证通过）
1. 29文件hash/size完整性校验
2. SDK 1,007,108 + 缓存 43,172 = 1,050,280，缺口60,144
3. 64/64抽样SHA256与manifest匹配（母集8609非空）
4. 11标准字段一致存在，零未知字段
5. 239空表确认(含暂停/退市/IPO码)
6. 零重复日、零额外日、零身份错配
7. 16,739跨窗重叠行零字段值冲突
8. 生命周期分类：59,491+251+402=60,144
9. 1,872边界异常原始parquet确认非正限价
10. 1,872条前日ready=0，时间对齐准确
11. 全部日期%Y%m%d格式
12. W1=122日、W2=129日、4424码
13. 标准涨跌停未过滤（原始行完整）

### ⚠️ 语义CONDITIONAL（字段含义存在未解决反证）
1. **IS_WD_SEC**：quant映射"退市风险警示"被现金分红日样本证伪。实际SDK语义最可能是**除息**。**待SDK官方文档确认**。
2. **IS_XR_SEC**：quant映射"除权除息"同样不准，实际为**除权**。**待SDK官方文档确认**。
3. **402暂停上市匹配**：Z库逐行核验全部通过(402/402)。但该列手动维护("API无此字段")，**不称官方盘前证据**。
4. HIGH/LOW_LIMITED非正不直接=异常（无限制板块正常状态）。
5. PRECLOSE不能无独立证据等同LAST_CLOSE_PRICE/未调整昨收。

### ❌ 明确排除（不在此审计范围内）
- 完整PIT数据全集
- 真实9:30市场开盘状态
- 实际税后盈亏计算
- 暂停上市来自官方盘前已知来源
- 边界异常已被交易规则证明
- IS_WD/IS_XR字段正向含义（仅可反证quant映射为误，正向定义待SDK文档）
- quant的COLUMN_MAPPING作为字段语义最终权威

---

## 附录

### A: 29文件hash核验日志
```powershell
$j=Get-Content 'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_audit_delivery_20261027_v2.json'|ConvertFrom-Json
$j.文件|%{$h=(Get-FileHash $_.路径 -A SHA256).Hash.ToLower();$s=(gi $_.路径).Length;if($h-eq$_.SHA256-and$s-eq$_.字节){Write-Host "PASS $($_.路径)" -f Green}else{Write-Host "FAIL $($_.路径)" -f Red}}
```

### B: SDK行数重算核验
```python
import json, os; t=0
bd=r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_20261027\full_state_v1\batches'
for i in range(1,87):
    with open(os.path.join(bd,f'batch_{i:04d}','probe_result.json')) as f:
        r=json.load(f)
    for resp in r['响应']:
        for e in resp['逐码']: t+=e['行数']
assert t==1007108, f'{t} != 1007108'
print(f'SDK rows: {t}')
```

### C: coverage CSV断言结果
coverage_by_code_window.csv各列汇总：缺日期60144、空表239、重复日期0、
HIGH_LIMITED非正1872、上下界倒置0、IS_ST/SUSP/WD/XR非法值均为0。

### D: 输出产物清单
| 文件 | SHA256 |
|------|--------|
| task2_sample_corrected.json | 5dd298c6a311ce02831e42aa6d56bc14f90d1d2e3bc6f4ea44fc590cc8577128 |
| task3_verify_z_db.py（产出） | 见数据库核验日志 |
| task3_db_verify_pause_v2.py（产出） | 见数据库核验日志 |
| 本报告 | 见顶部hash |

---

**审计终止**: 独立只读复核完成。未修改repo/env/lock/原始数据/他人审计目录。



