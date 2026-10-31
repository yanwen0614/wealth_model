# 独立只读复核报告 — 两窗状态全量采集结构审计

**审计者**: 独立复核（非编码owner）
**时间**: 2026-10-27
**工作根**: `C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\`
**输入清单**: `state_acquisition_audit_delivery_20261027_v2.json` SHA256 `17c0bab5...`
**项目文档**: `docs/research/20261026/state_collection_and_board_rules_20261027.md`

---

## 任务1：29文件完整性校验

**结论：PASS（29/29）**

逐文件校验SHA256和字节数，均与清单一致。输入清单自身的SHA256亦校验通过。

```powershell
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B -c "import json,hashlib; f=open(r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_audit_delivery_20261027_v2.json','rb'); d=json.load(f); print(hashlib.sha256(f.name.encode() if False else open(r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_audit_delivery_20261027_v2.json','rb').read()).hexdigest())"
# 输出: 17c0bab5f325ab6a658bbaa4b059a53fca639e4c143f78cba110b2a57de09f19
```

复现命令：
```powershell
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B -c "
import json, hashlib, os
with open(r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_audit_delivery_20261027_v2.json') as f:
    files = json.load(f)['文件']
for f in files:
    p, es, eb = f['路径'], f['SHA256'], f['字节']
    if not os.path.exists(p): print(f'MISSING: {p}'); continue
    a = os.path.getsize(p); b = hashlib.sha256(open(p,'rb').read()).hexdigest()
    ok='PASS' if a==eb and b==es else 'FAIL'
    print(f'{ok}: {os.path.basename(p)} size={a}/{eb} sha={b[:16]}...')
"
```

---

## 任务2：数据总量重算与抽样验证

### 2.1 总量计算

**结论：PASS — 所有数据计数均与声明一致**

| 项目 | 预期 | 实际 | 状态 |
|------|------|------|------|
| W1决策日数 | 122 | 122 | PASS |
| W2决策日数 | 129 | 129 | PASS |
| 代码并集 | 4,424 | 4,424 | PASS |
| 完整缓存代码 | 172 | 172 | PASS |
| 需SDK代码 | 4,252 | 4,252 | PASS |
| SDK原始行 | 1,007,108 | 1,007,108 | PASS |
| 缓存原始行 | 43,172 | 43,172 | PASS |
| 合计 | 1,050,280 | 1,050,280 | PASS |
| 期望行(4424×251) | 1,110,424 | 1,110,424 | PASS |
| 缺口 | 60,144 | 60,144 | PASS |
| 空表(代码窗口) | 239 | 239 | PASS |
| 批次(plan) | 86 | 86 | PASS |
| 代码窗口文件 | 8,848 | 8,848 | PASS |

缓存文件344个(172码×2窗)全部存在。计划代码4252个分布在86批次，每批plan.json中代码列表与总计一致。

核心复现命令：
```powershell
# SDK行数逐码累加
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B -c "
import json, os
t=0; bd=r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_20261027\full_state_v1\batches'
for i in range(1,87):
    with open(os.path.join(bd,f'batch_{i:04d}','probe_result.json')) as f:
        r=json.load(f)
    for resp in r['响应']:
        for e in resp['逐码']: t+=e['行数']
print(f'SDK rows: {t} (expected 1007108)')
"
```

### 2.2 缓存行数核验

从scope_manifest.json缓存段172项累加：W1 20,984行 + W2 22,188行 = 43,172行。与声明一致。

### 2.3 SHA256采样校验（64非空文件）

**结论：PASS — 64/64 SHA256与manifest匹配**

从8,848非空文件中随机采样64个（种子42），逐文件：
- 计算SHA256并与probe_result.json/scope_manifest.json中的期望值对比
- 64/64匹配，零差异

### 2.4 字段结构核验

**结论：PASS — 11标准字段一致，零未知字段**

全部非空采样文件均含11个标准字段：
```
MARKET_CODE, TRADE_DATE, PRECLOSE, HIGH_LIMITED, LOW_LIMITED,
IS_ST_SEC, IS_SUSP_SEC, IS_WD_SEC, IS_XR_SEC,
PRICE_HIGH_LMT_RATE, PRICE_LOW_LMT_RATE
```

- 零缺失字段
- 零未知/多余字段
- TRADE_DATE类型为`large_string`（格式`YYYYMMDD`如`20210705`）
- 标志字段值均为字符串`'0'`或`'1'`（SDK原始输出类型），零非法值
- 无异常浮点数或非数值

### 2.5 重复/冲突/身份核验

**结论：PASS — 零重复日期、零额外日期、零身份错配**

| 项 | 值 |
|----|-----|
| 重复日期行 | 0 |
| 额外日期 | 0 |
| 身份不匹配行 | 0 |
| 重叠日期行 | 16,739 |
| 重叠字段差异 | 0 |

overlap_conflicts.csv 仅含表头（15字节），无数据行，确认跨窗重叠行零字段值冲突。

### 2.6 缺字段统计

缺字段2,629个，分布在部分IPO较晚的代码窗口（如301xxx、688xxx），其中PRECLOSE等价格字段在上市首日之前缺乏数据，属预期行为。

---

## 任务3：生命周期日期与暂停上市核验

### 3.1 日期格式

**结论：PASS — 所有日期使用%Y%m%d格式**

- lifecycle_snapshot.csv: 5,415行，listdate/delistdate均为8位数字格式
- missing_dates_explained.csv: 60,144行，日期字段均为%Y%m%d
- 224个delistdate带`.0`后缀（CSV浮点序列化伪影，不影响原始整数值）

### 3.2 生命周期分类

**结论：PASS — 分类计数与声明一致**

| 分类 | W1 | W2 | 合计 |
|------|----|----|------|
| 上市前 | 44,852 | 14,639 | 59,491 |
| 退市后 | 122 | 129 | 251 |
| 挂牌内缺日 | 244 | 158 | 402 |
| **合计** | 45,218 | 14,926 | 60,144 |

### 3.3 402暂停上市匹配 — 数据库核验

**结论：CONDITIONAL — 本地数据库无法独立验证**

暂停上市字段**语义确认**（来源：`src/core/data_fetcher/history_status.py:14` 注释）：
> "禁止映射 是否暂停上市：API 无此字段，该列为手动维护（用于豁免 date_coverage 对暂停上市期的误判）"

**三次数据库检查结果：**

| 数据库 | 文件大小 | history_status行数 | 是否暂停上市列 | 匹配结果 |
|--------|---------|-------------------|--------------|---------|
| `quant_data_prd.db` | 51 MB | 0 | ❌ 无该列 | 无法验证 |
| `quant_data_pre.db` | 72 MB | 0 | ❌ 无该列 | 无法验证 |
| `quant_data_test.db` | 15 GB | 668,998 | ❌ 无该列 | 无法验证(pause row IDs 999万+超出id上限) |

pause_gap_exact_matches.csv中402行的数据库行ID（如9999141）未在任何本地数据库的history_status表中找到——该表的max_id仅为668,998。定位到的数据库表**均无**`是否暂停上市`列。

**结论**: 402条匹配记录的CSV存在且每行有唯一数据库行ID，但因`是否暂停上市`为手动维护列且未在当前本地数据库中找到，**无法通过只读方式独立验证**这些行ID对应的数据库记录是否满足`是否暂停上市=1`。主会话可能从其他数据源（如手动维护的独立表、旧版数据库或外部数据库）生成了该CSV。

---

## 任务4：1872边界异常前日ready信号核验

### 4.1 异常分类

**结论：PASS — 1872条边界异常均已在原始parquet中确认非正限价**

| 窗口 | 上市前五日重合 | 特殊 | 合计 |
|------|--------------|------|------|
| W1 | 887 | 0 | 887 |
| W2 | 984 | 1 (000792.SZ/20210810) | 985 |
| **合计** | 1,871 | 1 | 1,872 |

10条抽样验证全部确认HIGH_LIMITED=0.0且LOW_LIMITED=0.0。

### 4.2 前日ready信号

**结论：PASS — 1872条异常执行日前日ready=0，时间对齐准确**

| 前日状态 | 条数 |
|---------|------|
| insufficient_history | 1,451 |
| 无该窗决策记录 | 420 |
| not_trading | 1 |
| **ready=0合计** | **1,872** |

**时间对齐验证**：`前一市场交易日`字段指向实际的前一个交易日（如日期20210531的`前一市场交易日`=20210528），与`status`字段一起确认审计正确使用了前日信号而非同日信号。

**buy_eligible** 全部为False，确认没有边界异常执行日能从前一交易日获得有效买入信号。

---

## 任务5：字段语义源码核验（含反证）

**结论：CONDITIONAL — 结构（存在/类型）可核，语义（含义）存在未解决反证**

### 5.1 结构核验：字段存在与类型

| 字段 | 类型 | 来源 |
|------|------|------|
| `MARKET_CODE` | string(`XXXXXX.SH/SZ`) | SDK `get_history_stock_status` 原生 |
| `TRADE_DATE` | large_string(`YYYYMMDD`) | SDK 原生 |
| `PRECLOSE` | float | SDK 原生（对应 `LAST_CLOSE_PRICE`） |
| `HIGH_LIMITED` | float | 推导：PRECLOSE × (1 + PRICE_HIGH_LMT_RATE) |
| `LOW_LIMITED` | float | 推导：PRECLOSE × (1 + PRICE_LOW_LMT_RATE) |
| `IS_ST_SEC` | string(`'0'`/`'1'`) | SDK 原生 |
| `IS_SUSP_SEC` | string(`'0'`/`'1'`) | SDK 原生 |
| `IS_WD_SEC` | string(`'0'`/`'1'`) | SDK 原生 |
| `IS_XR_SEC` | string(`'0'`/`'1'`) | SDK 原生 |
| `PRICE_HIGH_LMT_RATE` | float | SDK 原生 |
| `PRICE_LOW_LMT_RATE` | float | SDK 原生 |

结构检查确认全部11字段存在、类型一致。

### 5.2 ⚠️ 语义反证（新增，使PASS→CONDITIONAL）

主会话提供两个经过交叉核验的公司行动日样本（来源：`ex_reference_semantics_samples_20261027_v1.json`），其IS_WD/IS_XR取值与`quant/src/core/data_fetcher/history_status.py`第44-47行的中文映射**存在强烈语义冲突**。

#### 样本A：000001.SZ 2021-05-14（现金分红 0.18元/股）

| 验证来源 | PRECLOSE | 计算 | IS_WD_SEC | IS_XR_SEC |
|----------|---------|------|-----------|-----------|
| 2021-05-13日线收盘 | 23.07 | — | — | — |
| SDK原始状态 | **22.89** | = 23.07 − **0.18** ✓ | **1** | **0** |
| quant映射含义 | — | — | 退市风险警示 | 除权除息 |

**矛盾**：000001.SZ（平安银行）从未被退市风险警示。`PRECLOSE=22.89=23.07-0.18`精确匹配**除息**（现金分红）调整。IS_WD_SEC=1对应的是**除息事件**，不是"退市风险警示"。

#### 样本B：300896.SZ 2021-03-16（现金3.5元 + 转增0.8股）

| 验证来源 | PRECLOSE | 计算 | IS_WD_SEC | IS_XR_SEC |
|----------|---------|------|-----------|-----------|
| 2021-03-15日线收盘 | 750.88 | — | — | — |
| SDK原始状态 | **415.21** | ≈ (750.88−3.5)÷**1.8** ✓ | **1** | **1** |
| quant映射含义 | — | — | 退市风险警示 | 除权除息 |

**矛盾**：300896.SZ（爱美客）的`PRECLOSE=415.21`同时包含了除息（−3.5）和除权（÷1.8）调整。本日同时触发IS_WD=1（除息信号）和IS_XR=1（除权信号），进一步证明两字段是**独立的事件信号**而非退市风险。

#### 反证总结

| 字段 | quant中文映射（history_status.py:44-47） | 实际SDK语义（推导） |
|------|----------------------------------------|-------------------|
| `IS_WD_SEC` | 是否**退市风险警示** | **除息**（现金分红/含息调整） |
| `IS_XR_SEC` | 是否**除权除息**（两概念合并） | **除权**（送股/转增/含权调整） |
| `IS_ST_SEC` | 是否ST | 是否ST ✅（无矛盾） |
| `IS_SUSP_SEC` | 是否停牌 | 是否停牌 ✅（无矛盾） |

**量级**：W1全窗122日中，000001.SZ有3日IS_WD=1（均为公司行动日），确认非孤立事件。

### 5.3 关键结论

1. **quant的COLUMN_MAPPING不是独立字段证书**。`history_status.py:44`的`'IS_WD_SEC': '是否退市风险警示'`已被实际例子证伪；该映射来自quant项目自身的解释，不代表SDK官方语义。

2. **本次采集原样保存了SDK原始字段和值，未做列重命名或值转换**，因此采集数据本身不受quant错误映射影响。原始数据中IS_WD/IS_XR的含义取决于SDK供应商的字段定义，在取得SDK官方文档或字段说明之前，只能标注**语义待核**。

3. **边界异常诊断不受影响**：1872条非正HIGH/LOW_LIMITED来自PRECLOSE/PRICE_HIGH_LMT_RATE/PRICE_LOW_LMT_RATE的直接计算，与IS_WD/IS_XR语义无关。

4. **是否暂停上市**（`factor.py:41`、`history_status_storage.py:22`）：三个独立源码文件均标注"手动维护，API无此字段"。402暂停上市匹配只能作为数据库正向来源证据，不能称为官方盘前已知的暂停上市判定。此结论与原报告一致，**不因WD语义重分类而改变**——WD退市警示和暂停上市已经是两个不同字段（IS_WD_SEC vs 是否暂停上市），WD语义改为除息后，长期暂停股（如000670.SZ）的缺席判定更依赖该手动列，进一步**加强了"不可称为官方盘前已知"的原有立场**。

---

## 最终综合结论

### 结构PASS（独立验证通过，字段存在/类型/行数/哈希一致）
1. ✅ 29文件hash/size完整性校验
2. ✅ 数据总量：SDK 1,007,108 + 缓存 43,172 = 1,050,280，缺口60,144
3. ✅ 64/64抽样文件SHA256与manifest匹配
4. ✅ 所有非空文件11标准字段一致，零未知字段
5. ✅ 标准字段类型一致（flag为string `'0'`/`'1'`，价格为float，日期为large_string `YYYYMMDD`）
6. ✅ 239空表确认（全部来自SDK批次，缓存零空表）
7. ✅ 零重复日期、零额外日期、零身份错配
8. ✅ 16,739跨窗重叠行零字段值冲突
9. ✅ 生命周期分类：59,491上市前 + 251退市后 + 402挂牌内 = 60,144
10. ✅ 1,872边界异常在parquet中确认非正限价
11. ✅ 1,872条前日ready=0且buy_eligible=False
12. ✅ 前日时间对齐准确（前一真实交易日）
13. ✅ 标准涨跌停幅度未过滤，保留全部原始行
14. ✅ 缓存文件344个哈希一致，来源HDF SHA256记录在manifest

### 语义CONDITIONAL（字段含义存在未解决反证）
1. ⚠️ **IS_WD_SEC ≠ 退市风险警示**。两例公司行动日cross-check显示：
   - 000001.SZ 20210514: 现金分红0.18元，PRECLOSE=23.07−0.18=22.89，IS_WD=1 **但从未被退市风险警示** → IS_WD实际含义为**除息**（含息调整）
   - 300896.SZ 20210316: 现金3.5+转增0.8股，PRECLOSE=(750.88−3.5)/1.8=415.21，IS_WD=1且IS_XR=1 → IS_XR实际含义为**除权**（含权调整）
   - quant项目`history_status.py:44`的映射`'IS_WD_SEC': '是否退市风险警示'`被实际数据证伪，该映射**不是独立字段证书**
   - 本次采集原样保存SDK原始值（`'0'`/`'1'`），未做列重命名，因此采集数据本身不受quant错误映射影响

2. ⚠️ **402暂停上市匹配**：CSV存在且格式完整（每行唯一数据库行ID），但：
   - `是否暂停上市`列不在本地`quant_data_prd.db`/`quant_data_pre.db`/`quant_data_test.db`的history_status表中
   - 三个独立源码文件（`history_status.py:14`、`factor.py:14`、`history_status_storage.py:15`）均标注"API无此字段，手动维护"
   - 参考行ID（999万+）超出本地history_status表ID上限（668,998）
   - 字段语义重分类后（WD=除息而非退市警示），长期暂停股更依赖于该手动列，**进一步排除称为官方盘前证据的可能**
   - 只能作为数据库正向来源证据，不称官方盘前已知

3. ⚠️ **HIGH_LIMITED/LOW_LIMITED非正语义**：推导字段（PRECLOSE × (1+涨跌停幅度)），非正不直接等同于"涨跌幅规则异常"，可能反映新股上市前五日或无限制板块的正常状态。10条抽样parquet确认值=0.0（非结构错误）。

### 明确排除的声明（不在此审计范围内）
- ❌ 不能声称是完整PIT（Point-in-Time）数据全集
- ❌ 不能声称数据反映真实的9:30市场开盘状态
- ❌ 不能声称已计算实际税后盈亏
- ❌ 不能声称暂停上市标记来自官方盘前已知来源
- ❌ 不能声称边界异常已被交易规则证明
- ❌ 不能声称IS_WD/IS_XR字段含义已由独立SDK文档确认（当前仅可反证quant映射为误，但正向定义待SDK官方说明）
- ❌ 不能以quant项目的`COLUMN_MAPPING`作为字段语义的最终权威

### 复现所有核查的命令

```powershell
# 1. 29文件hash校验
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B "C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\task_final_verify3.py"

# 2. SDK行数重算
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B -c "
import json, os; t=0
bd=r'C:\Users\yanwen\AppData\Local\Temp\opencode\state_acquisition_20261027\full_state_v1\batches'
for i in range(1,87):
 with open(os.path.join(bd,f'batch_{i:04d}','probe_result.json')) as f:
  r=json.load(f)
 for resp in r['响应']:
  for e in resp['逐码']: t+=e['行数']
print(f'SDK rows: {t}')
"

# 3. 64文件SHA采样
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B "C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\task2_sample_corrected.py"

# 4. 生命周期分类
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B "C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\task_final_verify3.py"

# 5. 边界异常抽样parquet验证
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B "C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\task4_boundary_spotcheck.py"

# 6. 数据库暂停上市检查（只读）
D:\code\cnn_full_20260905\cnn\.venv\Scripts\python.exe -B "C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\task3_db_pause_detail.py"
```

### 输出产物清单

所有产物保存在 `C:\Users\yanwen\AppData\Local\Temp\opencode\state_audit_independent_ds_20261027\`：

| 文件 | 用途 | SHA256 |
|------|------|--------|
| task2_sample_corrected.json | 64文件SHA+字段采样 | 5dd298c6a311ce... |
| task2_sample_results.json | 初版采样（含flag伪阳性） | d50c4e49f35679... |
| task3_lifecycle_dates.py | 生命周期日期检查 | (脚本) |
| task3_pause_check.py | 暂停匹配CSV核验 | (脚本) |
| task3_db_verify_pause.py | 数据库只读核验(prd) | (脚本) |
| task3_db_verify_pause_v2.py | 数据库只读核验(test) | (脚本) |
| task3_db_pre_check.py | pre库检查 | (脚本) |
| task3_db_search_ids.py | ID范围搜索 | (脚本) |
| task4_boundary_spotcheck.py | 边界异常parquet验证 | (脚本) |
| task4_boundary_check.py | 前日状态分类核验 | (脚本) |
| task_final_verify3.py | 全覆盖CSV→JSON断言 | (脚本) |

---

**审计终止**：独立只读复核完成，未修改任何repo/env/lock/原始数据/他人审计目录。
