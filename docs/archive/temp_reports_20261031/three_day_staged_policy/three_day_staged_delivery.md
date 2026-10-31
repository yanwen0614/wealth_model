# 分步预算组件交付记录

## 当前版本核验

- 核验时间：2026-10-26。
- 当前唯一实现文件：`D:/code/cnn_full_20260905/cnn/backtest/cnn_adapter/staged_allocation.py`。
- 当前唯一测试文件：`D:/code/cnn_full_20260905/cnn/tests/unit/backtest/test_staged_allocation.py`。
- 代码仍是待修复版本：有 `_seen_orders.add` 提前污染、无唯一 fill_id、日期推进清除 exit_pending、可变 episode 状态等已报告问题。
- 已检索 `D:/code/cnn_full_20260905`，未发现第二份 `staged_allocation.py`；当前实现没有另一个工作区版本。

## QA 会话与报告

- 原 QA 完整会话 ID：待唯一监控会话确认。
- 原 QA 报告绝对路径：待唯一监控会话确认；已知 `three_day_staged_state_review.md` 是旧状态审查，不是本轮原 QA 报告。
- 当前实施会话：`ses_e89c0199bffelOolRanu1xfy58`（GPT-6 Luna）。
- 复审状态：待原 QA 报告和会话定位后，复用原会话复审；不会另派 QA。

## 修改边界与执行限制

- 唯一可改代码范围：上述实现文件和对应测试文件。
- 不修改共享 runner/core、其他 owner 文件；不提交、不推送。
- 生产反馈接口仍需单独确认；组件不推算成交现金、费用或持仓数量。

## 待复审验收项

- `fill_id` 唯一去重；同一 `order_id` 可有多个不同 ID 的部分成交。
- 所有金额、费用、现金和数量拒绝 NaN、无穷、负数；拒绝事件不污染幂等状态。
- `episodes` 和 Episode 视图不可经外部引用修改内部台账。
- 日历推进不清退出锁；仅 core 权威快照确认无持仓、权益、活动订单后解锁。
- cash/positions 不从反馈事件自行累加；无 core fill 回调时生产桥接明确 BLOCKED。
