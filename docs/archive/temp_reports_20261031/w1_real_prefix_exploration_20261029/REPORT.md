# W1 cutoff 前缀真实运行尝试

日期：2026-10-29。状态：**BLOCKED，首分支未越过 prepared-input core SHA 门；按授权停止。**

## 执行范围与结果

- 目标仅为 W1，anchor 2020-12-31，cutoff / information cutoff 均为 2021-06-07。CLI 构造的八个策略×floor/ceil 命令均带这两个固定参数；没有请求修改参数。
- 实际通过 `--run-prefixes` 启动真实 CLI。B1/floor 在读取/验证 prepared manifest 时失败：`_verify_prepared` 要求 manifest 的 core SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`，而按用户指定的隔离 core 实际导入文件 SHA 为 `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`，抛出 `ValueError: 输入 SHA256 不匹配`。
- CLI 自身在分支失败后仍继续队列；检测到 B1/ceil 与 S1/floor 已依次启动且遇到同一错误后，发送 Ctrl-C 停止，不再尝试其余分支。实际尝试：B1/floor、B1/ceil、S1/floor。三者均未生成业务账本；没有一支从 2020-12-31 重跑到 2021-06-07。
- CLI 进程被中断，外层 `process_status.txt` 未能落盘，tmux 会话也未保留可读 pane 退出码。每个已尝试分支的完整捕获 stdout/stderr、异常 traceback 和 `branch_failure.json` 已由 CLI 留存；CLI 顶层 stdout/stderr 为空。未重跑以补状态。
- 因为没有 replay 五类 JSONL，无法逐行比较；原始 baseline 行数仍记录在下表。这不是相等或不等价结论，而是**不可比较/未证明**。没有裁剪或忽略任何字段。

## baseline 与本次输出

| 策略 | 原始五账行数：updates / daily / decisions / transitions / partial states | 尝试分支 | 本次五账 | 首差异 |
|---|---:|---|---|---|
| B1 | 872 / 103 / 102 / 974 / 872 | floor、ceil | 均缺失 | core SHA 门；无账可比 |
| S1 | 857 / 103 / 102 / 959 / 857 | floor | 缺失 | core SHA 门；无账可比 |
| S2 | 850 / 103 / 102 / 952 / 850 | 未运行 | 缺失 | 未运行 |
| C70 | 876 / 103 / 102 / 978 / 876 | 未运行 | 缺失 | 未运行 |

## 身份、固定约束与信任状态

- fix5 冻结清单 22 项实测均匹配；隔离 core import 实际路径为 `C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src\backtest_core\engine\account_runner.py`，SHA 为上列 `4d3a…1819`。这与原 baseline/wheel 身份 `aa156…daa00` 不同；本次遵从要求使用隔离 core。
- v12 prepared manifest SHA `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`，文件时间 `2026-10-27T18:01:54.634406+00:00`。W1 原信号 SHA `99198e069157e570ffc2fa83818d1738a4abe468a5d39c76fca30dfba5d762e9`；checkpoint SHA `a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde`；预注册 SHA `1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae`；官方 PDF SHA `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`。prepared manifest 引用的完整输入 SHA 清单已冻结在 `attestation-plan.json`，计划文件时间 `2026-10-28T16:52:36.4277858Z`；该计划覆盖所有输入 SHA，但不记录每个输入文件各自的原始创建时间。
- 四份原始 baseline 均通过代码内固定 identity/hash 检查，状态均为 INCOMPLETE，原因是 2021-06-08 公司行动数量异常中断。这里不把它们视作完整可锚定 canonical baseline。
- 官方 PDF 身份对应 300502.SZ、2021-06-07 登记日、2021-06-08 除权/上市日、原比例 0.4002532；身份仅核验，未把场景解释为实际获配。
- `TRUSTED_PREFIX_ATTESTATOR_SHA256`、`TRUSTED_PREFIX_ATTESTATION_SHA256`、`TRUSTED_PREFIX_PROOF_SHA256` 均为 `None`。没有生成 attestation；不会把任何 UNPINNED 研究文件改称可信 proof，也未解锁正式绩效。
- 未运行 6/8 或之后的事件/完整绩效、训练、依赖安装/同步；未更改源码、pin、wheel、输入数据、原 baseline；未提交或推送。由于门禁在 runner 读取市场/信号前拒绝，没有读取任何 2021-06-08 及之后行情或账本行。

## 证据索引

- `attestation-plan.json`：CLI 按固定约束生成的源码与输入哈希计划（不含 attestation）。
- `outputs/W1_B1_floor/`、`outputs/W1_B1_ceil/`、`outputs/W1_S1_floor/`：各分支 stdout、stderr、失败记录；另有 `run_prefixes.ps1`、空的 CLI 顶层日志。
- `run_prefixes.ps1` 以 tmux 启动；CLI 因首个固定 core SHA 门拒绝而取消，退出码未捕获。用户要求的输出树内未覆盖既有证据。
