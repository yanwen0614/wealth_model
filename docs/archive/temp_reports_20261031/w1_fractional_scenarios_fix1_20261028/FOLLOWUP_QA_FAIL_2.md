# fix1 第三轮独立复验发现与处理

审查方 verdict：FAIL。proof gate、直接构造 mini 防护、其他事件税务 fail-closed、93 项验证和哈希均通过；阻断项为 mini factory 的 provider 身份判断仅比较可伪造的类名和模块字符串。

## 已做修复
- 增加同名并伪造 `__module__` 的 provider RED 测试；修复前 factory 接受该对象。
- staged runner 与 mini factory 改为 `type(market) is SyntheticMarketProvider`，引用 core 包实际类。
- RED 反例修复后通过；最终定向 94 tests、Ruff、Pyright 全通过。
- `TRUSTED_PREFIX_PROOF_SHA256` 仍为 `None`，没有运行 W1 或八分支绩效。

本文件只记录修复事实，不代表第三轮之后的独立 QA 已通过；需同一审查方重新裁决。
