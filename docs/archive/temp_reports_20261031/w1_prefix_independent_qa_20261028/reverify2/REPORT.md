# fix3 独立复验报告

日期：2026-10-28。仅只读复验；未改源码、未安装依赖、未运行真实 prefix/12 路径/绩效。fix3 交付目录仅有 HANDOFF.md；未找到 HANDOFF 所称独立 QA fee PASS 报告。

## 分层结果

- **费用安全门：FAIL（PIT 证据不足）**。机械非前视子门 PASS：fee table 仅读取 `date <= information_cutoff`；cutoff 后请求用 cutoff 静态 CostConfig；突变未来表不被访问，缺 cutoff 费项 KeyError，动态 resolver 被 prefix fail-close。2021-06-06/07/08 及 SSE/SZSE 合成反例规则一致。
- 费率 bundle 只有 cutoff、规则函数名、两个 market config 和结果 JSON SHA。SHA 只覆盖结果 payload；不覆盖 `historical_costs.py` 源码/规则文件、预注册输入或已知性证明，也无 `unknown` 字段。当前规则代码生成的历史费率不能仅凭生成日期/值哈希成为 2021 PIT 证书。静态 mini 费用仅属诊断假设。
- **可信 proof 可用性：BLOCKED**。`generate_prefix_proof` 仍无条件抛 BLOCKED；`TRUSTED_PREFIX_PROOF_SHA256=None`；12 路径完整运行、来源身份和原始 baseline 绑定、三方比较均未实现/未执行。
- **实际目标：未达成/未证明**。没有真实 W1 prefix、PIT fee bundle、12 路径或绩效结果。
- 50 项目标定向测试含原 wheel/core 不同进程 staged mini 对照；另有 3 项历史费规则、22 项 proof/scenario、46 项 core orders、2 项信号/CA cutoff 测试通过。Mini 只证明合成输入相等。

## 边界审计

- 行情 guard 对 `get_bar/get_history/get_bars` 截止后日期 fail-fast；排名源记录访问并拒绝 `date > cutoff`；冻结全量 signal 可加载，但策略查询有 max_date。
- 真实 baseline CLI 仍在 `run_staged_window` 的 PIT fail-close 前载入 CA snapshot 和 prepared window；不见 core 执行，但尚非“读取前 fail-close”。fractional 绩效 CLI 在加载前受 pin gate 阻断。
- 原 wheel SHA 与隔离 core SHA 分别为 `aa156ec2…8daa00` / `4d3a28c4…2220a1819`；mini 独立进程对照测试通过。不得外推到真实历史 W1。
- 主区 Python `-B` + 显式隔离 core `PYTHONPATH`；未运行 uv。Core `.venv` 不存在。相关文件审后重算：27 项匹配审前记录；`quantity_rules.py` 清单原值不符，当前实测值已更正，文件仍为未跟踪且无 diff，故不对该项声称审前审后相同。

## 类型检查范围

目标实现及本轮 runner/verifier/probe 测试 Pyright 0 errors/warnings/informations；core 同样为 0。额外把未修改 `test_historical_costs.py` 加入的宽范围 Pyright 报 3 个既有类型问题（行 52、57、151），不归因 fix3，实现范围复跑通过。
