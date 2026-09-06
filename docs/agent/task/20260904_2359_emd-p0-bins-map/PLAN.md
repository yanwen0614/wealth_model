# 20260904_2359_emd-p0-bins-map Implementation Plan

> Generated: 2026-09-04 23:59
> Task Dir: docs/agent/task/20260904_2359_emd-p0-bins-map/

## Goal

修复 EMDLoss 设备迁移 P0 缺陷，并以全量分位重算 bins 为基础完成 52→11 类映射评估。

## Architecture

criterion 只改损失内部状态管理（plain Tensor → `register_buffer`，删除自定义 `to`，沿用 `nn.Module.to`，对标 `models/cnn_transformer/model.py:23`）；data 侧新增离线脚本全量扫描 parquet 求 `future_ret` 分位点，不碰 `ParquetDataset` 主链路；train 侧仅以外部 bins 注入做 52/11 对比评估。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| smooth_weights 存放 | `register_buffer` | 普通 attribute + 自定义 `to(device)` | 跟随模型 `.to()`/state_dict，消除 CPU/CUDA matmul 错配 |
| 自定义 `to` | 删除 | 保留修复签名 | 覆盖 `nn.Module.to` 破坏语义，Trainer 已调 `criterion.to(device)` |
| bins 来源 | 离线脚本全量分位 | 硬编码 linspace | 当前均匀 bins 尾部类 <0.1%，分位才能均衡 |
| 52→11 方式 | 评估期映射矩阵，不改训练默认 | 直接改 num_classes=11 | 先量化后决策，避免一次性推翻 52 类链路 |

## Impact

| 模块 | 文件 | 操作(create/modify) | 风险等级 |
|------|------|--------------------|----------|
| criterion | criterion/emd_loss.py | modify | high |
| data | scripts/recompute_bins.py | create | low |
| train/eval | scripts/eval_bins_mapping.py | create | low |
| data | data/dataset.py | modify | medium |
| train | train.py | modify | medium |

## Task Decomposition

### T01: EMDLoss P0 修复
- **文件**: `criterion/emd_loss.py` (modify)
- **描述**: `smooth_weights` 改 `register_buffer`；删除自定义 `to()`；补设备语义注释；`_apply_label_smoothing` 保持 device 一致
- **依赖**: 无
- **预估行数**: +15/-20
- **验收标准**: `EMDLoss(52,smooth).to('cuda'/'cpu')` 后 weights 与 logits 同 device；forward `[B,52]->scalar` 可反向；smoke 不报 device 错
- **风险因子**: 自定义 `to` 签名覆盖导致 state_dict 丢失；CPU/GPU 跨设备 matmul

### T02: Step0 全量 bins 分位重算脚本
- **文件**: `scripts/recompute_bins.py` (create)，`data/dataset.py` (modify 读外部 bins)
- **描述**: 全量 parquet（is_trading 过滤，horizon=5）求 future_ret 分位点，输出 `logs/bins_quantile.json`；dataset 支持外部 bins 注入
- **依赖**: 无
- **预估行数**: +90
- **验收标准**: 输出 51 边界单调递增；`ParquetDataset(bins=新)` 标签分布尾类占比提升；复用 `PerCodeGroupedScaler` 不重 fit
- **风险因子**: 全表 11M 行内存（分块/pyarrow 列裁剪）；验证集 bins 必须与训练一致

### T03: Step1 52→11 映射评估
- **文件**: `scripts/eval_bins_mapping.py` (create)，`train.py` (modify 可选 num_classes 切换)
- **描述**: 构造 52→11 映射矩阵，对比类均衡度/acc/相邻-acc/EMD 值；`ModelConfig(num_classes)` 与 `EMDLoss(num_classes)` 联动校验 `[B,F,60]->[B,11]`
- **依赖**: T01, T02
- **预估行数**: +110
- **验收标准**: 输出对照表（52 vs 11 分布/指标）；11 类下 forward 形状断言通过；不默认改 52 训练链路
- **风险因子**: `training/metrics.py` 默认 num_classes=6 过时，评估时显式传参
