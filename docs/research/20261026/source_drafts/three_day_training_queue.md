# 三天研究：训练运营预检与冻结队列

- 主编排：ses_e8c8206c4ffeO3iBdPVMl7qhfb；截止北京时间 2026-10-28 23:25。
- 本次仅只读项目与产物，写本会话临时脚本/报告；未启动训练、未构建真实数据集、未修改生产代码或记忆。
- 结论：W3检查点能受限安全加载、模型/AdamW/调度器状态可载入；不能精确恢复中断点。推荐获GPU许可后从seed42完整重跑W3，W1/W2不重训。
- 所有历史窗口均为研究证据；历史再切分不产生干净样本外，2026-01～08已探索，2026-09后当前本地parquet无数据。

## 1. W3恢复证据与边界

- 文件：`logs/relative/run_20261025_223839/best_model.pth`，44,818,257字节。
- SHA256：`bed0de2d4b523aa554e2dbdee76508414b4f843e59aaaab9691e7e2608e04525`。
- 加载使用`torch.load(..., map_location='cpu', weights_only=True)`；无不受限回退，无执行checkpoint中代码，无张量内容打印。
- 顶层仅`model/optimizer/scheduler/epoch/config`；`epoch=0`是零起点，对应完成的第1轮，不能称第2轮最佳。
- 第1轮22:47:55验证损失0.058208后保存；第2轮22:55:40 counter=1未保存；最后日志23:01:12是第3轮第4000/5424批。
- AdamW状态225份，全部step=5424，正好一轮；lr=0.0001，initial_lr=0.0003，betas=(0.9,0.999)，eps=1e-8，weight_decay=1e-5。
- 调度器LambdaLR（配置CosineWarmup），last_epoch=0，_step_count=1，base_lrs=[0.0003]，_last_lr=[0.0001]，lr_lambdas=[null]。
- 调度函数本身未序列化；必须由原配置重新建立30轮/3轮预热的同一函数，再载入调度与优化器状态。
- checkpoint.config与同目录config.json所核对训练字段无差异；真实TRAIN_END=2021-06-30，VAL=2021H2。旧TEST_START=2026-01-01只是预留元数据，训练入口没有测试推理。
- 保存发生于验证后、scheduler.step前（trainer.py早停调用后才更新调度）；要从该保存点继续第2轮，须先补做一次当轮调度，lr变为0.0002，不能重复第1轮学习率。
- 未保存Python/NumPy/Torch CPU/CUDA RNG、DataLoader采样器状态、早停状态、训练历史/global_step，亦无第2轮最新权重及第3轮批进度。
- 第1轮边界的早停最优值可由日志补入且counter=0；不能把第2轮counter=1配到第1轮权重上，也不能把已丢失两轮训练伪装成完整续训。
- 现有train.py无resume参数，Trainer.train固定range(EPOCHS)，load_model_state只装模型；直接重跑train.py不会自动续训。
- CPU微测已严格载入模型、225份优化器状态与调度器，补调度后lr=0.0002；2×53×60合成输入输出logits为2×52且有限。此测试不证明CUDA或逐位等价。
- 允许的结论：可评估第1轮最佳模型；工程另实现入口后可作为“从最佳点分支续训”，但不等于恢复第3轮中断。首选完整重跑，避免额外恢复接口阻塞。

## 2. W1/W2真实超参与早停核实

|项目|W1|W2|W3中断运行|
|---|---|---|---|
|实际run|run_20261025_203117|run_20261025_210454|run_20261025_223839|
|训练|2013-01-01～2020-06-30|2013-01-01～2020-12-31|2013-01-01～2021-06-30|
|早停验证|2020H2|2021H1|2021H2|
|训练/验证样本数|4,630,986 / 421,577|5,092,076 / 419,259|5,553,385 / 475,386|
|最佳保存|第1轮，epoch=0|第1轮，epoch=0|第1轮，epoch=0|
|最佳val loss日志|0.050513|0.053025|0.058208|
|最终状态|第4轮后counter=3早停|第4轮后counter=3早停|第3轮第4000批截断|
|最佳点优化器步数|4523|4973|5424|

- 三者日期字段之外，所核对超参一致：excess、relative、F53、H10、seq60、seed42、batch1024、workers4、epochs30、patience3、AdamW lr3e-4/wd1e-5、CosineWarmup预热3轮。
- EMDLoss p=2、label_smoothing=true、smooth_eps=0.1；纯分类，dual/pure_reg/gate/sample_weight均关闭；cs_rank/mkt_factors均关闭。
- 模型：CNN通道128，d_model256，8头，4层，kernels=[1,3,5,7,10]，dropout0.3，52类；完整冻结字段见JSON。
- 早停按验证EMD loss，delta=0、patience=3；本队列保留该原始基线，不在看测试后改用RankIC选模。任何新选模规则须单列预注册实验。
- 当前默认patience10/epochs50/batch256/F80/absolute与实际运行不同，不能省略覆盖参数；当前默认scheduler恰好相同，也显式固定。
- W1早先run_191130及run_202012均无best_model，不能冒充已完成运行；W1/W2推理报告明确指向表中的实际checkpoint。

## 3. 冻结半年expanding窗口

训练起点一律2013-01-01；训练终点为验证半年前一日。表内是日历边界，实际标签日按每股有效交易行计算，不机械减11个自然日。

|窗口|训练截断|固定早停验证半年|测试/信号目标区间|队列状态|
|---|---|---|---|---|
|W1 2021H1|2020-06-30|2020-07-01～2020-12-31|2021-01-01～2021-06-30|已有模型，复用|
|W2 2021H2|2020-12-31|2021-01-01～2021-06-30|2021-07-01～2021-12-31|已有模型，复用|
|W3 2022H1|2021-06-30|2021-07-01～2021-12-31|2022-01-01～2022-06-30|首要，获许可完整重跑|
|W4 2022H2|2021-12-31|2022-01-01～2022-06-30|2022-07-01～2022-12-31|第二优先|
|W5 2023H1|2022-06-30|2022-07-01～2022-12-31|2023-01-01～2023-06-30|随后|
|W6 2023H2|2022-12-31|2023-01-01～2023-06-30|2023-07-01～2023-12-31|随后|
|W7 2024H1|2023-06-30|2023-07-01～2023-12-31|2024-01-01～2024-06-30|跨市场扩展|
|W8 2024H2|2023-12-31|2024-01-01～2024-06-30|2024-07-01～2024-12-31|跨市场扩展|
|W9 2025H1|2024-06-30|2024-07-01～2024-12-31|2025-01-01～2025-06-30|预算允许|
|W10 2025H2|2024-12-31|2025-01-01～2025-06-30|2025-07-01～2025-12-31|预算允许|
|W11 2026H1|2025-06-30|2025-07-01～2025-12-31|2026-01-01～2026-06-30|已探索区间，先核对Round4能否复用|
|W12 2026H2|2025-12-31|2026-01-01～2026-06-30|2026-07-01～2026-12-31|仅到08-31，不能验收完整半年|

- 训练、验证的标签日及标签终点不越界：reader先按各自end_date截断，再逐code算open[t+11]/open[t+1]-1；末11条交易行自然无标签。
- relative验证保留start之前最多59条历史交易行作输入上下文；这些输入与训练历史重叠合理，但不产生验证标签日，也不把验证未来价格带回训练。
- 本地合成40条open验证：H10最后11条NaN；未全表扫描逐股真实边界，实际最后标签日期/样本清单须由各次运行导出验证。
- 评估当前scripts/eval_bins_mapping.py默认torch.cuda.is_available()时选cuda并构建数据；单次GPU占用轻于训练，但应在训练结束后串行运行，别与训练抢8GiB显存。
- 训练/验证保留excess标签，按当日可形成有效标签的截面减均值；不把跨期未来数据用于较早集合。
- 测试的“评分标签集”仍可按end_date自然purge，但交易“信号集”必须覆盖整个半年，包括末11个交易日。当前依赖有标签ParquetDataset的评估入口不能满足此要求。
- 无标签推理须只取截至signal_date的60行输入，不要求未来open或未来标签；不能通过延长数据截止日让未来可得性决定当时股票池。
- 旧D:/tmp/opencode/run_rolling_walkforward.py的WINDOWS前几项训练/验证重叠、缺2025H2且最后2026段为8个月；禁止直接运行。实际W1/W2/W3配置已经独立核对，无该日期重叠。

## 4. 待GPU许可的推荐训练命令

从仓库根执行；这是全新W3基线运行，不是resume。epochs30固定影响余弦曲线，不能为省预算改成4轮；靠patience3自然结束。

```powershell
uv run --no-sync --project . python train.py --parquet C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet --normalize relative --label_mode excess --no-cs_rank --no-mkt_factors --horizon 10 --seq_len 60 --seed 42 --batch_size 1024 --num_workers 4 --epochs 30 --patience 3 --lr 0.0003 --scheduler CosineWarmup --warmup_epochs 3 --featurenum 53 --model cnn_transformer --no-sample_weight --no-gate_head --train_start 2013-01-01 --train_end 2021-06-30 --val_start 2021-07-01 --val_end 2021-12-31 --test_start 2022-01-01 --test_end 2022-06-30
```

- 已用当前parse_args逐条验证12个窗口命令，未执行main；精确开关是`--no-mkt_factors`，不是文档中的`--no-mkt-factors`。
- 各窗口完整命令保存在three_day_training_windows.json。CLI未暴露wd/EMD/架构参数，启动前必须与冻结JSON逐项比对默认值，工程改动后重新核对。
- 每个窗口seed42全新初始化，不把前一窗口权重warm-start当成独立重训；唯一允许改变的是日期与已声明资源参数。
- train.py只训练/验证；test_start/end仅记元数据，不代表已经完成测试或信号覆盖。
- 后续诊断推理可用`python -m scripts.eval_bins_mapping --checkpoint <本轮明确路径> --parquet <同一文件> --val_start <测试起点> --val_end <测试终点> --horizon 10 --seq_len 60 --max_codes 0 --batch_size 1024 --num_workers 0 --seed 42 --device cuda --preds_cache <本轮专属npz> --out <本轮专属json>`。
- 上述推理只产有标签诊断子集，末期信号缺失；完整回测必须等工程无标签接口。禁止自动选择“最新run目录”，须记录本轮确切输出目录、checkpoint SHA和配置。

## 5. 资源预算与执行队列

- 现场修正：总内存约15.94GiB，2026-10-25 23:42空闲约9.97GiB；RTX 3070 8GiB。先前nvidia-smi观测为显存已用1166MiB、GPU利用16%，该观测有时点差异；启动前再次看GPU且不据此取消主会话许可门。
- parquet本地C盘文件4,279,965,200字节（约3.99GiB），12,254,385行、70列、12 row groups。只读了文件元数据，没有扫描行。优先此本地副本，避免网络盘。
- Windows num_workers=4是W1/W2/W3已跑通的基线配置，推荐首窗保持原样；样本/特征完整进入Dataset，特征缓存也会有内存映射和loader预取开销，4个worker可能复制/预取batch，空闲9.97GiB不等于可保证峰值安全。
- 训练期唯一一个完整ParquetDataset构建，不并行推理、回测、盘点大扫描或另一窗口构建；确认其他会话没有在读同一全表，再启动。优先命中现有同身份feature cache；冷构建会额外占I/O、CPU及内存。
- 主机当前报告“内存并发受限”；把空闲约10GiB当硬预算，保留系统余量。启动监看进程工作集/提交量、系统可用内存、pagefile、GPU显存；持续低于约2GiB可用或内存提交逼近系统上限，立即停本窗口并报告，不同时起第二训练。
- 经验计时：W3已跑两整轮及第三轮4000/5424批；从日志起训练到第三轮末累计约22分钟，第一轮约9分钟，第二轮约7分45秒。W1/W2每轮约6分20秒至7分钟，早停均4轮完成。
- W3数据量比W2训练集多约9%，验证集多约13%；按W3现有epoch速率，预计3～4个epoch约28～36分钟训练主体，数据构建/模型推理、混淆矩阵与写盘预留10～20分钟，总计约40～55分钟。此为已观察吞吐估算，不含冷cache构建延迟，且一次运行很短不足以定稳态。
- 第一个窗口只跑W3 2022H1并完成checkpoint/配置/log及推理前置盘点；只在结束清理资源占用、主会话检查证据后再排W4。后续顺序W4 2022H2、W5 2023H1……不并发。
- 若W3因资源问题不得不将workers改为0：先记录变更由现场内存约束触发，不改batch/优化器/epoch/scheduler；worker数可能改变DataLoader随机数消耗次序和每epoch吞吐，不能声称与workers4逐位等价。必须单独记录命令、Torch/DataLoader版本与新run路径，结果仍归原超参下的操作偏差副本。
- 推理使用num_workers=0保持小内存；不与模型训练并行。

## 6. 启动前阻塞与研究边界

1. GPU单窗启动许可：由主会话发放；本会话尚未启动训练。
2. 数据扫描互斥：资产盘点/工程须确认没有同时构建全量dataset；特别禁止多个ParquetDataset并发。
3. 日期层：需要工程date-range改动合并到共享工作区后复核。当前working tree中train.py、data/dataset.py、scripts/eval_bins_mapping.py等存在其他会话修改；本会话不编辑这些文件。此前CPU窗口命令解析基于当前可见CLI通过，但在共享代码继续变动后应重跑仅CLI解析。
4. 推理层：完整半年回测需signal-only无标签推理以覆盖测试期末11个交易日。现有eval_bins_mapping基于带标签ParquetDataset，不满足完整信号覆盖；工程会话已处理评估标签口径透传，但不因此认为末期信号已解决。
5. 2021H1/H2已训练并用于过往研究，不可算作独立验收。2022H1是最早待扩展窗口；2026H2本地只到2026-08-31，不足半年。
6. 目标仍是成本后净收益非负且跑赢沪深300，且实际持仓≤10；单看训练损失、RankIC或信号统计不能宣布过关。

## 7. 本次可复核产物与检查

- `three_day_training_queue.md`：本报告。
- `three_day_training_windows.json`：12个窗口、精确训练命令和冻结超参。
- `three_day_checkpoint_probe.json`：受限加载的checkpoint元数据摘要；不含checkpoint张量。
- `three_day_training_cpu_preflight.json`：CPU模型/优化器/调度器/标签边界契约结果。
- 辅助脚本`three_day_checkpoint_probe.py`、`three_day_training_windows.py`、`three_day_training_cpu_preflight.py`仅位于系统临时目录，每个文件不超过50行；未改仓库。
- 已执行：CPU weights_only检查；checkpoint模型strict load、AdamW/scheduler state load、微型前向；40行合成H10边界；12窗口命令解析；Parquet只读元数据检查。
- 未执行：真实Parquet扫描/构建、全量推理、CUDA微基准、长训练、pytest/compile/lint、正式回测。理由是避免与资产扫描/工程争用内存并遵守GPU许可门。
- 工作区git status显示其它会话已有改动：`.opencode/memory/{MEMORY,HISTORY}.md`、`train.py`、`data/dataset.py`、`scripts/audit_walkforward_execution.py`、`scripts/eval_bins_mapping.py`、`scripts/run_eval_pipeline.py`及若干测试；均未由本会话编辑。

## 8. W3单窗执行记录（2026-10-26 00:00中止）

- 启动门核验：资产盘点`ses_e8c54700affe7HRtrHRvJJIFv3`与质量门`ses_e8c3e8c0cffelHa3d2dlh7jswg`均idle；七关PASS（`tests.unit.scripts.test_eval_preprocessing`+`test_train_metadata`+`tests.unit.data.test_dataset_date_ranges`，Ran 50 OK，无必须修复）；工程会话busy但声明日期/标签文件冻结且无CPU/GPU任务；无Python/uv数据进程；GPU仅图形界面进程（显存约1.16GiB）；空闲内存9.62GiB。工程会话当前模型仍显示GPT-6.1 Sol为历史会话身份，本会话已确认按用户新约束不再向其派发任务，后续跟踪用DeepSeek。
- 实际执行（用户要求报告证据）：uv launcher PID 3616 → uv python PID 22656 → 训练主进程 PID 19344（工作集峰值约2.2GiB）+ 4个DataLoader worker PID 20360/6780/18128/4504（各约1.9GiB）。新run目录`logs/relative/run_20261025_235817`（旧产物未覆盖，旧W3 run_223839保留）。独有日志：`C:/Users/yanwen/AppData/Local/Temp/opencode/w3_2022H1_20261025_235808.stdout.log`（202行：配置回显+缓存命中+训练循环）与`w3_2022H1_20261025_235808.stderr.log`（tqdm+torch告警，无异常）。
- 启动证据：23:58:17日志初始化→23:58:21数据集就绪（训练5,553,385窗/验证475,386窗，均命中同身份feature cache，标签分布52类打印）→23:58:24训练开始（参数量3,698,485，`[batch,53,60]→52类`）→23:59:14首个batch日志（第100/5424批，Loss 0.0489）→最后00:00:07第700/5424批（stderr tqdm至764批，约14%）。运行配置与冻结超参逐项一致（excess/relative/F53/H10/seed42/batch1024/workers4/epochs30/patience3/lr3e-4/CosineWarmup预热3）。config.json（6,683字节）与training.log已落盘run目录。
- **内存中止**：约00:00:13观测系统空闲内存降至约2.20GiB（启动前9.62→训练中5.53→2.20），触及用户设定的约2GiB停止线；训练主进程+4 worker合计工作集约7.7GiB。按约执行`taskkill /PID 19344 /T /F`，确认uv/python进程树全部退出；中止后空闲内存8.51GiB、GPU回落1.2GiB。未到首个验证保存点（第1轮未完成），**未产生best_model.pth**；无OOM异常，属预防性停止。
- 状态：`stopped_for_memory_safety`；完整清单见`w3_2022H1_20261025_235817_manifest.json`（含run目录、PID树、资源观测序列、stdout/stderr/config/training.log的SHA256、数据parquet SHA256 `9125DA…0741`、git head `116cb31`+dirty文件清单及关键源文件SHA256）。本次属历史expanding诊断，非独立样本外验收。
- 遗留与建议（待主会话决策，本会话不自行重试/改参）：内存约束下可选路径为（a）`--num_workers 0`重跑（记录吞吐与随机性偏差副本，per §5约定）；（b）评估缓存root迁至D盘或关闭cache降低驻留；（c）等待其他会话释放内存时段串行重试原配置。无论哪种，均须主会话重新发放许可后执行；W4继续冻结。
