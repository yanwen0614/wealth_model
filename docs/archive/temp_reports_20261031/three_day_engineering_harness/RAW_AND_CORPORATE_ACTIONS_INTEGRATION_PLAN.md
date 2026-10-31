# Raw 行情与公司行动最小接入计划

status: rebuilt_core_wheel_offline_e2e_pass; ex_date_missing_mark_fail_closed; independent_luna_qa_re-review_pending; real_source_state_coverage_blocked

## Core hook 接入点与 owner

- Core 主循环唯一改动 owner：主会话 Luna；费用/终端 QA 已释放该文件，本轮变更及测试限定于账户事件、执行日历和考核截止。
- 订单循环当前次序：开盘前解锁 → 执行到期订单 → 收盘策略回调 → 尾日处理 → `_mark_day` → `AccountSnapshot`。
- `run_account_backtest_from_orders(..., account_actions_provider=None)` 增加可选账户操作 provider；缺省 `None` 时保留既有费用 resolver/账户路径行为。另支持 signal/execution/maintenance 日历及 `anchor_date`、`evaluation_end`，使 E 日主期结束并将退出 buffer 独立成段。
- Core 不 import CNN。由通用 Protocol / immutable account journal 表达事件；CNN 负责规范化 SQLite 事件和 provider。
- 日内阶段：开盘前将当日 reference/status gate 交给订单裁决；收盘时冻结 record-date 股数并登记 ex-date 应收/未上市权益；pay-date 与 listing-date 的变更只在日终完成，次交易日可用。
- `AccountState` / `AccountSnapshot` 当前只有 cash 与 positions。要正确计价 receivable、unlisted entitlement 和 accrued tax，必须扩展账户分录/快照并 bump schema；不得仅靠外部 NAV 后处理伪装 core 集成。
- 当前 `MarketBar.limit_up/limit_down` 是bool，不能表达参考价/状态unknown。接入时给core行情/执行裁决增加显式unknown态与拒单reason（旧构造兼容默认保留既有语义）；不得把unknown编码成False或伪造双边limit。

## 幂等和兼容

- 幂等操作ID由稳定 `source_event_id + action_kind + phase + effective_date` 组成。同一行现金+送转事件必须拆阶段；record归属、ex应收、pay到账、listing转股各自独立去重，不能用单个“event已处理”标记跳过后续阶段。
- pay-date EOD 把净额从 receivable 重分类为总现金；当日策略开盘可用额仍看不到该现金，次交易日才释放。`cash` 是总现金；`available_cash` 与 `blocked_cash` 仅表示可用性，不是 NAV 的独立资产项，不得重复相加。
- listed entitlement 转 core integer position 的同时清除同一 event 的虚拟权益估值；小数/舍入/登记规则未知时不转股、不当可卖股，显式保留 unknown。
- `cost_config_resolver=None` 原逻辑保持不变；新事件 hook 同样默认为 `None`。逐字段默认路径回归测试加独立公司行动端到端测试。

## 端到端验收

- 合成单一现金+送转事件：pay-date 与 listing-date 设为不同日。record 100股冻结；ex-date 同时建现金应收和 unlisted权益；pay-date EOD只将现金应收转账一次，重复hook不重复加现金；listing-date EOD再将股份转入core一次，不能因pay阶段已处理而跳过。
- 跨日验证 raw NAV 和可用现金：pay-date 开盘现金不变；pay到账只重分类一次；上市前权益只估值一次，listing转股后虚拟权益同时清除；重复各阶段hook及整段重放均不重复计现金/股数/NAV。
- 同一运行逐日核对 `cash + positions raw MV + net_receivables + unlisted_value - liabilities = NAV`，同时单独核对 `available_cash + blocked_cash = cash`、现金账和股份账分录的 event key。合成用例已覆盖 pay EOD 到次日可用额释放、重复 hook 幂等、listing 转股与 E 日 BUY 拦截；E 前信号可在 E 成交。
- 复用 core `AShareCostModel`、`MarketBar`、`MarketState` 与撮合流程；不复制执行引擎、不改默认 fee resolver 语义。
- 数据状态 unknown（ST、reference、停牌/交易状态）保留 unknown；core 执行 gate 未具备 fail-closed 能力前，不将 raw 输入当作可成交 MarketBar。

## Raw 输入文件 owner 与边界

- 主会话 Luna 只拥有新增 `backtest/cnn_adapter/raw_market_inputs.py` 和对应 CNN 合成测试；暂不碰 `market.py`、`runner.py` 与 core。
- 读取单标的 raw 日线：价格原样保留；volume 源单位 `/100` 且必须整除；amount 源单位 `/100000`；核验 code/date 唯一键、OHLC 与 amount/volume 推导 VWAP。
- 窗口只含 signal_start 前必要有效历史、信号期行及明确 execution/buffer end 行。只读文件 schema 与单标的元数据；不构造大数据副本。
- 原始源缺失的交易状态、ST 状态和官方除权 reference 均输出 unknown；不默认为正常交易，也不生成执行级 `MarketBar`。
- 当前 `Z:/dev/kline/day/*.parquet` 样本 schema 无 `is_trading`/ST/reference 列。000001.SZ与600519.SH各3336/3338行仅读 code/date/volume 检查：日期严格递增且volume可整除100；各首批1行再核amount/100000÷volume/100位于raw high/low内。这仅证明两个代码文件的数据形状，非目标股票池全量核验。
- 独立复核指出的全量行物化、volume浮点精度、零量额不一致、无界去重键及输出乱序已修复：dataset按code与execution cutoff谓词分批4096扫描；要求日期严格递增并相邻检重；仅保留历史最近N和signal/buffer；源整数volume保真，超精度float拒绝；零volume与非零amount拒绝。
- 新增模块 `backtest/cnn_adapter/raw_market_inputs.py` 与 `tests/unit/backtest/test_raw_market_inputs.py`；7项合成unittest、目标Ruff、目标Pyright均通过；独立Luna复核PASS，无剩余严重问题。多fragment若扫描日期乱序会安全拒绝，不输出乱序结果。

## 当前验证与限制

- CNN 普通环境定向测试（无 PYTHONPATH，PowerShell）：`uv run --offline --no-sync --project . python -m unittest tests.unit.backtest.test_corporate_action_runner_e2e tests.unit.backtest.test_raw_market_provider tests.unit.backtest.test_corporate_actions tests.unit.backtest.test_execution_audit tests.unit.backtest.test_cnn_adapter_orders`，当前 E2E+四模块实现方复验 36 项通过。
- core 定向测试（PowerShell）：`$env:PYTHONPATH='D:\\code\\cnn_full_20260905\\backtest-core\\src'; uv run --project D:\\code\\cnn_full_20260905\\backtest-core python -m unittest tests.test_account_actions tests.test_account_state tests.test_account_engine tests.test_market_state`，144 项通过。
- 针对 CNN runner/provider/action/audit/E2E 的 Pyright：普通环境、无 `PYTHONPATH` 0 errors / 0 warnings；Ruff 与 `git diff --check` 最近一次通过。
- 修复原 QA 的常规环境 wheel 阻断：从当前 core 源构建 `wheels/backtest_core-0.1.0-py3-none-any.whl`，最新 wheel SHA256=`7FCAB4EB0BA5CCA7BCC53E20A5E0C2047D5CCDAF308868B32816328B5127DE70`；`uv.lock` 只变更该本地 wheel hash；`uv sync --offline --locked --inexact --reinstall-package backtest-core` 只替换了 backtest-core 一个包。Torch/Torchvision 及其它 lock 条目未改。
- 常规 venv `uv run --offline --no-sync` 中直接 import `backtest_core.contracts.account_actions` 与 `run_account_backtest_from_orders` 成功；核验 38 个 Python 源文件 source/wheel/installed 字节完全一致，并检查 `account_actions_provider`、`execution_calendar`、`signal_dates`、`maintenance_dates`、`anchor_date`、`evaluation_end` 参数存在。
- `test_cnn_runner_wires_raw_actions_and_terminal_period` 现在直接调用 `run_cnn_backtest`，真实验证 entry/E/buffer 日历、unknown market state 的 `market_state_unknown` 拒单、E 日最高分 BUY 被记录为 buffer 抑制、应收/未上市权益/现金/持仓逐快照 NAV 恒等式；旧 core-level E2E 仍保留用于精细核对阶段 hook 与幂等。
- 公司行动估值边界选择“估值未知 fail-closed”：core 在正持仓的现金应收/送转权益 ex-date 阶段，要求同日存在可交易 raw close；缺 bar、停牌/非交易或无有效交易状态均明确抛错，事件/代码/日期/原因写入错误，不让旧 close mark 与新 accrued entitlement 同时入 NAV。`test_cnn_runner_fails_closed_on_ex_date_without_raw_close` 经真实 CNN runner 入口覆盖现金事件缺 bar。正常 raw close 照常盯市，不强制 NAV 除权前后相等；pay/listing 只做 receivable/entitlement 到现金/持仓的重分类，不另补收益。
- 无标签交易链复核：`test_cnn_runner_wires_raw_actions_and_terminal_period` 通过真实 writer `_signal_record` + `prediction_cache_arrays` 生成`label_availability=not_loaded`、`true_ret=NaN`的合成信号并送入 `run_cnn_backtest`；C 在 E 前的有限 `exp_ret` 且 `buy_eligible=True`，实际于 E 开盘成交；E 日最高分 B 的订单确实被终端 wrapper 记录为 suppressed。Runner provenance 报 `label_availability=not_loaded`、`labeled_rows=0`、`quality_metrics_status=not_available`、`rank_ic=not_available`；无真值不计算/伪造 RankIC。
- 最后 null quote 修复：`_validate_ex_date_action_marks` 显式检查 `close is None`、非有限值及非正值，统一返回含事件/代码/日期/reason 的 fail-closed `ValueError`。新增 core 回归先 RED（`TypeError: None <= 0`）再 GREEN；core `tests.test_account_actions` 3项通过，CNN原五模块36项通过。source/wheel/installed 的38个 Python 文件逐字节一致。
- 修后实跑数据必须与原独立审查分开陈述：独立 QA 首轮原环境 0 PASS；PYTHONPATH 诊断 22 PASS；core 81 PASS。实现方修后 ordinary-venv 五模块为 35 PASS，尚待同一 Luna QA 会话复审，不得称为独立 QA PASS。
- 缺失交易状态、ST/reference/涨跌停数据仍无法从现有 raw 日线可靠恢复。生产来源覆盖未补齐前，真实状态为 unknown 并拒单；合成测试显式提供已知状态，不构成真实市场可成交性或绩效证据。
- 本轮没有税额分录：税负/应收净额口径需真实税务规则来源后再接入；目前 synthetic dividend 使用 gross receivable。
- 真实历史收益、数据覆盖与公司行动完整性仍为 NO-GO；上述结果仅证明接口和合成会计闭环。

## Z 盘真实源两事件账务夹具（只读，不含策略收益）

- 只读脚本 `C:/Users/yanwen/AppData/Local/Temp/opencode/audit_z_corporate_actions.py` 查询 Z 库与 raw parquet；输出身份和逐阶段账目到同目录 `audit_z_corporate_actions.json`。DB SHA256=`bb1372c362e8a9b085af4984eb522f9a4b243e0d07f5c1b9777c532d94b7b14b`，metadata.dividend=`2026-10-04 03:53:38.635730`。
- `000001.SZ` id=17328：登记 2021-05-13、除权/派息 2021-05-14，每股税前现金 0.18，无送转；raw close 23.07→23.32。`300896.SZ` id=70078：登记 2021-03-15、除权/派息/红股上市 2021-03-16，每股现金 3.5、转增比例 0.8；raw close 750.88→439.6。
- 两事件均用预设100及1000股账户夹具调用 core `apply_account_actions`；cash、listed positions、receivable、unlisted entitlement 分项扩展 NAV 均逐日相加核对。每个 event 的登记、现金除权、现金支付、转增除权、红股上市 operation ID 独立列出；无交易订单、策略收益、RankIC或成交性结论。
- 派息日快照按 core 语义保留 `available_cash` 未增加；下一交易日开盘现金释放状态单独记录，证明付款不是当天开盘可用。
- 真实 raw provider 行情的 market_state、ST、reference 均为 unknown。转增比例来自唯一已实施源行，100/1000夹具为整数，但法律舍入规则未核实；因此审计只把舍入标为 fixture assumption。记录在除权日、支付/上市同日的顺序按现有 core 操作；没有额外假设当日开盘可用。
- JSON 显式记录代码仓库 HEAD/dirty、审计脚本 SHA256、SQLite 与各 parquet SHA256。300896 转增税务分类为 `unknown`，本轮 cash ledger 仍明确按 pretax 运算。
- 目录输入优化：`CnnRawMarketDataProvider` 现按代码定位 `{instrument_id}.parquet`，仅扫描目标代码文件；缺文件立即带代码和路径报错，单文件路径行为保留。`test_raw_market_provider.py` 增加了目标文件隔离与缺失失败案例。

## 税务缺口与下一最小接入计划（未实现，需独立 TDD/QA）

- 当前可执行 core 现金公司行动路径是 `pretax`：`CorporateActionProvider.account_operations_for_day` 的 `CreateCashReceivable` 只传源 gross `cash_per_share`，账户支付也把 receivable 全额转入 cash。`CorporateActionLedger.project` 有 `cash_dividend_20pct_stress` 投影和现金税估值，但 runner/core 现金 hook 未接收 tax policy；不得把 projection 的扣税与 core 毛额到账拼在同一 NAV，也不得因 broker 印花税/过户费通过而称全成本齐备。
- 后续最小接口应显式选择 `pretax` 或 `cash_dividend_20pct_stress`，并写入运行 provenance。压力模式在除权时按 gross 建应收并分账 `gross_receivable` 与 `withholding_payable`（或等价净应收+独立 withheld ledger）；支付时仅净额进入 cash，清除 gross receivable 与 withheld payable。NAV 在应收期只计一次净额，支付后只计到账净现金，不能再次扣税。
- 除权、应收/预提、支付/扣缴使用稳定独立 operation IDs；重放每阶段不得重复增加净现金或扣缴。测试覆盖 pretax、20% 压力模式、支付前/支付日/支付后 NAV 与可用现金、重复 hook 幂等、跨日状态恢复。
- 20% 是统一现金分红预提压力情景，不是中国个人实际税额或个体 FIFO 持有期税制的复刻，也不能证明真实成本后收益下界。实际税制仍需税务来源和 lot/取得日期等信息。
- 送股/转增必须区分已核准且适用免税规则的资本公积转增与税务性质/规则未知的送股；只有来源明确支持的类别才能按免税情景入账。未知 bonus tax rule 应 fail closed 或显式列为税务未知、阻止“成本后”结论，不能静默按零税。
- 本最小税务任务独立开 TDD 与独立质量门；不回开旧 core/runner 40 项门，也不改写本轮 pretax Z 源核账结论。未完成之前，收益核验须明确标注公司行动现金按 pretax 模拟、实际税待核，不声称保证收益下界。
