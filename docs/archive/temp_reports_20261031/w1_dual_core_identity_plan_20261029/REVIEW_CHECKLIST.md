# 独立复核清单

## 范围与基线

- [ ] 复核前后 v12 manifest 原始字节 SHA 均为 `a8ad2b0b…064441`；manifest 内原 core `aa156ec2…8daa00` 未变。
- [ ] 原 baseline 四策略目录、audit、sources manifest、artifacts 与五类账本 SHA 均未改；状态仍明确为 INCOMPLETE。
- [ ] 安装 wheel/core、fix5/reverify4 及其它会话文件只读；实验产物只写独立新目录。
- [ ] `PYTHONPATH`、`sys.path`、`inspect.getfile(run_account_backtest_from_orders)`、runtime SHA 在每个子进程内留证；以运行时观测为准。

## 身份门

- [ ] 普通生产 `_verify_prepared` 无实验参数，保持 manifest core path/hash 精确匹配；隔离 core 在普通模式必拒。
- [ ] prefix 模式先验证 manifest 文件 SHA、所有 artifacts、manifest 原 core identity；不跳过数据血缘校验。
- [ ] prefix runtime allowlist 仅包含经审定的 wheel 与隔离 core 两组 path+SHA；只匹配 SHA 或只匹配路径均拒绝。
- [ ] prefix identity 明确分列 `prepared_core_*` 与 `runtime_core_*`，并纳入实验配置、分支 audit、外部 attestation 的哈希绑定。
- [ ] 新 core identity 不得写入/替代 original baseline 字段；baseline validator 仍要求原始 wheel SHA。

## 信任、输入与 cutoff

- [ ] 三个 trusted pin 不变；None、错误 pin、运行目录自签见证均 fail closed。
- [ ] 独立 attestor source/input/runtime/output/access 哈希覆盖身份拆分；外置见证根不能由 runner 自己信任。
- [ ] source、signal、checkpoint、calendar、universe、CA snapshot、PDF、preregistration 和 manifest SHA 均绑定原冻结字节。
- [ ] 仅 `2021-06-07` close cutoff；读信号、排序、行情、费用、CA、ledger 的访问日全部受门控；cutoff 后行拒绝。
- [ ] 不把静态费用或 stress dividend tax 标注为历史 PIT/实际税务，不把 floor/ceil 当实际获配。

## 测试与运行

- [ ] 增加真实 manifest+mock import 的 `_verify_prepared` 身份测试，不再 mock 被测函数本身。
- [ ] 加入普通模式 exact pass / wrong identity fail、prefix 双白名单 pass、未知/错配 fail、原 manifest byte/hash 恒等测试。
- [ ] verifier 测试涵盖双身份字段篡改、runtime allowlist 外身份、原 baseline 被新 core 冒充、pin 缺失拒绝。
- [ ] 对两个 core 的 cutoff-only输出逐事件原始字节比较五类账本，并报告首个差异；失败时保留全部分支与完整日志。
- [ ] tmux 会话自然退出码、pane 状态、脚本状态文件、八分支状态清单一致；中断也有明确状态，不覆盖旧证据。
- [ ] 不执行 2021-06-08 后事件、全窗回放/绩效、训练、依赖安装或修改原 pin。
