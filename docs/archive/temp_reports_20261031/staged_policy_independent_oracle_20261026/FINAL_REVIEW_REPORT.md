# 最终独立复核报告

## Verdict

**PASS（仅合成规格/冻结契约复核）**。复核者为 `magpie/codex/gpt-6-luna`，OpenChamber 会话 `ses_e86efcd2fffe0ERwe5TxesWMKm`；最终复核消息 `msg_17914edf0001oebTirqBIPam30`。首次和第二次复核发现问题后已修复并再次复核；最终轮确认 PASS。不得解释为收益、真实策略绩效或真实市场成交验收。

## 复核范围与身份

- Oracle：同目录 `fixtures.json`（15 cases）、`REVIEW_CHECKLIST.md`、`README.md`，SHA-256 见 `FINAL_MANIFEST.json`。
- CNN 旧基线仅限 commit `ead9fc6ca13844dc262132a39f036fe385040206`；allocation blob `204cb54b09072f6167d3c6ef92356bd74042565a`；bridge blob `758087278a307792a3f7c6e868dc644d1df33761`。
- core 合约与 DAY runner 仅限 commit `893fc96925e029098f6c758dba8724d187c6b512`；各冻结路径 blob 见 manifest。
- 未读取 owner 正在修改的新实现。以下旧基线问题不代表 owner 当前代码状态。

## 数字与行为核验

- Case 01：`1000 − 4×200 + 0 = 200`；活动单冻结50使 available_cash=150；减 eE 承诺200后 free_cash=−50，拒绝新 episode。
- Case 02：C70 `B=200`、实际BUY借记140，剩余 commitment=60；`860−60=800`，新不同代码 episode 承诺200后 free_cash=600，准入正确；eA 再借记1使累计141>140应拒绝；eA关闭才释放60。
- Case 10：1900×10.50=19950；费用39.70+0+0.20=39.90；借记19989.90≤B=20000；100000−19989.90=80010.10。整手100股约束满足。
- Case 13：free_cash=`400−120=280`；新episode完整承诺200后余80；去重代码并集 `{AAA,BBB,CCC}=3≤10`，准入正确。
- Case 15：未确认卖出时去重并集11，拒绝；确认后8持股+权益1+候选1=10，且五槽/承诺另行通过，准入正确。分项统计与并集分开报告。
- 全部15个fixture JSON解析通过；清单与README项数一致。Luna 最终确认 02/10/13/15 和其它裁定未被末次修订破坏。

## Core DAY 与边界

冻结 core runner `account_runner.py` 第1738–1740行从 `pending` 按交易日 pop 后执行；1776–1786行只排入对应未来执行日，不滚存未成交余量；1366–1381行发终态反馈。DAY 结论须由 QA 使用该冻结 runner 取证，不能仅凭 OrderIntent 字段推断。限价SELL须保留 staged 身份与冻结限价；E日排名继续用于退出，BUY 在次日 buffer 禁止。

## 旧基线已知问题（严格限于 ead9fc6）

指定旧版 `open_episode` 对任一 episode 的 `exit_pending` 全局拒绝新开槽；`_sync_exit_state` 可在未来份额未取消/终态时提前 CLOSED。以上只描述 manifest 绑定的 `ead9fc6` 及其 blob，不声称 owner 独立树当前仍有这些问题。

## 复核历史

1. Luna 首轮 FAIL：指出 case01 借记超过B、case10预算数字错误、case13/15缺准入/并集断言、清单计数和旧基线身份未锁定。
2. 修正后第二轮 FAIL：指出 case02 对不同代码新episode错误预期拒绝；free_cash=800应准入。
3. 按裁定修正 case02 为允许新episode，同时eA的60承诺留存、eA追加借记超C70 cap拒绝；最终轮 PASS。

未运行收益、IC、大数据回测或业务测试；只对冻结 JSON 做解析检查及对规则/算术的独立审查。
