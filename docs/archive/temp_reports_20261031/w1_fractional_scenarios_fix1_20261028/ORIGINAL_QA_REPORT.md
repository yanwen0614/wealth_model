# W1 碎股条件情景独立 QA

## 范围与结论

审查冻结树 `C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`，HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。只读；未安装依赖、未提交/推送、未运行全窗绩效。源码前后 SHA 记录见 `HASHES.json`。

Mini 与静态门 PASS；总体 FAIL，因为 proof gate 只封 CLI main，公开 Python API 可绕过并直接启动绩效路径。Prefix 状态仍未验证，绩效继续禁止。

## 身份与数值

- 官方 PDF SHA-256 实测为 `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`，匹配公告身份。
- 已安装 core `account_runner.py` SHA-256 实测为 `aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`，匹配交付值。
- 情景常量绑定事件、原始行 hash、来源文件 SHA、PDF SHA、300502.SZ、登记日 2021-06-07、除权/上市日 2021-06-08 及 Decimal 比率 0.4002532。注入前记录持仓由 core `RecordPosition` 取得；注入在 core 观察更新后的登记仓位上解析。
- 100 股精确权益为 40.0253200；floor/ceil 分别增 40/41 股。core mini 验证成本 basis 总额守恒（按有效比例同比例分配是假设），登记/上市两阶段、零股完整清仓、锁仓不可卖及限价旧单拒绝。
- CLI 8 分支只生成四策略×两分支命令，没有实际运行。每账户假设影响为 floor/ceil 至多差 1 股（当乘积非整数）；不同后续成交、资金、槽位和持仓路径可放大/改变收益差异，无法用单事件 mini 推导全窗差异或收益界。

## 发现与风险

**阻断项：prefix gate 可绕过。** `fractional_scenario_cli.main()` 执行前验证 proof SHA，但 `run_staged_window(..., fractional_scenario=..., official_pdf_path=...)` 无 proof 参数或检查；`run_single_from_cli()` 也直接调用该入口。另 `fractional_scenario_cli.execute(commands, output_root)` 可被直接调用而不验证 proof。调用者可绕过 pin=None，在没有 canonical prefix 的情况下启动真实 W1 核心运行，产生看似有效的绩效输出。

**需修复后复审：** 将 gate 放在所有能触发情景绩效的公开入口，验证独立固定 SHA、proof 文件字节 hash、PASS 状态、HEAD/截止日和 canonical floor/ceil 匹配；未经 proof 的 `run_staged_window`、单分支运行和 `execute()` 均须在启动任何子进程/core 前拒绝。增加针对真实公开入口的反绕过测试。

**范围限制：** TDD RED 仅因缺模块而 import error，不证明具体需求行为失败；GREEN 与 84 tests 证明有限 mini 行为。现有测试未覆盖 Decimal 整数边界、足够大的登记股数和全事件账户分布。外部探针中 q=1 floor 得 0 股；q=2,500,000 与 5,000,000 在 float 可表示性检查处被 fail-closed；此为拒绝运行而非错误获配。该限制可能令大仓情景不能运行，应在适当精度范围的单测中明确预期。

没有完整事件级 canonical 前缀、core 状态、订单和 registry 对照；无法证明 floor/ceil 注入前与原记录一致。条件情景标签与税务免责声明保留明确：实际分配未知、官方分配规则未穷尽、20% 仅现金税压力假设、税后目标资格 false、生产 BLOCKED。不得宣称真实税后收益、实际获配或目标达标。

## 复现与阶段裁决

命令与退出结果见 `COMMAND_LOG.md`。失败触发：proof bypass 代码路径（`staged_candidate_runner.py` 的公开 `run_staged_window` 及 CLI `execute`）。修复后至少复跑 84 项定向套件、Ruff、Pyright 和反绕过测试，并由独立 QA 重新签署。Prefix proof 未建立前不得运行全窗。
