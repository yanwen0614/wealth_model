# W1 prefix 门 fix1 交付

## 状态
- Worktree：`research/w1-fractional-scenarios-20261028`，基线 HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。
- 改动仅在当前隔离 worktree；未安装、未提交、未运行 W1/八分支绩效。
- `TRUSTED_PREFIX_PROOF_SHA256=None` 保持硬失败；主 CLI、直接 batch `execute`、直接 `run_staged_window`、runner CLI、`run_single_from_cli` 和直接真实 W1 context 共用完整 proof 校验。
- 校验要求 proof 文件字节 SHA 匹配源码可信 pin，并检查 PASS、固定 HEAD、截至 2021-06-07、原始 canonical prefix 与 floor/ceil prefix 两项匹配；在创建输出目录、读重型信号/配置或启动 core 前失败。
- 单事件免 proof mini 限定固定 2021-06-03 至 2021-06-11 日历、单个白名单事件、core `SyntheticMarketProvider` 精确类型、`w1-mini` 配置及不超过 2MB/15行/5代码。公开 context 构造器只接受真实 W1 并强制 proof；不保留 mini factory 或 mini initializer。context 仅在 staged runner 的同一内部运行中、输入验证后内联创建，并将同一 `window`/`market`/signal 输入传给 core；context 不从公开 runner 返回，且边界外拒绝。
- 非白名单公司行动临时启用严格税务校验，保持 fail-closed；白名单事件仍只标记为税务未知压力情景。

## TDD 与验证
- RED：executor 全窗绕过先实际触发 subprocess；mini context 公开构造、同名伪造 provider、可返回未绑定 context 的 factory、name-mangled initializer 四种反例均先运行并失败。
- GREEN：新增直接 executor、全窗 runner、伪 mini、batch CLI、runner CLI、single runner、真实 W1 context、mini 构造/provider/factory及非白名单事件严格拒绝测试。
- 定向 unittest：95 tests passed（原 84 项 + 新增门禁回归）。
- Ruff：目标文件通过。Pyright：0 errors / 0 warnings / 0 informations。
- 原始独立 QA 文件保持未改；本目录保存其原始副本及原命令记录。

## 冻结与业务限制
- 原迁移清单 16 项中 14 项仍与冻结 SHA 完全相同；候选运行器和 production inputs 是已声明接线文件，本轮继续变更，SHA 见 `FIX1_HASHES.json`。
- core runner、官方 PDF、送转源文件 SHA 均与先前固定值相同；详见 `FIX1_HASHES.json`。
- 实际获配与税务仍未知，20% 仅现金分红压力假设；`actual_after_tax_target_eligible=false`、production `BLOCKED`。
- 原独立审查依次指出公开 mini context 构造、provider 类名伪造、context 与真实 core 输入不绑定、name-mangled initializer 可直调。当前不再保留 mini factory/initializer；context 仅由 staged runner 在已验证的实际 core 调用内联创建，runner 不返回该 context。对应反例均补了 RED/GREEN；等待同一审查方再次复验。
- prefix 尚无完整 canonical 对照，可信 SHA pin 保持 None；复验前不得运行绩效。
