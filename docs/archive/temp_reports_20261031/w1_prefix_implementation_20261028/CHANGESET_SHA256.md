# 两树完整工作区清单与 SHA-256

哈希是 2026-10-28 交付时文件原始字节 SHA-256。CNN 树包含此前已存在的未提交阶段文件；以下 `M`/`??` 是 Git 完整状态，不代表所有文件均由 stop-core 阶段创建。两树 HEAD 见 `HANDOFF.md`。

## CNN worktree (`w1-fractional-scenarios-20261028`)

| 状态 | 路径 | SHA-256 |
|---|---|---|
| M | `.opencode/memory/HISTORY.md` | `0cab59e78364ab2604008bee7337f5a9e385b30c5d40d15a329c69847bb830bf` |
| M | `.opencode/memory/MEMORY.md` | `84b838736b6dd4b0f854c6853d763bc3074b39f9d1642743bc87108889527952` |
| M | `backtest/cnn_adapter/raw_market_inputs.py` | `000c382d56bf6e9737677314d728d7306348d252189815896b9ec5be4f3bb920` |
| M | `backtest/cnn_adapter/raw_market_provider.py` | `53ce8d8e99c1705e54f571846c4a93fc3fb867f18991973854f0f172514d582e` |
| M | `backtest/cnn_adapter/staged_order_strategy.py` | `9c87f2e1de903f18748f98d4d55f368e415f4c797b8f7be9d3733c20e595b015` |
| M | `tests/unit/backtest/test_raw_market_inputs.py` | `aa9d72059026d92f7314c73a0a0f4cb5c4ad597497653b6025ab6d188253d6cf` |
| M | `tests/unit/backtest/test_raw_market_provider.py` | `a736ab4e750182fafa0ed4b80271476b498858211672010c741fb226cd8dd986` |
| M | `tests/unit/backtest/test_staged_order_strategy.py` | `d3ed3b034d189b6c563054222304437a7587af97dac267965b75992a985cfb3f` |
| ?? | `backtest/cnn_adapter/corporate_action_context.py` | `8c88683136972e032dc37c11d96c3eff4d04c34c508fe9a2545c823a1aa22510` |
| ?? | `backtest/cnn_adapter/corporate_action_snapshot_loader.py` | `31f72bec1f2adecd7e7914c191e2f442515544dd9eda802df928fb77c405dd49` |
| ?? | `backtest/cnn_adapter/fractional_prefix_gate.py` | `5f089dc31befeeb448a73624e9231305c0550449fc25b5582a8c8e71df1c187b` |
| ?? | `backtest/cnn_adapter/fractional_scenario_cli.py` | `5afd118728658bb1c0897c8fb7c580a74a3f2590e813345713707e3d21e78eae` |
| ?? | `backtest/cnn_adapter/fractional_scenarios.py` | `8af304dd90deac09dab8fcc870ad298b11bbfc2c28f74b59fc953cdcf5693bda` |
| ?? | `backtest/cnn_adapter/prefix_ledger_verifier.py` | `eb950cfa52d88148d7c0988de8f301c72a6bea8a6f37629d80ee02a526d548b0` |
| ?? | `backtest/cnn_adapter/quantity_rules.py` | `d88ed93ab5e41b698f1765bce37571f60707989d7ea2c4a7377340960f3dba8c` |
| ?? | `backtest/cnn_adapter/staged_candidate_runner.py` | `935469ba74612a08c5cc9c83909eb0a95df9aa24c1ff13e468dc9aadbfd135d8` |
| ?? | `backtest/cnn_adapter/staged_production_inputs.py` | `82499d7982acb396bfdf8ed80b1fc3a68520e22d22e71cf46904a22f88b10570` |
| ?? | `tests/unit/backtest/test_corporate_action_context.py` | `5cc9beb093f471f7a9ef9c5dcaadbd5fb6b7a7184e15b7a1ac3d10b6b3bac774` |
| ?? | `tests/unit/backtest/test_corporate_action_snapshot_loader.py` | `55d6e1ee8110a4baa46a03d39b806158e1ebdc7eaa23515a6925abdc01d4dbd2` |
| ?? | `tests/unit/backtest/test_fractional_scenarios.py` | `198920ce68e67e0bfe47cb67f1fdf6073223b5fb03f2bd8e629f34972ddb4f07` |
| ?? | `tests/unit/backtest/test_prefix_ledger_verifier.py` | `1bac7682700104920b91c4174fab750794fae845306e793e82e8b8a0a4c169fd` |
| ?? | `tests/unit/backtest/test_quantity_rules.py` | `414855dd66312570e368f9eefeffcb22f6f28bcc2dfa4727ee9996ed2dc5da3d` |
| ?? | `tests/unit/backtest/test_staged_candidate_runner.py` | `634dce1f105e718413e18d5c35b31c08eadf271df014c0dadb9fee5e2521a75f` |
| ?? | `tests/unit/backtest/test_staged_production_inputs.py` | `1e43d01e0a3d22d114be1b8bfac98fdc4b4612c0795468f8000ffae1cf9adfdf` |

## 隔离 backtest-core worktree (`research/w1-prefix-stop-core-20261028`)

| 状态 | 路径 | SHA-256 |
|---|---|---|
| M | `src/backtest_core/engine/account_runner.py` | `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819` |
| M | `tests/test_account_orders.py` | `cb6b4793fb10abb649f0760c5f710638edb6e65814e985c16d57b615168ffba8` |
