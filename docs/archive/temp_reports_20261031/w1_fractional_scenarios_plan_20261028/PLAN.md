# W1 300502 碎股条件情景：最小实施计划

## 范围与预注册
- 本轮仅规划与审查；不改任一源工作树、不跑 W1、不跑绩效。后续实施必须在主会话新建隔离 worktree，原冻结树只读。
- 目标仅为四策略 B1/S1/S2/C70 各自独立的 floor/ceil 两条条件路径，共8条。不是同一个现实账户的联合结果，也不是无条件收益界。
- 延用预注册的 W1 锚点2020-12-31、E日2021-06-30、buffer至2021-07-05、信号/政策/税务/费用/初始资金及2021-030事件以外所有 fail-closed；不得按绩效选支。
- 官方PDF：`ca_300502_official_search3_20261028/cninfo_2021-030_1210131886.PDF`，SHA256 `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`。第3页余数从大到小派股、同尾随机；第4页新股上市2021-06-08。缺账户全体股东余数/中登结果，实际获配未知。
- 每条运行与报告必须写明 scenario=`floor`/`ceil`、strategy、账户身份为独立假设账户、实际获配未知、无法证明全国分配规则可能性已穷尽、不可实际税后/不可生产接受。

## 续跑决策
- 选择从anchor 2020-12-31初始化、覆盖完整W1日历（首个交易/信号日2021-01-04）用原始冻结信号与准备输入重新跑；不用6月7日断点恢复。
- 理由：core `run_account_backtest_from_orders` 仅由初始现金创建空 `AccountState`、空 pending 订单/结果及 observer 序号；没有恢复/导入 API。策略另有 `AllocationRegistry`、episodes/tranches、history/rejections，core 有锁仓、应收、未上市权益、操作幂等集、限价订单与成交历史。仅凭现金和股数无法还原；当前断点也无法证明逐事件前缀相等。
- 完整重跑的“prefix一致”验收：同一冻结版本原始全程重跑的2021-01-04至6月7日事件/每日 core state/订单/registry/hash与已冻结原记录逐行 canonical 比对；若无可比的全量prefix记录，则标记未验证并停止情景绩效，不能称恢复等价。情景注入只在指定登记事件生效，注入前的两支及原基线前缀必须一致。

## 限定注入设计
- 真实 core 链：`run_staged_window` → `CorporateActionContext.account_actions_for_day` → observer `on_update` → `run_account_backtest_from_orders` 开盘前/成交/登记/收盘阶段 → `apply_account_actions` → `ListShareEntitlement`；动作有 operation_id 幂等。
- core 可登记未上市浮点权益，但 `apply_account_actions` 上市时要求 shares 为整数；`fractional=True` 只属 paper，account 操作明确拒绝。不可更改/猴补真实 core wheel。
- 在隔离树增加探索专用 adapter/shim：仅允许 `(event_id, source_snapshot_sha256, official_pdf_sha256)` 三元组等于冻结白名单、标的300502.SZ、原始share_ratio/record date/listing date与证据卡完全匹配时，把该账户登记总量转为 `floor(q*r)` 或 `ceil(q*r)`；其他事件、任何输入不匹配、负数/超界/未知权益一律异常 fail-closed。不得修改生产默认路径或复用到其他运行模式。
- shim 必须保留原始 q、r、精确 entitlement q*r、floor/ceil计算、差额及来源逐行审计；core动作实际整数必须与分支值一致。不得伪称某分支为真实获配或将两策略ceil拼成一个全国可行账户。
- 注意：core `CreateShareEntitlement` 用同一个 shares_per_share 同时计算权益股数与成本basis重分配。探索注入只能把有效比例显式设为 `scenario_shares / record_shares`，并同时记录公告原比例；这表示条件账户的成本basis按实际注入整股同比例分配，不代表官方税务成本或真实券商算法。独立账本须复算剩余旧股basis+新增股basis等于登记日总basis，shares与权益价值按注入股数核算。若这一显式探索假设不能接受或不能守恒，停止，不可暗中改比例/标签。
- 所有旧事件、旧无限循环、无来源/未知事件仍走原有拒绝；20%现金股息扣税压力策略在8支完全相同，仅为压力假设。

## core能力审查结论
- 登记、除权/现金应收、上市操作与成本移动加权存在；除权动作在当日未执行订单前创建权益，登记记录在该日订单之后，上市动作在收盘前；真实调用时序需用官方6月8日路径验证。
- core `apply_sell` 将普通请求按lot向下取整，整笔请求等于全部可卖余额时允许零股清仓；locked股先从sellable扣除。分批策略 episode/slot 释放由 bridge 接收 execution updates 与快照驱动，未上市权益、锁仓、活动订单占用代码。
- `OrderIntent.limit_price` 固定股数；引擎在滑点前后按买入成交价不得高于限价、卖出不得低于限价拒单。已知6/7卖单46.18高于6/8最高34.55，须由真实core拒单并按原订单到期/策略重生规则处理，不得人工改价；核查是否存在续单和 slot 保留。
- 现金税只有 `pretax` 与 `cash_dividend_20pct_stress` 两口径；后者为现金股息20%压力而非个人实际税。送转税身份/税额/时点未知。税务不因 floor/ceil 改变。
- 不可变限制：实际安装的 core wheel（account_runner.py SHA256 `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`）不得改。隔离实施前复核 wheel 路径、版本及全部相关模块哈希与此身份；若不是该版本，停止并重新审查。

## 次序与阶段门
1. 新建独立 worktree；逐文件复算 `SOURCE_HASHES_FINAL.json` 的16项，绑定HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`、真实wheel、信号/模型、v12 manifest及输入源hash；数据只读。
2. 增加探索隔离模块、scenario manifest/CLI及单事件 mini：原始事件、floor、ceil三路真实core开盘→登记→除权→旧单→6/8上市；先QA，不跑W1绩效。任何门失败即保留失败证据并停止。
3. mini PASS后固定8个独立输出目录，以策略×情景命名；仍先只跑审计批准的mini与QA。全窗绩效需另行明确授权后执行，不得自动扩展。
4. 只有mini QA签署通过后才可将完整日历命令列为可执行；四策略×两分支统一报告，成功/中断/INCOMPLETE均纳入，分支失败不删除、不改假设、不择优。

## 输出、执行与限制
- 复用只读 `staged_prepared_inputs_20261027_v12`（manifest SHA256 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`）；不得重建/覆盖。输出放独立临时根，不写 `logs/` 或准备目录。
- 每支保存输入/源hash、白名单与注入记录、全量交易/拒单、逐日账户与registry、状态updates、成本现金账、事件差异、NAV/持仓上限审计、异常与最终manifest；用独立账本复算并逐文件SHA256。
- 8支是两种账户级整数化假设各自按状态演进的条件情景集，不代表官方分配结果、所有混合路径、其他公司行动/持仓状态/税务身份/部分成交可能性，也不构成真实收益的上下界。不得称干净考试；2021数据已见。
- 长任务若未来获授权，使用tmux并显式cd隔离树、remain-on-exit、记录退出码；本计划阶段不启动。任何失败均保留原始stdout/stderr、异常审计、配置和输入哈希；禁止覆盖重跑证据。
- 收尾：审计后先保留交付物和证据，再明确合并或放弃隔离树；决定放弃后才清理临时worktree/分支及可再生大产物。当前原冻结树和源工作树不做任何清理。
