# 2025 A/B 条件执行桥接：fix1 交付记录

## 版本身份

- 工作树：`C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027`
- 分支 / HEAD：`research/corporate-action-fix-20261027` / `ce7d1c6e0bd64136f10759412c55f6da410f128f`
- 最终交付源码逐文件 SHA-256：见 `SOURCE_HASHES.json`；其中 16 项冻结基线文件均与既有审查哈希一致。
- 最初清单记录的是更早源码字节；独立 QA 实际审查时三份目标文件已更新。`SOURCE_HASHES.json` 并列记录旧清单值、QA 观察到的修复前值及最终 fix1 值，避免版本身份混淆。

## 改动与验证

- 修正 CLI 测试夹具返回类型及 Pyright 报错；新增 `run-prepared` 本地条件执行入口，验证 A/B 桥接、状态资格、本地数据身份，再分别调用真实 `run_staged_window` core。
- 微型夹具覆盖 A/B 独立账户、E 日时序、buffer 清算、仓位限制、NAV 守恒、基准与费用、哈希失败隔离及本地数据范围标注。
- 已完成的定向门：199 项 unittest 通过；`ruff check --no-cache .` 通过；五个目标文件 Pyright 0 errors；CLI `--help` 和 `git diff --check HEAD` 通过。
- 本轮没有重新运行测试；以上结果承接本工作树已完成的定向验证记录。

## 范围与限制

- 全年真实 A/B 未运行；没有完整已验证状态及公司行动来源，不能据此声称 2025 绩效、PIT 完整或生产合格。
- 微型夹具的 HDF 读取使用测试替身；本机解释器缺少 `tables`，真实 PyTables 读取尚未验证。
- 执行输出限定为 `IDENTITY_LOCAL`、`PIT_UNPROVEN`、`NOT_QUALIFIED`；缺项时 fail closed 或标记 `INCOMPLETE`。

## 交付证据

- `complete_diff_fix1.patch`：完整 diff，包含 tracked 修改和所有未跟踪文件。
- `tracked_diff_fix1.patch`：仅 tracked 文件 diff；不会单独呈现新增源码。
- `worktree_files_fix1.zip`：fix1 工作树源码快照；`worktree_status_fix1.txt`：冻结时 git 状态。
- `SOURCE_HASHES.json`：最终源码和证据文件 SHA-256、冻结基线清单及旧清单差异。
- 原独立 QA 报告：`C:/Users/yanwen/AppData/Local/Temp/opencode/validation_2025_bridge_independent_qa_20261029/REPORT.md`。