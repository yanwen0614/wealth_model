# W1 fix1 独立 re-verify

## 范围与身份

只读复验工作树 `C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`，基线 HEAD 前后均为 `ce7d1c6e0bd64136f10759412c55f6da410f128f`。FIX1_REPORT、FIX1_HASHES、FIX1_COMMAND_LOG、FOLLOWUP_QA_FAIL 及原 QA REPORT/VERDICT 已对照。fix1 六个目标文件哈希前后均与 FIX1_HASHES 一致；core 与官方 PDF 哈希也与固定值一致，见 HASHES.json。QA 未改源码或依赖。

## 复验结论

- **Mini 质量门 PASS：** 95 项定向测试全过（11.506 秒）；Ruff 通过；Pyright 0 errors / 0 warnings / 0 informations。
- **Prefix 绩效门 BLOCKED：** pin 仍为 None。自报字段齐全的 proof 与自报摘要不能通过可信 pin 校验；没有发现能在校验前启动 core/子进程或读取重型输入的路径。
- **本轮不运行全窗或绩效。** Mini PASS 不代表 canonical prefix 存在，不改变 W1 绩效锁定状态。

## 入口逐项核验

| 入口 | 复验结果 |
|---|---|
| `fractional_scenario_cli.main --execute` | 在 build/read manifest、配置、PDF 前验证 proof |
| 直接 `execute()` | 在创建输出目录和 subprocess 前验证 proof |
| runner CLI `main()` | 在读取 signal/calendar 前验证 proof |
| `run_single_from_cli()` | 在读取 config 前验证 proof |
| `run_staged_window()` | 非 mini 在创建输出目录、读 signal、调用 core 前验证 proof |
| `_run_staged_window_impl()` 直接调用 | 重复验证；独立反例在尝试读取大输入前被拒 |
| 直接构造 W1 context | 在读官方 PDF 前验证 proof；mini period 公开构造被拒 |
| batch/runner/context 自报 proof | `TRUSTED_PREFIX_PROOF_SHA256=None` 时 fail-closed |

## mini、fail-closed 与基线

免 proof mini 仅接受固定 2021-06-03 至 06-11 日历、W1-mini 标识、单个固定事件、真实精确类型 `SyntheticMarketProvider`、信号文件≤2MB；加载后再限≤15行、≤5代码。mini context 由 runner 内联建立并用于同一真实 core 调用；不存在可返回未绑定 context 的公开 factory/initializer。伪造类名 provider 与用 mini 标签包装全窗均被拒绝。真实 core mini/slot bridge、成本 basis、除权登记与上市行为在 95 项中通过。

非白名单事件在情景上下文中强制严格税务检查，专测通过；默认生产上下文的 fractional 非整数事件仍 fail-closed。基线 corporate action、runner、bridge、strategy 定向回归均包含在 95 项中并通过。fix1 交付中列出的此前 context 泄露、伪造 provider、factory/initializer 可直调问题均未复现。

实际 prefix 仍不存在；不据此认定任何完整 W1 逐事件、core state、订单或 registry 等价。实际分配和税务未知；不声称真实税后达标、全收益界或全国分配已穷尽。
