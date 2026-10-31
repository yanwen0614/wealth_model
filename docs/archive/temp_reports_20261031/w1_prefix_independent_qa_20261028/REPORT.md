# W1 prefix 独立质量门报告

审查日期：2026-10-28。范围：CNN 冻结树、隔离 backtest-core 冻结树及交付证据。
边界：只读；未运行真实 W1 12 路径、完整 W1 prefix 或任何绩效；未安装依赖。

## 结果摘要

- CNN 定向 unittest：78 项通过。Core `test_account_orders`：46 项通过。
- 两树定向 Ruff `--no-cache` 通过；定向 Pyright 均为 0 errors / 0 warnings / 0 informations。
- 交付清单 26/26 文件 SHA-256 匹配。core 实际导入路径和哈希与交付一致；原 wheel 哈希仍为用户给定值。
- 结构审查未发现默认完整运行新增 stop 行为：`stop_after_close=None` 时原循环继续至完整日历末；prefix 在截止日订单排程、CA 当日处理、收盘 mark/snapshot 和 observer snapshot 后 break。
- 截止日收盘信号会排程 T+1 订单；测试保留 pending 元数据，未误执行。W1 full evaluation_end、完整日历、信号和 buffer 仍由窗口定义保留。

## P0 / P1

- P0：未发现可绕过真实绩效门的路径。所有情景入口经共享 gate；`TRUSTED_PREFIX_PROOF_SHA256=None` 时明确拒绝。
- P1 FAIL：Verifier 比较调用者指定的两目录五种 JSONL，未验证真实运行、四策略×三路径的 12 份绑定、基线来源真实性、稳定业务 ID 完整性或跨策略/重复事件。普通合成五账本即可产 `ledger_comparison=PASS`。
- P1 FAIL：`generate_prefix_proof` 输出不含 gate 要求的 `status/base_head/through_date/canonical_prefix_match/floor_ceil_prefix_match`；没有从完整 12 路径生成生产 proof 的执行路径或可信 pin 流程。
- P1 FAIL：prefix `_freeze_fees` 预读截止日后第一个执行日的费用；结果用于截止日策略预算/订单计算（runner 884–892 行）。这属于 6/8+ fee access，违反本次明确边界，需评估是否改变订单决策。
- TDD：Core RED/GREEN 有证据；CNN runner/verifier 无 RED 证据，按要求不宣称 TDD 通过。
- 观察序列：core mini 只比较 snapshots 与完整运行共同日；未证明旧 wheel 与新 core 的逐 observer/registry/order-request 序列一致。

## 时间边界 / 公司行动

- 市场 guard 对请求日期超过 cutoff fail-fast；排名 wrapper 限制 cutoff，并记录已访问信号日。完整冻结信号文件加载本身被设计允许，但只应允许 cutoff 日期进入决策。
- prepared 输入路径复用完整信号/排名及完整市场覆盖缓存；虽然覆盖摘要在 prefix path 不触发逐日重新扫描，尚无按物理读取/逻辑查询日期的独立审计证据。
- prefix 会初始化目标情景上下文；它在 6/8 ex-date 才构造目标权益操作，6/7 record position 仍由 core 原序处理。未运行真实数据，无法证明 CA snapshot 与公告材料按当时可得性过滤。
- 税务保持未知、税后资格 false、情景生产接受 BLOCKED；mini PASS 不代表真实获配、官方取整规则穷尽或目标达成。

## 三层裁决

- Mini gate：FAIL（有限机制测试通过；要求的旧 wheel 对新 core 同输入 staged mini 逐事件/观察序列比较未完成）。
- 真实 prefix 一致性：未证明（未运行；不得标 PASS）。
- 最终目标/绩效：未证明且门禁锁定（12 路径与可信 proof 路径缺失）。

## 复现

命令、导入身份和哈希见 `logs/review.log`、`HASH.md`。静态源审查重点：core `account_runner.py` 1649–1652、1728–1819；CNN `staged_candidate_runner.py` 781–807、884–932；`prefix_ledger_verifier.py` 83–175；`fractional_prefix_gate.py` 9–35；`fractional_scenario_cli.py` 20–55。
