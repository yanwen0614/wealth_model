# 独立质量门裁决

**总体：FAIL（需阻断绩效执行）**

- **Mini / 静态质量门：PASS** — 真实 core 定向 84 tests、Ruff、Pyright 均通过；官方 PDF、core runner 与 5 个关键目标源码哈希匹配。
- **绩效解锁门：FAIL / BLOCKED** — `run_staged_window` 与 CLI `execute()` 可在不校验 proof 时直接运行；CLI `main()` 的 proof pin 不能保护公开调用面。
- **Prefix 证据：未建立** — 没有可逐事件比较的 canonical 完整前缀。不得运行 W1/八分支绩效。
- **实际获配 / 税后结论：未知** — floor/ceil 是两种账户条件情景；不代表全国实际分配、无条件收益界或目标达标。

绩效解锁前需将 proof gate 下沉到运行器与执行器入口，添加未经 proof 的直接调用拒绝测试；独立建立并核验完整 canonical prefix 后再单独复审。
