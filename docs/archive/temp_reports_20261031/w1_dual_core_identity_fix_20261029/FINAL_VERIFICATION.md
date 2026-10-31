# W1 双 core 身份实验：最终验证记录

## 结果

- 定向单测：106 项通过，0 失败；命令由 `run_tests.ps1` 执行，tmux 自然退出码与脚本 `EXIT_CODE=0` 一致。完整日志见 `UNITTEST.log`。
- Ruff：`uv run --offline --no-sync ruff check .` 通过。
- Pyright：使用 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe` 为 `--pythonpath`，目标四模块为 0 errors、0 warnings、0 informations。
- 差异空白检查：`git diff --check` 通过。
- 第一次全量测试出现 2 个 fixture errors、2 个 fixture failures：旧 fixture 缺 sidecar、完整 access 文件或 W1 标识。补齐 fixture 后完整重跑通过。
- 首轮只读 QA 发现 prefix `_verify_prepared` 在固定身份检查前遍历 manifest artifacts。新增 RED→GREEN 回归覆盖 manifest SHA、schema、W1 与 prepared core 身份不符时不会触碰声明 artifact；现已将固定 v12 身份验证移到 artifacts 哈希循环之前。

## 固定输入与执行身份

- 实际 v12 manifest：`C:/Users/yanwen/AppData/Local/Temp/opencode/staged_prepared_inputs_20261027_v12/manifest.json`。
- 原始 SHA-256：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；`.sha256` sidecar 字节精确等于该摘要。
- Schema 为 `staged_prepared_v1`，包含 W1；原 core 字段仍指向安装 wheel，SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`。
- 固定隔离 core 文件 SHA 为 `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`；core 文件未由本任务修改。
- 单测验证默认模式拒绝隔离 core，prefix 固定上下文只接受两组完整路径+SHA，manifest/artifact/sidecar/runtime/import/context 篡改被拒；三个 production trusted pin 均为 `None`。

## 固定源码 SHA 清单

下列 15 项在复核时全部与 attestor 固定清单一致（0 mismatch）：

| 文件 | SHA-256 |
|---|---|
| staged_candidate_runner.py | `834c4adaeb3d1f36d99fe53e898323a47c9aa531d7a6da8739312dd7200903a7` |
| staged_production_inputs.py | `621614715bee614c6ba3f5a662a0fac1653f62ffc5be8eaab6035105f23a03c3` |
| fractional_scenarios.py | `9e78eae5ddfa9776e1b248e4bd3b389d06da5c254c8d01bacba54f369eb6f2f2` |
| fractional_scenario_cli.py | `4e6246dbdd56bf5da6edebb88ac87c45dfa692de45b04e6a1c177e63e709a46f` |
| prefix_ledger_verifier.py | `92c842a375b5e719761df8144dc686b27455c491aeed2a1f3811c3fb6c32145a` |
| historical_costs.py | `aca04da66bebfe34765bb166639a5f88bfed215d7343e142fe306ed0567af329` |
| corporate_action_context.py | `8c88683136972e032dc37c11d96c3eff4d04c34c508fe9a2545c823a1aa22510` |
| corporate_action_snapshot_loader.py | `31f72bec1f2adecd7e7914c191e2f442515544dd9eda802df928fb77c405dd49` |
| quantity_rules.py | `d88ed93ab5e41b698f1765bce37571f60707989d7ea2c4a7377340960f3dba8c` |
| staged_allocation.py | `c4bd8a85f6ab3564efd8f8b5c4d6daeaccb7277e1ee81deec8eef6d69d22a314` |
| staged_order_strategy.py | `9c87f2e1de903f18748f98d4d55f368e415f4c797b8f7be9d3733c20e595b015` |
| staged_execution_bridge.py | `37d65236b2d2ee55884f2126826ab77eff13009021fc1c8985498ca44d611e63` |
| raw_market_provider.py | `53ce8d8e99c1705e54f571846c4a93fc3fb867f18991973854f0f172514d582e` |
| raw_market_inputs.py | `000c382d56bf6e9737677314d728d7306348d252189815896b9ec5be4f3bb920` |
| isolated account_runner.py | `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819` |

## 边界

- 未重哈希实际 manifest 中的 4812 个 artifacts；单测使用小型合成输入，不读取完整实盘准备数据。
- 未运行真实八分支、cutoff 行情、真实逐事件 core 对账或绩效。原四份 baseline 仍为 `INCOMPLETE`。
- mini 等价不代表真实事件等价；proof/attestor/attestation-root pins 保持 `None`，最终绩效目标仍为 LOCKED、未证明。
