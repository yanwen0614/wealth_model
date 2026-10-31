# 批准裁定与审查清单对照

以下对照 ORCHESTRATOR_DECISIONS.md、PLAN.md 和 REVIEW_CHECKLIST.md 的实际要求；后续裁定优先于早期计划的宽泛表述。

| 检查项 | 结果 | 依据与限制 |
|---|---|---|
| 独立树四文件交付、不改core/runner | FAIL（最终冻结） | 测试完成时四文件哈希吻合；末次复核loader和context测试被外部改写，见SHA_FINAL_CONFLICT.json |
| 原始来源、文件SHA、行hash | PASS | manifest外部钉住，三个实际输入均验SHA；8752行逐行哈希复算；另12项来源SHA独立复核 |
| 原始进度未知，不凭进度造实施 | PASS | 3=3506、1=4112、2=1119、12=2、4=1；保留原值，不按码判定官方实施 |
| T唯一总送转、不C fallback、不双算 | PASS | 451行B或C正全部T=B+C；8行两者同时正；descriptor单一event且raw保留B/C/T |
| 混合现金股权单次成本分配 | PASS | 真实core复合事件30新股，成本守恒；无exempt_capitalization税务声明 |
| 透明observer、完整post_state | PASS | 原update对象转发、所有ExecutionPhase、sequence连续、delegate异常原样传播并留INCOMPLETE |
| hook开盘前、core开盘单后登记 | PASS | core account_runner实际1721/1742-1744时钟；真实订单入口买入后登记100股 |
| anchor前且空仓reset才跳过缺record | PASS | 严格早于anchor+empty_reset；anchor当天/之后缺记录反例已拒绝 |
| 零登记无幽灵、无关未知不误阻断 | FAIL | 常规零登记真实core通过；同日record/ex的空仓事件独立反例失败，P1-01 |
| 登记后现金卖至零仍支付、股权变仓不造账 | PASS | 真实core现金18元；股权变仓明确core_share_holdings_changed_unsupported |
| 精确整数、不floor、正权益缺字段阻断 | FAIL | 非整数、缺上市/派息/除权日期测试通过；未知现金数额未被阻断，P1-02 |
| 税未知严格模式、探索机械账与stress边界 | PASS | strict默认true；探索正权益仍INCOMPLETE；现金stress仅20%，不认定实际税后 |
| unresolved保留、无阶段descriptor、配股coverage | PASS | 缺ex有record保留并登记，正暴露INCOMPLETE；1/2全部阶段缺失仍保留；12行配股无账户操作 |
| 单窗证据与runner owner后续接入 | 部分通过 | 未改runner/bridge；有scope/reset_anchor/来源coverage，但窗口身份及终点不全，P2-01 |

未新增第二套现金、成本或持仓账本；没有把不支持的record→ex变仓算作成功。当前只审模块及合成真实core路径，未宣称运行器已完成接入。
TDD审计保留交付日志证据局限：导入RED不等于行为断言RED；不能从摘录独立恢复历史执行顺序。两个新增独立反例是真实当前契约失败，与owner历史TDD无混用。
