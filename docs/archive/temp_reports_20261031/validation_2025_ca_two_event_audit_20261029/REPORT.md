# 2025 A/B 两条公司行动中断只读审计

审计范围：仅读指定年度 `summary.json`、core 前缀/CA 观察记录、`ca_full174` 导出和 `run_2025_restricted.py`；未运行回测，未更改账本或源库，未重算 4GB 数据库哈希。

## 结论

- A/B 均在 2025-01-06 的 core fill 回调后中断：A 买入 34,700 股 000159.SZ，B 买入 31,800 股 000595.SZ。前一交易日 2025-01-03 发出订单，core `execution_updates` 显示 execution_date 为 01-06，fill 与 observer 检查均在 01-06。summary 标为 `NOT_EVALUABLE / INCOMPLETE / PIT_UNPROVEN`，回报不可用。
- 两条被报错事件各自的候选公告日为 2025-07-25、2025-08-29，晚于 01-06；登记/除权/派息/实施公告/红股上市字段全空，金额与送转均为 0。它们不能证明 01-06 已发生权益，也不能证明当日未知事件实际存在。
- 根因可定为 guard 对未来候选快照提前拦截（不按可得时间/事件时序筛选）；就这两条事件而言，属于“误用后来才公告的未知登记候选”，不是已证实的 01-06 公司行动风险。该结论不证明整个 A/B 2025 CA 覆盖完备，也不证明 01-06 没有其他真实权益事件。

## 原始完整字段（按导出原值；null 即未填）

共同字段顺序：方案进度；每股送转/税前派息/税后派息；登记日/除权除息日/派息日；预案公告日/分红实施公告日；基准日期/基准股本；货币；公告日期/方案是否变更/分红年度/分红对象/股东大会公告日；红股上市日/每股转增比例/方案变更说明/每股送股比例/备注/预案预披露公告日/记录类型；row hash。

- A `dividend:103185`，000159.SZ，hash `0ae6df2addb8583a16863a0c49c73091648ed7008177a6253a7ef6d109c637d5`：`1；0/0/0；null/null/null；2025-07-25/null；null/null；CNY；2025-07-25/0/2025-06-30/null/null；null/null/null/null/null/null/null`。源 JSON 行 9892–9918。
- A 同代码另一条年报候选 `103186`：`2；0/0/0；null/null/null；2025-03-28/null；null/null；CNY；2025-04-19/0/2024-12-31/null/2025-04-19；null/null/null/null/null/null/null`；hash `af14470f5ad697d40456c48a6565e504359a18695abb57cb9730f37a32d8150a`。源 JSON 行 9921–9947。
- B `dividend:55290`，000595.SZ，hash `25bfb2b5d9e7a88766cb9952630f6c03c17e14f1912f45eeaa7cd8e2dea890dd`：`1；0/0/0；null/null/null；2025-08-29/null；null/null；CNY；2025-08-29/0/2025-06-30/null/null；null/null/null/null/null/null/null`。源 JSON 行 5600–5626。
- B 同代码另一条年报候选 `55291`：`2；0/0/0；null/null/null；2025-04-26/null；null/null；CNY；2025-05-17/0/2024-12-31/null/2025-05-17；null/null/null/null/null/null/null`；hash `642b7d9e6616c56410960cb1c3667ec0420f00570ae9e6e09a32a3835d5252e8`。源 JSON 行 5629–5655。

## 公告时序与证据界限

- 免费公开公告目录检索得到：国际实业 2024 年报与“关于2024年度利润分配预案的公告”公告日 2025-03-28；该年报股东大会决议目录日期 2025-04-19。国际实业 2025 半年报目录日期 2025-07-25。宝塔实业 2024 年报与“2024年度拟不进行利润分配的公告”目录日期 2025-04-26；对应源字段股东大会公告日 2025-05-17。*ST宝实 2025 半年报目录日期 2025-08-29。以上目录时间均晚于 01-06；目录来自 Eastmoney 公告检索 API，仅用于定位时间/标题，非正式公告内容证据。
- 巨潮资讯官网 `cninfo.com.cn/new/hisAnnouncement/query` 请求返回 500 或零结果；官方静态 PDF 未能解析出可验证的附件 URL。因此本审计未取得可核对的巨潮 PDF 页码、官方文件 SHA256，未能以官方正文确认是否否决、终止、通过或确实产生权益。不得把上述目录标题、源表方案进度 `1/2` 或零金额字段升级成正式公告结论。
- 已交付候选导出查询区间为 2024-12-31 至 2025-12-19，筛选基于列出的公告/登记/除权/派息/预案等日期字段；同代码在该文件中仅见上述两条。该有限导出不含 PIT `known_at`，`history_known_at=UNKNOWN`、`pit_evidence=false`、`implementation_certified=false`；不能据此作整个市场/全年“无其他行动”的完整性证明。

## guard 根因与最小安全边界

- 受限脚本 `run_2025_restricted.py:268-298` 的 `ca_exposure()` 注释称不以事后资料筛选信号，且仅生成旗标；`:301-332` 的 `ObservedCAContext.on_update()` 却逐 core 更新遍历全部快照 descriptor，并在 `record_date is None and held > 0` 时立即 `_issue(..., "record_date_unknown_positive_holdings")`。此分支不检查 `announced_date`、`raw_row[公告日期]`、`window_end` 或任何未来阶段日期。`corporate_action_snapshot_loader.py:63-95` 又将所有零/空除权候选保留为 descriptor（`event=None`、`record_date=None`），所以同一 fill 回调即触发。两次 `ca_observed_checks.json` 明确记录公告字段在未来、登记日 null、边界为 `missing_record_first_positive_holding`。
- 本次判断：对指定两条 event 是未来事件候选过早阻断；其他未来未知日期事件或真正发生于 01-06 的行动，现有证据无法判定。不是“进度码 1/2 即未实施/无权益”的推论。
- 最小安全修复方向（未实施）：仅在 `announcement/record/ex/pay/list` 任一经来源证实的日期到达时检查事件；没有任何已到达日期、仅存在未来公告或日期全空的候选，不得在 01-06 因正持仓中断。到达已证实除权/登记边界而登记量或权益计算仍不明时继续 fail closed。仅适用于经完整、可审计的 PIT 事件清单；对当前候选导出，过滤未来公告只能消除这两条已知未来污染，不能证明无遗漏。
- 若坚持使用未知日期候选保护真实权益风险，最小安全范围是：仅阻断有证据显示该事件在当日已公开/已进入实施阶段且持仓确实可能享有权益；未知可得时间不得伪装为当日风险。缺乏此类证据时标为“覆盖未知/结果不完整”，不能擅自重写历史账本或声称未来无风险。

参考：A/B `summary.json` 错误字段、`core/manifest.json` 前缀截点、`core/execution_updates.jsonl` execution_date/fill、`ca_observed_checks.json`；候选文件 `ca_full174/task2_v2/dividend_range_rows.json` 与 `delivery_manifest_v4.json`。报告只读研究；未验证收益目标、同期沪深300或全年度可执行结果。
