# W1 双 core 身份实验实施进度

## 范围

- 仅改 CNN W1 研究 worktree；backtest-core worktree、wheel、原 manifest、baseline、共享环境不改。
- 保持 proof、attestor、attestation-root 三个 trusted pin 为 `None`。
- 仅做 v12 小型身份夹具与受控 mini；不跑 4GB 源准备、不重跑八分支或绩效。

## RED/GREEN

- [x] RED：双身份实验上下文尚不存在，隔离 core + 原 prepared core 身份组合无法通过 `_verify_prepared`。
- [x] GREEN：原 wheel default exact pass；default 隔离 core fail closed；固定 prefix 上下文允许原 wheel / 隔离 core 两组真实路径+SHA。
- [x] 篡改 manifest core path/hash、artifact、sidecar、fixed manifest、runtime import 和任意 context 均拒绝。
- [x] 原 manifest bytes 保持不变；导入路径通过独立 Python 子进程实际核验。

## 实施状态

- [x] fixed prefix experiment CLI 开关仅生成固定 cutoff 命令；不接受调用方 core 路径/hash。
- [x] branch identity 保存 prepared/runtime 两套 core 身份、manifest SHA、sys.path、`PYTHONPATH`、实验 ID、UNKNOWN PIT。
- [x] attestor 与 verifier 对双身份、配置 SHA、runtime allowlist 与原 baseline core 身份分别校验。
- [x] cutoff 访问门含市场、排序、quantity rule lookup 与五类账本；T+1 数量规则查询日夹到 information cutoff。
- [x] 106 项定向测试通过；全量 Ruff 通过；目标模块 Pyright 0 errors/warnings/informations；`git diff --check` 通过。
- [x] 固定源码及隔离 core 共 15 项 SHA 全部匹配；v12 manifest 原始 SHA、sidecar、W1/schema/core 身份已核对。
- [ ] 只读独立 QA；QA 后停止写入。

## 约束结论

mini 两 core 等价仅是执行器接口诊断，不证明真实逐事件等价。原 W1 baseline 保持 INCOMPLETE，仅供 cutoff 前缀账本参考。真实逐事件对账仍是未来门。

## 最终复核状态

- 完整定向测试日志：`UNITTEST.log`；自然退出 `pane_dead=1`、`pane_dead_status=0`、脚本 `EXIT_CODE=0`。
- 首次完整运行暴露 2 个测试夹具契约缺失与 2 个身份夹具字段缺失；修正夹具后 105 项全绿。
- 首轮只读 QA 指出 prefix manifest 身份校验晚于 artifacts 遍历；已加顺序回归并把固定身份门前移，RED→GREEN 后 106 项全绿。
- 实际 v12 manifest SHA 为 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`，sidecar 精确字节相符；未遍历重哈希 4812 个实际 artifacts。
- 无真实八分支、真实行情读取或绩效运行；无 wheel、core、共享环境或原输入改动。
- 最终命令、身份/源码 SHA 与限制见 `FINAL_VERIFICATION.md`。
