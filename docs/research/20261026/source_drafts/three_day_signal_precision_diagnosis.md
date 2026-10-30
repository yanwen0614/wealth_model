# W1 信号差异：张量与推理精度诊断

## 结论

差异由推理执行精度造成的证据很强：旧评估在 CUDA 上使用默认 `cudnn.allow_tf32=True`，冻结信号生成器在 CPU 上以 FP32 推理。同一 checkpoint 和完全相同的输入张量，CPU 预测与旧缓存不同；CUDA 且 `matmul.allow_tf32=False, cudnn.allow_tf32=True` 则在两代码全期 214 个样本上复现旧缓存，最大 `exp_ret` 差仅 `8.35e-9`。本诊断没有修改冻结生成器或调整比较容差。

## 证据

- 样本覆盖：`000001.SZ` 与 `600519.SH`，2021-01-04 至 2021-06-15 的全部 214 个旧缓存样本；投影数据集 F=53、窗口 53×60。
- 214/214 个样本的旧 `ParquetDataset` 窗口与冻结生成器窗口逐元素完全相同（最大张量差 0）。两路输入在 CPU 上推理后，logits、概率和 `exp_ret` 也逐元素完全相同。
- CPU FP32 对旧缓存 `exp_ret`：最大差 `2.3867e-5`，平均差 `5.6083e-6`，214 个样本中 193 个超过 `1e-6`。
- CUDA，TF32 关闭（matmul=False、cuDNN=False）：最大差 `2.3886e-5`，平均差 `5.6102e-6`，193 个超过 `1e-6`。
- CUDA，matmul TF32 关闭、cuDNN TF32 开启：最大差 `8.3458e-9`，平均差 `2.0549e-9`，0 个超过 `1e-6`。
- 另两组 TF32 设置均不能复现缓存：matmul=True/cuDNN=False 最大差 `2.4536e-5`；两者皆 True 最大差 `2.2730e-6`。
- 当前旧评估入口没有显式设置这两个后端开关；检查环境默认值为 matmul TF32=False、cuDNN TF32=True，与复现旧缓存的组合一致。

## 判断范围

这足以定位两代码投影上 CPU 与旧 CUDA 评估缓存的差异来源，并证明没有发现特征张量错位。此前全量比较的 419,259 行中 367,304 行超过 `1e-6`；这里没有逐行重推全量数据，因此不把小投影结果冒充全量逐行复验。`1e-6` 是比较口径，不应据本诊断放宽。

## 产物与身份

- 逐样本证据：`C:/Users/yanwen/AppData/Local/Temp/opencode/precision/precision_probe.json`
- 只读诊断脚本：`C:/Users/yanwen/AppData/Local/Temp/opencode/precision/precision_probe.py`
- checkpoint SHA256：`8e2c79b1965970d8b768efdbf52e40d50bf4929a6996467d6bc0f44d451466dc`
- 投影源文件 SHA256：`9125da792bb906eb3d31a82649efa4358274fec2b59f1dc911f7c71871910741`
- 运行时：PyTorch `2.12.0+cu130`，NVIDIA GeForce RTX 3070。
