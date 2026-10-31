# W1 prefix fix4 交付报告

日期：2026-10-28

## 范围

- CNN worktree HEAD：`ce7d1c6e0bd64136f10759412c55f6da410f128f`。
- 隔离 core worktree HEAD：`893fc96925e029098f6c758dba8724d187c6b512`；本轮未修改 core。
- 仅运行 mini/单元测试和静态检查；没有运行真实 12 路径、完整 W1 或绩效。
- 未提交、未推送；没有修改主区、已安装 wheel 或源数据。

## 完成内容

- cutoff fee bundle v2 绑定 resolver 源码 SHA、preregistration SHA、scope/calendar/universe SHA、截止日及生成时间；PIT 证据、费用来源可得性、实际券商费用显式保持 UNKNOWN。
- 未来执行费用仅使用 cutoff 冻结 bundle；缺少显式 information cutoff 时 fail closed。
- run identity 绑定信号文件及内容、配置、checkpoint、准备清单、预注册、core 源码、交易日历和 universe。
- machine proof 从固定 4 份 baseline 与 8 份 scenario 输出重算文件来源、账本 SHA、截止日前原始行和行序；验证器重建并验签 proof，不接受自报 PASS、复制/同目录输入、缺项、换序或篡改。
- Gate 校验 proof schema、内容 SHA、12 路径清单、账本比较及费用 UNKNOWN 状态。`TRUSTED_PREFIX_PROOF_SHA256` 仍为 `None`，未 pin 前无法解锁绩效。

## 验证结果

- 定向单测覆盖 proof 生成成功、缺失拒绝、复制目录拒绝、自报 proof 篡改拒绝、账本换序/缺行失败；最终 74 项通过，详见 `RUN_LOG.txt`。
- Ruff：涉及的 8 个文件全部通过。
- Pyright：涉及的 8 个文件 0 errors、0 warnings、0 informations。
- `git diff --check`：通过。
- Python 使用现有 `D:/code/cnn_full_20260905/cnn/.venv`；`PYTHONPATH` 指向隔离 core 源码。没有安装依赖。

## 裁决边界

- 本报告只证明合成 mini 上的生成/验签逻辑、篡改检测和 fail closed 行为。
- 4 份旧 baseline 都是 `INCOMPLETE` CA 中断产物；只能作受控 cutoff 前缀比较来源，不构成完整 W1 或绩效证据。
- 8 份新 core floor/ceil 输出没有运行，真实 12 路径 proof 未生成、未证明。不能据此宣称 canonical W1 等价或绩效达标。
- PIT 费用来源及真实券商费仍 UNKNOWN；机器 proof 获得 reviewer pin 之前保持不可用于绩效放行。
- 独立 QA 尚未执行；代码 SHA 清单见 `HASHES.sha256`，命令和结果见 `RUN_LOG.txt`。
