# fix2：真实持仓与登记反馈上的 CA 阻断

状态：OWNER_READY_FOR_ORIGINAL_QA_REVERIFY。未启动全年账户，owner自测不等于独立QA通过。
目录：本隔离树；HEAD ce7d1c6e0bd64136f10759412c55f6da410f128f；无提交/推送/装包/修改共享环境。

## 两个缺陷的修复

- P1A：CA信息不再进入任何信号日的买入资格。`blocking_reasons=[]`；公告字段只保留为未认证来源。
- P1B：不再以“已知ex在期外”推断缺登记事件安全。缺登记日且首次真实正持仓时明确中断。
- 有登记日：核core实际登记量；登记前已卖出，登记量0，不因事后未来事件改变早期交易。
- 配股仅请求core的RecordPosition记录当日真实库存，不生成配股股份/现金或实施声明；正登记时权益未解即中断。
- 现金金额未知、送转税/整股政策未知均在真实正权益时中断；已解现金仍由原context/core记应收及20%压力扣缴。
- observer先透明交给既审记录器，后检查未知。保存引发中断的完整core回调，禁止回写过去订单或外推整期NAV。
- 记录日期作为条件事件日使用；公告日期不等于known_at证书。晚公告、已填公告、公告unknown均不反向预筛。

## 接线范围

复用既审Staged策略、预算registry、bridge、RecordingObserver与导出器；新薄接线通过原core公开observer/
account_actions_provider接口接入ObservedCAContext。无核心猴补、第二账本、已审源改动或状态伪造。
完整榜、五槽、T+1、每个反馈正持仓<=10、ST仅禁新买而允许已有持仓SELL均由原门及定向回归保留。
新增测试文件test_2025_restricted_fix2.py，其余修改仅既有入口与对应测试；两份QA记忆文件不覆盖。

## 真实RED/GREEN与结果

- RED_QA_PROBES.log：直接复用QA的完整80行信号与两份CA raw_row；旧实现两项均FAIL。
- GREEN.log：31项通过（原24项适配修正后的CA边界，新增7项）；REGRESSION.log：既审8套109项通过。
- RUFF.log：全仓--no-cache通过；PYRIGHT.log：0 error/0 warning；完整命令在verify.ps1。
- PROBE_RESULTS.json：11组持久真实core探针；core_*各目录是独占新输出。
- 晚rights/missing_cash：目标000001.SZ的1/3买、1/7卖与无CA对照逐成交全字段一致，无ca拒因。
- 缺record、ex=2/3：1/3真实买入后报record_date_unknown_positive_holdings；库存和锁仓均19,100股。
- 持仓记录1/6：登记反馈当日中断，1/3买入前缀与对照一致，保留库存，不发布主期或buffer终值。
- 登记日1/7开盘已卖：不误阻断；非持仓000099未知事件不干扰其他持仓。
- 停牌/未知ST/缺close锁住实际库存时，仍在正登记权益处中断，不假称清仓。
- A/B可有不同分数：NPZ小fixture明确令B不同，并断言各自rows逐值回映自己的exp_ret；未改原NPZ读取逻辑。

## 类型检查与来源

使用本目录真实存在的pyrightconfig.json及绝对--pythonpath；include按Pyright要求相对配置文件，extraPaths为绝对路径。
IMPORT_CONTRACT.json记录实际导入、签名及SHA：raw_provider来自只读集成树，core来自指定venv。
history_bars确属该集成provider关键字参数（默认20、正整数，读raw时的历史预热条数）；本入口显式21。
未删除参数或忽略类型错误。若解析到当前树旧provider，参数不匹配，应修正解析路径，不能改实际契约掩盖错误。

## 待独立QA与限制

PIT/公告/实施真实性、官方2025规则沿革、原件404、实际税及全市场数据覆盖仍未闭合；日期来源仅条件假设。
全部结果保留CONDITIONAL_RND/INCOMPLETE/PIT_UNPROVEN、NOT_EVALUABLE；未运行全年或据mini证明用户目标。
本次不证明异常源日期和全量真实CA资料完备性；未知实际权益路径会停止，不能当历史可执行收益。
BEFORE.json和FREEZE.json保留QA记忆两文件的前后SHA；FREEZE完成后owner停写，交原QA复验。
