# 公司行动纯权益投影进度

status: synthetic_projection_complete_pending_independent_review
candidate_status: NO-GO

- 唯一代码所有权：新建 `backtest/cnn_adapter/corporate_actions.py` 和 `tests/unit/backtest/test_corporate_actions.py`。
- 未改core、runner、费用/终端/身份文件、已冻结日期标签测试、真实DB或registry。
- provider只接规范化事件映射；没有假设SQLite原始列语义或公告盘前可知。
- ledger在record close冻结股数；只产出应收、日终现金转账指令、未上市/已上市权益和raw盯市投影，不更改现金或核心持仓。
- cash pay-date EOD转账，开盘不可用；20%现金红利税只作为压力估算，FIFO/红股税拒绝声称。
- listing-date采用保守EOD后解锁；权益比例保留精确数量，rights固定不认购并将权利价值标unknown。
- 缺reference仅标记该证券ex-date `corporate_action_unknown`；原股仍按raw价计值，不回溯剔除信号。
- known_at verified timestamp须为带时区时间；date-only仅从次日信号时点起保守可用，同日不授权盘前决策。
- 主会话按独立审查修复：date-only可用日期固定转为Asia/Shanghai；上市后权益只由core持仓计值，调用者须在下个交易日前把已上市权益转入core。
- 转账投影是可重放快照，event_id为稳定幂等键；真实core消费端去重尚未实现/验证。
- RED：测试模块先因 `corporate_actions` 缺失导入失败。
- GREEN：`rtk uv run --offline --no-sync python -m unittest tests.unit.backtest.test_corporate_actions`：6项通过。
- 二审定向回归：同命令6项通过；定向 Ruff：通过。
- Ruff：`rtk uv run --offline --no-sync ruff check backtest/cnn_adapter/corporate_actions.py tests/unit/backtest/test_corporate_actions.py`：通过。
- 锚点：000001.SZ 100/1000股应收18/180；300896.SZ 100/1000股应收350/3500、待上市80/800股，EOD保守估值。
- 独立质量门待主会话安排；本实现不含SQLite读取器、不含core hook，不构成真实市场/税后/NAV执行验收。
