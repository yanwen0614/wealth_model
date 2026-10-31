# W1 双 core 独立只读 review_verify

审查日期：2026-10-29。审查者：接手独立复验的 Sol 主会话。总体 **FAIL**。
**封存修正：审查期间目标源码和双身份测试被外部修改，冻结完整性 FAIL。下述动态证据属于 HASHES_before 对应版本；不能认证最终磁盘版本。详见 FREEZE_DRIFT.md。**
有关外部新门的静态行号均指首次漂移`1213a9…c39d`，随后还观测到`a5e3c7…46ab`，未对移动版本重复验收；最后观测见 FREEZE_DRIFT.json。
CNN：`ce7d1c6e0bd64136f10759412c55f6da410f128f`，审查冻结工作区的实际文件，含既有未提交文件。
目标树：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`。
core 树：同级 `backtest-core-w1-stop-20261028`；HEAD 见 `CORE_after_HEAD.log`。
本报告及 VERDICT.md 是本次接手复验结论；目录中已有 FINAL_VERIFICATION.md 不替代本报告。

## 四层裁决

| 层次 | 裁决 | 依据 |
|---|---|---|
| mini 质量 | **FAIL**，审前版本自动检查部分 PASS | 106/106、0 skip，但独立反例及审期源码漂移失败 |
| 是否可尝试真实 cutoff | **FAIL / 不放行** | 公共 runner 仍依赖未来 proof，底层行情会读取截止后行，见证链错误 |
| 可信 prefix proof | **BLOCKED / 未证明** | 三个 trusted pin 均 None；真实前缀、12 路径比较未运行 |
| 实际目标 | **LOCKED / 未证明** | PIT、实际费用、税务/获配资格未知；无真实绩效证据 |

## F1：P1，公共 runner 对 cutoff 仍强制已有 proof

- 位置：`backtest/cnn_adapter/staged_candidate_runner.py:716-723`；内层 `:837-841` 仅在无 cutoff 时验 proof，两层不一致。
- 触发：调用公共 `run_staged_window`，使用 W1、floor、固定 2021-06-07 cutoff、相同 information_cutoff、真实 v12 构造的双身份。
- 结果：立即抛出 `prefix proof SHA is not independently pinned; performance is locked`，不会抵达 cutoff 身份检查或引擎。
- 证据：`BOUNDARY_PATH.log:1`，探针 `边界与路径探针.py`。市场为哨兵对象，日历为合成日历；不消费真实信号/行情、不运行真实分支。
- 影响：`run_single_from_cli` 在 `staged_production_inputs.py:839` 调用的就是该包装层。CLI 前面的绕 proof 逻辑和内层判断无法消除这里的循环依赖。
- 测试缺口：`test_fractional_scenarios.py:276-288` 只到缺失日历异常，不走完公共包装层。
- 建议：公共与内层共享同一套先验 prefix 资格校验；只允许固定身份、固定 cutoff 的研究运行免未来 proof；完整绩效继续硬阻断。补覆盖公共入口的回归。

## F2：审前版本 P1，默认 prepared 入口接受自签隔离 core 身份

- 位置：`backtest/cnn_adapter/staged_production_inputs.py:687-705`。
- 触发：QA 目录新建极小 manifest，声明当前真实隔离 core 路径和 SHA、`artifacts={}`，自行计算 sidecar；调用默认 `_verify_prepared`，不传 prefix context。
- 结果：**成功返回**。无 mock 的反例见 `IDENTITY_ISOLATED_RETRY.log:9`，样本 `自签runtime_manifest.json`。
- 根因：默认分支以用户提供的 sidecar 为 manifest 可信来源，再把 manifest 的 core path/SHA 当权威；并不独立固定原 wheel。
- 影响：一般 prepared-run 入口能接纳隔离 core 的 manifest；“默认生产只接受原 wheel”不成立。此探针只证明入口旁路，没有执行完整绩效。
- 归属：这是旧 prepared 设计保留的信任边界缺口，不能称为本轮新放宽。原 `ROOT_CAUSE_EVIDENCE.md:8` 已记录 sidecar→artifacts→当前 core 的同一设计。
- 建议：为生产模式独立固定允许的 manifest/schema/core 身份；至少在读取 artifacts 前强制原 wheel path+SHA，拒绝自签的新 core manifest。
- 现有拒绝测试仅覆盖“原 wheel manifest + 隔离 runtime”，没有覆盖本反例“隔离 manifest + 隔离 runtime”。
- 封存时外部新版本已加入 `_trusted_runtime_identity` 和原 wheel scope 检查；本反例不能直接归于新版本。修复效果未经本轮动态复验，不能以审前106项为其背书。

## F3：审前版本 P2，默认模式在 core 身份门前读取外部 artifacts

- 位置：同文件 `:697-705`，artifacts 循环先于 runtime path/hash 校验。
- 真实 v12 低开销探针：默认分支先请求首个 integration_inputs.json；prefix 分支先核真实 v12 字节、原 wheel、实际 runtime，再请求该 artifact，见 `IDENTITY_ISOLATED_RETRY.log:4-7`。
- 独立攻击：自签 manifest 索引 QA 哨兵文件并声明原 wheel，实际 runtime 为隔离 core；真实 open 顺序证明先读取哨兵，之后才因 core SHA 不符拒绝，见同日志 `:11-12`。
- 严重性：可用恶意 manifest 触发身份拒绝前的任意可读路径哈希/额外 I/O；可能导致耗时或提前错误。没有证明文件内容外泄或代码执行，故此顺序问题单独判 P2。
- 归属：**旧行为，非本轮新增**，旧根因记录明确证实；本次只新增 prefix 分支前置检查，默认路径保留旧序。未取得旧未提交源码的逐字快照，不能提供该段提交级 diff。
- 建议：生产硬身份、schema、manifest 字节和 sidecar 核验完毕后再遍历已信任清单；测试应断言被拒绝输入不触碰任何索引 artifact。
- 封存时外部新版本 `_verify_prepared:744-777` 已把 runtime/scope/sidecar 检查放在遍历前；这里只记录旧版本实测漏洞与既有来源，不声称新顺序仍同旧版。

## F4：P1，attestor 清空已核验的双身份，合法拒绝、空身份通过

- 位置：`backtest/cnn_adapter/prefix_attestor.py:135-138` 构建真实 `experiment`，`:157` 又设为 `{}`；`:169-175` 用空字典核分支。
- 合法反例：用真实 v12、真实 PDF、真实 import 和当前固定源码构造计划；合成八个目录填写完整正确身份。attestor 报 `branch dual-core identity differs from plan`。
- 攻击反例：仅把分支 prefix_experiment.json 和 audit 的 controlled_run_identity 清空为 `{}`，同一计划却能生成 **UNPINNED_ATTESTATOR**。
- 原因：`branch_identity == {}`，而缺失的 run_identity 字段与 `experiment.get(...)` 同为 None，逐项比较通过。
- 证据：`ATTESTOR_PROBE_RETRY.log:1-5`、`见证链探针.py`、`空身份攻击见证_复跑.json`。返回 SHA 为 `1ba4ad8a7c8331f82ec00e63c14084fbc5566142702a2942108552f192a4cbbc`。
- 范围：此探针明确 mock **整个 `_fixed_inputs`**，避免遍历 4812 路径/内容；没有 mock 身份构造、运行时 import、源码15项核验或分支身份比较。仅证明这一控制流错误，不证明真实八分支见证已成功。
- 影响：双身份虽进入 audit/verifier，却未贯穿 attestor。正常真实分支最终会被拒；空身份见证也不应生成。
- 安全限制：可信 verifier 在 None pin 门仍拒绝。未得到可信 proof PASS，空身份见证更不能代替真实 prefix。
- 建议：保留已构造 experiment，测试模式单独初始化；强制完整字段且拒绝空值。补生产 schema 下的合法端到端见证及空身份攻击回归。

## F5：P1，截止日行情请求仍解析、缓存截止后行情

- 接线：审前 `staged_production_inputs.py:609-610`（封存时新版 `:649-650`）设置 `signal_end=cutoff`，但 `execution_end=calendar[-1]`，该问题在新文本中仍可见。
- 底层：`raw_market_provider.py:66-72` 将完整 execution_end 传入加载器并缓存全部 records；`raw_market_inputs.py:215-245` 据该上界扫描、逐行验证并保留 execution_buffer。
- 独立两行合成 parquet：只请求 2021-06-07，delegate 缓存同时出现 6/7 与 **6/8**；guard 日志仅显示 6/7。
- 仅把 6/8 volume 改成 -100，6/7 的 get_bar 就因 **6/8 成交量非法**失败。将 execution_end 收窄至 cutoff 后，同一毒化文件能正常返回 6/7。
- 证据：`FUTURE_LOAD.log:1-3`、`未来行情加载探针.py`。这里是数据行解析/校验依赖，不能解释为无语义的整文件 SHA 校验。
- 范围：探针直接构造与真实加载接线相同参数的 provider，再经过真实 guard；使用 QA 合成数据，未读取真实 W1 行情，也未执行引擎。
- 影响：修复 F1 后，真实 cutoff 仍不能保证 6/8 以后行情不可用；API 访问日志不足以证明底层无未来访问。
- 建议：完整日历仅用于 T+1 排程，行情 scanner/provider 的数据上界独立限定为 cutoff。状态懒加载也应同样审核；新增“修改任意未来行不改变 cutoff 行为”的毒化回归。

## 已确认的身份与防线

- 真实 v12 manifest SHA：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；sidecar 精确64字节，无新增换行。
- manifest core_path 保持 `D:/code/cnn_full_20260905/cnn/.venv/Lib/site-packages/backtest_core/engine/account_runner.py`，原文件实算 `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。
- 显式隔离 PYTHONPATH 的真实 import 为 core 树 `src/backtest_core/engine/account_runner.py`，实算 `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- 独立子进程清除 PYTHONPATH 后实际导入原 wheel，原 wheel 不支持 stop_after_close，隔离 core 支持。证据：`ORIGINAL_IMPORT.log`、`IDENTITY_ISOLATED_RETRY.log`。
- 固定 prefix 身份构造真实成功；未 mock `_verify_prepared`，只在真实 v12 首次 artifact 内容读取前用哨兵主动截停。因此不把入口成功称为完整 prepared 校验成功。
- 一字节篡改真实 v12 副本、sidecar 加换行、伪造 singleton context 均拒绝；将相同 core 字节经 importlib 实际从 QA 异路径导入，也因路径不在固定 allowlist 被拒。
- audit 写入双字段（runner `:942-967`），verifier 核固定 prepared 身份、runtime path/hash、摘要及 audit 一致性（verifier `:342-380`）；F4 证明见证环节仍断链。
- 固定路径仍以实际文件和 inspect.getfile 检验；没有仅凭 PYTHONPATH 字符串认定 import。追加环境路径本身不等于身份旁路，本次不把环境字符串未固定单独判缺陷。
- 直接给公共 runner 构造 prefix identity 而不提供 cutoff，完整绩效仍被 pin 门拒绝。三个 trusted pin 均 None，没有改 pin、重签真实源或尝试发出 PASS proof。

## cutoff、时钟与知识边界

- 显式 6/8 get_bar/get_bars/get_history、排名访问、访问记录的四种日期字段，以及截止后账本行均被拒，见 `BOUNDARY_PATH.log:5-13`。这些通过不能抵消 F5 的底层解析缺口。
- signal loader 使用截止过滤（runner `:119-121`）；数量规则 lookup 日期取 execution_day 与 cutoff 的较小值（`:316-320`）；费用冻结只查询 cutoff 以前，未来待执行预算使用 cutoff 静态研究费用。
- 隔离 core `account_runner.py:1728-1819` 顺序仍为当日公司行动/解锁→执行已有订单→当日策略→收盘快照→cutoff break。6/7 close 决策仍解析到 6/8 open 的待执行订单，未把 6/7 变成日历尾日。
- 原 wheel `:1719-1808` 对应循环无 cutoff break；隔离版 `:1823-1836` 保存 pending_orders。两版默认 signal_time 15:00、T1_OPEN 09:30，adapter `:1140` 仍传15:00。
- 106 套件内实际执行了原 wheel/隔离 core 的合成逐事件等价比较（测试 `test_staged_candidate_runner.py:618-646`）；该证据仅限 mini，不能推断真实 W1 事件等价。
- 费用 PIT、来源可得性、实际券商费用保持 UNKNOWN；税务未知、压力税口径不等于真实个人税；actual_after_tax_target_eligible=False。未获得真实获配资格证据。
- 未来状态底层加载、真实 CA 全部行的可得性，本次未做完整独立数据访问跟踪；不得宣称真实运行全程无未来访问。

## 原 artifacts 与完整性范围

- v12 清单共有 **4812** 项；摘要均为64位小写十六进制，索引均为绝对路径。抽取8项小 JSON 输入实算 SHA 全与原清单相符，完整明细见 `IDENTITY_ISOLATED_RETRY.log:17`。
- 未重哈希剩余4804项，不证明全部 artifacts 当前存在、未变或 PIT 合法；未消费4GB训练源或真实行情窗口。真实 `_verify_prepared` 在首次 artifact 内容读取前截停。
- 四份原 baseline 的 audit/artifacts/sources manifest 共12项元数据摘要都匹配当前硬清单，原 core 仍为原 wheel；四份 audit 仍为 INCOMPLETE、原非整数送转中断，见 `BASELINE_METADATA.log`。
- 未复核四份 baseline 完整五类账本，不把元数据 pin 认作独立 canonical 信任锚。没有生成真实八分支、双 core 真实逐事件对账或12路径 proof。
- 首次中途快照曾23/23与补充4/4一致；最终封存发现 production_inputs 和双身份测试字节变化，最终清单以 `HASHES_before_*`、`HASHES_after_*`、`FREEZE_DRIFT.json` 为准。
- 审前探针确认 attestor 固定源码15/15匹配，仍非独立签名根；后来源码漂移使该结论不能外推至最终版本。HEAD/git status 清单相同也不能证明既有未提交文件内容不变。

## 执行记录与范围

- 审前版本定向单测：**106 项，失败0、错误0、skip0，167.170秒**，命令自然退出0，见 `UNITTEST.log:195-197` 和 `UNITTEST_命令.json`；源码/测试漂移后的版本未重跑。
- Ruff：固定主区 Python `-B -m ruff check --no-cache .`，退出0。Pyright：与交付相同四模块，0 errors/0 warnings/0 informations；不是全仓类型检查。
- `git diff --check` 退出0；全部实际命令、cwd、PYTHONPATH、起止 UTC 和返回码见各 `*_命令.json`，汇总 `CHECK_SUMMARY.json`。
- 长程检查在 tmux 运行；会话及 dead/status 见 `TMUX_STATUS.json`。执行器会继续收集后续检查，因此 pane退出0仅证明执行器完成，各检查应以各自记录为准。
- `IDENTITY_ISOLATED.log` 是最初绝对路径脚本运行时缺少 repo import 路径的失败日志，随后显式加入 repo PYTHONPATH 后通过，保留原失败证据。
- `ATTESTOR_PROBE.log` 首次探针因10秒工具超时中断，没有完成结果；随后在 tmux 下使用新目录复跑。复跑明确 mock `_fixed_inputs` 的范围已在 F4 列出，不能误记为全量输入见证通过。
- 日志里 synthetic COMPLETE、八目录、attestation 摘要均属于合成夹具；没有启动真实 cutoff 八支或绩效。
- 未修改项目/core 源码、wheel、v12 manifest、sidecar 或原 artifacts；未安装、未使用 uv、未提交/推送。新增脚本与证据仅写指定 QA 目录，每次写入不超过50行。

## 修复后最低复验建议

先修 F1/F2/F4/F5，并前置 F3 身份校验；保持三个 pin None。补公共 cutoff 入口、默认自签隔离身份、生产 schema 见证、未来行情毒化四类回归，重跑现有定向门及本目录独立探针。只有这些门通过，才能另行评估真实 cutoff 尝试；真实输入完整性、真实双 core 逐事件比较与独立信任锚仍是后续门，不得直接放行 proof 或绩效。
