# 2025 A/B 真实执行桥接实施计划

> 仅计划；未改代码、未训练、未运行完整回测。执行时必须新建隔离 worktree，并由唯一编码 owner 修改。

**目标：** 在固定政策下让2025 A/B分别经真实 backtest-core 单一账户账本运行，导出逐订单/逐日审计，判断探索结果是否同时满足成本后非负、严格跑赢同期沪深300、实际持仓≤10。

**架构：** 复用已审 staged 生产 runner/真实 core作为唯一执行账本；增加一个窄的 NPZ→ranking 输入桥和2025专用调度/汇总入口。A/B共享一次准备完成的原始行情、状态、公司行动、指数和日历证据，各自只替换已双哈希验证的checkpoint与NPZ信号；不创建第二账本，不改CA/W1冻结证据。

**技术栈：** Python 3.12、backtest-core已安装wheel、现有 `backtest.cnn_adapter`、NPZ/Parquet、unittest、ruff。

## 结论与A/B比较

- 普通 `run_cnn_backtest` 可承载真实raw行情/CA/verified states及core账户，但 `CnnTargetOrderStrategy(target_size=10)` 的目标槽策略与terminal audit并非现成完整管线；单用CLI或设10不能保证买单成交后硬≤10或导出所需全账本。它不应成为第二实现路径。
- 最小路径是 `staged_candidate_runner.run_staged_window`：`StagedExecutionBridge`消费core真实ExecutionUpdate，`CorporateActionContext`接账，`StagedOrderStrategy`做核容，收尾有exposure audit。2025要桥接的是输入与薄调度，不替换撮合/账户引擎。
- staged政策明确 `BUY_RANK_MAX=5`、`EXIT_RANK_MIN=11`，固定5个slots；它不是10持仓策略。可作为事前冻结、满足≤10的研究候选，A/B用完全相同政策且同时执行，不按表现择优；不得将结果解释为“最优10只”。
- 现有staged `run_staged_window` 本身对未知暴露会记为BLOCKED/INCOMPLETE；可在逐码/逐日状态未知处拒绝相应成交、保留原完整ranking次序及全部机会记录，不能先删unknown候选再重排，也不能把全市场拒单产生的零收益称达标。须单独报告因未知被拒机会及暴露覆盖；未知影响估值/状态的关键账目则整组INCOMPLETE。

## 冻结输入及协议

- A/B NPZ四键 `exp_ret,true_ret,dates,codes`，各1,180,872行、232个信号日、5,135码；源报告称行匹配、标签一致。新入口须验证NPZ原始字节SHA-256及独立来源manifest/报告SHA-256，报告双值、逐数组结构摘要；拒绝重复(date,code)、不匹配A/B日期/代码、不完整行或非有限score。不可仅做NPZ内容指纹。
- 两份旧signal parquet使用字段 `date/code/exp_ret/status/buy_eligible` 等，与原始NPZ并非同一可直接信任产物。计划从原始NPZ构造完整逐日ranking，`status=ready`、资格由显式状态/策略输入定义并留证；若改读既有parquet，必须与原NPZ逐键逐值全量等价，并同时验证NPZ源SHA与parquet SHA，禁止parquet单SHA冒充来源链。
- 预测信号训练配置HORIZON=10，`exp_ret`为52类中心加权期望收益；不能沿用adapter固定 `PREDICTED_HORIZON=5`声称。桥接必须在provenance记录“10日训练标签的期望排序分数、交易持有政策独立”，不改写模型输出或称5日预测。
- A/B为训练截止2024-12-31、2025全年验证期；权重、NPZ及评估报告于2026形成。称“已观察验证期历史回放探索”，不称独立测试、前瞻或干净验收。首次读权重/配置时冻结实际SHA与config对应关系；不重新训练。
- 账户均¥1,000,000；共用锚点2025-01-02，信号/主期结束E=2025-12-16，主期按E日收盘NAV；严格3个交易日buffer只清算，不计入主期成绩。执行日历必须含锚点、完整2025交易日及E后3日；不可缩窗。
- 固定候选政策 `Policy`、五槽、费用、滑点、税务情景、买卖规则；staged已设固定槽与执行缓冲，具体Policy枚举及费用须在实现前从源码/规则证据锁定，不能看绩效选政策。不能因为未满10只而扩大至10。
- 逐笔费用需 `resolve_historical_costs`/staged `PreparedFeeResolver`按成交日期解析，冻结来源与逐费率；不得假定2025全年统一当前费率。滑点、税、CA税务状态单列；无法证明个人实际税时只能报告明确税前/压力情景，不称真实税后。

## 代码边界与真实执行接口

- 冻结基线：已审树 `C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027`（ce7d1c6、未提交），SHA证据位于 `staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`。执行前重核HEAD/哈希，绝不在该树或W1研究树编码。
- 复用 `backtest/cnn_adapter/staged_candidate_runner.py`: `load_frozen_signal_parquet`(76)、`build_signal_ranking`(271)、`run_staged_window`(531)、内部 `_run_staged_window_impl`(603)；runner现有读取冻结Parquet双身份仅限单一signal文件，NPZ桥应置于新专用入口/小型模块，构建相同 `RankingSnapshot`契约，不篡改loader或既有证据。
- 复用 `staged_order_strategy.py`: `RankingSnapshot.from_scores`(69)、`StagedOrderStrategy.orders_for`(173)、`_new_episode_orders`(343)的占用代码核容；复用 `staged_execution_bridge.py:StagedExecutionBridge.on_update/consume`、`corporate_action_context.py`、`corporate_action_snapshot_loader.py`、`raw_market_inputs.py`、`raw_market_provider.py`、`historical_costs.py:resolve_historical_costs`、`quantity_rules.py:MappingQuantityRuleResolver`。
- `staged_production_inputs.py`已有 `build_execution_state_mapping`(100)、raw/state懒加载、来源SHA链、`PreparedFeeResolver`(206)、CA快照与完整输入准备功能；优先调用可复用纯函数/输入构造，不重复做状态账本。其现有2021/2022 scope配置不能假定覆盖2025，需明确的新输入清单与窗口配置。
- core调用位于 `staged_candidate_runner.py` 的 `_run_staged_window_impl`：执行 `run_account_backtest_from_orders(... observer=ctx or recorder ...)`；只能保持该core为唯一记账源。最终结果必须输出core快照/成交/locked/拒绝事件、CA现金与股份权益、逐日持仓和终端审计，不以adapter汇总指标代替。

## 2025状态/行情与阻塞门

- 已审状态构造明确“盘前known_at未知”(`staged_production_inputs.py:137-139`)，不能因此假装已验证2025 PIT。先盘点原始逐日状态来源及其源哈希/日期可见时点；若尚缺证，适用股票日保守UNKNOWN拒单并留候选/拒单/原因/机会，不把unknown删出截面或挤占重排。若未知股票导致实际持仓无法可靠估值、卖出能力无法判断、CA权益不明，结果标INCOMPLETE，停止目标资格判定；禁止因全拒零持仓取得“非负”。
- 需原始未复权OHLC及来源覆盖到E后3日，逐日停牌、上市/退市、板别/ST、参考价/历史限价与数量规则，状态冲突即失败；停牌、涨跌停锁单、T+1和未知都保留真实core执行事件。未知涨跌停不可默认为False/可成交。日线不能证明队列顺序，按core既定保守撮合语义声明限制。
- 原始状态准备必须覆盖所有候选和账户持仓生命周期；公司行动原始股息/送转/配股事件覆盖全窗口并接现有 `CorporateActionProvider`/`CorporateActionContext`。未知碎股/税务必须保留unknown并按规则拒绝/不声称实际税后；不能重写CA冻结文件或W1输入。
- `Z:/dev/kline_index/day/000300.SH.parquet`已知2025共243行；桥接输出必须对齐2025-01-02至12-16对应指数close-to-close价格指数，首末close显式核验、缺日/缺值失败，不沿用前值，不含分红再投资须标清。
- 如果状态/CA/原始行情覆盖缺失，保留真实拒绝机会记录与完整输入缺口清单，结论为INCOMPLETE；不得缩短窗口、换未知代码、将UNKNOWN变可交易或删除受阻交易来制造净值。

## 隔离实施、TDD及验收

- 唯一编码owner从冻结基线新建一个隔离worktree/分支；其他代理只读审查该冻结提交/快照，不并行改同树、依赖环境、锁文件或产物。范围限新 `scripts/run_2025_ab_execution.py`（调度/CLI）与 `backtest/cnn_adapter/npz_ranking_bridge.py`（NPZ→RankingSnapshot/provenance）；必要时只改staged runner的参数透传以暴露逐日审计，先证明无法从现有返回对象读取才扩改。测试只加 `tests/unit/backtest/test_2025_npz_ranking_bridge.py` 与真实core小fixture集成文件；不碰W1/CA冻结证据、训练、旧NPZ。
- TDD顺序：先写失败测试：四键/schema/date-code唯一性、数组完全配对、两级SHA拒错、NPZ到完整RankingSnapshot不丢候选/不改排序、H10谱系、未知逐码拒成交仍保留机会、状态未知暴露INCOMPLETE、五槽≤10、T+1/涨停/停牌/拒单/部分成交、历史费率、CA登记权益、E日与3日buffer、benchmark缺日失败、账户NAV恒等与A/B同协议。再用现有core小型合成fixture实现最小桥；禁止用全量NPZ/生产2025跑测试。
- 每关：编码owner交付commit/hash及测试结果；独立QA在只读冻结版本逐项复核diff/哈希、账本单源、边界测试、ruff与项目相关adapter/CA/审计单测，PASS才进入数据准备/回放。QA FAIL由同一owner修复，最多两轮，复审同一冻结快照；不让QA代理写代码。
- 数据先准备一次并共享两账户：全日历/raw/状态/CA/指数/历史费率均记录输入SHA、coverage与unknown明细。A、B分别执行同一固定策略/config，除source/checkpoint/NPZ身份外config hash相同；账户输出目录分离、无共享可变状态。用 `--help`确认真实CLI后冻结A/B完整命令与返回码；长任务只能tmux/psmux、显式cd隔离树、remain-on-exit并短轮询，不能工具前台运行。
- 目标资格：完整审计、主期税费后NAV≥¥1,000,000、严格超过同区间沪深300、逐订单结算后及每日实际正持仓证券数≤10，三条件同时满足；buffer结果单列。若数据或状态unknown影响账本，资格为INCOMPLETE；A/B均报告，不按表现择优。
- 粗略工时：输入2025覆盖/来源身份盘点2–4小时；NPZ桥和调度2–4小时；TDD、独立QA及最多两轮修复2–4小时；共享数据准备与双账户全窗运行/独立对账2–5小时，合计8–17小时。历史状态/CA补证、全量运行性能和qa修复可能增加数日；当前已知状态PIT未知是实质阻塞，不能承诺得到可判定目标结果。

## 建议命令模板（实现后按help冻结，当前不可直接运行）

```powershell
git worktree add "C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_bridge_20261029" -b research/validation-2025-bridge ce7d1c6
uv run --project . python -m unittest tests.unit.backtest.test_2025_npz_ranking_bridge tests.unit.backtest.test_2025_execution_bridge
uv run ruff check backtest/cnn_adapter/npz_ranking_bridge.py scripts/run_2025_ab_execution.py tests/unit/backtest/test_2025_npz_ranking_bridge.py
uv run --project . python -m scripts.run_2025_ab_execution --help
uv run --project . python -m scripts.run_2025_ab_execution --prepare-once --manifest <冻结输入manifest> --output-dir <prepared-2025>
uv run --project . python -m scripts.run_2025_ab_execution --source A --prepared <prepared-2025> --npz logs/preds_fullA_2025.npz --npz-sha256 <A_SHA> --checkpoint <A_CHECKPOINT> --checkpoint-sha256 <A_CKPT_SHA> --initial-capital 1000000 --policy <事前锁定政策> --anchor 2025-01-02 --evaluation-end 2025-12-16 --buffer-trading-days 3 --output-dir <A结果>
uv run --project . python -m scripts.run_2025_ab_execution --source B --prepared <prepared-2025> --npz logs/preds_fullB_2025.npz --npz-sha256 <B_SHA> --checkpoint <B_CHECKPOINT> --checkpoint-sha256 <B_CKPT_SHA> --initial-capital 1000000 --policy <同一事前锁定政策> --anchor 2025-01-02 --evaluation-end 2025-12-16 --buffer-trading-days 3 --output-dir <B结果>
```

尖括号参数必须来自冻结manifest/sha报告和实现后help，不能照抄占位运行。严格限制只读原始来源；输出只写新临时目录；不得重写输入、staged树、W1树或任何冻结证据。
