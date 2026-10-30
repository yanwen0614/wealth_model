# 保守价格包络与执行输入必要性审查

日期：2026-10-26。只读研究；未改代码/env/git，未跑策略收益。结论只谈价格规则与数据必要性。

## 结论

**有条件数学 GO，不是无条件全样本 GO。** 对沪深人民币普通股（A股），只要某个交易日已证实适用普通日涨跌幅规则、官方有效参考价 P>1元、股票tick=0.01元，且自定买限价不高于 floor_tick(1.045P)、卖限价不低于 ceil_tick(0.955P)，则该4.5%保守带落在至少±5%的法定日涨跌幅范围内。此证明不依赖个股ST值：沪深主板最窄适用率历史上为5%；创业板/科创板风险警示股票为20%。2026-07-06起沪深主板ST改为10%，但历史研究仍须按生效日分段。

证明：5%未取整边界距4.5%边界为0.005P>0.005元（P>1）；法定限价按0.01元取整的最大舍入误差为0.005元，故4.5%保守取整边界仍不越过5%法定界。若交易所特定证券/规则版本采用非普通舍入、不同tick/最小跳动例外，或参考价≤1，此证明不适用，须拒绝包络模式或用官方精确价。

这只能证明**日涨跌幅价格边界包含关系**，不能证明某日确有涨跌幅限制、限价申报有效、订单排队成交或9:30真实成交。它能省去未知 ST 状态对“该自定带不越过已知最低法定百分比”的判断需求；不能省略交易日期状态、证券板别/类型、上市与退市生命周期、参考价、除权/特殊基价、tick、停复牌/盘中临停、订单申报时段及交易机制输入。不得把 envelope 证据写成 `st_known=True`、`normal` 或官方限价。

## 规则与真实例外

- **板别/日期**：深交所主板 ST/\ST 历史限幅5%，创业板 ST/退市整理股票20%（深交所2021修订规则）；上交所主板风险警示限幅曾为5%，上交所2026-04-24公告修订为10%，并于2026-07-06实施。深市2026-05-07 ST利源（002501）公告记载原5%并随7月6日新规调整。创业/科创板20%，北交所普通限幅30%（超出“沪深”范围，说明A股不等于单一板别）。
- **无日涨跌幅的反例**：沪深新股上市前5个交易日；沪深退市整理期首日；交易所认定的其他无涨跌幅情形。示例：科创板臻宝科技688797于2026-06-24上市，首5日无涨跌幅；深交所ST金刚（300064）退市整理首日2022-06-06无涨跌幅，之后创业板退市整理适用20%。在这些日子不能说4.5%“位于5%法定界内”，虽可另称自定报价/价格范围约束。
- **复牌须分型**：普通停牌复牌不能一概说无涨跌幅；历史暂停上市后恢复上市/退市后重新上市首日曾有特别无涨跌幅规则，现行规则及证券生命周期按交易日版本查验。未证实是普通复牌还是特殊恢复/重新上市时，状态 unknown，不能靠ST或前收推定。
- **低价/tick**：沪深A股通常申报最小变动单位0.01元；特定历史风险警示低价股规则可能采用绝对0.01元限制。当前包络限定有效 P>1可避开该低价特例，但必须检验的是**执行日官方reference P**，不是只看T日raw close；公司行动或特殊基价可令两者不同。有效参考价未知或≤1即不通过包络充分条件。
- **连续竞价价格笼子**：深交所规则规定连续竞价限价申报动态有效范围（买入基准价102%或加10 tick孰高、卖出98%或减10 tick孰低；创业板2%规则）；北交所另有105%/95%或10 tick范围。它们是申报有效性范围，不是涨跌停。4.5%订单若到9:30才提交，可能因当时盘口基准的价格笼子无效；须区分开盘集合竞价截止前预埋订单与9:30连续竞价新申报。
- **日线成交边界**：无报价/无交叉不成交；日线 next-open/首成交价只能作为“已有订单于该价格可成交”的模型假设。日线 OHLC 不给9:30订单到达时刻、队列优先级、开盘匹配量或盘中临停；不宣称实际排队或实盘成交。信号预算/持仓名额不得预支卖出款或预期卖出空位。

## 两类输入设计（提案，不改core）

1. 保留现有 `strict_official` 默认且语义不变：`st_state_known`、`daily_limit_state_known`、reference及精确上下限按当前严格 gate；unknown继续拒单，不填 `st_known=True`/`normal`。
2. 新增显式 opt-in `verified_envelope`，只表达政策证明，不覆盖市场状态：字段建议 `limit_evidence_mode`、`envelope_pct_floor=0.05`、`envelope_rule_id/version`、`exchange/board/security_type_asof`、`daily_limit_status={limited,no_limit,unknown}`、`listing_event_type`、`reference_price/value_source/known_at/effective_date`、`reference_price_verified`、`tick_size/source/version`、`raw_price_unit`、`envelope_check={pass,fail,unknown}`及理由。ST仍可 unknown；独立状态字段不得以包络推导正常/可交易。
3. 当已取得官方精确数据时，存 `official_limit_up/down_price`、`official_limit_pct_up/down`、`official_reference_price`、`official_tick_size`、交易所产品/涨跌幅类型、来源记录ID与版本、生效日/可知时刻；标记 `official_exact`。它与 `verified_envelope` 是证据模式，不是优劣参数；不能拿5%推算价冒充官方价。
4. 包络模式仅对已核沪深A股、规则表覆盖日期、`daily_limit_status=limited`、无IPO/退市整理首日等无涨跌幅事件、无未核特殊基价/公司行动、reference>1、tick及方向性保守取整均通过的股票日开放。任一字段缺失、状态冲突、规则生效期不明即 `unknown/reject`。价格范围通过不代表实际申报通过价格笼子或有成交。
5. 两种模式的逐日账户处理均保持：固定信号时预算/股数/名额；未确认卖出不释放名额、不把预期卖款用于买入；未成交持仓保留。需单独记录模型成交依据、无报价/停牌/临停与盘口/队列缺证。

## SQL稀疏异常表能否作研究输入

**可作为带明示假设的恢复输入，不是无缺漏覆盖证明。** `history_status` 按异常行存储，touch 按码保存最新水位；fetcher 意图是每码逐日完整API快照，标准限幅事件经滤除后以空结果touch推进水位，且touch携带当日真实涨跌幅度。标准限幅重建只有在供应商确实对每码完整返回区间逐日快照、批次完整成功、code key未缺、过滤映射与版本无误、失败被重试且无未覆盖水位断档时才成立。

库内 touch 只表示某码某日一次“确认无异常”处理及其 per-code 最大日期；不存请求起止、原始逐日日期集、请求身份/成功行数。metadata 是表级统计；缺行也可能是正常日或漏码/失败。故仅用现存 SQL 可输出 `assumed_sparse_reconstruction` 研究态，并强制携带 `supplier_complete_daily_response_assumption=true`（假设声明，不是验证布尔）、`per_code_watermark`、`touch_or_event_source`、`coverage_start/end`（未知则unknown）、`gap_check`、SDK/字段映射版本及缺失理由；不得发布为 verified。欲升级 verified，须另有逐码请求manifest/完整raw响应或相同强度覆盖证据，验证每窗交易日集合及代码生命周期。

## 明确失败条件与执行分层

包络对某日不成立的精确条件：无法证明其属于有日涨跌幅的沪深A股；规则/板别/事件状态 unknown；官方有效reference缺失或≤1；特殊除权/恢复/上市基价未确认；tick/舍入规则不符；存在无日涨跌幅情形；或限价越出连续竞价申报有效价格范围。前五项阻断“法定5%包络”声称，最后一项阻断相应时段的有效申报声称；都不能通过假定 normal 解锁。

最终执行结论应分栏披露：①法规包络证明（或精确官方价）；②执行日交易/停复牌与订单有效性；③日线撮合模型假设；④真实9:30队列/盘口证据。当前SQL可以在上述供应商假设下恢复研究输入；没有订单簿/逐笔执行证据时始终不称实盘成交。

## 公开来源

- 上交所：2026-04-24交易规则公告，主板风险警示涨跌幅改10%、2026-07-06生效：https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml
- 深交所：2021年3月交易规则修订对照（主板ST 5%、创业板ST 20%、退市整理首日/后续规则）：http://docs.static.szse.cn/www/lawrules/rule/fund/trade/W020210331716400676919.pdf；2026年半年度报告披露深市主板ST 5%→10%新规自7月6日生效（交易所公告文件）：https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-28/85e257d8-cb88-4b55-951e-5e6b0aeac522.PDF
- 深交所：创业板交易特别规定（20%、IPO前5日无涨跌幅、连续竞价限价申报范围）：http://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf
- 北交所：《北京证券交易所交易规则》3.3.11–3.3.13（30%、IPO/退市整理首日无涨跌幅、价格笼子）：https://www.bse.cn/jygl_list/200028217.html
- 上交所：市场数据接口规格含价格档位、涨跌幅限制类型及上下限价字段说明：https://www.sse.com.cn/services/tradingtech/development/c/10789328/files/3c6ccdac26eb4639919413594d2d3d62.pdf
- 深交所：ST金刚2022-06-06退市整理首日公告：https://disc.static.szse.cn/download/disc/disk03/finalpage/2022-05-26/d7d2d914-6da0-4722-934d-9a94c51e762b.PDF
- 本地SQL语义依据：`docs/research/20261026/verified_state_source_contract.md`、`state_data_acquisition_plan.md`；quant `history_status.py`、`history_status_storage.py`、`touch_confirm_mixin.py`、`history_status_update_pipeline.py`。
