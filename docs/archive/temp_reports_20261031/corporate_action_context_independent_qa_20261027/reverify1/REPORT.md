# 公司行动模块修复轮一独立复验

**VERDICT：PASS（机械模块质量门，本轮指定范围）。生产真实税后目标：未验收 / BLOCKED。**
任务：`corporate_action_context_20261027_fix1`；模式：`re_verify`；修复轮：1；日期：2026-10-27。
唯一审查树与所有验证cwd：`C:/Users/yanwen/AppData/Local/Temp/opencode/corporate-action-fix-20261027`。
基线：`ce7d1c6e0bd64136f10759412c55f6da410f128f`。本轮未读取或修改旧工作树，未使用旧audit脚本，未改源码、环境、锁文件或提交。

## 实际验证

| 验证 | 结果 | 证据 |
|---|---|---|
| 定向四测试模块 | 37/37通过，新两文件24项、旧两文件13项，含真实core E2E | targeted.log |
| 上轮原两个独立反例 | 2/2通过，执行原反例代码并强制TREE为新树，未执行原audit | independent.log、boundaries.py |
| 本轮最小补充边界 | 2/2通过，含真实core未知现金严格/探索/零登记，及窗口参数与缺省证据 | independent.log |
| 四新增文件Ruff | PASS，--no-cache | ruff.log |
| 四新增文件Pyright | PASS，0错误、0警告、0提示；另有工具版本更新通知，未更新 | pyright.log |
| 冻结一致性 | 4/4 SHA及字节数审查前后均吻合fix1清单和用户给定hash | SHA_BEFORE.json、SHA_AFTER.json |
| 实际ROOT/cwd/导入 | 均为新树，loader导入路径有断言及记录 | VALIDATION.json、IMPORT_ROOT.json |

执行均使用主区 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`，Pyright的--pythonpath指向同一解释器。未重跑全树851错误基线。

## previous_issues收敛

| 上轮问题 | 本轮结论 | 核验 |
|---|---|---|
| P1-01 同日record/ex无持权也全局拒绝 | 已关闭 | hook只产出RecordPosition；core实际开盘买入后登记100股才拒绝；0股登记可走完且无应收/股权；严格与探索的正登记均拒绝不支持时序 |
| P1-02 现金None当作0且正持权不留证 | 已关闭 | loader保留None并标cash_amount_unknown；100股登记strict抛错且INCOMPLETE；exploratory继续但INCOMPLETE；明确0不冒充未知；0登记未知不全局阻断，无幽灵对象 |
| P1 最终冻结冲突 | 新树已解决 | 四文件本轮前后hash一致；不对仍被外部修改的旧树作结论 |
| P2-01 窗口证据不完整 | 模块交付要求已关闭，runner验证待办保留 | 导出period_id、anchor/reset_anchor、window_end、calendar_sha256及metadata；省略值为None；始终pending_runner_validation，不称日历已核验 |
| P2-02 全树类型检查851错误 | 范围外保留，未声称修复 | 按用户明确范围只检查四文件，不将本轮PASS泛化为全树PASS |

## 正确行为保持

37项回归继续覆盖T单一复合事件、来源原始值/行hash/文件SHA、总送转与成本守恒、observer原对象逐update转发和完整post_state、开盘单后登记、现金卖至零仍支付、锚点缺record条件、零权益无幽灵、unresolved正暴露阻断、股权变仓拒绝、非整数不floor、现金20%仅stress及配股coverage。未引入影子账户或对不支持股权路径造成本账。
本轮未重新全量扫描真实冻结输入：仅核修复代码和指定测试，不把owner的8752行实测冒充本轮独立重跑。

## TDD与结论边界

fix1 DELIVERY中的三组red_passed/green_passed均true。RED_P1含同日hook提前抛错及未知现金未抛错的完整栈；RED_P2含缺构造参数和metadata键的接口失败，均有对应GREEN。本轮37项GREEN及原反例已独立执行，未将导入失败充当本轮行为RED。
机械模块可交runner owner接入；窗口日历真实性与运行器整体集成尚需runner验证。送转税、实际现金税、官方零碎股等没有新增证书；所有模式actual_after_tax_target_eligible仍false。此PASS不构成生产实际税后收益验收或排名授权。
本轮范围内无未解决P0/P1/P2源码问题；范围外类型检查基线和生产验证待办如上。机器可读结果见VERDICT.json。
