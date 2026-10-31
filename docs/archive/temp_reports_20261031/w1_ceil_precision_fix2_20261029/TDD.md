# TDD 证据

## RED 阶段

更新审查源码清单和新增身份校验器之前，这两项新增测试按预期失败：

- `test_fixed_source_inventory_accepts_exact_files_and_rejects_tampering` 对 `fractional_scenarios.py` 报 `source fixed SHA mismatch`（清单仍是旧 pin）。
- `test_attestor_requires_complete_dual_core_experiment_identity` 报 `ImportError`，因为 attestor 尚无可独立测试的身份校验器。

## GREEN 阶段

- `test_prefix_attestor`：4 项通过，逐项核对 15 个固定文件；拒绝篡改副本；逐一拒绝缺少任一必需字段的身份对象。
- 主区交叉回归：生产默认严格拒绝、完整上下文 pin 门通过；双 core 测试分别验证原始 wheel 和隔离 core 身份，外部信任 pins 均保持 `None`。
- 各模块结果和进程/资源证据见 `logs/`；逐项 SHA 见 `SOURCE_INVENTORY.json`。
