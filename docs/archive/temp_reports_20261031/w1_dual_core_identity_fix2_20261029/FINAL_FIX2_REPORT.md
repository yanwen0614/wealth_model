# W1 双 core 身份与 cutoff 边界修复报告

日期：2026-10-29

## 结果

- Mini gate：**PASS，仅限合成回归与代码门禁**。最终只读 QA 未发现 P1/P2/P3 阻断项。
- 真实 12 路径 proof 与最终绩效：**BLOCKED／未证明**。未运行真实 prefix、真实 6/8 数据、12 路径 proof 或绩效。
- Trusted proof/attestor pins 仍为 `None`；v12 manifest 与 sidecar 未改写。

## 修复

- 默认 prepared 入口先核实际导入 core 路径与固定 SHA，再验证 sidecar、manifest、schema/scope 与 prepared core 身份，最后才访问 manifest 声明的 artifacts。默认生产拒绝隔离 core；prefix 入口使用固定双身份与精确 `PYTHONPATH` allowlist。
- 无 cutoff 的 fractional 绩效仍要求可信 proof。cutoff-only 路径不再先要求未来 proof；实现层继续强制固定 W1 cutoff、信息边界、受限输入与双 core 身份，且完整主区收益标为 `NOT_COMPUTED`。
- Cutoff 同时限制 raw market scanner 的 `execution_end`、`StateLookup` 的读取/迭代/长度视图。cutoff 加载跳过完整窗口 coverage JSON；runner 只用 cutoff market guard 重算 coverage。完整窗口路径保留既有 coverage 校验。
- 生产 prepare/run 集成测试在原 wheel 子进程中执行；原 wheel与隔离 core 的身份及前缀一致性分别核对。

## 验证

- 九个 W1 定向模块：**165 tests，OK**。最终日志：[FULL_REGRESSION_FINAL3.log](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix2_20261029/FULL_REGRESSION_FINAL3.log)
- Ruff、Pyright、diff-check：退出码均为 0；Pyright 无 diagnostics。见 [STATIC_STATUS.log](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix2_20261029/STATIC_STATUS.log)
- 固定源码清单：15/15 SHA 匹配。见 [SOURCE_SHA256_FIX2.txt](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix2_20261029/SOURCE_SHA256_FIX2.txt)
- RED→GREEN cutoff 根因记录： [CUTOFF_BOUNDARY_RED_EVIDENCE.md](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix2_20261029/CUTOFF_BOUNDARY_RED_EVIDENCE.md)
- 原 wheel prepare/run 子进程通过： [PRODUCTION_WHEEL_REPRO.log](C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix2_20261029/PRODUCTION_WHEEL_REPRO.log)
- 独立复核报告由原 Sol 会话完成；最终裁决为 Mini gate 合成范围 PASS，真实 proof/绩效仍 BLOCKED。

## 固定身份

- 生产 wheel `account_runner.py` SHA：`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`
- 隔离 core `account_runner.py` SHA：`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`
- W1 v12 manifest SHA：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`
