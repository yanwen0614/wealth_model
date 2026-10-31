# W1 ceil precision fix2

## 修复与信任边界

- `fixed_source_sha256()` 将 `fractional_scenarios.py` 的过期 pin `9e78...` 更新为审查确认的 `7112BEDEF9A10D802E58F18580E391E25355803C838B401C215941CB9CE37180`。
- Attestor 将双 core experiment identity 的必需字段完整性验证抽为 fail-closed 函数并补齐 RED/GREEN 测试。
- `TRUSTED_PREFIX_PROOF_SHA256`、`TRUSTED_PREFIX_ATTESTATOR_SHA256`、`TRUSTED_PREFIX_ATTESTATION_SHA256` 均未改，保持 `None`。源码清单更新不代表外部信任、proof PASS 或生产解锁。

## QA 前后冻结核对

见 [QA_SHA_AUDIT.md](QA_SHA_AUDIT.md)：独立 QA 报告记录 fractional 源码和测试审前/审后 SHA 相同；本轮开工和结束时再次核对相同。core 源码未修改。

## 验证

- TDD：旧固定 SHA 与缺失身份 validator 均先 RED，修正后 `test_prefix_attestor` 4 项全过；见 [TDD.md](TDD.md)。
- 主区 Python `-B` 串行交叉回归 **124 项通过**：fractional 28、attestor 4、prefix verifier 16、staged runner 43、staged production 12、dual core identity 11、run identity 10。各模块日志分别记录测试名、退出码及前后内存/页面文件占用。
- Core 隔离源码路径：账户动作/订单/状态 **95 项通过**。原始 wheel 路径兼容用例 **93 项通过**；原 wheel 全量 95 项中的另外 2 项要求 wheel 不支持的 `stop_after_close` 参数，traceback 见 `logs/core_original_wheel.log`，未改 wheel。
- Ruff：通过。Pyright：0 errors / 0 warnings / 0 informations。`git diff --check`：通过。
- [SOURCE_INVENTORY.json](SOURCE_INVENTORY.json)：固定清单 14 项适配器源码 + 隔离 core 文件，共 **15/15 SHA 匹配**，含逐项 expected/actual。
- 物理内存约 16 GiB；开始时可用约 7 GiB；页面文件分配约 42.8 GiB、当时占用约 2.2 GiB。分段期间可用内存约 5.8–7.0 GiB；没有复现 `WinError 1455` / `cufft64_12.dll` 错误。
- 独立 QA 首轮指出缺少专项页面文件回归证据；补充串行单测重跑了 8 次 prepared attempts 用例与 CLI batch 用例，均通过，具体内存记录见 [CROSS_FAILURE_CLOSURE.md](CROSS_FAILURE_CLOSURE.md) 与 `logs/failure_repro_*.log`。

## 交叉失败核对与限制

- 可取得的旧 QA 交叉日志有两处固定源码 SHA 错误；本轮 `test_parent_attestation_plan...`、`test_machine_proof...` 均通过。旧报告所述另外 8 failures 的逐项 traceback 未随交付归档；新的同等 7 模块回归完整日志全部通过，因此不为旧失败推断未留证的逐项根因。
- 独立只读 QA 第二轮为 **PASS（限于本轮复核范围）**；详见 [INDEPENDENT_QA.md](INDEPENDENT_QA.md)。旧 122 项逐项 traceback 未归档，历史 8 个失败根因仍不能逐条重建。
- 原 wheel 的 2 项 API 差异已单独记录；隔离 core 同测试组 95 项全过。
- 没有运行真实 W1 cutoff、真实八支或绩效。获配、税务/PIT 与最终策略资格仍未知；proof/绩效仍由空 pins 硬阻断。

## 交付物

- `logs/`：逐模块回归、core 两导入路径、Ruff、Pyright 日志。
- `SOURCE_INVENTORY.json`、`QA_SHA_AUDIT.md`、`CROSS_FAILURE_CLOSURE.md`、`TDD.md`、`HASHES.sha256`：逐项源码、QA 前后冻结核对、旧失败对照和哈希证据。
