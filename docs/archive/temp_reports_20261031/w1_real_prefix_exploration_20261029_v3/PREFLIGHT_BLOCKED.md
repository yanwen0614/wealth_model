# W1 v3 prefix 预检结果

状态：BLOCKED；没有启动任何分支；v3 目录仅含本预检报告，分支 `outputs/` 根未创建。

## 只读身份核验

- fix2 独立 QA 为有限范围 PASS：未运行真实 W1 八支；旧 8 项失败缺逐项 traceback，不能声称逐项追溯完成。
- fix2 `HASHES.sha256` 当前 32/32 匹配；`SOURCE_INVENTORY.json` 固定源码 15/15 匹配。
- prepared manifest SHA-256：`a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；sidecar 与此值一致。
- prepared/original core SHA：`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`；隔离 runtime core SHA：`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- proof、attestor、attestation 三个 trusted pins 均为 None。v1/v2 未改；共享源码、wheel、源数据、环境均未修改。

## 阻断原因

- v12 manifest 声明 4,812 个 artifact；按文件元数据合计约 2.069 GiB。包括 4,427 个逐代码 Parquet、W1/W2 市场覆盖与状态映射文件，以及 W1/W2 信号等。
- 固定 runner 的 `_verify_prepared` 会逐项对 manifest 中全部 artifacts 执行整文件 SHA（`staged_production_inputs.py` 中 prefix 分支的 artifact 循环）。八个 runner 子进程都会经过此校验。
- 因此公开 prefix-only runner 会物理读取完整 artifact 集，包含 W2 和 cutoff 后相关输入；该读取面超出本任务明确允许的完整信号文件 SHA 边界。
- 未创建过滤 manifest、未改源码或绕过该完整性门。虽然 CLI 支持独立 `--output-root`，该接口无法收窄上述物理读取范围，故停止。

## 运行状态

- B1/S1/S2/C70 × floor/ceil：均未启动；不存在本次 wrapper 状态、子进程 stdout/stderr 或分支 manifest。
- v3 `outputs/` 根保持不存在；v1/v2 证据保持原样。
- 预检时约 6.8 GiB 可用 RAM、29.7 GiB 可用虚拟内存；页面文件分配 42.79 GiB、当前占用 2.14 GiB。资源不是本次阻断原因。

## 2026-10-29 用户裁定与复核续记

用户明确裁定：v12 manifest 引用文件允许为冻结身份核验作逐块 SHA 全字节读取；这不是 PIT 证据，也不等同策略读取。原始 4GB 训练源严禁重哈希。cutoff 后业务行情、状态、事件、信号行不得交给策略或执行；发现实际未来业务行进入即停止。该裁定取代上文“全文件哈希范围超出许可”的判断。

### v12 物理哈希结果

- 独立 tmux 会话 `w1_v3_v12_hash_preflight`，单进程串行；运行时间 `2026-10-28T23:37:52.691677Z` 至 `2026-10-28T23:39:03.778731Z`。
- v12 manifest SHA 与 sidecar 均为 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；manifest 引用文件 **4,812/4,812 PASS**，SHA 逐块实际读取 `2,221,465,003` 字节（与文件大小总和相同）。
- 全部预期路径、SHA、文件大小：[v12_declared_artifacts.jsonl](v12_declared_artifacts.jsonl)；逐文件实测 SHA 与读取字节：[v12_artifact_hashes.jsonl](v12_artifact_hashes.jsonl)；汇总：[v12_hash_audit.json](v12_hash_audit.json)。原 4GB 训练源未读取、未哈希；无 artifact mismatch。
- 原固定源码 15/15 匹配；prepared/original core 与隔离 runtime core 身份不变；proof、attestor、attestation pins 均保持 None。

### 新的业务读取边界阻断

- 每支 runner 在 `_verify_prepared` 完整哈希后，会调用 `load_corporate_action_snapshot` 载入全量 dividend/right_issue descriptor；当前固定接口没有 cutoff 参数或事件行过滤。
- `W1FractionalScenarioContext` 接收整个 snapshot。目标 descriptor 固定为登记日 `2021-06-07`、除权日及红股上市日 `2021-06-08`；其 6/7 登记持仓回调会据该 descriptor 计算 floor/ceil 条件情景。父 `CorporateActionContext` 还会逐日遍历 snapshot descriptors。此路径没有证明 cutoff 后事件信息未进入策略上下文，故依用户“实际未来业务行进入即阻断”规则，不启动任何 branch。
- 原始市场、信号、状态 API 有截止过滤；core `stop_after_close=2021-06-07` 在 6/7 close 后 break。源码显示这不能收窄上述公司行动 snapshot 输入；且本次没有执行策略或 6/8 交易日 API。
- v3 `outputs/` 未创建，八支均为 **NOT_STARTED**；v1/v2 与固定 attestation 根未改。后续若要运行，需先提供不改变既有 pinned source/manifest 门、且不把 cutoff 后事件行送入策略的 cutoff-safe 事件读取接口；当前固定源码不具备此条件。
