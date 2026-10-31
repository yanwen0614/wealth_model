# W1 ceil 精度修复独立只读 QA：FAIL

日期：2026-10-29。不采用 owner 的“独立QA PASS”作为证据。本报告基于当前代码、独立测试及v2旧账本。
HEAD=`ce7d1c6e0bd64136f10759412c55f6da410f128f`，保留既有未提交改动，未修改共享源码或core。
修复源码SHA=`7112bedef9a10d802e58f18580e391e25355803c838b401c215941cb9ce37180`；测试SHA=`d8105496c0f0a19017ef2e18be47c8ef03190b5efd4d01c2e37d4548c67831a5`，均与用户指定一致。

## 四层裁决

| 层次 | 裁决 |
|---|---|
| Mini质量 | **FAIL**；28项定向与独立机械场景通过，但168项交叉回归有2个ERROR，固定源码门仅14/15匹配 |
| 真实cutoff可尝试 | **不放行**；attestation plan及source门已实测因旧pin阻断 |
| 可信proof | **BLOCKED／未证明**；三个trusted pins仍None，没有新的真实八支或12路径证明 |
| 实际目标 | **LOCKED／未证明**；分配、税务、来源/PIT及实际绩效均未证明 |

## P1，必须修正：fixed_source_sha256 仍固定旧源码

- 位置：`backtest/cnn_adapter/prefix_attestor.py:35`。
- 清单声明 `fractional_scenarios.py` 为 `9e78eae5ddfa9776e1b248e4bd3b389d06da5c254c8d01bacba54f369eb6f2f2`，实际是本轮 `7112bedef…37180`。
- 独立对15项实算，只有这一项不匹配。真实 `_check_fixed_paths` 报 `source fixed SHA mismatch`，`PIN_ARITHMETIC.log:2-8` 保存原始异常和非零退出码。
- 交叉回归第一处：`test_dual_core_identity.py:276`→`fractional_scenario_cli.py:79`→真实file_sha256，attestation plan建立阶段就拒绝，见 `CROSS_REGRESSION.log:189-210`。
- 第二处：`test_prefix_ledger_verifier.py:372`→`prefix_ledger_verifier.py:245`，报 `external attestation source SHA mismatch`，见同日志`:213-230`。
- 影响：不是只有事后QA不认可，真实前缀入口准备计划就会被阻断，不能尝试真实八支后再看。28项通过无法抵消该P1。
- 必须修正：在独立审阅新源码后同步本轮固定source摘要，并重新冻结source/attestor及新交付证据，再重跑dual/prefix/attestor交叉门。不得改写历史fix3清单冒充旧冻结版仍匹配；不得通过mock或放宽检查跳过。
- 本会话按只读授权未修复该pin，也未改任何主交付文件。

## P3，非阻断：历史根因说明中的floor算术错误

- `w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md:28` 把“所有floor”及q=4000→1600合并描述不准确。
- 精确官方乘积4000×0.4002532=1601.0128，floor应为1601，有效比例0.40025，不是1600/0.4。
- 当前源码、独立Fraction计算、两种真实core合成结果均为1601。建议修正文档，不改变本次ceil根因结论。P2：未发现新增事项。

## 数学、有限/循环小数与原比例

| q | 精确q×0.4002532 | floor n | ceil n | ceil有效比例小数 |
|---:|---:|---:|---:|---|
| 1300 | 520.32916 | 520 | 521 | 521/1300，非终止 |
| 2800 | 1120.70896 | 1120 | 1121 | 1121/2800，非终止 |
| 4000 | 1601.0128 | 1601 | 1602 | 1602/4000，有限 |

- 用独立Fraction精确计算n，未把被测resolve当作期望值。六组均验证 q×Fraction(n/q)==n，且 q×core float_ratio==float(n)，数量没有epsilon。
- 原比例仍是0.4002532；snapshot原raw_row未变。仅目标事件校验时创建临时adjusted descriptor，不修改原descriptor或官方事件源。
- NaN、±Inf、0、负数、非整数登记量均实测拒绝；非目标非整数事件和生产默认上下文仍精确拒绝，不作通用rounding。

## 官方证据与白名单拒绝

- 独立读取固定PDF `cninfo_2021-030_1210131886.PDF`，共4页；实际SHA由测试夹具实算，并用validate_descriptor与固定值c09dfd…277bd核对。
- 第1/3页确认调整后每10股转增4.002532股，因此本模型登记权益比例为0.4002532；第3页登记日6/7、除权日6/8；第4页无限售转增股起始交易日6/8。
- 公告第1/2页的0.3999999是除权定价所用总股本摊薄口径，不能替换本次登记数量计算的0.4002532。
- 第3页说明不足1股按尾数从大到小派发，同尾数随机；无法仅据单账户q证明其实际floor或ceil。因此两分支仍是条件假设，非真实获配证书。
- CA snapshot loader实际核验e7b1…86bcf manifest与3份core_data JSON摘要，再选择目标descriptor。没有伪造官方PDF，也没有重哈希训练源。
- 独立分别篡改event id、源文件SHA、PDF SHA、证券、record/ex/listing日期、原比例、row SHA共9项，validate_identity全部拒绝；正式descriptor路径还检查record/ex/listing和source_snapshot_hash。
- 这些检查在可信snapshot loader输出范围内成立；不能把可写Python对象或人工构造mini上下文当作真实输入PIT认证。

## n/q字符串、JSON与实际loader/core路径

- `fractional_scenarios.py:165-173` 的 `n/q` 是临时raw_row内的普通字符串，供基类 `Fraction(str(total))` 使用，不是JSON中不支持的Fraction对象。
- 独立观测实际传给基类的adjusted descriptor，序列化为 `{"每股送转":"521/1300"}` 等，再解码后Fraction仍精确，且原snapshot raw_row不变，见 `PIN_ARITHMETIC.log:1`。
- `corporate_action_context.py:87-90` 同时校验精确Fraction乘积与float机械乘积。`:179-181` 生成CreateShareEntitlement时仅传event.share_ratio这个float。
- 目标 `_ex_actions` 也用同一resolution构造effective float；实际action JSON中的shares_per_share均为数字，不包含分数字符串。
- 原core/隔离core不读取adapter的raw_row；`engine/account.py:143-157`只用记录数和action.shares_per_share生成权益并分摊basis，`:174-184`严格要求上市权益是整数。
- 没有“把含n/q的伪原始行再交官方snapshot loader加载”的实际路径。官方loader仍加载原始受哈希保护的0.4002532；不声称官方loader接受任意n/q输入，也不应把临时行写回官方源。

## 真实core合成回放与cost basis

- 两个独立进程分别真实import原wheel `aa156ec2…8daa00`、隔离core `4d3a28c4…0a1819`，路径与实算SHA见 `CORE_ORIGINAL_RETRY.log` / `CORE_ISOLATED_FINAL.log:1`。
- 两版各运行q=1300/2800/4000×floor/ceil六个五日合成case：6/4发买单，6/7成交后登记q；6/8CreateShareEntitlement数量恰n，随后List后持股q+n；旧卖单limit46.18实际拒绝。
- 6/8动作生成前使用真实登记state，单独调用真实apply_account_actions观察未上市阶段，验证旧股basis+entitlement.cost_basis_total等于权威record_costs；再对实际core上市快照验证总basis守恒。
- 原始登记basis分别45513、98028、140040；额外成交成本使其不同于报价35×q。守恒对比的是权威登记basis，不是忽略执行成本的报价。
- 两个ceil关键例：1300→521→1821，2800→1121→3921；q4000 floor→1601→5601、ceil→1602→5602均通过。数量断言为精确相等；货币basis仅用标准float舍入误差界比较，不修改生产数量规则。
- 独立mini初始化明确使用短日历和__new__+基类初始化，仅供机械验证，不能当作公开完整绩效绕门。所有市场价格来自SyntheticMarketProvider，未跑真实W1。
- 初版QA误用固定报价35×q比较basis而失败；仅修正QA为record_costs后通过。隔离prefix探针第一次漏设evaluation_end=cutoff，被core契约拒绝；补齐QA参数后通过。原日志保留，不把夹具错误归因共享代码。
- 对隔离core额外运行q1300/2800 ceil cutoff=6/7：完整五日日历保留，原生stop_after_close与evaluation_end一致，市场guard和动作provider均未请求6/8业务数据，6/7 observer已算出521/1121。见 `CORE_ISOLATED_FINAL.log:9-10`。
- 原wheel没有stop_after_close参数，按其原默认五日路径核验；没有声称其支持真实cutoff。

## v2已有真实前缀五账：只读检查，不是本修复重跑

- 实际流式读取8分支×5类JSONL，共40份旧账本，约2.337GB；逐行解析统计日期与目标record_positions，未重新哈希这些账本或重放账户。
- 所有有日期行的最大业务日期均为2021-06-07；B1登记4000，S1/S2登记1300，C70登记2800，符合真实失败的q来源。
- 五分支exit0但INCOMPLETE；S1/S2/C70 ceil仍为旧的FAILED，错误是noninteger_or_unrepresentable_share_quantity。没有任何分支因本次QA而更新状态。
- `V2_LEDGERS.log`保存每账本行数、日期区间、文件大小和登记q；`SUMMARY.json`保存汇总。没有读取真实6/8行情，也没有新的6/8真实公司行动执行。
- 不重做canonical baseline逐行比较、不生成12路径proof；旧账本支持根因诊断，不证明当前新代码已真实运行成功。

## 测试和静态门的实际结果

- 固定主区python -B、显式隔离core/src;CNN PYTHONPATH；全部长任务tmux。原wheel对照为独立子进程仅repo PYTHONPATH，实际路径/SHA已记录。
- 定向 `test_fractional_scenarios`：**28 tests in 16.525s，OK，0 skip，exit0**。
- 九模块交叉：**168 tests in 259.210s，errors=2，0 skip，exit1**，包含既有dual、prefix verifier、attestor、production inputs、staged runner、allocation、order strategy、execution bridge及fractional。
- 两个ERROR均已定位P1旧source pin，并非随机测试不稳定；没有修改清单或mock掉失败重新报PASS。
- 独立有理数/JSON/白名单探针：算术部分通过，随后真实source门断言exit1，作为P1复现证据保留。
- 原wheel六场景 `CORE_ORIGINAL_RETRY` exit0；隔离core六场景+两cutoff `CORE_ISOLATED_FINAL` exit0。此前QA夹具失败日志均保留，以最终命令记录为准。
- Ruff `python -B -m ruff check --no-cache .` exit0；Pyright七模块0 errors/0 warnings/0 informations，exit0；git diff --check exit0。
- 全部实际argv/cwd/PYTHONPATH/UTC起止/退出码见各 `*_命令.json`，汇总见SUMMARY.json。tmux pane退出0仅表示执行器收集完毕，不能掩盖交叉exit1。

## 审前审后、证明边界和修复要求

- 审前审后38项摘要完全一致，两个HEAD/status路径清单一致；见HASHES_before.json/HASHES_after.json/HASHES.sha256。包含两树既有改动文件、固定源码、原wheel、v12 manifest/sidecar与本轮报告/根因说明。
- 新源码与测试恰为用户指定SHA；fixed_source却14/15匹配，差异已存在于审前并持续至审后，不是审查过程中源码漂移。
- core account_runner仍为隔离4d3a28…0a1819、原wheel aa156e…8daa00；CorporateActionContext默认精确校验代码未改。本会话没有改共享源、core、wheel、官方PDF或原数据。
- 三个proof/attestor/external-root trusted pins均None；实测proof gate拒绝，完整fractional绩效未放行。即使后续同步source pin，也不能把本机候选见证当可信根。
- official_fractional_rule_exhaustiveness_proven=False、production_acceptance=BLOCKED、actual_after_tax_target_eligible=False及tax_unknown均保留。公告差别化税率不等于本账户实际税；20%仅压力假设。
- 成本守恒只验证core的条件float账务公式，不等于券商真实成本或税务证书。官方尾数排序/随机规则不能从单账户q推出实际分配。
- 未访问完整4GB训练源，未遍历/重哈希4812个prepared artifacts，未安装、uv同步、提交或推送。只读检查了旧v2账本，**真实W1 prefix尚未按本修复重跑**，更未运行真实绩效。
- 修正项：P1同步本轮源码固定pin并重跑交叉门；P3纠正根因文档floor4000笔误。前者完成并独立复验前，不放行真实cutoff尝试。当前没有其他P2阻断。
- 审查完成，停止新增探测；只在指定独立目录保留QA脚本、合成夹具、原始日志及报告。
