# Fix2 冻结版独立 re_verify：FAIL

日期：2026-10-29。主区固定 Python -B 实测，所有新证据仅写本目录。
对象：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028` 与同级隔离 core。
依据原 `FINAL_VERIFICATION.md` 和 Fix2 交付重跑，不采用 owner/lite 或本会话此前只读 PASS 代替实测。
本轮结果纠正此前整体 PASS：生产 schema attestor 仍有 P1；审前审后无源码漂移，不能归因于移动快照。

## 四层裁决

| 层次 | 裁决 | 证据和边界 |
|---|---|---|
| 单测机制 | PASS；独立 Mini 质量门 **FAIL** | 165/165、0 skip；另有生产 schema 见证链攻击反例 FAIL |
| 是否适合尝试真实 cutoff | **不放行** | 固定 runner 身份/截止门已改善，但合法结果无法通过 attestor，空身份却可获得候选见证 |
| 可信 prefix proof | **BLOCKED／未证明** | 三个 trusted pins None；无真实八分支/12路径证明，外部根未独立锚定 |
| 实际目标 | **LOCKED／未证明** | 无真实绩效；PIT、来源可得性、实际费用、税务和实际获配资格未证明 |

## P1：attestor 重置已核验的 experiment，合法身份拒绝、空身份攻击生成见证

- 准确位置：`backtest/cnn_adapter/prefix_attestor.py:135-138` 构造并核对真实双身份；`:157` 随后执行 `experiment: dict[str, Any] = {}`；`:167-175` 以该空字典核分支身份和 audit。
- 合法反例：真实 v12、真实 PDF、实际隔离 import、真实15项源码清单形成生产 `w1_prefix_attestation_plan_v1`，八个合成目录写入完整正确身份。实际返回 `branch dual-core identity differs from plan: W1_B1_ceil`。
- 攻击：不改计划，仅把分支 prefix_experiment.json 设为 `{}`、audit.controlled_run_identity 设为 `{}`。attestor 实际生成 `UNPINNED_ATTESTATOR`，SHA=`76a209b428db1626ff8de0056d2324d4dad9ca9813cffd18d0ca9a0d95ac951f`。
- 原因：`branch_identity == experiment == {}`；audit 缺失键与空 experiment.get 的结果同为 None，比较全部通过。
- 独立证据：`LEGACY_见证链探针.log:1-14`。原探针适配保留攻击条件，只改变输出根；新增正确性断言以 exit 1 标识失败，没有把“脚本执行完”当 PASS。
- 探针限制：明确 mock **整个 `_fixed_inputs`**，避免遍历或重哈希4812项；真实身份构造、实际 import、15项源码哈希、分支比较均未 mock。该控制流缺陷独立于被跳过的输入完整性检查，但本探针不证明真实八分支可运行。
- 严重性：P1，阻断从合法 prefix 结果走到外部见证的闭环，同时允许身份缺失的候选见证。不是可信 proof 已被绕过；可信 verifier 仍因 None pin 拒绝。
- 165项为何未发现：`tests/unit/backtest/test_prefix_attestor.py:44` 用 `w1_prefix_attestation_test_plan_v1`，不走生产 schema 的身份检查分支。
- 必须修正：在 schema 分支前初始化默认 experiment，生产分支保留已构造身份；拒绝空身份/缺失关键字段。补合法生产 schema 正向见证和空身份攻击回归，再独立重验。本会话按只读范围不修代码。
- P2 另见下节；没有额外 P3。外部信任根和真实输入范围仍按下述限制 BLOCKED。

## 原 QA 身份/顺序反例已关闭：双环境实测 PASS

- `IDENTITY_ISOLATED.log`：实际 inspect.getfile 为隔离树 account_runner.py，SHA=`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- `IDENTITY_ORIGINAL.log`：独立子进程实际导入主区 wheel account_runner.py，SHA=`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。
- 默认自签 isolated manifest+isolated runtime：真实入口拒绝；原 wheel runtime 下同一合法结构恶意 manifest 也因声明 isolated core 被拒。两者均未打开不可信哨兵 artifact。
- 默认真实 v12+隔离 runtime：在读取 sidecar/manifest/artifact 前就拒绝。原 wheel 的默认真实 v12：通过 runtime/schema/scope/manifest 后才到首个 artifact 哨兵；在内容读取前主动截停，避免全部4812项哈希。
- Prefix 真实 v12：两种允许 runtime 的身份构造均通过，到首个 artifact 前截停；实际 cutoff CLI 仍只准支持 stop 的隔离 core。
- 任意构造 context、自签 prefix manifest、v12副本一字节篡改、sidecar换行、追加本 QA 目录的未批准 PYTHONPATH 尾部，全部拒绝且未读哨兵。
- 相同 core 字节经 importlib 从 QA 异路径实际导入仍被拒，见 `LEGACY_边界与路径探针.log:3-4`。
- 原 QA 四个脚本均已适配复跑，分别保存 `LEGACY_身份入口探针.log`、`LEGACY_见证链探针.log`、`LEGACY_边界与路径探针.log`、`LEGACY_未来行情加载探针.log`；路径、恶意manifest、guard、未来账本和原毒化条件均保留。

## P2：cutoff 信号仍完整 read_bytes 预载，再做受限的业务行读取

- 位置：`staged_candidate_runner.py:107-108` 对信号执行 `raw_bytes=p.read_bytes()` 并哈希整个文件；`:119-121` 才另走带日期谓词的 pq.read_table(path)。cutoff 模式不会把 raw_bytes 交给业务解析器，但完整文件字节仍先进入内存。
- 独立观察：`CUTOFF_BYTES_AUDIT.log` 记录包含未来合成信号行的整个 parquet 被 read_bytes，随后带 `date<=2021-06-07` 的 table 才返回两行。
- 严重性：P2，针对本轮“不得先加载未来整文件再过滤”的严格要求；它不是观察到未来信号参与评分/交易，也不是 raw/state 行过滤重新失效。
- 此完整读取用于固定信号文件身份 SHA，属于来源完整性操作，不产生历史 known_at/PIT 证据；不能把它说成“仅访问 footer”。若边界只排除未来业务行，则该业务行边界通过；若包括整文件预载，则当前不满足。
- 必须修正建议：cutoff 模式不保留完整 raw_bytes，改为流式 SHA 并直接用谓词读取业务表；这保持整文件摘要语义，但仍会对未来物理字节做完整性 I/O。若要求未来物理字节也零读取，应另设可信外部输入见证/截止分片，不能据当前完整文件 SHA 宣称零访问。

## cutoff 业务行、状态和 coverage：独立合成实测 PASS

- `截止边界.py` 创建自己的微型 signal/raw/states/fees/coverage，不使用真实 W1 数据。用实际 `_load_prepared_window`、provider、StateLookup、scanner，未 mock loader、状态或 raw 读取结果。
- 在实际 Arrow 调用外包裹观测器，记录 scanner 谓词并核对每个返回 batch；不是先伪造一个已过滤 DataFrame。raw 谓词为 `code==AAA AND kline_time<2021-06-08 00:00:00`，输出只含6/3、6/4、6/7。
- 未来6/8 raw volume=-100；按旧 execution_end 会触发真实校验异常，当前 cutoff loader 查询6/7正常，provider records无未来日期。旧参数反例保留于 `LEGACY_未来行情加载探针.log`，不可误记为当前 loader 失败。
- StateLookup 的 get/_rows/iteration/len 实际受 date<=cutoff 限制，三个允许日期，future get为None；pqarrow真实读取的filters和返回行数均已记录。
- 完整 coverage 故意写不可解析字符串，并把 Path.open 拦截为一旦打开该文件即 AssertionError：cutoff loader通过，PreparedWindow.coverage为{}；普通路径遇同文件实际 JSONDecodeError，换成合法coverage后正常解析并绑定实际SHA。
- 日志：`CUTOFF_POISON_FINAL.log` 与 `CUTOFF_BYTES_AUDIT.log`；完整普通路径控制仅限 QA 合成数据，未启动引擎。
- 其他业务日期门：guard、未来ranking、访问记录四类日期、截止后账本行均实际拒绝，见原边界探针复跑日志。
- 物理I/O边界：Arrow可能读取共用page/row group、schema、footer或统计量后完成谓词过滤；本探针证明进入Python业务解析/记录的行不越界，不证明存储层绝不触碰含未来值的压缩页。footer/元数据不是交易状态输入；完整信号read_bytes与footer访问须分开说明。
- 当前未完整独立跟踪真实 fee/CA/PIT来源可得性；静态费用冻结和 cutoff lookup 不能把未来准备的数据追认为当时已知。

## proof gate 与完整收益硬阻断

- 原 proof 循环探针已改为得到 `real W1 prefix requires prepared inputs...`，证明调用到实现层，未被未来 proof 抢先拦截；非法合成输入被拒，无真实数据访问。
- 相同调用去掉 cutoff 就报 `prefix proof SHA is not independently pinned; performance is locked`。CLI/context/公开wrapper/私有实现中的完整 fractional 路径仍保留可信 proof 校验。
- 实现层固定W1、cutoff==information_cutoff==2021-06-07，要求prepared/CA/数量规则/预注册费用及真实runtime与manifest摘要。带cutoff只计算截断账本，main_total_return为NOT_COMPUTED。
- 受限mini只允许固定短日历、SyntheticMarketProvider、至多5股/15行，不是完整真实W1的收益旁路。
- 未观察到prefix参数解锁完整fractional绩效；普通非fractional baseline本来不属于本proof门的目标，不能混称所有回测均须该proof。

## 独立回归、静态检查和实际命令

- 主解释器：`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`；没有使用uv或安装依赖。
- 独立九模块165项：**165 tests in 225.958s，OK，0 skip，exit 0**，见 `UNITTEST_165.log:186-188` 和命令JSON。不是照抄交付日志的229.692秒。
- 九模块为 dual_core_identity、staged_production_inputs、staged_candidate_runner、prefix_ledger_verifier、prefix_attestor、fractional_scenarios、staged_allocation、staged_order_strategy、staged_execution_bridge。
- 单独原 wheel prepare/run：**1 test in 3.400s，OK，exit 0**。165项中的生产测试也会从实验进程委派到清除PYTHONPATH的原wheel子进程；另跑单项用于核对生产环境不回归。
- Ruff 实际 `python -B -m ruff check --no-cache .`，exit0；Pyright实际核5模块（含runner和attestor），0 errors/0 warnings/0 informations，exit0；`git diff --check` exit0。
- 两种显式PYTHONPATH：隔离 core/src + repo；生产仅repo。实际 inspect.getfile 与SHA见双环境身份日志，没用环境字符串代替实际导入证据。
- 每条实际命令、cwd、PYTHONPATH、UTC起止、退出码保存各 `*_命令.json`。所有长任务在tmux执行，`TMUX_STATUS.json`记录pane状态。
- 执行器继续收集全部检查，故tmux pane退出0不能替代各命令状态。生产schema见证探针单独exit1，正是本次FAIL证据；没有用165项退出0掩盖它。
- 初版独立截止夹具缺两个buffer日，首次失败为自身fixture配置；第二版缺quantity_sources元数据，亦为自身夹具缺项。均仅修QA脚本，保留 `CUTOFF_POISON.log` / `CUTOFF_POISON_RETRY.log`，最终实际loader/scanner探针通过见FINAL与BYTES_AUDIT日志。

## 前后完整性、原始输入及范围限制

- 本轮对两树 git ls-files 的全部modified/untracked文件加固定source清单、原wheel、v12 manifest/sidecar做审前审后摘要，共**36项，全部一致**。`HASHES_before.json`、`HASHES_after.json` 和 `HASHES.sha256`记录实际值；两个HEAD/status清单亦一致。
- 当前 production_inputs SHA=`cef7b7bb2b7e21ce31f58929a07f2531e6f5e25aa5b6239475d45f05d0675f84`；runner SHA=`46450be07562b4d49387b8cc4955df096931641af768f4b4e91886a40c322ae3`。
- attestor fixed_source 15/15均实算匹配，包括更新的两个文件；attestor自身和gate也在本次工作树改动快照中哈希，但不属于独立签名信任根。
- 真实v12 SHA仍`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；sidecar精确64字节，原wheel/隔离core当前实算均匹配固定身份。
- 只抽样重哈希8项小JSON输入，原清单、探针实际、审后实际三方相等；其余4804项未全量核验。不能声称所有历史输入已独立证明未变。
- **未访问、未重新哈希完整4GB训练源，也未访问真实W1/真实6/8业务行。**未读取真实raw/state parquet业务数据；原反例里的未来行均是QA内新建夹具。原官方PDF及小配置用于身份和计划，不是运行真实窗口。
- 真实v12入口在首个artifact前截停，原输入完整校验、真实CA、真实费用、独立canonical baseline五账、实际prefix逐事件等价均未覆盖。
- 全局manifest/源码/输入哈希仅绑定文件完整性，不表明数据在2021年已可得。原准备过程对完整窗口做过的数据准备也不获得PIT认证；实际券商费率、来源可得性、个人税、实际分配资格均不据此闭合。
- 三个trusted pins保持None；不写外部信任根，不把本机可写见证或本报告当作独立签名。`UNPINNED_ATTESTATOR`不是可信proof PASS。
- 日志中的COMPLETE、八个分支名和attestation摘要全部是合成测试产物。真实八分支/12路径proof/绩效均未启动。
- 未改项目源码、core、wheel、真实manifest/sidecar或源数据；未安装、提交、推送；全部新增脚本/夹具/日志/报告仅在指定reverify1目录，每次工具写入≤50行。

## 必须修正及后续门

1. P1：保留生产schema已验证的experiment，拒绝空身份，补生产schema正反见证回归。
2. P2：严格禁止完整信号预载时，cutoff改流式完整性核验并走谓词读取；若连未来物理字节也禁止，则需可信外部输入证明或截止分片，明确该边界，不能称当前仅footer读取。
3. 修复后重新冻结相应源码与fixed_source，再重跑本目录两个attestor反例、身份/截止探针及165项门。即便mini质量恢复PASS，真实cutoff可行性、可信根与完整输入仍需另证，不自动放行proof或绩效。
