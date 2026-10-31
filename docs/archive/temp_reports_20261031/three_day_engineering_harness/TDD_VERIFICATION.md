# T01–T03 实现与真实验证记录

status: complete
task_id: T01-T03
quality_gate: 待主代理独立派遣；本记录不是质量门通过结论
blocked_reason: 无范围内实现阻塞；范围外零售回归失败待主代理处理

所有 unittest 均单文件启动，未运行全量套件、真实训练或 GPU 推理。
命令工作目录：D:/code/cnn_full_20260905/cnn。
每次 unittest 进程启动前使用以下 PowerShell 前缀：
`$env:CUDA_VISIBLE_DEVICES=''; $env:TEMP='C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_engineering_harness'; $env:TMP=$env:TEMP;`
下列命令均为真实执行，rtk 仅包装终端输出。

| 任务 | 实际命令 | RED | GREEN |
|---|---|---|---|
| T01 | `rtk uv run --project . python -u -m unittest tests.unit.scripts.test_eval_preprocessing` | FAILED (failures=6)：两入口 excess/crash_conditioned/非法值被默认为 absolute | Ran 29 tests in 0.205s；OK |
| T02 | `rtk uv run --project . python -u -m unittest tests.unit.test_train_metadata` | FAILED (failures=2)：None != 2013-01-01；None != 2019-01-01 | Ran 19 tests in 2.072s；OK |
| T03 | `rtk uv run --project . python -u -m unittest tests.unit.data.test_dataset_date_ranges` | FAILED (failures=25)：ValueError not raised | Ran 2 tests in 0.041s；OK；lint修正后复验 0.035s，OK |

T03 首次试跑因测试替身缺少 index 出现25个 AttributeError，未计为有效 RED。
补全替身的长度/特征/scaler 属性后，先得到上表25个预期断言失败，再修改生产代码。
T01 保持缺键回退 absolute；非法值原样传入，继续由真实 Dataset 既有校验拒绝。
T02 直接调用 main，mock 日志与工厂，在工厂处停止；覆盖默认、自定义 no_val 及普通验证。
T03 两个测试方法包含25个拒绝子场景及5个合法子场景。
拒绝矩阵覆盖非法日期/NaT/空串/不可能日期、区间逆序、同日相接、交叠/包含/反向及缺必要边界。
成功矩阵覆盖单日合法区间、可省外端点、无验证无界/半有界训练、原样边界与 scaler 对象复用。
拒绝路径同时断言 Dataset 构造、reader、scaler.fit 和 DataLoader 调用为零。

```yaml
tdd_verification:
  - behavior: 两个评估入口透传检查点标签模式并保留缺键回退
    red_passed: true
    green_passed: true
  - behavior: no_val保留默认与自定义训练边界且普通验证不变
    red_passed: true
    green_passed: true
  - behavior: 数据工厂在构造及拟合前拒绝非法或不可证明的日期切分
    red_passed: true
    green_passed: true
```

定向回归真实命令与结果（均使用上文环境前缀）：

| 实际命令 | 结果 |
|---|---|
| `rtk uv run --project . python -u -m unittest tests.unit.data.test_data_excess_labels` | 10项，0.596s，OK |
| `rtk uv run --project . python -u -m unittest tests.unit.data.test_context_warmup_windows` | 7项，1.243s，OK |
| `rtk uv run --project . python -u -m unittest tests.unit.data.test_dataset_cache` | 24项，3.338s，OK |
| `rtk uv run --project . python -u -m unittest tests.unit.training.test_training_retail_wrapper` | 9项，1.128s；FAILED (failures=1, errors=2) |

零售失败证据：两个空 cfg={} 用例在 train.py:247 触发 KeyError: CNNTransformerConfig；
test_parquet_helper_passthrough 在第75行断言 cs_rank=False，但当前默认为True。
本轮 train.py 仅修改 main 的两个日期赋值；未修改上述 helper、默认配置或零售测试。
此失败没有被隐藏或顺手修复，交主代理判断质量门与另排任务。

静态检查实际命令：
`rtk uv run ruff check scripts/eval_bins_mapping.py scripts/run_eval_pipeline.py train.py data/dataset.py tests/unit/scripts/test_eval_preprocessing.py tests/unit/test_train_metadata.py tests/unit/data/test_dataset_date_ranges.py`
首次 C408 指向新增测试的 dict()；改为字面量后复验 All checks passed!。
`rtk git diff --check`：无输出，通过。
未运行 pyright，交独立质量门按本轮范围检查。

精确源码范围：4个生产文件、2个扩展测试、1个新测试：
- scripts/eval_bins_mapping.py：新增 label_mode 透传1行。
- scripts/run_eval_pipeline.py：新增 label_mode 透传1行。
- train.py：替换2行训练日期赋值，no_val 只关闭验证。
- data/dataset.py：工厂首个构造前新增30行日期防线，复用 pandas。
- tests/unit/scripts/test_eval_preprocessing.py：新增38行两入口参数矩阵。
- tests/unit/test_train_metadata.py：新增26行 main 日期回归。
- tests/unit/data/test_dataset_date_ranges.py：新增日期拒绝/成功矩阵测试。

风险与质量门建议：
- 工厂契约收紧；无界训练加验证、缺 val_start 等旧调用将明确报错，零售入口需另排。
- 日期检查拒绝有时区值，匹配当前无时区日线；不会推断数据内容或扫描 parquet。
- 不加 horizon 自然日 embargo；训练标签末端仍由 end_date 截断；context仍可作输入。
- 旧 no_val 模型及旧真值缓存独立性不会被修复追认；重算应新命名，不能覆盖旧证据。
- pipeline 的 H5、cs/mkt遗漏、缺 scaler 重拟合、多种子/零售漏传保持范围外。
- Quality Gate 应审查7文件最小diff、三项TDD、零IO拒绝、scaler复用及context/标签回归。
- 主代理另行处理新增NO-GO及运行器；本轮未修改审计、回测、模型、记忆，未提交推送。
