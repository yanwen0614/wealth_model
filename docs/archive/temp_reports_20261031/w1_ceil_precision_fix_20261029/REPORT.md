# W1 ceil 精度修复交付

## 修复

针对唯一已验证的 W1 事件，以 floor/ceil 计算得到的权威整数 entitlement `n` 与登记股数 `q`，将 `n/q` 作为精确分数字符串供 observer 的 `Fraction` 校验。交给隔离 core 的仍是 `float(n/q)`，且先验证 `q * float(n/q) == float(n)`。未改 core 默认规则、官方原比例或源行；未增加 epsilon 或通用取整。

## 冻结源码

| 文件 | SHA-256 |
|---|---|
| `backtest/cnn_adapter/fractional_scenarios.py` | `7112BEDEF9A10D802E58F18580E391E25355803C838B401C215941CB9CE37180` |
| `tests/unit/backtest/test_fractional_scenarios.py` | `D8105496C0F0A19017EF2E18BE47C8EF03190B5EFD4D01C2E37D4548C67831A5` |

变更位于：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028/`。隔离 core 未修改。

## 验证

- RED：新增 q=1300、2800、4000 ceil observer 测试在修复前因 `noninteger_or_unrepresentable_share_quantity` 失败。
- GREEN：fractional scenario unittest 28 项通过；包含 q=1300/2800/4000 的 floor/ceil `CreateShareEntitlement` 与 `ListShareEntitlement`、basis 守恒、生产默认严格拒绝、非白名单 fail closed。
- Ruff：通过。Pyright：0 errors / 0 warnings / 0 informations。`git diff --check`：通过。
- 独立只读 QA：PASS；SHA 匹配，独立运行 unittest、ruff、pyright 均通过；未发现通用 rounding、epsilon 或 core 变更。

## 结论边界

本交付只证明隔离 mini 的机械整数路径。没有运行真实 W1 cutoff 或绩效 runner。trusted proof/attestor pins 仍为 `None`；实际获配、税务/PIT、绩效资格仍未知或未证明。
