# fix2 独立 re_verify 报告

日期：2026-10-28。范围：fix2 交付、CNN 冻结树、隔离 core 冻结树。只读；未安装依赖、未运行真实 W1、12 路径或绩效。

## 分层结果

- 可安全诊断 mini：PASS。48 项定向测试通过；其中一个测试在独立子进程分别导入原 wheel / 新 core，核实真实路径与 SHA，并逐项比较 cutoff 前 snapshots、trades、五类 observer/registry 账。测试只证明该合成 staged mini 的一致性。
- 真实 W1 12 路径 proof：BLOCKED / 未实现。当前真实 W1 在缺 cutoff scoped PIT 输入时 fail-close；proof generator 无条件抛 BLOCKED。12 次真实运行、基线/策略/分支身份绑定、三方逐账比较均未完成。
- 真实目标 / 绩效：未证明、LOCKED。`TRUSTED_PREFIX_PROOF_SHA256=None`；不能由 mini 或 BLOCKED 记录推成目标通过。

## 上轮问题逐项复核

1. 未来费用：修复为截止日内冻结费率；截止日后执行订单仅用 cutoff 时静态 `CostConfig`，不调用未来费率 resolver。测试覆盖 fee lookup 越界和动态 fee resolver fail-close。mini 的静态费用明确限制于 `test_W1_mini`/合成市场，不能代表真实 PIT 费用。真实 W1 无 PIT 包会在 core 执行前 fail-close。
2. 任意账本可信 PASS：修复为诊断字段 `rows_identical`；空账失败、同目录拒绝。两个不同但复制相同内容的目录仍可得到诊断性相同结果，但无 PASS/status。生产 proof 函数硬抛 BLOCKED，复制/伪造输入无法写出 proof。
3. 12 路径与 production proof：未完成，原 P1 **不得标 fully fixed**。BLOCKED 记录列出 B1/S1/S2/C70 × default/floor/ceil 共 12 项；它们是要求清单，不是运行证据。可信 proof schema/pin 尚无可放行实例。

## 剩余边界

- CLI 的真实 W1 baseline prefix 路径会在 `run_single_from_cli` 先载入完整 CA snapshot 和 prepared window，再进入 runner 的 PIT fail-close；尚未做到在所有源文件读取前拒绝。scenario 绩效 CLI 因 pin=None 会更早拒绝。未观察到 core 执行或前缀决策发生。
- mini probe 比较 observer prefix、决策订单、交易和快照；不等于真实历史行情/状态/费用/CA 的 W1 等价证明。
- P1 安全阻断项：12 路径完整可信 proof 缺失；CLI fail-close 前的数据预载需纳入 PIT 边界设计。未来费用污染订单的原 P1 已由 cutoff 静态值隔离，但真实 fee bundle 流程仍 BLOCKED。

## 检查

CNN 48 tests、core 46 tests 通过；Ruff `--no-cache` 两边通过；Pyright 两边均 0 errors/warnings/informations。fix2 哈希 8 项审前/审后均匹配。精确命令与摘要见 `logs/reverify.log`；哈希见 `HASHES.sha256`。
