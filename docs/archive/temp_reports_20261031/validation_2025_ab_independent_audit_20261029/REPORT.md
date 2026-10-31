# 2025 A/B 执行前缀独立审计

审计范围：只读复核 `validation_2025_ab_real_20261029_v1` 的 prepared 输入、外层日志、A/B 年度产物及 core 账本；未安装、训练、重跑或修改源数据/其他工作区。逐行扫描了两份 1.28 GB opportunities JSONL，并重算关键 SHA-256。

## 结论

- A、B 均只形成一个实际买入前缀；core 于 2025-01-06 首次持有正仓时，遇到登记日缺失的股息事件并 fail-closed。完整年度执行未发生。
- 实际事件持仓峰值 A=1、B=1，前缀范围内符合 ≤10；这不能证明全年持仓约束。
- 两账户 `main_end_nav=null`、`buffer_end_nav=null`、`main_return_usable=false`、`target_verdict=NOT_EVALUABLE`。wrapper 记录 exit 0 与各有一笔成交均不构成策略达标或收益证明。
- 年度 JSONL 机会榜包含中断日之后的未来日期；A17/B10 是全期榜中 eligible top5 计数，不能当作中断前成交机会数。

## 执行前缀对账
| 账户 | 实际成交 | 成交价/基准价 | 成交金额 | 费用合计 | 成交后现金 | 成交后持仓/locked | 峰值 |
|---|---|---:|---:|---:|---:|---|---:|
| A | 2025-01-06 09:30，买 000159.SZ 34,700 股 | 5.52 / 5.50 | 191,544.00 | 734.22424 | 808,415.77576 | 34,700 / 34,700 | 1 |
| B | 2025-01-06 09:30，买 000595.SZ 31,800 股 | 5.92 / 5.90 | 188,256.00 | 675.53376 | 811,704.46624 | 31,800 / 31,800 | 1 |

费用由 commission、slippage、transfer fee 组成：A=38.30880+694.00000+1.91544；B=37.65120+636.00000+1.88256。无卖出；成本账面分别为 5.52、5.92；现金、available_cash 相同。没有后续 mark 或清算状态。逐事件持仓峰值按 execution_updates 的每个 post_state 持仓代码数计算，包含唯一 fill 事件。

## 中断时序与外层状态
- 两账户均在 2025-01-03 信号日提交买单，执行日 2025-01-06；此前 2024-12-31、01-02、01-03 core snapshots 均无持仓。
- 01-06 09:30 core `execution:9` 先记录上述买入成交，随后公司行动 observer 在该事件状态看到正持仓，因缺失 record_date 中断；中断边界为 `missing_record_first_positive_holding`。core 后续日期/年度事件未执行。
- A 触发 `dividend:103185:0ae6df2addb8583a16863a0c49c73091648ed7008177a6253a7ef6d109c637d5`，涉及 000159.SZ 34,700 股，record_date=null，announcement_field=20250725。B 触发 `dividend:55290:25bfb2b5d9e7a88766cb9952630f6c03c17e14f1912f45eeaa7cd8e2dea890dd`，涉及 000595.SZ 31,800 股，record_date=null，announcement_field=20250829。两项 PIT 均 false。
- 外层 `preflight_exitcode.txt=0`、`runner_exitcode.txt=0`、`runner_status=EXITED_0`，run_status 同记 runner_exit_code=0；annual stdout/stderr 为空。tmux session 仍在 PowerShell 提示符，`remain-on-exit=off`、pane 未 dead，因此没有可独立读取的 tmux pane 退出状态；exit 0 仅由 wrapper 文件/状态记录支持。

## 完整榜、unknown 与覆盖
- 两份 `full_opportunities.jsonl` 各 1,180,872 行，和 prepared NPZ rows 一致；signal_date 从 2025-01-02 到 2025-12-16，execution_date 最晚 2025-12-17。每份 1,170,788 行 signal_date 晚于最后 core 成交信号日 2025-01-03，明确属于未来预计算榜，不能并入执行前缀。
- A/B summary 都称 1,160 个 top5 机会；eligible_top5 分别 17、10。完整排名表保留各代码原始 rank，输入 QA 的预注册规则为 unknown 拒绝、排名不删减且不补位；现有摘要/榜支持“全榜保留”，但未提供独立逐日 tie-break 证明。前缀 core 实际只观察到两天决策：01-02 空单，01-03 各提交一单；其余年度榜不能证明当时机会。
- 状态 coverage 不能解释成全市场覆盖：本批 prepared manifest 为 state_rows=40,796、state_codes=174、raw_codes=172，缺 raw 000040.SZ、000584.SZ；上游独立 QA 另核对 190 个 HDF 状态文件哈希，但只是候选文件完整性，不是 5,135 证券全覆盖。未认证来源时点或缺失原因；unknown 保留为 unknown。
- `opportunity_coverage.jsonl` 为 0 字节。summary 的 missing-state/raw 与 quantity rejection 计数是整段候选扫描统计，不能推导 core 前缀当日的成交机会或全年拒单行为。

## 基准、估值及限制分层

- manifest 给定沪深300 close：2024-12-31=3934.9109，2025-12-16=4497.5545；端点算术收益=(4497.5545/3934.9109)-1=14.2987634%，即 14.2988%，类型为价格指数、不含分红再投资。
- 提供的 prepared manifest 只有端点值与交易日历，没有逐日沪深300收盘原始序列/源文件哈希；因此本审计能复算端点收益，不能验证端点来源、期间缺日或中间连续性。benchmark 指标不是策略可比收益。
- **执行事件层：** 未知登记日正持仓即中断，故全年路径不存在；修复前缀截断不能补成全年账本。
- **source/PIT 层：** HDF 本地字段 `history_known_at=UNKNOWN`、signal_original_produced_at=null、pit_verified=false；模型信号为事后生成/封存声明，非当时可得性证据。状态原始文件哈希与字段抽样通过不等于 PIT 认证。
- **公司行动/税层：** CA 导出内容 hash 不证明公告可得时点、实施、整股权益分配或实际个人税。20% 现金股息扣税是压力假设；公司行动首次正持仓 guard 正确阻断未知登记日，但当前无法计算实际税后全年回报。
- **验证期/决策时点层：** 模型配置将 2025 设为 VAL_START/VAL_END；当前比较属于事后使用已见验证期的探索，不是独立样本验收。信号/预测产出时间未认证。

## SHA 与后续对照可用性

- 关键输入、A/B signals、榜单、summary、core execution_updates 的 SHA-256 见 `SHA256SUMS.txt`；核心代码/模型/checkpoint 哈希另见每账户 core manifest 与 sources。
- 这些封存文件足以锁定本次输入、模型身份声明、执行前缀和中断事实，支持后续修复对照的身份基线；不足以证明外部源/PIT、benchmark日线、真实公司行动税务或全年可执行结果。
- 后续有效对照须保留相同原始信号、prepared 数据、策略冻结与 core 身份，只变更明确修复项，并逐事件对账；即使绕过中断，也必须补齐登记日/实施/税和期间数据证据后才可评估全年主期及缓冲期 NAV。

## 证据边界

`annual_end_utc`、runner 状态、账本及完整榜来自此次运行的本地封存产物；本审计未重新执行策略。对 2025 年度结果的唯一结论为 `NOT_EVALUABLE`，不得引用 wrapper exit 0、单笔成交、前缀持仓峰值或机会榜推断跑赢/非负收益/全年持仓合规。
