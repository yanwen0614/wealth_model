# 公司行动 loader/context 独立只读审查

VERDICT: **FAIL**。任务：`corporate_action_context_20261027`；模式：`review_verify`；日期：2026-10-27。
现有机械回归 **PASS（32/32）**，机械模块完整契约 **FAIL（新增独立边界断言 0/2）**；生产真实税后目标 **BLOCKED**。
审查树为交付指定独立树，基线 `ce7d1c6`；测试前及测试完成后的四文件 SHA/字节数均与交付一致，但最终交付复核检测到外部变动，见下文冻结冲突。本审查未修改源码、环境、锁文件或提交。

## 问题分级

- **P0：未发现。** 没有发现双算 T/B/C、影子现金持仓账、虚构税后达标或配股入账。
- **P1-冻结冲突：最终树已偏离交付哈希。** 测试完成并保存 SHA_AFTER 后，末次复核发现 loader 与 context测试被外部改写；当前loader SHA=`bf398a083992d6c235df39451d00502a3c3868e8212ba56220f1ebfcd71c4ebd`，context测试 SHA=`be11b61effb13fc0e690efff9abf4eb8494668435473307f7cdedd2cb31382f9`。本报告源码缺陷、32项GREEN和2项反例只针对原交付SHA，不对变化后版本作结论。须重新冻结后另行复验；不恢复或覆盖owner改动。
- **P1-01：未持权事件也会提前阻断全账户。** `corporate_action_context.py:111-114` 在读取实际登记数量之前，对同日 record/ex 无条件抛出 `same_day_record_ex_unsupported`。独立探针给出空仓 core 状态、strict=True，调用当日 hook 即失败。与“仅实际正持权阻断、零登记无关未知不全局 raise”冲突。应先保留登记机会，再按 core 实际正暴露拒绝不支持时序；不能根据开盘前空仓跳过登记。当前冻结输入同日 record/ex 为 0 行，属于可复现的接口边界缺陷。
- **P1-02：正登记的未知现金数额被当作零。** loader `corporate_action_snapshot_loader.py:70-78,88` 保留 `None`，却未标现金未知；context `corporate_action_context.py:69-81,159` 全用真值分支。独立探针：税前现金=None、T=B=C=0、core 登记100股、strict=True，observe 不拒绝，ex 操作为空，证据仍为 `MECHANICAL_ONLY`。应区分未知与明确0，并仅对正登记持权形成 INCOMPLETE/严格阻断。当前冻结输入现金None为0行，不能用这个事实替代模块未知值契约。
- **P2-01：导出证据缺少可自解释的窗口身份和范围。** context `corporate_action_context.py:174-184` 未导出 `period_id`、执行日历指纹或窗口终点；snapshot `corporate_action_snapshot_loader.py:110-116` 未导出已加载 metadata。文件哈希能定位输入，但仅凭 evidence 无法确认实际执行覆盖范围。建议由 owner 接入时补足窗口身份、日历指纹及结束范围。
- **P2-02：全树类型检查不通过。** `pyright --pythonpath 主区解释器` 返回851个错误，落在既有文件（例如 `order_strategy.py:91`、`data/cs_mkt.py:41`、`training/trainer.py:198`），四个新增文件无诊断。此项是全树验证阻塞，不能归因为本次新增；没有创建基线副本重跑差分。

## 验证与证据

| 项目 | 独立结果 | 证据 |
|---|---|---|
| 现有定向+旧 corporate_action+真实 core E2E | 32通过；新增两文件19项、旧两文件13项 | targeted.log |
| 独立契约反例 | 2失败；分别对应P1-01/P1-02 | independent_boundaries.log、test_independent_boundaries.py |
| 全树 Ruff | PASS，--no-cache | ruff.log |
| 四新增文件 Pyright | PASS，0错误/警告 | pyright_targeted.log |
| 全树 Pyright | FAIL，851错误/0警告 | pyright_full.log、full_typecheck_result.json |
| 四文件冻结 | 测试前后4/4相同；末次复核2文件变化 | SHA_BEFORE.json、SHA_AFTER.json、SHA_FINAL_CONFLICT.json |
| 来源文件验证 | 独立12/12 SHA通过；manifest外部SHA吻合 | PROBES.json |
| 全部原始行哈希 | loader实际加载8752行且逐行复算通过 | PROBES.json |

所有执行使用主区现有 `.venv/Scripts/python.exe -B`，cwd=被审工作树；Pyright显式同解释器。首轮组合脚本因全树类型检查超过60秒被工具终止；只重启全树类型检查并完成，未重复32项测试。未安装/更新任何包。
实际导入core来自主区 `.venv/Lib/site-packages/backtest_core/engine/`；account.py与account_runner.py的SHA均与本地backtest-core/src对应文件完全一致，已写入SHA_FINAL_CONFLICT.json。

## TDD核验

交付 `DELIVERY.json` 四组 red_passed/green_passed 均true；`TDD.log` 前两轮是新模块缺失的导入RED，仅证明接口尚不存在，不能当作行为断言RED。后两轮明确为 ValueError未抛出和证据状态错误的断言RED，各有GREEN；cost_basis夹具错误被明确排除。按交付记录检查为 **PASS，历史证据有限**：文件为摘录，无完整原始栈/时间顺序证据；本审查无法独立证明历史RED确实先于实现，也未把当前新反例包装为历史TDD。现有GREEN已独立复跑。

## 结论边界

现金和股份仍由真实core维护；observer原对象逐update转发并保留post_state，delegate异常原样传播。登记在开盘订单后执行；登记后卖至零仍支付现金；零登记不建应收/股权；股权record到ex变仓明确拒绝；精确整股、不floor、混合bonus税未知、现金20%仅stress、配股仅coverage均符合。
当前冻结输入的机械用例通过不等于完整模块契约通过。两个P1应由编码owner处理后复验；本次不修复。所有模式 `actual_after_tax_target_eligible=false`，真实税后生产目标继续BLOCKED，不能进入实际税后收益排名或达标结论。
