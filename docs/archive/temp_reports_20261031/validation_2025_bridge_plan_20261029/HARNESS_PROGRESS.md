# Harness进度记录

## 本次只读分析

- [x] 用户边界锁定：只读分析和任务拆解；不写代码、不训练、不执行完整回测。
- [x] 使用现有2025执行计划 `validation_2025_execution_plan_20261029/PLAN.md` 作为事实底稿，核对其EVIDENCE与COMMANDS。
- [x] 查看共享主区 `backtest/cnn_adapter/runner.py`：真实core订单入口存在，但普通target CLI不能提供本任务完整输入、终端审计和持仓硬约束证据。
- [x] 查看已审staged树：`staged_candidate_runner.py`、`staged_production_inputs.py`、`staged_order_strategy.py`、`staged_execution_bridge.py`、`quantity_rules.py`。
- [x] 得出最小建议：以staged真实core账本为唯一执行路径，新增窄NPZ-ranking桥和2025薄调度；不造第二账本。
- [x] 明确固定staged五槽政策仅为满足≤10的候选研究政策；不是10只策略，A/B必须并列且不可择优。
- [x] 明确状态盘前时点未证是关键阻塞；允许逐码UNKNOWN拒成交但必须保留机会与rank；关键估值/状态未知则INCOMPLETE，禁止全拒零收益冒充达标。
- [x] 形成新隔离worktree、唯一编码owner、TDD/独立QA、命令模板、安全边界、预计8–17小时与依赖清单。
- [x] 写出PLAN、REVIEW_CHECKLIST、HARNESS_PROGRESS三个任务文档。

## 未执行

- 未写/改项目代码，未运行单测、ruff或完整数据准备。
- 未训练，未运行A/B完整回测，未重算输入哈希，未读取/修改W1研究树和CA冻结证据。
- 2025真实状态来源/盘前时点、行情/CA完整覆盖、历史费率逐笔可用性仍是实施前必须核查的输入阻塞；不把本计划等同于审计PASS。

## 实施阶段门

1. 负责人冻结基线、输入清单和来源SHA；如关键状态/CA缺源，先补证据或接受整组INCOMPLETE。
2. 单一owner在一个新worktree实现NPZ桥与薄调度；先写红测，再以mini fixture打通core observer和账本审计。
3. 独立QA针对冻结commit审查输入谱系、硬约束、未知拒单/机会保留、单账本与全量diff；最多两轮修复。
4. 门禁PASS且输入coverage足够后才允许一次共享准备、A/B连续全窗运行、独立逐账对账；长任务仅tmux/psmux。
5. 最终按成本后净NAV、同期沪深300、每笔/每日持仓上限三条件联合判定；报告验证期非独立性质和所有UNKNOWN/未覆盖。
