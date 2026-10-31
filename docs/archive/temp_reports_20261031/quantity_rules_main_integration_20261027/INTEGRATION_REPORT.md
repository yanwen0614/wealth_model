# 四文件主区移植记录

状态：PASS，已获继续处理换行差异授权；四文件原始字节与冻结源完全一致，指定18项测试通过。
目标：D:/code/cnn_full_20260905/cnn
源：C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/board-quantity-rules-20261027
源基线与目标 HEAD：ce7d1c6e0bd64136f10759412c55f6da410f128f。
已读目标根 AGENTS.md；backtest、tests 下未发现模块 AGENTS.md。
已读指定独立 QA 报告：冻结版 PASS，307 tests，2 skipped，Ruff/Pyright 通过。
移植前四个目标路径无工作树、暂存区或未跟踪既存变更。
源四文件 SHA256 均与用户指定值一致。
所有源码编辑均使用 apply_patch，每次新增行数不超过50。

## 目标当前 SHA256

| 文件 | SHA256 | 匹配冻结值 |
|---|---|---|
| backtest/cnn_adapter/quantity_rules.py | d88ed93ab5e41b698f1765bce37571f60707989d7ea2c4a7377340960f3dba8c | 是 |
| backtest/cnn_adapter/staged_order_strategy.py | 4101d8af474727ebd55ab83ccb38e21dbf8aef1d5401f279336987967f08be42 | 是 |
| tests/unit/backtest/test_quantity_rules.py | 414855dd66312570e368f9eefeffcb22f6f28bcc2dfa4727ee9996ed2dc5da3d | 是 |
| tests/unit/backtest/test_staged_order_strategy.py | d391b88c79ce43a5ae305265b012c72365ac51323dfda1074205f52e51bf727f | 是 |

## 换行根因与修正证据

续办先只读比较：两个文件 CRLF->LF 后字节完全相同，文本 unified diff 均为空，证实仅换行差异。
策略归一化 SHA256：0dbb8f0230e8a5f87aa291ebfc9f9938bc5c1f346f10946ac3fab2e0a9ebf68d。
策略源 CRLF/LF 为449/43，修正前目标452/40；差异行122、404、469、472、473、481、482。
测试归一化 SHA256：4072f0fc21f62032dbe3ad543678365af4161c8db29da0cddc6fc2aac0113b33。
测试源 CRLF/LF 为415/45，修正前目标420/40；差异行20、21、29、30、31。
源文件本身混合换行，apply_patch 精确匹配各行原始换行；中间复核发现测试第28行被连带转LF，随后恢复其CRLF。
最终使用只读 read_bytes 比较四个源/目标文件均完全相等，且目标 SHA256 均匹配冻结值。

## 实际测试结果

主区环境变量 CNN_ALLOW_LEGACY=1。
命令：.venv/Scripts/python.exe -B -m unittest tests.unit.backtest.test_quantity_rules tests.unit.backtest.test_staged_order_strategy
结果：Ran 18 tests in 0.015s，OK，退出码0，无跳过；未调用 uv。

## Git 范围

本次仅新增 quantity_rules.py（80行）、test_quantity_rules.py（72行）；修改 staged_order_strategy.py（+28）、test_staged_order_strategy.py（+38），无删除。
既有 memory、PARALLEL_WORKSPACES、f4_signal_delivery、state_acquisition_request_v2、scripts/audit_walkforward_execution.py、_check_signals.py 未编辑。
未执行 git add/commit/push、stash/reset/switch/restore/clean 或 worktree 清理。
未修改源树或其他活跃树；最终暂存区无差异，HEAD仍为上述基线。
主区其他用户WIP仍列于git状态；本次写入仅限四个指定目标文件及本临时记录。
