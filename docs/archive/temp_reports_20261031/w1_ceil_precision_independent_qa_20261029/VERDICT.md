# Ceil 精度修复独立最终裁决：FAIL

| 层次 | 裁决 |
|---|---|
| Mini质量 | **FAIL**：28项和机械场景通过，168项交叉回归2个ERROR |
| 真实cutoff可尝试 | **不放行**：固定source清单未同步，计划/source校验被阻断 |
| 可信proof | **BLOCKED／未证明**：三个trusted pins None，无新真实12路径证明 |
| 实际目标 | **LOCKED／未证明**：实际获配、税务、PIT、真实绩效未知 |

**P1必须修正**：prefix_attestor.py:35仍固定fractional_scenarios旧SHA `9e78…6f2f2`，实际为用户指定`7112…37180`；15项仅14项匹配。真实源码门及dual/prefix两个交叉测试均复现拒绝。
证据：PIN_ARITHMETIC.log、CROSS_REGRESSION.log:189-235、HASHES_before.json、HASHES_after.json。

**P3非阻断**：历史根因文档把q4000 floor写作1600；正确值1601，代码和两种core实测均正确。无新增P2。

已确认：q1300 floor/ceil=520/521，q2800=1120/1121，q4000=1601/1602；n/q JSON字符串和Fraction校验通过，core接收float且机械乘积精确为n。
原wheel与隔离core各六组合成登记/除权/上市和basis守恒通过；隔离core两条合成cutoff未访问6/8业务数据。默认生产和其他事件仍严格拒绝，未知资格保留。

38项前后哈希一致；源码与测试匹配用户给定SHA；原wheel/隔离core身份未变。
v2旧40账只读解析，业务日期均≤6/7；三条ceil仍为旧FAILED。未重跑真实W1 prefix或绩效，不能声称真实八支成功。

完整报告：REPORT.md；实际命令、退出码与汇总：SUMMARY.json；证据索引：EVIDENCE_HASHES.sha256。
停止只读审查；不改共享源码/清单，不安装、uv或提交。交原owner修正P1后再冻结复验。
