# 审查清单 — 20260905_dual-head

> 生成时间：2026-09-05 00:10

## 需求理解

EMD+0.2*Huber双头52+1改造+冒烟对比baseline。模型`fc_cls52+fc_reg1`共享pooled；
Dataset返`(x,y_cls,y_ret clip±0.5)`；新`dual_loss.py: L=EMD+λHuber(λ0.2)`；
Trainer兼容单/双头；`train.py`加`--dual_head/--lambda_reg`，默认关保baseline可比；
冒烟`max_codes20/epoch1`对比loss/acc。
显式假设：(1)clip±0.5可接受（BINS±0.25的2倍）；(2)默认双头关；(3)Huberδ=1.0；
(4)`fc→fc_cls`重命名+ckpt迁移；(5)bins centers仅诊断不用入loss。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| data | data/dataset.py:368 | 修改 | `__getitem__` 2元→3元，future_ret clip±0.5 |
| models | models/cnn_transformer/model.py:86 | 修改 | `fc`→`fc_cls`+`fc_reg`，forward恒返tuple |
| criterion | criterion/dual_loss.py | 新增 | 组合EMDLoss+Huber，不碰emd_loss.py |
| training | training/trainer.py:101,141 | 修改 | batch/output双兼容解包 |
| entry | train.py:58,72,87 | 修改 | 开关+DualLoss装配+冒烟对比 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 |
|------------|---------|------|
| ParquetDataset/groups future_ret | 是（未返回） | data/dataset.py:308-310存，368未返 |
| EMDLoss | 是（复用，不重复实现） | criterion/emd_loss.py:5 |
| Huber/dual/fc_reg | 否 | 全项目grep无命中（可新建） |
| ModelConfig/CNNTransformer | 是 | models/cnn_transformer/config.py:1, model.py:64 |
| Trainer单头假设 | 是（待兼容） | training/trainer.py:101,141 |
| bins centers/exp_ret | 否（仅诊断用） | scripts/eval_bins_mapping.py:148有只读参考 |
| scaler/45维 | 是（不动） | data/scaler.py, dataset.py:91 →45维保持 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名/日志/注释风格；ruff line-length 120 | HIGH |
| 2 | 模块边界 | models未侵入data/training；criterion仅被training/model依赖；dual_loss组合不改EMD签名 | HIGH |
| 3 | pluggable兼容 | `out[0] if tuple else out`即`[B,52]`；`[B,F,T]->[B,52]`断言保留 | HIGH |
| 4 | 数据安全 | 无硬编码凭证；parquet/logs不入库 | HIGH |
| 5 | 导入合规 | 无通配符/未使用import | MEDIUM |
| 6 | 错误处理 | batch/output解包异常不静默吞；空val告警保留 | MEDIUM |
| 7 | 性能风险 | 无O(N²)扫描；fc_reg仅+257参数；clip为向量化op | MEDIUM |
| 8 | 数值断言 | 45维/`[B,52]+[B]`/λ=0退化EMD/clip±0.5/digitize一致性 | HIGH |
