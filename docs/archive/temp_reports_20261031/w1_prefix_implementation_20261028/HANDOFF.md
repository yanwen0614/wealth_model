# W1 prefix-stop core 交付记录

记录时间：2026-10-28。交付类型：实现与 mini 验证记录；不构成真实 W1 prefix 验收。

## 两棵工作树与身份

- CNN 树：`C:/Users/yanwen/AppData/Local/Temp/opencode/w1-fractional-scenarios-20261028`，branch `research/w1-fractional-scenarios-20261028`，基线 HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。树内原有未提交改动；完整 modified/untracked 清单见 `CHANGESET_SHA256.md`。
- core 隔离树：`C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028`，branch `research/w1-prefix-stop-core-20261028`，基线 HEAD `893fc96925e029098f6c758dba8724d187c6b512`，owner：当前 Codex 会话。仅修改 `src/backtest_core/engine/account_runner.py` 与 `tests/test_account_orders.py`；diff stat 为 30 insertions/1 deletion、44 test insertions。
- `core` 主仓 `D:/code/cnn_full_20260905/backtest-core` 保持干净、HEAD 仍为 `893fc96925e029098f6c758dba8724d187c6b512`。主区安装 wheel 文件 `D:/code/cnn_full_20260905/cnn/.venv/Lib/site-packages/backtest_core/engine/account_runner.py` SHA-256=`aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00`，复核与用户给定值一致，没有改动 wheel 或安装环境。
- 运行 CNN 测试时显式设置 `PYTHONPATH=C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src`，Python=`D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe` (3.12.13)。因此这些测试**实际导入隔离 core 源码**，不是原 wheel。导入路径：`C:/Users/yanwen/AppData/Local/Temp/opencode/backtest-core-w1-stop-20261028/src/backtest_core/engine/account_runner.py`；最终完整模块 SHA-256=`4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819`。
- core 测试同样通过 `PYTHONPATH` 导入隔离源码。原 wheel 仅在无该环境变量的单独只读身份核验中导入/哈希；没有用原 wheel 执行本次 stop-core 测试。

## 实现范围

- core 新增 `stop_after_close`：要求 cutoff 同时是执行日与 `evaluation_end`，仅支持 `T1_OPEN`；保持完整 execution calendar 解析截止日 T+1 订单，在 cutoff 收盘快照后跳出循环，不把 pending 订单误判为无下一交易日。
- pending 订单以 JSON provenance 留存：订单/episode/证券/方向/数量/限价/信号日/执行日。合成测试检查 prefix 快照与同输入完整运行的共同观察日状态一致；这不是原版 core W1 的等价证明。
- CNN runner 提供 `--prefix-stop-after-close YYYY-MM-DD` 与 Python 参数 `prefix_stop_after_close`。保留原 W1 完整 `WindowDefinition`/日历，将 cutoff 传 core；prefix 市场 API 与排名 API 会拦截并记录 cutoff 后请求。费用范围限至 cutoff 及唯一下一执行日，后者只供 cutoff 收盘订单 T+1 预算计算，记录在 `prefix_fee_access.jsonl`。
- prefix 不计算 adapter 侧主区收益，标记 `main_total_return=NOT_COMPUTED`。输出含 `prefix_market_access.jsonl`、`prefix_ranking_access.jsonl`、`prefix_fee_access.jsonl`，以及 execution updates、daily registry、strategy decisions、registry transitions、partial account states 等现有运行账本。
- `prefix_ledger_verifier.py` 有固定五类账本的顺序/逐行字节与字段比较、重复 JSON key 拒绝、来源/输出哈希。它只产出 `ledger_comparison`，不生成可解锁的完整 W1 proof。

受限 CLI 形式（参数占位，**未执行真实 W1**）：

```powershell
& 'D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe' -B -m backtest.cnn_adapter.staged_candidate_runner --signal-parquet <frozen-signal.parquet> --expected-sha256 <sha256> --source-id <W1-source> --checkpoint-sha256 <sha256> --anchor-date 2020-12-31 --evaluation-end 2021-06-30 --execution-calendar <full-W1-calendar.txt> --policy B1 --output-dir <new-output-dir> --input-config <frozen-input.json> --prepared-manifest <prepared-manifest.json> --prefix-stop-after-close 2021-06-07
```

- core API 只允许 `T1_OPEN`，`stop_after_close` 必须是完整日历日期且与 core `evaluation_end` 相同；adapter 另限制 `W1`/指定 mini period。runner 仍接收 full W1 end/calendar，不以截短日历替代真实 T+1 排程。
- CLI 示例仅记录参数契约。直接用原 wheel 会因缺少 `stop_after_close` 参数失败；显式加载隔离 core 后，现有 prepared manifest 又会因 `_verify_prepared` 的 core path/hash 身份绑定而拒绝。重建匹配新 core 的 prepared identity 与 CLI 全流程尚未通过 mini/真实 W1 验证。
- `--fractional-scenario floor|ceil` 还受 proof gate 限制；当前源码 pin 为 None，故不能运行真实情景绩效。未绕过 gate。
- 输出目录包含常规运行 artifacts、`attempt_audit.json`/`manifest.json`/`artifacts.json`，另有 prefix market/ranking/fee access JSONL。verifier 当前只要求并比较 `execution_updates.jsonl`、`daily_registry.jsonl`、`strategy_decisions.jsonl`、`registry_transitions.jsonl`、`partial_account_states.jsonl` 五类；不编排 B1/S1/S2/C70 × default/floor/ceil 的 12 份运行，也不比对完整三路径订单账。

## 能力缺口与绩效门

- 尚无四策略 × 三路径（default/floor/ceil）12 次运行的编排、全套独立输入/runner/core/observer/CA 源身份矩阵、逐策略三方 canonical 裁决、目标事件首差异证明或可信 pin 流程。
- 目前 verifier 仅固定比较五类事件账本；尚未证明 2021-06-07 前缀内容完整，也未对真实冻结四策略账逐行验证。生成的 ledger comparison 不能代替 baseline 原账真实性核验。
- 原始四策略失败重放、真实 W1 prefix、floor/ceil prefix、12 条大重放全部未运行；没有跑真实行情/绩效。真实 full W1 prefix 与原账一致仍未证实。
- `TRUSTED_PREFIX_PROOF_SHA256=None`；fractional 情景绩效门仍锁定。现有 prepared manifest 绑定原 core 路径/hash；切换隔离 core 后需重新建立并独立核验匹配该新 core 的输入身份，当前 CLI prepared 身份路径尚未验收。
- prior fractional mini 的 QA 结论不作为本交付验收。本 stop-core 代码另有只读 quality-gate 复审（先 FAIL、修复后代码审查 PASS）；该代理没有重跑测试，也没有运行真实 W1，因此不构成真实 prefix 的独立验收/等价证明，且不能解锁绩效。

## 验证结论和限制

- CNN 定向 unittest：78 项通过、0 项报告 skip；core `tests.test_account_orders`：46 项通过、0 项报告 skip。Ruff 两边通过；Pyright 两边均 0 errors、0 warnings、0 informations。Python/Ruff/Pyright 版本、命令和输出见 `logs/`。
- core 接口曾有真实 RED：新测试先因 `unexpected keyword argument 'stop_after_close'` 两个 ERROR 失败；实现后两个针对测试通过，随后完整订单测试 46 项通过。CNN runner/verifier 的 RED 未记录，测试是在对应实现之后加入。
- 测试合成 mini 不能证明新 core 在原版观察窗口等价；真实 prefix 未执行，任何“默认重放/情景分支截至 6/7 与原账户相同”的断言均待独立逐事件核验。
- 两树均保持未提交。本交付未安装依赖、未运行真实 prefix/绩效、未提交。完成本交付后停止修改两个源码工作树；本目录只存文档和执行日志。
