# REVIEW_CHECKLIST — 换手 + 行业暴露归因

## 影响范围

| 项 | 内容 |
|---|---|
| 源码变更 | **无**（analyze 模式） |
| 新增文件 | `docs/agent/task/20260916_0010_turnover-industry-attribution/*.md` |
| 新增数据产物 | `logs/attribution_20260916/*.csv`（`logs/` 已被 `.gitignore` 忽略，不入库） |
| 外部数据读取 | `logs/backtest_*/holdings_*.csv`、`Z:/test/industry_weight/8010*0.SI.parquet`、`Z:/test/index_weight/000300.SH.parquet` |
| 编译/测试影响 | 无 |

## 质量关卡

| # | 关卡 | 检查点 | 结果 |
|---|---|---|---|
| 1 | 完整性 | 33 个回测目录全部纳入，未遗漏 sbg 24 组 | PASS |
| 2 | 正确性 | 换手/持仓期与 `n_trades`、`avg_pos` 自洽（b500_s5 159 笔 / 146 code / 中位 7 天） | PASS |
| 3 | 口径 | 行业映射 point-in-time；未持有日补 0 | PASS（初版未补 0，已修） |
| 4 | 恒等 | `t0.00` 与 `t0.02` 换手/超额逐位一致 | PASS |
| 5 | 复算 | `Σ(weight×ret_net)` 与 metrics `annual` 同号同量级 | PASS（简单求和近似） |
| 6 | 可复现 | 脚本 + 产物 CSV 路径已在报告记录 | PASS |

## 已知局限

- 行业 P&L 为简单求和近似（未复利、未计现金拖累），仅用于横向比较。
- 日频换手以建仓权重近似，未反映持仓市值漂移。
- 单 seed、单区间（160 交易日）、小组合，统计效力弱。
- 无行业指数价格数据，未做 Brinson 式基准相对归因。
