# 独立最终裁决：FAIL

日期：2026-10-29。审查已停止，未修改被审源码；后续修复交原编码 owner。
详细证据与限制见同目录 REPORT.md；本结论替代此前仅只读检查给出的整体 PASS。

| 四层 | 最终裁决 |
|---|---|
| 单测机制 | **PASS：165项、0 skip；独立Mini质量门FAIL**，因生产schema attestor反例失败 |
| 是否适合尝试真实cutoff | **不放行**：合法双身份结果仍被attestor拒绝，空身份却可生成候选见证 |
| 可信prefix proof | **BLOCKED／未证明**：三个trusted pins None，无真实12路径证明 |
| 实际目标 | **LOCKED／未证明**：无真实绩效，PIT/费用/税务/实际获配未知 |

## P1，阻断：attestor 重置 experiment

- `prefix_attestor.py:135-138`构造并验证双身份后，`:157`将experiment清空为{}，`:167-175`再以空字典验证分支。
- 合法生产schema合成分支实际失败：`branch dual-core identity differs from plan: W1_B1_ceil`。
- 将分支identity和audit identity都清空后，实际生成 `UNPINNED_ATTESTATOR`；可信proof仍被None pin拒绝。
- 复现：`LEGACY_见证链探针.log`、`原探针适配.py`；适配器复用原QA脚本，仅重定向输出，增加正确性断言，exit1。
- mock范围：仅跳过 `_fixed_inputs` 的4812项全量输入校验，避免真实大源；真实身份/实际import/15项源码/分支比较未mock。
- 必须修复：保留已构造experiment，拒绝空/缺失身份，补生产schema正向与攻击回归。

## P2，严格边界待修：cutoff信号仍整文件预载

- `staged_candidate_runner.py:107-108` read_bytes整文件作SHA，随后`:119-121`另以日期谓词读取业务行。
- `CUTOFF_BYTES_AUDIT.log`实测完整1448字节合成信号预载，再返回截止前两行；未证明未来行参与业务决策。
- 若严格要求不预载完整未来文件，此项不满足；流式SHA可消除完整内存预载，物理未来字节零I/O则另需可信输入证明/截止分片。完整SHA读取不能称仅footer。
- 其他P2/P3：无新增发现。

## 已通过与完整性

- 独立165项225.958秒、0 skip；原wheel单项3.400秒；Ruff、五模块Pyright、diff-check均exit0。
- 双环境默认自签isolated拒绝、身份先于artifact、prefix context/PYTHONPATH限制及实际import均实测通过。
- 合成raw/state日期过滤、future毒化、coverage跳读与普通coverage校验通过；不等于真实PIT认证。
- 审前审后36项SHA一致，固定source 15/15匹配；v12/sidecar/原wheel/隔离core未变。8项小输入抽样一致，其余4804项未核验。
- 没有访问/重哈希完整4GB源；未运行真实八分支、真实6/8数据、12路径proof或绩效；未安装、提交、推送。
