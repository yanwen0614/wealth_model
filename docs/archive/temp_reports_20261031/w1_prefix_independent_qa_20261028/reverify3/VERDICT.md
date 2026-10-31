# 独立裁决

| 层级 | 结果 | 依据 |
|---|---|---|
| Mini 质量门 | PASS（只限合成） | 74 CNN tests、46 core tests，Ruff/Pyright 通过；独立进程 old wheel/new core mini 对照相等。 |
| 实际 12 路径 proof | **FAIL / 当前不可执行且候选 PASS 不可信** | 无输出目录；执行命令无 cutoff；生成输出需先有 trusted proof；真实 W1 prefix 自身 fail-close。mutable audit/artifact 被反例重签后仍可 PASS。 |
| 实际目标 | **LOCKED / 未证明** | trusted pin 为 None；未运行真实前缀、12 路径或绩效。 |

## 必须修复的 FAIL

1. 给 8 条命令提供真正的 cutoff runner；消除“生成情景前需已有 proof”的循环。`period_id=W1` 不能被 `test_W1_mini` 专用门拒绝；真实 cutoff-scoped CA/数量/费用/行情输入必须有契约。
2. 证明产物来源：audit 与 artifacts manifest 需由受控 runner 外部绑定/签名，验证器不能接受运行目录自行重写后再哈希的自述。固定 runner/source SHA、精确 artifact 集、真实访问日志及截止时序。
3. prefix proof 应拒绝 cutoff 后输出行或绑定 stop-after-close 的运行证据；当前会截去未来行后继续报候选 PASS。
4. 在真实八目录独立运行成功、验证真实四 baseline 与八输出逐账一致、独立审查并显式设置 pin 前，保持性能 gate 锁定。

费用 UNKNOWN 和 `actual_after_tax_target_eligible=False` 标记恰当；不构成实盘认证。绝不把本次合成候选 `PASS` 当可信 proof。
