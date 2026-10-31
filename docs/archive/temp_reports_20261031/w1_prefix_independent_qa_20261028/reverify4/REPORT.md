# fix5 独立复验 reverify4

日期：2026-10-29。审查对象：CNN HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`，隔离 core HEAD `893fc96925e029098f6c758dba8724d187c6b512`。

## 裁决

- Mini 质量门：**PASS（仅合成/mini 范围）**。独立运行 94 项 CNN 定向测试、46 项 core 测试；Ruff、Pyright 均通过。
- 真实 W1 cutoff 八分支：**未证明**。静态接线显示 `--run-prefixes` 注入固定 cutoff 且绕过未来 proof；实际真实分支未启动，不能判为可执行或成功。
- 真实 12 路径 proof：**BLOCKED**。原始 B1/S1/S2/C70 baseline 全为 INCOMPLETE；没有真实八分支输出。
- 绩效目标：**LOCKED**。proof、attestor、attestation root 三个生产 pin 均为 None；完整绩效 gate fail-closed。

## 信任与边界

- Attestor 在独立进程中计算 source/input/output/access 记录摘要，但程序、计划和见证根仍位于本机可写文件系统；只读 chmod 不是独立签名或信任锚。见证不能自证可信。
- fee PIT、来源可得性、实际券商费用为 UNKNOWN；获配资格保持 False。不能据此推导历史费率可得或实盘绩效。
- 检查 cutoff 后账本行会拒绝；proof gate 在 pin 缺失时会拒绝。上述结论结合源码检查和合成测试，未用真实 prefix 验证。

## 范围与完整性

- 审前/审后固定源码 SHA 清单一致，15 项 source/core SHA 匹配；23 个重点代码/测试文件审后哈希见 `HASHES.sha256`。
- CNN/core 工作区状态未变化；不清理原有用户修改。未安装依赖、未修改 wheel/源数据/代码，未提交或推送。
- 未运行真实 cutoff 八分支、12 路径 proof 或绩效。不得将 mini PASS 扩大解释为生产 proof PASS。
