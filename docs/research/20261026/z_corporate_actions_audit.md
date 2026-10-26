# Z 库两项公司行动账务核验

## 范围与结论

本次只读核验了 `000001.SZ` 现金分红和 `300896.SZ` 现金加转增事件。脚本从 SQLite 唯一实施行取值，以 100/1000 股预设账户夹具调用现有 core 账户阶段操作，并按 raw 收盘价核对现金、持仓、应收、未上市权益分项 NAV。没有执行订单、计算策略收益或 RankIC。

四组夹具账务分项闭合。结果只证明指定源行和阶段操作下的账务计算闭合，不证明实际成交可行性、公司行动完整覆盖、策略盈利或税后表现。

## 来源与事件

| 标的 | SQLite 行 | 登记日 | 除权/派息/上市 | 税前现金/股 | 转增/股 | raw 除权前→除权日 close |
|---|---:|---|---|---:|---:|---|
| 000001.SZ | 17328 | 2021-05-13 | 2021-05-14 | 0.18 | 无 | 23.07→23.32 |
| 300896.SZ | 70078 | 2021-03-15 | 2021-03-16 | 3.50 | 0.8 | 750.88→439.60 |

事件查询要求每个 `(证券代码, 除权除息日)` 恰好一行，且 `方案进度=3`、`方案是否变更=0`；不唯一或不满足条件即失败。派息日/上市日与除权日同日的事件按 core 现有 operation 顺序执行；派息日现金进入总现金，下一交易日才释放到可用现金。

## 税务与数据边界

- 现金公司行动路径明确为 pretax：应收和到账沿用源税前金额，未扣个人现金红利税。300896 转增税务状态为 unknown；不能按免税处理后宣称全成本结果。
- 已知的 `cash_dividend_20pct_stress` 只是统一压力情景，不是实际个人税制复刻，也不构成收益下界保证。实际税与按成本后口径的收益均未核验。
- 两例 raw 行情的 `market_state`、ST、reference 均为 unknown。未知状态不被当成正常交易状态。
- 0.8 转增比例来自唯一实施行；100/1000 股夹具的新增股数为整数，但法定舍入规则未核准。
- 账面总 NAV = 现金 + 上市持仓 raw close 市值 + 现金应收 + 未上市权益估值。available_cash 是可用性子项，不重复加入 NAV。

## 身份与复现

原始核验身份、SQLite/Parquet SHA256、事件行哈希、CNN/core HEAD 与 dirty 状态及逐日操作 ID 记录在配套 JSON。源数据绝对路径是本地复现路径，不包含认证凭证；路径/hash用于数据身份，不能替代源覆盖审查。

```powershell
uv run --offline --no-sync --project . python -m scripts.audit_z_corporate_actions `
  --db Z:/dev/quant_data_dev.db --raw-dir Z:/dev/kline/day `
  --output docs/research/20261026/z_corporate_actions_audit.json `
  --core-root ../backtest-core
```

脚本需要 Python 项目依赖（`pandas`、`pyarrow`、`backtest-core`）及显式可读的数据源。默认数据路径适用于原核验主机，可通过参数替换。完整机器输出见 `z_corporate_actions_audit.json`。
