# 来源与检索日志

| 来源 | 实际返回 | 证据用途/限制 |
|---|---|---|
| 新浪分红列表 https://money.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/300502.phtml | 2021-06-01；4.00253、2.71708；登记06-07、除权06-08 | 二级索引，比例精度被截短 |
| 新浪详情 https://money.finance.sina.com.cn/corp/view/vISSUE_ShareBonusDetail.php?stockid=300502&type=1&end_date=2021-06-01 | 实返登记/除权日期；比例约4.00/2.72；“每股碎股”显示-- | 未载目标公告附件 |
| Tavily 搜索 query: `2021-030 新易盛 PDF` | 返回2021年年度报告段落，明确公告日期/编号、调整后比例、总额与实施日 | 非目标公告原件；结果含同一报告多处文字 |
| Tavily 搜索 query: `300502 2021-030 4.002532 2.717082 2021年 权益分派实施公告 PDF` | 新浪列表、搜狐记录等；日期和近似比例一致 | 搜索引擎索引，不替代原始PDF |
| Tavily 搜索 query: `2021年年度权益分派实施公告 成都新易盛通信技术股份有限公司` | 2022-023 2021年度实施公告等 | 不同年度，排除 |
| 巨潮 `/new/hisAnnouncement/query` GET | HTTP 500 | 请求条件含股票、日期、公告编号文本；失败不等于无公告 |
| 巨潮同接口 POST | HTTP 200，JSON `totalAnnouncement=0` | `stock=300502`、2021全年；接口参数组合返回空 |
| 既有报告 `ca_300502_document_search2_20261028/report.md` | 2020-043官方PDF SHA/3页及第2页碎股措辞；2021原件仍未取回 | 2020年公告仅历史旁证 |

本轮直接HTTP请求曾尝试官方巨潮历史查询：第一次 urllib GET 返回 HTTP 500；POST 返回 HTTP 200、空集。新浪HTML字符集在网页抓取工具输出中出现乱码，但页面行项目可由HTML表格数值及搜索索引交叉读取。未保存无法可靠获取的目标PDF。
