# W1 碎股条件情景隔离交付

## 状态
- 目标 worktree：`research/w1-fractional-scenarios-20261028`，HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。
- 未提交、未推送；未安装/同步依赖；未运行全窗 W1 绩效。
- 原样移植清单16/16源哈希均匹配。清单文件来自 `staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`；冻结源树中未发现该清单副本。
- `staged_candidate_runner.py`、`staged_production_inputs.py` 后续增加探索入口；其余14项迁移文件保持原始清单内容。详见 `SOURCE_MIGRATION_VERIFICATION.json`。

## 身份核验
- 解释器：`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`。
- 实际 core `account_runner.py` SHA256：`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`（匹配固定值）。
- 送转源行 SHA256：`5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462`。
- 公司行动源文件 SHA256：`5ad5bfe8259b1a0075ebef0c731019c678a589a8f9d6b013bd46684edbe3168b`。
- 官方 PDF SHA256：`c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`。
- v12 prepared manifest SHA256：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`。

## TDD 与验证
- RED：首次执行 `python -B -m unittest tests.unit.backtest.test_fractional_scenarios` 因缺少 `fractional_scenarios` 模块导入失败。
- GREEN：真实 core floor/ceil、生产默认拒绝、零股规则、成本 basis、公司行动日期和 staged slot bridge 均通过。
- 定向回归：83 tests passed（情景、公司行动 context/runner、staged runner/bridge/strategy、八分支失败汇总）。
- Ruff：定向文件 `ruff check --no-cache` 通过。
- Pyright：定向文件 `0 errors, 0 warnings`。
- CLI plan-only 已生成四策略×floor/ceil共8条独立命令；没有执行这些全窗命令。

## 条件与未验证项
- 情景仅在 W1 白名单身份完整匹配时允许；每股原比例 `0.4002532` 与假设整数股及有效比例均审计留存。
- 成本 basis 按 core 使用有效比例同比分配；此为条件假设，不代表官方或券商实际算法。
- 实际获配未知；税务未知。现金分红20%仅压力口径，`scenario_only=true`、`actual_unknown=true`、`actual_after_tax_target_eligible=false`、生产 `BLOCKED`。
- 无完整冻结 execution_updates/daily_registry canonical 前缀证据；CLI 执行八分支必须先通过独立 prefix proof 校验。绩效阶段未启动。
- 为阻止调用者自造 proof，当前源码的可信 prefix SHA pin 保持 `None`，所以批量执行硬锁关闭；必须由后续主会话在独立核验后显式 pin 对应 SHA。
- 独立 QA 仍需审查来源边界、运行器接线、mini账本和 prefix proof 门禁。
