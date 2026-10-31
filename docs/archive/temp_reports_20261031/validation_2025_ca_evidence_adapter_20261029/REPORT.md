# 单事件官方原文证据映射机制

状态：DEADLINE_CLOSEOUT / BLOCKED。按21:55指令收束，官方证据映射尚未实现，不能启动真实解锁。
生产入口保持fix3源码不变；无证据参数、无官方豁免开关、无默认规则改动，未运行年度或覆盖v1/v2。

## 实际完成及未完成

- 新增tests/unit/backtest/test_ca_evidence_adapter.py：严格单事件映射的fixture字段草案及两条关闭性测试。
- 草案逐项列出event_id、证券、源row SHA、报告期、原资料文件SHA、外部文件SHA、发布日期、动作、日期范围和原文quote。
- fixture文件明确EVIDENCE_FIXTURE_ONLY，非PDF、非官方；不能当作原文真实性或映射功能实现。
- 真正的证据文件真实性核验、PDF正文提取/语义匹配、最终决议与后续变更核验、正式适配器均未完成。
- 未新增可启动真实路径。不能将“已有fixture schema/绿色关闭性测试”说成正式映射RED/GREEN完成。

## 收束测试及审查入口

verify.ps1仅复跑既有38项、新增2项关闭性测试、109项既审回归、ruff --no-cache及定向pyright。
第一条新增测试经真实core买入后仍触发默认unknown-record保护，库存/锁仓保留，收益不可用；
即使向fixture JSON写approved=true也没有任何豁免能力。第二条确认入口根本没有evidence_adapter参数。
完整结果以GREEN/REGRESSION/RUFF/PYRIGHT.log为准；没有伪造新增映射的RED日志或声称独立QA已通过。
Pyright使用fix3已冻结的显式extraPaths配置、绝对pythonpath，并显式列出本轮全部五个源码/测试文件。

## 最新候选取证状态（主会话提供，非本任务新增核验）

A 000601：2025半年度官方PDF URL https://static.cninfo.com.cn/finalpage/2025-08-05/1224387247.PDF。
主会话给定SHA A90B9633553D7C38F3BE3B503648E1476158A162FDC66DFC6C3596E4189E0445；本任务未独立下载/提取。
A的2024年度17917未闭合，17918亦须继续按真实已实施事件保留；不得声称000601已全面解锁。
B 000506：年报摘要 https://static.cninfo.com.cn/finalpage/2025-04-29/1223379365.PDF。
主会话给定SHA 455ba0e09ef005cf1fd4486c9c9b288634f4aca0791976afad0094dcc4144022，仅2024年度预案。
股东大会最终决议官方PDF及后续变更链未核；单有预案“不派现金、不送、不转”不足授予真实豁免。
上述SHA是已提供的预期值，不冒充本任务测得的附件SHA或完整适用性认证。

## 剩余阻塞及后续审查

必须先核官方原PDF/正文、最终决议、确切source row/证券/报告期及适用时间、其他事件和变更。
正式实现须逐事件逐日期绑定，任何缺失/错配均fail-closed；不能用用户布尔或进度/零金额代替权威。
PIT/version、实际税/市场状态/其他事件继续UNKNOWN；目标NOT_EVALUABLE，三项pins不能全局升格。
closeout.py记录生产fix3未变、源码/依赖/原行SHA及最终日志；FREEZE完成后停写，交独立QA。
