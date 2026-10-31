# 独立复验裁决：FAIL

日期：2026-10-29。对象：冻结 CNN 工作树及 stop-capable 隔离 core；只读审查完成。
**封存发现外部改写源码/测试，冻结完整性 FAIL。106项通过和动态反例属于审前版本，不构成最终磁盘版本的验证。详见 FREEZE_DRIFT.md。**
权威明细：同目录 `REVIEW.md`，包含确切文件行号、反例、攻击条件、范围和修复建议。

| 裁决层 | 结果 |
|---|---|
| mini 质量 | **FAIL**；审前自动检查106/106通过、0 skip，但独立反例和审期冻结漂移失败 |
| 是否可尝试真实 cutoff | **FAIL，不放行**；公共包装层循环依赖 proof、未来行情解析边界及见证链未闭合 |
| 可信 prefix proof | **BLOCKED，未证明**；三个 trusted pin 均 None，无真实12路径证明 |
| 实际目标 | **LOCKED，未证明**；PIT、费用、税务和获配证据不足，无真实绩效运行 |

阻断项：

1. **F1 / P1**：runner `:716-723` 对真实 cutoff 仍先索取尚不存在的可信 proof。
2. **F2 / 审前P1**：旧默认 `_verify_prepared` 接受自签隔离 core。外部新版新增硬身份门，效果未复验，不把旧反例归于新版。
3. **F3 / 审前P2**：旧默认分支身份门前读 artifacts，为既有行为。本轮封存时外部新版已前置检查，未完成新版本复验。
4. **F4 / P1**：attestor `:157` 清空 experiment；完整合法身份被拒，空身份攻击能输出 UNPINNED 见证。
5. **F5 / P1**：查询6/7时底层加载6/8；只毒化未来成交量就改变截止日行为，而 guard 日志没有未来请求。
6. **冻结完整性 / FAIL**：production_inputs 和 test_dual_core_identity 的最终字节异于审前。F1/F4所在文件未变，F5接线在新版文本中仍存在。

确认通过但不扩大解释：

- v12 原 SHA `a8ad…4441`、sidecar、原 wheel `aa156…daa00` 和真实隔离 import `4d3…1819` 均核实，审前审后未变。
- prefix 固定身份先于 artifacts，真实入口已做低开销只读验证；默认入口仍存在上述问题。
- 相同字节不同真实 import 路径、一字节 manifest 篡改、sidecar 换行、伪造 context 均被拒。
- 106定向单测通过；Ruff `--no-cache` 通过；四模块 Pyright 0 errors/warnings/informations；diff空白检查通过。
- 最终23项中22项一致，production_inputs变化；补充4项中原wheel/manifest/sidecar一致，双身份测试变化。HEAD/git status清单不变不等于内容冻结。
- 四份原 baseline 元数据12项匹配当前硬清单，但全部 INCOMPLETE；没有重证完整五账或独立 canonical 根。

未覆盖：4812 artifacts 只抽样实算8项小文件，未全量复核；真实八支、真实双 core 事件等价、12路径 proof 与绩效全部未运行。
F4 探针用真实 v12/实际 import/真实源码核验，但明确 mock `_fixed_inputs`；合成见证不是可信 proof。
没有修改代码或源数据，没有安装、uv、提交、推送。三个 trusted pin、PIT/税务/获配 UNKNOWN 边界均未放宽。

交付：`REVIEW.md`、本文件、`HASHES.sha256`、审前/后清单、`CHECK_SUMMARY.json`、`TMUX_STATUS.json`、各真实检查日志、实际命令 JSON 与独立复现脚本。
