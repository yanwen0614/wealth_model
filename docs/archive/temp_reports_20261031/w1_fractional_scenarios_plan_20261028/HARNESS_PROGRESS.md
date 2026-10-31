# Harness 进度：W1 碎股条件情景规划

状态：ANALYZE / 只规划审查。本轮未编码、未跑测试、未执行mini或W1绩效，未更改任何源工作树。

## 已完成的只读工作
- [x] 读取 `ca_uncertainty_bounds_20261028/最小预注册方案.md`：必须先审6月8日状态转移、证明完整状态前缀、固定假设，失败分支不得丢弃；两值不是无条件界。
- [x] 复核 `SOURCE_HASHES_FINAL.json`：16个冻结整合源/测试文件；独立QA `reverify1/QA_REPORT.md` 记录16/16匹配、HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`、v12 prepare退出码和manifest绑定PASS；不等于W1绩效通过。
- [x] 读取真实core调用链：`engine/account_runner.py:1590+` 初始化空账户并逐日运行；`:1721-1802` action与开盘订单/登记/收盘顺序；`engine/account.py:105-192` 动作幂等、记录持仓、应收、成本与上市；`:434+` apply_sell整手与全部可卖零股清仓。
- [x] 读取整合树 `corporate_action_context.py`：`:83-92` 非整数权益显式阻断；`:110-181` 生成阶段动作、仅现金20%压力税；`staged_candidate_runner.py:623-636` continuous未实现，旧provider拒绝；真实wheel不可修改。
- [x] 选择全程重跑而非断点恢复：core没有state restore API；策略registry/histories及core pending订单等均需恢复，只有现金/持仓不能保证前缀一致。
- [x] 规划临时输出根及所需文件：`PLAN.md`、`REVIEW_CHECKLIST.md`、`HARNESS_PROGRESS.md`。

## 文件级预期影响（未来隔离树，仅计划）
- `backtest/cnn_adapter/corporate_action_context.py`：目标事件来源绑定与探索模式显式假设；默认生产路径不变，未知事件仍拒绝。
- `backtest/cnn_adapter/<exploration_scenario_shim>.py`：仅白名单事件将登记权益整数化为floor/ceil，审计输入/推导/输出；不依赖改动core wheel。
- `backtest/cnn_adapter/staged_candidate_runner.py`：接收明确的exploration身份、写出免责声明、实际税后资格false、独立输出目录；原运行入口保持冻结默认。
- `tests/unit/backtest/test_<scenario>.py`：身份绑定、失败关闭、余数数量/成本/资金守恒、重复调用幂等、账户隔离。
- `tests/integration/backtest/test_<scenario>_real_core.py`：真实core wheel与mini fixture执行6/8状态迁移、旧单/上市/锁仓/零股卖出、前缀和独立账本；不得只mock。
- 输出证据目录：8个策略×情景独立目录及mini，保存manifest、原始状态updates、订单/拒单、日账、独立核算、hash和退出证据；复用v12只读输入。

## 待后续阶段（均未获本轮执行授权）
1. [ ] 主会话新建隔离worktree，确认base/原树状态；绑定16源文件hash、真实安装wheel及信号/数据输入身份。
2. [ ] 核实core成本basis转移与整数化权益兼容性。若保留官方比例和整数股无法由不可变wheel表达守恒成本，不得用替换比例掩盖；转为BLOCKED并呈证据。
3. [ ] 先写失败测试再实现白名单 shim（TDD）；补真实core mini测试。未知event/source/PDF及旧无限循环必须仍fail-closed。
4. [ ] 运行定向测试、Ruff/类型检查及独立7关QA；mini只验证6月8日，不产W1绩效比较。任一失败保存产物并停止。
5. [ ] 若mini与QA全通过，输出8支固定配置的命令与清单等待后续明确绩效执行指令；本任务不自动启动全窗。
6. [ ] 若后续获授权才用tmux启动长任务；记录自然退出码、stdout/stderr、输入与产物SHA。统一报告8支，失败照列，不择优。
7. [ ] 交付证据之后明确合并或放弃worktree；仅放弃且保存证据后清理临时树/分支和可再生缓存。

## 阻断/风险记录
- [x] 实际余数与中登结果不存在于当前已核材料：真实获配无法恢复；floor/ceil只是两种明确账户假设。
- [x] 无限循环与未知其他公司行动不在注入范围，继续原有fail-closed；两分支未穷尽其他不确定性。
- [x] 6/7限价卖单46.18高于6/8最高34.55；失败订单可改变持仓、资金与五槽生命周期，必须运行真实策略状态机审计。
- [x] `cash_dividend_20pct_stress`仅现金股息压力假设；实际税、PIT、送转税规则/时点未知，八支一律标非实际税后、生产BLOCKED。
- [x] 旧窗口属于已见历史数据；任何表现不构成干净考试，也不应用来事后选策略/分支。
- [ ] core成本转移与探索整数化注入的可表达性尚待隔离mini证明；证明失败时本计划终止于BLOCKED。

## 本轮边界与证据
- 仅读取已有临时证据、冻结整合源码和backtest-core源码进行调用链审查；未调用训练、prepare、测试或绩效命令。
- 最终只读查看主仓 `git status --short` 时发现多项既存修改/未跟踪文件；本轮未编辑、暂存、清理或恢复其中任何文件。由于没有任务开始前的status快照，不能声称这些改动由本轮前后对比证明为原有，后续隔离实施须先记录状态并避免覆盖。
- 三件套写入 `C:/Users/yanwen/AppData/Local/Temp/opencode/w1_fractional_scenarios_plan_20261028/`；源仓库不变更。
