# 独立质量门审查证据

VERDICT: "FAIL"
task_id: T01-T04
mode: review_verify
审查日期：2026-10-25；工作目录：D:/code/cnn_full_20260905/cnn。
结论：三项行为修复符合计划，但新增测试存在1项类型错误；全仓静态门及零售回归亦未通过。
本轮只读审查源码，仅写本报告；未修源码、改记忆、提交、推送、删除既有产物或启动训练/GPU任务。

## 输入与范围

已读本目录 REVIEW_CHECKLIST.md、PLAN.md、HARNESS_PROGRESS.md、TDD_VERIFICATION.md。
已读根 AGENTS.md、data/AGENTS.md、README_TRAINING_CHAIN.md、docs/per_code_normalization_spec.md。
已读 .opencode/skills/cnn-harness/SKILL.md；用户限定优先，未执行技能中的过时入口、训练回退、提交及记忆步骤。
审查4个生产文件：scripts/eval_bins_mapping.py、scripts/run_eval_pipeline.py、train.py、data/dataset.py。
审查3个测试文件：tests/unit/scripts/test_eval_preprocessing.py、tests/unit/test_train_metadata.py、tests/unit/data/test_dataset_date_ranges.py。
git diff：已跟踪6文件合计98行新增、2行删除；另有83行未跟踪日期测试，已单独读取。
保留审计脚本、回测测试和两份记忆的既有修改；它们不属于本次结论范围。

## 七关卡结果

gate_results:
- {gate: 规范一致性, result: PASS, issues: []}
- {gate: 模块边界, result: PASS, issues: []}
- {gate: 数据安全, result: PASS, issues: []}
- {gate: 导入合规, result: PASS, issues: []}
- {gate: 错误处理, result: PASS, issues: []}
- {gate: 过度防御, result: PASS, issues: []}
- {gate: 性能风险, result: PASS, issues: []}
以上针对指定diff；全仓导入错误作为验证失败另列，不冒充本次diff问题。
新增边界检查为4个端点常数级解析，无新增扫描、fit、缓存或反向依赖，无凭证，无吞异常。

## 强制行为核查

T01：eval_bins_mapping.py:284、run_eval_pipeline.py:247 均使用 run_cfg.get("LABEL_MODE", "absolute")。
缺键回退absolute；absolute/excess/crash_conditioned及非法字符串均原样传递；scaler对象和evaluation角色保持。
非法模式由 data/dataset.py:168-169 在读数前统一拒绝；新增测试没有替代该生产校验。
T02：train.py:437-452 真实main始终传TRAIN_START/TRAIN_END，no_val只清空验证边界。
新增main测试在工厂处中止，覆盖默认no_val、自定义no_val、普通验证；没有训练或模型执行。
T03：data/dataset.py:404-433 在首个cls(train_cfg)（440行）之前解析并检查所有端点。
非法值/NaT/空串/不可能日期、内部逆序、同日相接、包含/反向/交叠、缺必要内端点均拒绝。
验证启用时要求train_end与val_start非空且严格递增；外端点train_start、val_end允许None。
无验证允许无界/半有界训练；单日训练/验证区间各自合法，只要两区间严格分离。
25个拒绝子场景断言构造/reader/fit/DataLoader均未调用；5个成功子场景保留端点及训练scaler复用。
context代码未修改：reader.py:87-102保留历史输入；context回归覆盖首日标签、无未来输入及三种归一化。
未添加自然日embargo；不把历史context输入误判为训练/验证标签日期交叠。

## 三项验证与TDD

运行前设置CUDA_VISIBLE_DEVICES=''、PYTHONDONTWRITEBYTECODE=1，TEMP/TMP指向本任务目录。
uv均使用 --offline --no-sync，避免依赖同步。测试只用mock/mini parquet与CPU模型构造，不启动训练。
日志中配置打印DEVICE=cuda来自默认配置值；main测试mock种子与工厂，未实际使用该设备。
测试命令前缀：`rtk uv run --offline --no-sync --project . python -u -m unittest`。
测试模块（以下7个模块在同一命令中执行）：
- tests.unit.scripts.test_eval_preprocessing（29项）
- tests.unit.test_train_metadata（19项）
- tests.unit.data.test_dataset_date_ranges（2项，含30个子场景）
- tests.unit.data.test_data_excess_labels（10项）
- tests.unit.data.test_context_warmup_windows（7项）
- tests.unit.data.test_dataset_cache（24项）
- tests.unit.training.test_training_retail_wrapper（9项）
实测：100项，7.708秒，97通过，1失败、2错误；前6模块91项均通过，零售模块6通过、3未通过。
原始测试日志：C:/Users/yanwen/AppData/Local/rtk/tee/1792943221_uv.log（1053-1055行总计）。
Lint命令：`rtk uv run --offline --no-sync ruff check --no-cache .`。
全仓结果：1项I001，training/trainer.py:1-17，criterion.gate_loss项目导入混在第三方导入中。
七文件同命令显式列路径结果：All checks passed!；`rtk git diff --check`通过。
全仓ruff日志：C:/Users/yanwen/AppData/Local/rtk/tee/1792943231_uv.log。
TypeCheck版本：pyright 1.1.411，可用，未安装或升级依赖。
全仓命令：`rtk uv run --offline --no-sync pyright --outputjson`。
结果：分析263文件，769错误、0警告，41.227秒；不可宣称类型检查通过。
原始JSON日志：C:/Users/yanwen/AppData/Local/rtk/tee/1792943273_uv.log。
随后以`uv run --offline --no-sync pyright --outputjson`显式列七个审查文件，结果62错误、0警告，4.661秒。
七文件诊断主要为既有Dataset动态属性和train历史返回类型；新增测试第250行有明确新增错误，详见下文。
rtk包装会转换JSON展示，首次管道解析未成功；改为直接uv输出JSON后读取摘要，以上七文件统计来自成功命令。
lint: {passed: false, errors: 1, scope_diff_passed: true}
typecheck: {passed: false, errors: 769, seven_files_errors: 62, confirmed_new_errors: 1}
test: {passed: false, total: 100, failures: 1, errors: 2, scope_and_data_regression_passed: 91}
tdd_check: {passed: true, reason: "三项red_passed/green_passed全部true，记录有预期RED断言及GREEN计数；独立运行再次确认GREEN"}
TDD依据：TDD_VERIFICATION.md:14-40；T01 RED=6断言失败，T02 RED=2断言失败，T03有效RED=25断言失败。
T03早期替身AttributeError没有计作有效RED；本轮不回退源码重演RED，只审核原记录与当前GREEN。

## 旧失败的独立因果核验

使用git show HEAD:train.py读取源码，在内存新建types.ModuleType并exec，替换sys.modules['train']后运行零售9项。
没有checkout、覆盖、删除源码或创建基线源码文件；使用当前未修改的config/defaults.py与零售测试。
HEAD内存基线同样产生1失败、2错误，证明这三项并非本次main日期改动造成。
基线日志：C:/Users/yanwen/AppData/Local/rtk/tee/1792943296_uv.log。
两个cfg={}用例在HEAD:train.py:247也因缺CNNTransformerConfig报KeyError，尚未执行到main日期装配。
第三项在零售测试:75期待cs_rank=False，而HEAD默认CS_RANK=True；MKT_FACTORS也为True，:76旧期待同样过时但被:75遮挡。
`git diff HEAD -- training/trainer.py config/defaults.py tests/unit/training/test_training_retail_wrapper.py`无输出。
因此全仓ruff的I001和上述零售三项均为HEAD已有问题；不能将它们称为新增回归，也不能将失败命令记为PASS。

## all_issues与具体阻塞

all_issues:
- severity: MEDIUM
  file: tests/unit/scripts/test_eval_preprocessing.py:250
  description: 新增类型回归；run_cfg在248行由单一字典值推断为dict[str, dict[str, Unknown]]，250行写入LABEL_MODE字符串触发reportArgumentType。
  suggestion: 显式标注该混合配置字典的合适类型，例如沿用项目dict注解；再复验七文件pyright，不能仅看unittest与ruff。
- severity: MEDIUM
  file: training/trainer.py:1
  description: HEAD既有I001导致全仓ruff失败；指定七文件ruff通过。
  suggestion: 交主代理单列历史导入排序问题；本只读审查不修改。
- severity: MEDIUM
  file: train.py:247
  description: 零售两个空cfg单测触发KeyError，HEAD内存基线精确复现；并非本次日期修复引入。
  suggestion: 后续按helper输入契约决定修正测试初始化或helper行为，不能为本任务随意补默认配置。
- severity: MEDIUM
  file: tests/unit/training/test_training_retail_wrapper.py:75
  description: HEAD默认cs/mkt为True，但旧测试均期待False；实测先在cs断言失败。
  suggestion: 后续按当前默认契约更新或显式关闭两个开关；不将其计为本次新增回归。
- severity: MEDIUM
  file: data/dataset.py:262
  description: 全仓pyright769错误、七文件62错误，含既有动态groups/index/num_features属性、五元素返回类型及train历史类型问题。
  suggestion: 将新增第250行问题优先收敛，其余按静态基线另排；本轮未对全仓类型错误逐项重跑HEAD，不声称769项全部为旧错误。

新增阻塞明确为测试第250行类型错误。行为修复与七关卡未发现新增HIGH问题，仍因三项验证不全通过给整体FAIL。
仅MEDIUM审查问题不单独否决，但lint/typecheck/test任一验证失败即整体FAIL，历史来源并不自动豁免验证。
不进行fix轮次；retry_count=0，未写MISTAKES.md，不修历史问题。

## 结论边界

pipeline仍硬编码horizon=5（run_eval_pipeline.py:235），且未透传cs/mkt；它们在计划中明确列为范围外，不随LABEL_MODE修复宣称完成。
日期工厂收紧会拒绝无界训练加验证的旧调用；合法开放外端点仍通过。这是明确契约变更，不伪装为全面兼容。
旧no_val模型、旧预测真值和2026-01至08探索样本不因本次修复恢复独立样本资格；未重新评估收益。
审查结束git状态保持相同文件集合；共享工作区其他代理修改不归因本轮，仅本任务报告由本轮写入。
主代理应据本报告处理新增类型阻塞及历史失败的范围决策；本轮不询问用户、不自动修复。
