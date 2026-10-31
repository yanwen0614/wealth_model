# fix4 独立 re_verify

复验日期：2026-10-28。未沿用前轮 PASS。主区 Python 3.12.13 `-B`；core 通过显式 `PYTHONPATH` 导入。未用 uv、未安装/同步依赖；两隔离树与冻结输入仅读。未运行真实 prefix、12 路径或绩效。

## 三层裁决

- **Mini 质量门：PASS（合成诊断范围）**：fix4 声称的 74 项测试复跑通过；另 core 46 项通过。CNN/core Ruff、Pyright 均通过。核心对照在独立进程分别导入 wheel 与隔离 core，五类 observer prefix、snapshots、trades 完全相等。
- **实际 12 路径 proof 可执行性：FAIL（设计阻断）**：固定原始四份 baseline 可按 pins 验真，但皆为 CA 中断的 `INCOMPLETE`。八输出根目录不存在。CLI 构造的八命令都跑到 E=2021-06-30，无 `--prefix-stop-after-close` / `--information-cutoff`；CLI 执行前又要求已 pin proof。实际 W1 prefix API 明确 fail-close（只让 `test_W1_mini` 进入，且拒绝 prepared inputs/CA/数量源）。没有可由交付脚本产生并供 proof 使用的八个真实 cutoff 输出。
- **实际目标：LOCKED / 未证明**：`TRUSTED_PREFIX_PROOF_SHA256=None` 硬阻绩效；未生成真实 proof、未做 12 路径比较、未计算绩效。

## Proof 与输入真实性

- 四份实际 W1 baseline 的 audit、artifacts、sources 和五类账本哈希与 pins 相符；严格标识为 `INCOMPLETE`，只适合作为 2021-06-07 前账本比较锚点，不是完整 W1。
- 候选 proof generator 会重算基线 pins、策略、信号/准备清单/预注册、scope、calendar、universe、core SHA、cutoff、分支路径、五类账本和输入访问日志。Gate schema 字段与生成器匹配；pin None 时不可绕过。
- **真实性 FAIL**：scenario `attempt_audit.json` 与 `artifacts.json` 没有外部固定 hash/签名；后者可由目录内容自行重算。磁盘型探针将 ceil 目录复制到 floor、改写 audit/branch/evidence 与 artifacts manifest，并在五类账本追加 2021-06-08 行；`verify_machine_prefix_proof` 仍接受候选 `PASS`。`_prefix_records` 静默截取 cutoff 前缀，`_assert_access_cutoff` 只读同样可被重签的访问日志。故候选 PASS 不代表真实运行或无未来账/未来访问。
- 测试覆盖同目录比较拒绝、复制路径拒绝、缺/空账、换序、缺行、自报 PASS、proof 篡改；这些不足以抵消上述 mutable audit/artifact 反例。

## Fee / 日期 / 实盘边界

- Fee bundle v2 绑定 2021-06-07 cutoff、preregistration、scope/calendar/universe、resolver 源码 SHA，并强制 PIT/source availability/实际券商费均为 `UNKNOWN`。截止日规则复算印花税 0.1%、过户费 0.002%；cutoff 后费用取静态配置。其证据只支持限定 2021 研究假设，不是历史时点可得性或实盘费用证明。
- E 日与 buffer 的 no-BUY/三日 buffer 语义有 mini 测试；core cutoff 测试验证 6/7 收盘停止且 6/8 订单保持 pending。该行为没有连到可运行的真实 W1 floor/ceil 路径。
- 主区 wheel 导入 SHA `aa156ec2…8daa00`；隔离 core 导入 SHA `4d3a28c4…2220a1819`。对照仅为 mini，不能证明真实 W1。

审前/审后源树、28 个源文件及 wheel 哈希见 `HASHES_PRE.txt` / `HASHES_POST.txt`；四原 baseline 与 10 个关键冻结输入见 `HASHES_INPUT_PRE.txt` / `HASHES_INPUT_POST.txt`。共核对 70 项，0 mismatch。执行日志与命令见 `RUN_LOG.md`；攻击探针见 `probe_forged_audit.py`。
