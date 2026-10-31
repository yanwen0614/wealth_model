# 本地来源扫描结果 2026-10-27 13:38

## 任务说明
核实 000670.SZ 和 000792.SZ 暂停上市/恢复上市生效日的官方来源。

## local quant 代码库中发现的来源

### 唯一来源文件
`D:\code\quant\scripts\backfill_paused_listing.py` 第 27-43 行，硬编码区间表：

| 代码 | 暂停起始 | 暂停结束 | 备注（脚本内原文） |
|------|----------|----------|-------------------|
| 000670.SZ | 2020-04-07 | 2022-08-19 | `# *ST盈方 暂停上市 2020-04-07~2022-08-19 公告` |
| 000792.SZ | 2020-05-22 | 2021-08-09 | `# 000792 暂停区间` |

### 来源说明（脚本第 28 行）
> `# 来源：date_coverage B类 13只长洞 + 公告确认（000670/000155/000995等暂停上市公告）`

### 关键缺失
- **没有存储任何官方公告 URL、公告编号、深交所链接或巨潮链接**
- "公告确认"无具体引用（无公告ID、无PDF、无截图）
- 审查清单（REVIEW_CHECKLIST.md）第 15 行明确：
  > "13 只暂停上市区间清单以 000670 20200407-20220819 为例，其余 12 只区间在回填脚本中硬编码補全，需业务方提供完整清单"
  说明清单完整性依赖业务方，代码库无原始来源记录。

### 其他相关文件
- `docs/agent/task_archive/20260829_0029_paused-listing-history-status/PLAN.md`
- `docs/agent/task_archive/20260829_0029_paused-listing-history-status/REVIEW_CHECKLIST.md`
- `docs/agent/task_archive/20260829_0029_paused-listing-history-status/HARNESS_PROGRESS.md`

### SZSE API / CNINFO URL
在整个 quant 代码库的 docs/ 和 scripts/ 中未发现任何官方公告 URL。

---

## 结论
本地 quant 代码库**仅提供硬编码区间**，**无任何可直接追溯的官方来源**（URL/公告编号/PDF）。
