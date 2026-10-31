# W1 CA cutoff availability 审计

审计时点：2021-06-07 收盘；范围仅为冻结输入、程序静态路径和既有 prefix 账本。没有运行真实绩效或读取训练数据。

## 结论

当前冻结程序不是可认证的 point-in-time（PIT）公司行动链路。`load_corporate_action_snapshot` 一次解析全量源行，`_load_prepared_window` 将完整 snapshot 传给 provider/runner；Context 接受 `window_end`，但该值只进 evidence，没有过滤 descriptors。`account_actions_for_day` 和 `on_update` 会枚举全量 descriptors。provider 也接收全量事件的ex-date集合。不过集合只在取到相同代码/相同交易日 bar 时标记 reference required；未来ex日在cutoff后的prefix日期上不会匹配。

因此需区分物理读取、descriptor枚举和业务影响：未来事件确实被物理读取并进入枚举，但只有 `record == day` 才创建登记，事件阶段日期相等才请求相应操作，且正持仓校验依赖已登记数量。当前统计中，cutoff前登记的1306条股利行公告日期均≤cutoff；未来ex日且公告日期晚于cutoff的1959条没有在cutoff前登记。故现有证据不能断言这些1959条已改变W1截至cutoff账本；同样，完整descriptor加载、日期集合、源历史版本未知也不构成PIT隔离证明。300502是相反的关键例子：公告在cutoff前，未来ex不能因日期在未来而删掉。

## 字段语义与冻结源统计

loader 将 `公告日期` 映射到 `CorporateActionEvent.announced_date`，`股权登记日` 映射 descriptor.record_date，`除权除息日`、`派息日`、`红股上市日`分别映射 event.ex/pay/listing_date。它没有取“公告日期、预案公告日、实施公告日中的最早可信公开时间”做 PIT 筛选，也不验证公告时间戳/收盘前后。right_issue 仅留公告日期并不构造事件。

对 `dividend_range_rows.json` 全量8740行作只读扫描：公告日期非空8740/8740；公告日期≤cutoff 2497；至少一个公告类字段（公告日期/预案公告日/实施公告日）≤cutoff 4091；登记日≤cutoff 1306，均有正现金或送转比例字段；未来ex日2279，其中公告日期晚于cutoff 1959。当前字段统计没有公告日期缺失，但这只证明导出字段完整，不证明字段本身是当时版本或可获得时间。`right_issue_range_rows.json` 12行，公告日期非空12，≤cutoff 6；没有登记日或ex日期字段。

300502.SZ / dividend id=27726 的源行 hash 为 `5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462`：公告日期、实施公告日2021-06-01，预案公告日2021-04-23；登记日06-07，除权、派息、红股上市日06-08；每股送转0.4002532、税前现金0.2717082。官方PDF证明这一个事件内容及公告日期，且截止日应知道06-08的将来除权安排；故不能简单按 `ex_date > cutoff` 删掉，正确可得性条件是公告已公开且事件版本有证据。

现有 v2 prefix 账本在2021-06-07均有300502正持仓：B1 4000股、C70 2800股、S1/S2各1300股；floor/ceil等既有前缀相同不能替代信息时点证明。只检查了这些现存账本，不代表已经逐一核算1306条登记日≤cutoff的全部账户暴露；未核算项保持未知。公告PDF只证目标事件，不构成全市场源的可信背书。

## 数据历史版本边界

冻结文件来自后来导出的数据库快照，manifest 元数据记载相关表在2026年更新；文件SHA与逐行hash只固定“当前交付的字节/行”，不证明行在2021-06-07已存在、当日内容相同，或公告字段等同于真实公开时刻。当前库记录可能含事后补齐/修订的登记、ex、pay、listing字段。任何没有独立当时公告证据的行必须标 `availability_unknown`；禁止把今天数据库存在记录解释成历史可得。

## 安全 prefix-only 方案

1. 新建只读审计/执行 wrapper，不改冻结CA源；保存源文件原始SHA、manifest SHA、路径/字节数、schema、每行原始 `_row_hash`，并把 hash 算法/规范化方式写清楚。保存公告原件URL、抓取/归档SHA、页面发布时间或交易所公告时间（含时区/时分）；若只有日期而无时刻，按保守边界处理。
2. 每个 cutoff 生成双层事件表：`source_observed`（物理存在，绝不直接供策略）与 `decision_eligible`。后者仅允许 cutoff 前有独立公开证据且版本字段均可溯源的事件。依 cutoff 前公告筛选，不按未来 ex 日期剪裁；已知的未来ex/record/pay/list日期保留供后续日程登记/处理。截止公告时刻不确定的事件排除于控制流并记unknown。
3. 对未知行实行 fail-closed：若相关代码在 `record_date <= cutoff` 有正持仓，或窗口内未来阶段可能触发，整个策略/窗口标 `INCOMPLETE`，不以“假定没有事件”继续报可比结果。对无正暴露但事件可能改变行情解释/机会覆盖的，也记unknown，不能宣称PIT。
4. B1、S1、S2、C70共用同一个 per-cutoff eligible snapshot、相同证据表、日期范围和fail-closed规则；baseline不可使用另一套“全部数据”或被忽略的事件。事件证据缺口对四者同时传播；按预注册逐策略状态报告，不因有的策略没有暴露就将该策略升级为PIT。
5. 仅可在输出中称“条件机械 prefix 研究”：列出数据库历史版本未知、覆盖/未知暴露、公开证据边界；不称PIT证书、不运行/声称真实绩效。官方PDF的少数抽样不推断全域可得性。

## 修改点与最小验证建议（本次未改代码）

- `corporate_action_snapshot_loader.py`：增加显式 cutoff 与独立 announcement-evidence 输入，输出 observed/eligible/unknown 分层；保留全量原始审计，但不能让 observed descriptors 默认可进入策略。
- `staged_production_inputs.py::_load_prepared_window`：加载该窗口/截止日的 eligible snapshot，校验它与窗口身份/证据manifest绑定；不要直接传全量 snapshot。provider 的 `corporate_action_dates` 同样只基于符合可得性条件的事件。prefix 日期截断与“已知未来 ex”分开处理。
- `CorporateActionContext`：由 runner 的 cutoff-aware snapshot驱动操作；`window_end`不能只是证据字段。事件尚未被公开证据确认时禁止 register/ex/pay/listing 进入控制流。未知暴露在最终 outcome、四策略比较和 summary 中传播为 `INCOMPLETE`。
- 最小TDD：公告早于cutoff且ex晚于cutoff必须保留并可在record日登记；公告晚于cutoff但record早于cutoff不得登记且有正暴露即INCOMPLETE；公告缺失/时间不明 fail-closed；window_end不得放行未证事件；provider不得泄漏未合格未来ex；四策略共享相同snapshot哈希及状态。另做静态调用链审查、全量行统计重现、独立QA核验哈希与输出状态。此处不执行测试。

## 证据位置

- 冻结输入配置：`staged_prepared_inputs_20261027_v12/integration_inputs.json`，CA root为 `staged_execution_input_snapshot_20261027_v1`。
- loader：隔离工作树 `corporate-action-fix-20261027/backtest/cnn_adapter/corporate_action_snapshot_loader.py`；执行加载：`.../staged_production_inputs.py`；Context：`.../corporate_action_context.py`。
- 账本：`w1_real_prefix_exploration_20261029_v2/outputs/W1_*/*daily_account.jsonl`。该账本只供正暴露查验，不作为PIT证据。
- 详细哈希和机器统计见 `EVIDENCE.json`。
