# 训练日期与评估标签契约修复计划

## 目标（Goal）
仅规划：修复评估标签模式遗漏、无验证训练越过日期边界、训练/验证日期重叠未拒绝三类问题。
状态：规划完成，源码和测试均未修改，测试未运行；可交 Generator 执行下述确定范围。
遵循 cnn-harness/quant-model 的分析流程；用户要求优先：不询问、不提交推送删除、不改记忆、每次写入不超过50行。
任务目录：C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness/。

## 架构（Architecture）
调用链：train.parse_args → apply_args_to_config → build_parquet_data_config → ParquetDataset.create_dataloaders → reader 时间过滤 → Dataset 标签与窗口。
评估链：eval_bins_mapping.load_eval_preprocessing → build_val_loader；run_eval_pipeline.load_checkpoint_config → run_inference → Dataset → 预测缓存。
已读：根 AGENTS、data/AGENTS、training/AGENTS、docs/AGENTS、README_TRAINING_CHAIN、per_code_normalization_spec；未找到 MISTAKES.md。
目录扫描未发现 scripts/、tests/、config/ 模块 AGENTS；不涉及模型结构，无需新增模型或修改 ModelConfig。
技能旧路径 main_parquet/data.parquet_dataset/models.model2 已过时，实施以 train.py/data.dataset 和当前根规范为准。
归一化契约：训练 fit，验证复用训练 scaler/state；relative 无状态；context 可入窗口但不可作标签日。
维度保持 Dataset 实测派生，F53/F80 取决于 cs/mkt 开关；本任务不改分组、特征、horizon、bins 或 forward 接口。

## 证据与重复检测（Impact）
| 编号 | 当前证据（仓库相对路径:行） | 结论 |
|---|---|---|
| E1 | train.py:271-298，尤其282 | 已有 LABEL_MODE→label_mode 正确透传，不重复造训练配置工厂 |
| E2 | scripts/eval_bins_mapping.py:260-284 | build_val_loader 读 run_cfg 的 cs/mkt，却未传 label_mode |
| E3 | scripts/run_eval_pipeline.py:209、232-247 | run_inference 已加载 run_cfg，Dataset 未传 label_mode |
| E4 | data/dataset.py:107、168-169 | 默认 absolute；支持 absolute/excess/crash_conditioned，非法值已有统一校验 |
| E5 | train.py:437-452 | no_val 将训练和验证日期全部清空；传给工厂的训练区间变成无界 |
| E6 | data/dataset.py:389-449 | 工厂先构建训练集，再按任一验证边界非空建验证集，无日期顺序或交叉检查 |
| E7 | data/reader.py:87-102 | 标签区间首尾使用 >=、<=，同日端点属于交叠；输入 context 是另一个概念 |
| E8 | data/dataset.py:254-275 | excess 改写 future_ret/discrete；修复会改变真值和评估指标，不能沿用旧真值缓存 |

搜索范围：scripts 全部 Python 构造点、data/training/config 主链、tests Python、docs/agent Markdown。
共5处 scripts 构造点：eval_bins_mapping 1、run_eval_pipeline 2、eval_retail_predict 1、multi_seed_train 1；均未传 label_mode。
pipeline.build_scaler:169 是训练 scaler 拟合分支，不是预测评估真值入口，本轮不改。
multi_seed_train.run_single_seed:110-125 同样漏传，但属独立训练入口；记录后交主代理另排，不扩大最小修复。
eval_retail_predict.main:129-152 漏传且将 create_dataloaders 返回的训练 loader 用作推理；涉及独立链路，本轮不改。
docs/agent 命中仅 handoff-3070-training.md 的标签实验记录，未找到这三项修复的既有任务。
tests 未搜索到 create_dataloaders 调用、no_val 回归或训练/验证区间校验测试；未发现可直接复用的生产日期切分校验器。

## 关键决策（KeyDecisions）
评估构造点直接增加 label_mode=run_cfg.get("LABEL_MODE", "absolute")；保留旧 checkpoint 缺键回退。
不新增重复 resolver，不从当前全局默认猜旧 checkpoint 标签模式；非法值交 Dataset 现有校验。
no_val 仅关闭验证 loader，训练起止日期始终保持配置值；默认训练区间也保留，不能隐式全数据训练。
日期防线放在 create_dataloaders 的首个 Dataset 构造之前，所有调用者共享，使用 ValueError 而非可被 -O 关闭的 assert。
拟定日期规则：解析非空边界（复用 pandas 日期解析）；各区间 start<=end，非法日期/NaT 明确拒绝。
验证启用（任一验证端点非空）时要求 train_end 与 val_start 明确存在且 train_end<val_start；其余外端点可为 None。
因此无界训练+验证、缺验证起点、同日相接、反向/包含/部分交叠均拒绝；无验证时允许无界训练。
这是一项有意收紧的 API 契约：无法证明验证晚于训练的调用必须先报错，绝不以全 parquet 试算边界。
不对 context 历史输入断言不相交，不机械添加 horizon+1 自然日 embargo；标签未来端点保持原算法截断。

## 任务拆解（TaskDecomposition）
| task_id | 名称与描述 | files / 函数 | dep | accept |
|---|---|---|---|---|
| T01 | 两个主评估入口透传 checkpoint 标签模式 | scripts/eval_bins_mapping.py::build_val_loader；scripts/run_eval_pipeline.py::run_inference；tests/unit/scripts/test_eval_preprocessing.py | 无 | excess/absolute/crash_conditioned 原样传入；缺键 absolute；scaler 复用不变 |
| T02 | no_val 保留训练日期 | train.py::main 日期装配；tests/unit/test_train_metadata.py | 无 | 自定义及默认训练日期不丢；val_start/val_end=None；普通验证模式日期不变 |
| T03 | 数据工厂前置校验日期切分 | data/dataset.py::ParquetDataset.create_dataloaders（必要时本模块私有小函数）；新增 tests/unit/data/test_dataset_date_ranges.py | T02 | 非法/逆序/重叠/不可证明切分在 Dataset/读数/fit 前拒绝；合法及无验证调用通过 |
| T04 | 定向复核与证据交付 | 本任务三件套中的状态与命令记录 | T01、T02、T03 | 单文件 RED/GREEN、定向回归及 lint 证据；无训练/GPU扫描，无源码范围扩张 |

最小生产修改严格为4文件：两个评估脚本、train.py、data/dataset.py；测试扩展2文件、新增1文件。
估计生产改动20～55行、测试约100～180行，以契约覆盖为准；每次写入仍须<=50行。
T02 可把日期装配提为 train.py 内小函数供单元验证，但必须证明 main 使用该结果；不为测试重构整个 main。
T03 测试可通过 patch Dataset 构造/DataLoader 检查提前拒绝与 scaler 对象复用，不读大型 parquet。

## 现有测试与推荐定向验证
可复用 TestBuildValLoader.test_loader_relative_passes_stateless_scaler（test_eval_preprocessing.py:239-256），增加标签模式参数矩阵。
pipeline 当前测试只覆盖 mode/scope/维度解析，需新增 run_inference 配置捕获测试；mock 模型、checkpoint、CUDA 检测、DataLoader 与输出，禁止真推理。
test_train_metadata.py::TestTrainCLIT06 可扩展日期装配；现有测试不覆盖 main 的 no_val 行为。
test_training_retail_wrapper.py:66-76 已验证训练配置 helper 的部分字段，可作回归；无需复制工厂实现。
test_data_excess_labels.py 已覆盖手算、context 排除、缺省 absolute 与缓存模式隔离；无需再写 excess 算法。
test_context_warmup_windows.py 已覆盖首日标签、context 不是标签、窗口无未来输入；守住合法历史输入。
以下仅推荐给 Generator/Quality Gate，本轮没有执行：
`uv run --project . python -u -m unittest tests.unit.scripts.test_eval_preprocessing`
`uv run --project . python -u -m unittest tests.unit.test_train_metadata`
`uv run --project . python -u -m unittest tests.unit.data.test_dataset_date_ranges`
`uv run --project . python -u -m unittest tests.unit.data.test_data_excess_labels tests.unit.data.test_context_warmup_windows tests.unit.data.test_dataset_cache tests.unit.training.test_training_retail_wrapper`
`uv run ruff check scripts/eval_bins_mapping.py scripts/run_eval_pipeline.py train.py data/dataset.py tests/unit/scripts/test_eval_preprocessing.py tests/unit/test_train_metadata.py tests/unit/data/test_dataset_date_ranges.py`
运行时临时目录/缓存/日志必须显式落在任务目录下；旧测试使用 tempfile 的，执行前设置 TEMP/TMP 至该根，并在 Python 进程启动前生效。

## 风险与边界
工程风险中等，历史证据污染风险高：no_val 历史 checkpoint 可能已训练到评估期，修复不能追溯恢复独立性，主代理审计后判断是否需重训。
标签修正不会证明收益；旧预测缓存只读保留，后续评估另命名生成并记录 label_mode；不自动重算或覆盖历史产物。
pipeline.run_inference:235 硬编码 horizon=5，与主默认H10不一致；零售同有H5。必须单列后续任务，当前不可宣称完整评估契约已修好。
pipeline 还未透传 cs/mkt，build_scaler 允许缺失时重新拟合；均为本轮范围外风险，不顺手修复。
新日期防线会暴露 eval_retail_predict 的无界训练+验证调用；这是已知兼容性风险，须主代理安排修该入口后再使用。
禁止修改 scripts/audit_walkforward_execution.py、tests/unit/backtest/test_cnn_adapter_contract.py 和两份 memory 已有修改。
不涉及运行器、引擎、W4恢复、长训练、GPU、研究扫描、提交推送删除或 memory 写入；遇范围外阻塞返回 blocked 给主代理。
