# W1 完整 prefix 一致性证明方案

## 决策
- 可从冻结输入独立生成 floor/ceil 两分支到 2021-06-07 为止；不需要跑到 E 日，也不需要恢复 core checkpoint。应以 anchor 初始化、复用冻结信号/输入/日历，执行至 6/7 收盘状态，硬性禁止消费 6/8 行情/订单成交/登记日事件。
- 现有 `staged_candidate_runner` CLI 只接受完整 `evaluation_end` 与 execution calendar；当前情景 CLI 构造完整 W1 命令。当前 `fractional_prefix_gate.TRUSTED_PREFIX_PROOF_SHA256=None`，只检查调用者给入的文件摘要/字段；不能由手写 JSON PASS 解锁。
- 因此实现前需隔离树内源码改动：加受限 prefix-only 运行模式和机器生成 proof verifier / 可信独立 pin 流程；不改主区及其他会话 worktree。编码仅由隔离树唯一 owner 完成，Quality Gate 独立 QA PASS 后才交付审查；本研究未授权执行后续全窗/8分支绩效。
- 仅把 calendar 截短而仍传 6/30 evaluation_end 可能改变窗口信号/缓冲语义；需设计明确的 prefix stop-at-date 参数，runner 在目标末日完成收盘 snapshot 后立刻停止，并验证不处理下一日。不得直接复用绩效入口伪装 prefix-only。

## 受控重放阶段
1. 先冻结只读身份：base HEAD、16 个整合源文件、情景相关实现/配置/脚本、CLI argv、uv.lock/pyproject/Python 3.12、backtest_core wheel SHA/版本/导入路径、v12 manifest、预注册及其全部输入、W1 signals/checkpoint SHA、CA 官方 PDF SHA。输出放新建独立证据目录。
2. 以原失败默认模式分别运行 B1/S1/S2/C70 四次，从 anchor 2020-12-31 重放完整原始 W1，预期同一 2021-06-08 CA ValueError；使用各自全新目录，运行至异常但不汇总/读取绩效指标。核对异常类型、事件 ID、失败原因及前一交易日末状态。
3. 对每策略将新运行到 2021-06-07 的 updates、daily_registry、strategy_decisions、registry_transitions、partial states 与冻结原账逐行比较；行数必须相同、键/序号无洞无重复、日期严格符合预注册交易日序列，缺行/多行/乱序/任一未解释差异均 FAIL。
4. 再用 prefix-only 引擎各跑 floor 与 ceil；事件注入点在 6/8 登记处理之前。逐策略要求两分支截至 6/7 的四套事件账、core state、所有已提交订单/数量/限价/状态、registry、episode/slot 与原始默认重放完全相同；源运行与分支的稳定实体键序列一致。
5. 注入事件的审计必须唯一匹配 300502 目标 operation/event ID、source snapshot SHA、官方 PDF SHA、登记日、原始比例、账户登记股数、floor/ceil 取值。事件之前先要求相同 hash chain 和逐行匹配；首个允许差异须正好是目标登记动作的 fractional quantity/新增权益与由其直接派生的状态字段。
6. 两分支都要证明“只在指定事件后分叉”：列出第一差异 event/key/old/new；目标事件之前要求零差异，事件之后要求所有更新可由分支数量账解释。分支订单与 registry 只有在受影响状态传播后才允许不同。

## Canonical 比对、证据可信与门禁
- 逐行读取 JSONL，拒绝空行以外的非法 JSON；建立 `line_no + sequence_no/event_id + date + phase + stable order/fill/operation IDs` 键。禁止 set 化、排序后比对或仅比较行数/汇总 hash。
- 生成字段级差异表：策略、分支、源文件、基线行号、重放行号、事件键、JSON Pointer、基线值、重放值、分类、裁决。缺行/多行单列，任一无豁免项即 FAIL；保存全量机器 diff 和零差异摘要。
- 先对原始 JSON 行字节及解析值做精确逐行比较；只有复跑实证确认不稳定后，才允许白名单化绝对输出根等环境字段。不得默认剥离 run ID（原账 ID 是关联业务键），更不可删除 phase、sequence、order/fill ID、状态字段；确需映射时须证明一对一、无悬空引用并同时保存原值差异。
- proof 由独立 verifier 从实际输出、源哈希和差异产物计算，proof 包含每输入/输出 SHA、CLI argv、环境/wheel、截止日期、计数、逐日/逐事件链根、差异数量、异常、verifier 版本与退出码。Verifier 不接受 caller 提供 `PASS`、布尔通过字段或自报 SHA 作为结论。
- 独立 QA 复核 canonical 规则、恶意篡改/漏行/换序/改字段失败用例及 proof 再生成；之后由独立可信 pin 流程核验 proof 内容并固定 SHA 到受保护源码/配置，再验证 tamper/caller SHA 不能通过。只有上述全通过才允许后续授权的情景绩效入口消费 proof。
- 绑定四策略三路径：分别绑定默认重放、floor、ceil 的 runner/策略/桥接/数量分配/core observer/CA context/CA hook/registry recorder/CLI/输入校验配置 SHA；目录清单外文件不得动态 import，分支参数不可由调用者覆盖。所有 12 个重放输出逐文件哈希归档。

## 前视阻断、mini、运行成本
- 6/7 prefix 运行的信号读取允许冻结全量信号文件，但决策 API 仅可返回 signal_date≤6/7；应记录加载 SHA、每次读取的数据日期范围、执行决策时间与事件时间。行情 provider 请求上限为 6/7；对调用层加硬 guard，任何 `date>2021-06-07` 或 6/8 corporate action/order fill 请求立即抛错并记录，输出无 6/8 内容。
- CA 输入保留原冻结 manifest 与公告 PDF 的路径/哈希；按实际可得时点过滤，避免用事后资料驱动 prefix 决策。目标 floor/ceil 数值仅在 6/8 登记动作执行点注入，登记前任何读取均 fail-closed。记录每个 market/state/CA 文件打开时点、逻辑查询日期和哈希。
- 可先做真实 mini：截取冻结原数据中不含目标事件的少量连续交易日，原默认与 floor/ceil 在共同日期应完全一致；再用独立小夹具验证目标注入及 6/8 越界 guard。mini 只验机制，不代表全前缀证明，不可发 PASS proof。
- 预计 4 个默认重放约等于既往 W1 批次单策略计算总时长；历史八窗预计算约 2041 秒仅作量级参照。追加 8 个 prefix 分支涉及同样日期/状态 IO，但截止 6/7，预计总计约 12 次单策略前缀运行、约 40–90 分钟，最敏感变量是共享行情读取和重放落盘量；先用 mini/单策略计时校准，禁止为省时并发争用 Z 盘。
- 若需后台运行，tmux 新建唯一命名会话、命令内显式 `Set-Location` 到隔离树对应 shell 可用的绝对路径、remain-on-exit 保留退出码；输出重定向到新的独立证据目录，逐策略子进程记录 argv/stdout/stderr/退出码。短轮询 pane_dead/status 与退出码；禁止复用会话、覆盖输出、后台作业直接启动或跨 worktree 操作。

## 放行条件与边界
- 放行仅表示四个原始失败 prefix 可复现，且两分支直到 6/7 与原账一致、6/8 目标事件前无差异；不代表目标真实获配，不代表两场景穷尽官方分配，不代表可执行/实际税后，也不构成策略目标验收。
- 当前目标仍未验收；2026-01~08 已探索数据不能作新规则考试。不得把 prefix proof 写成完整收益资格或自动触发任何全窗/绩效运行。
