# fix1 第五轮独立复验发现与处理

审查方 verdict：FAIL。此前 factory 已删除，但 name-mangled `__initialize_context(..., allow_mini=True)` 仍可通过属性名直调，调用者可绕开 staged runner 构造 mini context。

## 已做修复
- 完全删除 mini initializer；`W1FractionalScenarioContext.__init__` 只接受 `period_id="W1"`，并先验证共享 proof gate。
- staged runner 在已验证 mini 输入、同一 `_run_staged_window_impl` 路径中内联初始化 context，并随后把相同 window/market 和 signal ranking 交给 core；公开 outcome 不返回 context。
- `test_no_publicly_callable_factory_returns_unbound_mini_context` 扩充为同时检查 factory 与 name-mangled initializer 不存在；修复前 RED，修复后 GREEN。
- 定向 95 tests、Ruff、Pyright 通过。Prefix pin 为 None，未运行绩效。

本文件不代表第五轮之后的独立 QA 已通过；需同一审查方重新裁决。
