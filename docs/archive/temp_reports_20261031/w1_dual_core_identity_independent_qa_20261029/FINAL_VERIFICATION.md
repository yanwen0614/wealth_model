# W1 双 core 身份修复：独立 re_verify

日期：2026-10-29。复核对象：`w1_dual_core_identity_fix_20261029`；根因证据：`w1_dual_core_identity_plan_20261029/ROOT_CAUSE_EVIDENCE.md`。只读审查，未改源码、wheel、manifest、sidecar、prepared inputs 或 PYTHONPATH；未运行真实 8 支/绩效。

## 四层裁决

1. **Mini gate：PASS（限定合成范围）**。独立运行 106 项定向测试全通过；Ruff 通过；Pyright 0 errors/warnings/informations。
2. **真实 cutoff-only：预期可由固定实验入口尝试，但本次未启动，实际可运行性未证明。**真实 v12 身份构造成功，CLI 固定注入 2021-06-07 cutoff 和 `--prefix-experiment`。因下述 P1 默认入口绕门缺陷及输入未全量重哈希，本次不能给真实运行安全放行。
3. **可信 prefix proof：BLOCKED。**`TRUSTED_PREFIX_PROOF_SHA256`、`TRUSTED_PREFIX_ATTESTATOR_SHA256`、`TRUSTED_PREFIX_ATTESTATION_SHA256` 均为 None；本机可写 attestation 不是独立信任根。
4. **绩效目标：LOCKED / 未证明。**无真实 cutoff 账本、无 12 路径比较；税务与 PIT 仍 UNKNOWN。

## 关键发现与判级

- **P1 / 高：默认生产 `_verify_prepared` 可接受实验 core。**独立临时微型 manifest 以 isolated core 的真实固定 path+SHA、有效 sidecar 和一个有效微型 artifact 调用默认模式，函数返回成功。该 manifest 不是固定 v12。故“默认生产永远不接受实验 core”不成立；一般 prepared-run 入口可接受用 isolated core 准备的 manifest。
- 106 项虽通过，但默认拒绝测试只用“原 wheel manifest + isolated runtime”；没有覆盖“isolated manifest + isolated runtime”，因此未发现上述旁路。
- **P1 / 高：默认模式身份检查晚于 untrusted artifacts。**以真实 v12 manifest 做只读拦截探针，`_verify_prepared` 首先尝试校验声明的 `integration_inputs.json`，尚未核 runtime core path/hash。若 artifact 缺失/恶意，失败发生在身份门之前。
- 实验模式顺序符合要求：真实 v12 下先核 sidecar/manifest、原 wheel path+SHA、runtime import path+SHA，再进入 artifacts 循环。真实 manifest 探针未重哈希 4,812 项 artifacts。
- **P2 / 中：PYTHONPATH 没有固定 allowlist。**附加无效尾部路径后，真实 manifest identity builder 仍接受并记录该环境；当前 import 仍是 approved isolated core。环境值进入 identity digest，但若计划和运行同时使用被改环境，不会因环境本身被拒。
- 固定 attestor 源码清单 **15/15 与当前源码 SHA 匹配**，含 14 个 runner/依赖源码及 isolated core。清单本身未列 `prefix_attestor.py` 或 `fractional_prefix_gate.py`；attestor SHA 仅写入计划，trusted pins None 时没有独立锚定。

## 真实身份与未覆盖项

- v12 manifest 原始 SHA `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`；sidecar 字节精确等于固定 SHA；schema `staged_prepared_v1` 且含 W1。
- manifest 仍绑定原 wheel 路径及 SHA `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`；本次在原路径直接重算 wheel SHA 一致。
- 当前 `inspect.getfile` import 指向隔离 core 路径；直接重算 SHA 为 `4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。实验 identity 独立记录 prepared 与 runtime 两组身份、`PYTHONPATH`/`sys.path`、PIT UNKNOWN 和资格 False。
- 没有重哈希 manifest 中 4,812 项 artifacts（约 2.22GB 历史清单），因此不能声称全部原输入当前未变；只确认 manifest/sidecar/wheel/runtime 身份。
- cutoff 代码将数量规则 lookup 日钳制到 cutoff，行情 guard 和 ranking max-date 限制未来访问，attestor 检查访问记录日期（包括 `rule_lookup_date`）。本次没有真实日志，不能宣称真实运行未访问 6/8。
- Mini 输出中的 COMPLETE/attestation 摘要均为测试夹具，不是 W1 证据。4 份 canonical baseline 仍为 INCOMPLETE。

## 文件完整性

- QA 报告写入前/后固定源码清单均为 15/15 匹配；关键身份常量与实际 wheel/runtime SHA 一致。
- 测试解释器：主区 `.venv/Scripts/python.exe -B`；显式 `PYTHONPATH` 指向隔离 core。未安装依赖、未提交；完整命令和反例见 `UNITTEST.log`。
