# fix1 第四轮独立复验发现与处理

审查方 verdict：FAIL。上一轮精确 provider 类型及 94 项验证通过；本轮阻断是私有 mini factory 返回 context 后，context 未绑定之后直接 core 调用的 market/window/signal。

## 已做修复
- 移除 `_from_bounded_mini_runner`，不再有 mini factory 可返回 context。
- 公开 `W1FractionalScenarioContext` 构造器仍拒绝 mini。mini context 仅由已验证的 `run_staged_window` 内部创建；它不作为结果返回，并在同一执行路径将已验证的 window、market、signal 数据交给真实 core。
- 新增 `test_no_publicly_callable_factory_returns_unbound_mini_context`，修复前 RED，修复后 GREEN。
- 最终定向测试 95 项、Ruff、Pyright 均通过；provider 类型伪造用例仍通过拒绝验证。
- Prefix proof 仍未建立，pin 为 None；没有运行 W1 或八分支绩效。

本文件不代表第四轮之后的独立 QA 已通过；需同一审查方重新裁决。
