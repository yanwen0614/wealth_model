# W1 双 core 身份与 cutoff 信号修复（fix3）

日期：2026-10-29

## 修复内容

- `prefix_attestor.py` 保留生产 schema 已核实的 experiment 身份，不再在后续逻辑中清空；验证 identity 必填字段，要求 branch identity 与内部身份完全一致，并拒绝缺失或非字典的 audit identity。
- 同步更新 `fixed_source_sha256` 中 `staged_candidate_runner.py` 的固定摘要。当前生产 schema 探针实际验证了全部 15 项固定源码。
- `load_frozen_signal_parquet` 在同一 `pa.OSFile` 句柄上分块计算原始文件 SHA，再由 Arrow 按 cutoff 谓词读取业务表；无 cutoff 的完整读取路径也保持 SHA 校验与原始列映射。
- 截止模式的 SHA 仍覆盖完整物理文件，因此会读取截止日后的物理字节；Arrow 谓词限制返回的业务行，不能据此宣称物理零访问。

## RED → GREEN

- P1 RED：真实 v12、真实隔离 runtime、15 项固定源码下，合法 identity 被拒；清空 identity/audit 的分支却被接受。记录见 `RED_PRODUCTION_SCHEMA_PROBE.log`。
- P1 GREEN：合法 identity 生成 `UNPINNED_ATTESTATOR`；空身份与缺少 `runtime_core_sha256` 均被拒。外部可信 root 未 pin，proof 仍被阻断。见 `GREEN_PRODUCTION_SCHEMA_COMPLETE.log`。
- P2 RED：单测拦截 `Path.read_bytes()`，旧 cutoff 路径因整文件预载失败。见 `RED_CUTOFF_SIGNAL_TEST.log`。
- P2 GREEN：相同单测通过；截止日未来信号行被过滤，返回 SHA 与 Parquet 文件字节 SHA 一致。见 `GREEN_CUTOFF_SIGNAL_FINAL.log`。

## 验证

- 九个定向模块：**166 tests，OK**，耗时 227.353 秒。冻结源码后重跑记录见 `FULL_REGRESSION_FINAL.log`。
- 首次全量运行有 1 个 SHA mismatch：运行期间修改了 runner 文档和固定摘要，测试夹具记录旧摘要后读到新源码。源码冻结后完整重跑通过；首次记录保留在 `FULL_REGRESSION.log`。
- CA 合成回归：**33 tests，OK**；原 wheel 小文件生产集成：**1 test，OK**。
- Ruff：通过；Pyright：0 errors / 0 warnings / 0 informations；`git diff --check`：exit 0（仅有既有 CRLF 转换提示）。
- 可信 prefix proof、attestor、外部 attestation root 的 pins 均为 `None`；proof 与完整绩效路径仍硬阻断，见 `TRUST_PINS.log`。
- 固定源码：**15/15 SHA 匹配**；包括源码与 QA 证据在内的 452 个文件摘要见 `FIX3_SHA256.txt`。

## 边界

- 未运行真实 8 分支、真实 W1 业务回放或绩效；未读取/重哈希完整训练源或 4,812 项 prepared artifacts。
- production schema 探针 mock 的仅是 `_fixed_inputs` 全量 artifact 检查；v12 manifest、官方 PDF、实际双 core 身份构造与 15 项源码核验均真实执行。
- `UNPINNED_ATTESTATOR` 是合成候选见证，不代表可信 proof PASS。mini 门通过不解除 proof 或绩效 LOCKED 状态。
- 未更改 core、wheel、真实 v12 manifest/sidecar或源数据；未安装依赖、提交或推送。
- fix3 交付路径：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1_dual_core_identity_fix3_20261029/`。待 Sol 独立复验。
