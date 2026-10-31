# Harness 进度

status: ready_for_quality_gate
阶段：T01–T03 实现与单文件TDD完成；独立质量门待主代理派遣。
task_dir: C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness/
执行约束：中文；不询问；不提交推送删除；不改 memory；保留已有修改；每次写入<=50行。

## 已完成研究
- 已读两份技能及必读项目约束，扫描模块 AGENTS；MISTAKES.md 不存在。
- 已完成 scripts 构造点盘点、生产调用链核查、相似实现/现有测试/旧任务重复检测。
- 已将证据行号、最小修改点、测试建议、范围外风险写入 PLAN。
- 本轮没有执行任何测试、训练、GPU任务或 W4 扫描；没有修改项目源码。

## 任务列表
| task_id | 名称 | 状态 | 依赖 | 验收 | 修复轮次 |
|---|---|---|---|---|---|
| P00 | 只读研究与三件套 | complete | 无 | 三份文档存在并读回复核 | 0 |
| T01 | 两评估入口标签透传 | complete | 无 | 两入口缺键/三模式/非法值透传，RED→GREEN，29项通过 | 0/2 |
| T02 | no_val保留训练日期 | complete | 无 | main默认/自定义/普通验证，RED→GREEN，19项通过 | 0/2 |
| T03 | 工厂日期切分前置检查 | complete | T02 | 25拒绝+5合法子场景，RED→GREEN，2项通过 | 0/2 |
| T04 | 定向审查与证据交付 | 待独立质量门 | T01/T02/T03 | Generator自检与证据已交；零售定向回归3失败另交主代理 | 0/2 |

T01与T02逻辑独立；T02/T03先后落地以免日期防线掩盖 no_val 原因。当前不派遣其他会话。
TDD：三项真实RED→GREEN；Quality Gate：未运行，不能据此宣称质量门PASS。
详细命令、失败信息、范围外风险与tdd_verification见本目录TDD_VERIFICATION.md。

## 可直接交 Generator 的范围
按 PLAN 修改两个主评估脚本、train.py 和 data/dataset.py；扩展 test_eval_preprocessing.py、test_train_metadata.py，新增 test_dataset_date_ranges.py。
T01缺键回退 absolute；T02只关闭验证；T03验证启用时要求 train_end、val_start 存在且严格递增，内部区间合法。
所有日期检查在工厂首个 Dataset 构造前；非法/NaT也拒绝。无验证时允许无界训练，context不是标签交叠。
采用单文件TDD和CPU mock，不做训练/全 parquet；具体命令及TEMP/TMP要求见 PLAN。
脚本H5、零售错误loader、多种子漏传、cs/mkt缺失和缺失scaler重拟合另交主代理；不顺手扩大修改。
遇范围冲突返回 blocked 给主代理，不询问用户。代码完成后返回文件清单、RED/GREEN、定向回归、风险与剩余问题。

## 工作区只读基线
开始时 git status 有四份已修改文件：scripts/audit_walkforward_execution.py、tests/unit/backtest/test_cnn_adapter_contract.py、.opencode/memory/MEMORY.md、.opencode/memory/HISTORY.md。
以上均非本任务修改对象；本任务产物在仓库外，无需 git add/commit。
源码完整性只能报告本轮未写源码；共享工作区其他代理后续变化不归因本轮。
