# W1 prefix fix5 交付报告

交付版本：fix5；独立复验完成：2026-10-29（reverify4）。原生成时间为 00:30，晚于原截止时间。

## 完成内容

- 新增 proofless `--run-prefixes` 八分支命令路径，命令固定传入 `--prefix-stop-after-close 2021-06-07` 与相同的 information cutoff；完整绩效 `--execute` 和非 cutoff fractional runner 仍要求 trusted proof。
- cutoff runner 要求冻结 prepared manifest、真实 CA snapshot、数量规则、冻结静态费率与预注册；信号行/排名及行情访问限制在 cutoff，CA context 也以 cutoff 结束。费用 PIT/source availability/实际券商费和获配标签仍保持 UNKNOWN/False。
- 新增独立 `prefix_attestor` 子进程：核对代码内固定的 14 项 source SHA、固定 core SHA、prepared manifest 引用的输入库存和八分支完整输出哈希；四类访问记录复制到 runner 输出根以外并设只读。verifier 另核对 attestor 可执行文件 SHA 和外部见证根 SHA，不再将运行目录自签的 audit/artifacts 当独立证据。
- 场景账本中任何 2021-06-08 及之后行均拒绝；QA 攻击测试复制 ceil→floor、伪造 audit/evidence、重签 artifacts manifest 并给五账追加 6/8 行，proof 生成拒绝。

## 验证

- TDD RED：两项 QA 攻击最初复现为 `ValueError not raised`；cutoff 命令用例最初因 `prefix_only` 接口缺失失败。随后相应 GREEN 用例通过。
- 提交者及 reverify4 独立复跑：定向 mini 单测均为 94 项通过；Ruff 通过；相关文件 Pyright 为 0 errors/warnings/informations；隔离 core `test_account_orders` 为 46 项通过。独立命令见 `RUN_LOG.md` 和 reverify4。
- 独立进程 attestor 测试验证了固定 source/input、八分支输出 hash、外置只读访问记录，以及 attestation 后输出被修改时哈希失配。

## BLOCKED 与信任边界

- 三个 pin 均保持 None：`TRUSTED_PREFIX_ATTESTATOR_SHA256=None`、`TRUSTED_PREFIX_ATTESTATION_SHA256=None`、`TRUSTED_PREFIX_PROOF_SHA256=None`。正式 attestor 会标为 UNPINNED，verifier 硬阻断，不会生成可用于放行的真实 proof，完整绩效仍 LOCKED。
- 独立 QA 对初版 fix5 发现 source/input SHA 由计划自述的缺陷；本次改为固定 source 清单、attestor pin 门和 prepared manifest 输入库存校验。reverify4 再次核对 15 项 source/core SHA 与固定清单一致，重跑 94 项 mini、46 项 core 测试与静态检查通过；结论仍为 BLOCKED，因为生产 proof、attestor、attestation root 三个 pin 均未独立锚定。
- 本轮没有真实八分支输出，按要求未运行真实 8 分支、绩效、wheel 或源数据修改。外置见证机制只在合成 mini 中执行；attestor、外部见证根和 proof 尚无独立信任锚。
- 最小缺口：先在授权环境运行 cutoff-only 八分支并由独立 QA 审核外置 attestation root；审核后才可固定 attestation SHA，再独立验真 prefix proof。真实数据可得性、税费 PIT 与实际获配仍未知，不能据此认定绩效。
- core 隔离 worktree、本地安装 wheel、主区和源数据均未修改；未安装依赖、未提交或推送。项目现存其他工作区改动未清理。
- reverify4 独立裁决：mini 质量门 PASS；真实 W1 cutoff 八分支可执行性未证明（未启动真实运行）；12 路径 proof 与绩效目标 BLOCKED/LOCKED。四份原始 baseline 仍为 INCOMPLETE。

源码 SHA-256 清单见 `HASHES.sha256`；带实际命令的日志见 `RUN_LOG.md`。
