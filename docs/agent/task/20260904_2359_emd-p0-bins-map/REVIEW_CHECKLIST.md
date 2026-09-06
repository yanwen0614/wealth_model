# 审查清单 — 20260904_2359_emd-p0-bins-map

> 生成时间：2026-09-04 23:59

## 需求理解

P0 修 `criterion/emd_loss.py`（register_buffer + 删 `to` + 注释）+ Step0 全量 bins 分位重算 + Step1 52→11 映射评估。目标模块：criterion/emd_loss.py，data/dataset.py，train.py。

显式假设：
- A1：smooth_weights 必须随模型 `.to()` 迁移（Trainer 已调 `criterion.to(device)`，trainer.py:73）。
- A2：Step0 用全量 parquet + is_trading 过滤 + horizon=5 口径求分位（与 dataset 标签一致）。
- A3：Step1 只评估不切换默认 52 类链路；num_classes 切换仅评估脚本内进行。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| criterion | criterion/emd_loss.py | 修改 | buffer 化 + 删自定义 to |
| data | data/dataset.py | 修改 | 外部 bins 注入 |
| data | data/scaler.py | 复用 | PerCodeGroupedScaler 不动 |
| train | train.py | 修改 | BINS 外部加载 + num_classes 联动 |
| scripts | scripts/recompute_bins.py | 新增 | Step0 分位脚本 |
| scripts | scripts/eval_bins_mapping.py | 新增 | Step1 映射评估 |
| training | training/trainer.py | 间接 | 验证 criterion.to 兼容 |
| models | models/cnn_transformer/config.py | 间接 | ModelConfig num_classes 校验 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 |
|------------|---------|------|
| EMDLoss/emd_loss | 是（唯一） | criterion/emd_loss.py；training/custom_loss.py 已删 |
| register_buffer | 是（范例） | models/cnn_transformer/model.py:23（pe） |
| ParquetDataset/create_dataloaders | 是（唯一） | data/dataset.py |
| PerCodeGroupedScaler/scaler | 是（唯一） | data/scaler.py |
| BINS/bins/digitize | 是（默认值） | data/dataset.py:60，train.py:34；分位脚本不存在 |
| 52→11/mapping | 否 | 无映射实现，需新建 |
| metrics num_classes | 是（过时默认6） | training/metrics.py：评估须显式传 52/11 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名/日志/注释风格 | HIGH |
| 2 | 模块边界 | criterion 只损失；dataset 只数据；新增脚本不侵入 scaler/trainer | HIGH |
| 3 | 数据安全 | 无硬编码凭证；parquet/scaler 路径走配置 | HIGH |
| 4 | 导入合规 | 无通配符/未使用 import | MEDIUM |
| 5 | 错误处理 | 异常不静默吞掉；空 bins/空映射要报错 | MEDIUM |
| 6 | 性能风险 | parquet 全量分块读；无 O(N²) 循环；forward `[B,F,60]->[B,52/11]` 维度断言 | MEDIUM |
