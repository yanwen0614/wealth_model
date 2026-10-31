# 独立合成闭环进度

status: implementation_complete_pending_handoff
candidate_status: NO-GO
task_dir: C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness/
费用接口、core逐单注入、cnn runner E2E与终端审计已实现；cnn 10项/core 102项定向unittest和两仓定向ruff全通过。身份模块由其他执行者处理，本会话不改。
日期标签7文件及原三件套冻结，交主会话独立Luna审查，本轮不触碰。

## 研究与交付
- [x] 读取core根及契约规范、费用模型/配置、OrderStrategy、账户快照、订单驱动入口。
- [x] 确认费用模型无日期参数，并在core订单入口增加可选逐单resolver，默认静态成本路径不变。
- [x] 读取两条指定费用来源，确认2022-04-29过户费、2023-08-28印花税断点。
- [x] 检查已有模块/测试，未发现三个同名实现；复用core契约/费用公式，避免造撮合运行器。
- [x] 输出SYNTHETIC_PLAN.md、SYNTHETIC_CHECKLIST.md、SYNTHETIC_PROGRESS.md。
- [x] 完成历史费用/终端审计及cnn runner费用E2E；CNN 10项、core 102项定向unittest与两仓ruff通过。
- [x] JSONL E2E证据：`cnn_fee_e2e_xv8fqoth/{accounts,orders,trades,audit}.jsonl`；mark末日仅记真实残仓，locked事件数为0。

## 任务与依赖
|task_id|名称|状态|依赖|验收|修复轮次|
|---|---|---|---|---|---|
| S00 | 最小研究与独立三件套 | complete | 无 | 明确API、证据、六文件范围及NO-GO | 0 |
| S01 | 历史费用+core订单注入 | complete | 无 | 费率纯接口及实际订单/清算resolver | RED/GREEN；core定向102例PASS |
| S02 | 退出包装与审计 | complete | 无 | X/E/B、mark/T+1、当天估值/残仓审计 | post-X BUY RED/GREEN；6项相关测试PASS |
| S03 | 逐分支执行身份 | complete | 独立Luna会话 | capture_id独立、git根/模块/产物/依赖可核验 | 首轮FAIL后定点修复；复审待完成 |
| S04 | 独立合成闭环复核 | complete | S01/S02 | cnn runner真实现金、费率断点、JSONL证据 | cnn 10项/core 102项PASS；末日mark不推断locked |

## Generator交接范围
仅新增backtest/cnn_adapter/historical_costs.py、execution_audit.py、run_identity.py。
仅新增tests/unit/backtest/test_historical_costs.py、test_execution_audit.py、test_run_identity.py。
API签名/边界见SYNTHETIC_PLAN；历史费用函数不兼容冒充core无日期CostModel，必须显式传execution_date。
TerminalPlan固定X=max(d<evaluation_end)、E=max(d<=evaluation_end)；非交易日截止时X可等于E，buffer为E后至少一交易日。
ExitOnlyStrategy只读账户；core负责真实T+1与撮合；audit不修NAV，严格当天报价及最多10只。
身份仅采集/校验并返回结构，不保存/覆盖既有产物；实际执行前后都应独立采集并比对。
合成测试直接调用core订单入口验证终端；core改动仅新增可选费用配置resolver并继续复用原AShareCostModel与账户现金算法。
不新增通用运行器，不改已有审计脚本/__init__/记忆；仅订单resolver扩展core account_runner。日期标签代码冻结，测试仅有独立类型标注微修。
不提交推送删除、不问用户；每次写<=50行，中文，临时文件均在本任务根；无训练/GPU/W4扫描。
复审完成后交主会话；保留core/CNN定向测试、lint及JSONL证据，明确性能NO-GO边界。

## 不可解除的NO-GO
日期感知费用已接入合成真实订单现金路径；尚未证明真实市场执行可用：复权价/raw成交额/股数notional、完整半年无标签信号覆盖、公司行动台账与同时间基准仍未闭环。
buffer不保证清仓；mark不是liquidation；合成通过不是候选收益或真实成交有效性证据。
最终仅主会话根据独立审查决定后续接入与实验；本任务不比较任何候选结果。
