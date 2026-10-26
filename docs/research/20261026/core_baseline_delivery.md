# core 联合执行基线交付

日期：2026-10-26。该交付仅证明软件与合成账户契约通过，不代表最终收益目标达成。

## 提交与隔离合入

- core提交：`40f9612`，从独立分支`openchamber/core-baseline-20261026`快进合入core main。
- 初始18个已跟踪修改与2个新文件完整保留；合入前使用独立临时索引保存原WIP树。
- 审定增量仅为`account_runner.py`及新增`test_account_runner_qa.py`。
- 应用增量后核验主区完整索引树与已审分支树一致，再快进；未使用stash/reset/批量恢复。
- core主区合入后干净；后续observer开发仍由唯一owner在隔离工作树进行。

## 已闭合的QA问题

- 策略读取的NAV纳入净现金应收及未上市权益，与权威估值组成一致。
- 明确锚点、主评估截止日、缓冲执行及trade_end行为；空信号锚点报ValueError。
- 未知市场/ST/限价/参考价拒单具有专门reason，买卖两侧均有行为用例。
- 原独立QA：`ses_e88ee9cf5ffeLe3Tw2WHq5is0d`，复审PASS。

## 主会话复验与包身份

- 隔离树与合入后的core主区均实跑697项测试、Ruff、Pyright通过。
- 重建并安装本地core wheel后，CNN backtest全目录263项通过；legacy测试显式开启，不改生产默认。
- wheel：`wheels/backtest_core-0.1.0-py3-none-any.whl`。
- SHA256：`667b25fea821d1f5f6cb79df9701a058d2c59b62f01d9b3a32a449d6165f168f`。
- core源码、wheel及CNN实际安装包38个Python模块逐字节一致；uv.lock固定上述hash。
- 同名本地wheel更新时，uv缓存曾保留旧hash；记录实际新hash后离线locked安装成功，未更新其他依赖。

## 后续

真实成交observer、稳定订单/fill身份及逐笔权威快照另起批次；纯分批组件尚未接该路径。
现有状态数据继续核对语义与覆盖；没有新增API补采授权，不从缺行推断正常状态。
