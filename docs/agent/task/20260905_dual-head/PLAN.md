# 20260905_dual-head Implementation Plan

> Generated: 2026-09-05 00:10
> Task Dir: docs/agent/task/20260905_dual-head

## Goal

CNNTransformer 加回归辅头做 EMD+0.2*Huber 双头（52+1）改造，冒烟对比 baseline 的 loss/acc。

## Architecture

共享 `pooled_feat[d_model]` 分叉 `fc_cls(52)+fc_reg(1)`；Dataset 附带返回
clip 后的连续 `future_ret`；新 `criterion/dual_loss.py` 组合复用 `EMDLoss` +
`HuberLoss`（`L=EMD+λ*Huber`）；Trainer 用 `isinstance(tuple)` 解包兼容单/双头；
`train.py` 加 `--dual_head/--lambda_reg` 开关，默认关闭保 baseline 可比。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| y_ret clip | clip±0.5 | 不clip/按BINS±0.25截断 | 防1273%尖刺主导Huber；0.5=2倍BINS边缘，覆盖99.9%+样本且保留尾部信号 |
| forward兼容 | 恒返`(logits,ret_pred)`，Trainer/inference用isinstance解包 | `return_aux` flag切换返回类型 | 类型稳定可静态分析；pluggable契约`[B,F,T]->[B,52]`由`out[0] if tuple else out`保持 |
| ckpt兼容 | `fc`→`fc_cls`重命名+`strict=False`/键映射迁移 | 保留`fc`别名双写 | 旧`best_model.pth(fc.2.*)`可迁移加载；别名双写易造成梯度双计数 |
| loss落点 | 新建`criterion/dual_loss.py`组合EMDLoss | 直接改`emd_loss.py`加回归分支 | 守`criterion/AGENTS.md`的`(logits[52],labels)`签名；EMD单测不受影响 |
| 默认开关 | 默认`--dual_head`关（baseline），显式开才双头 | 默认开 | 冒烟对比要求baseline可比；防存量`train.py --smoke`行为漂移 |
| Huber δ | δ=1.0，reduction=mean，λ=0.2可配 | δ自适应/MSE | Huber对clip后±0.5残差稳健；MSE会被尾部放大 |

## Impact

| 模块 | 文件 | 操作(create/modify) | 风险等级 |
|------|------|--------------------|----------|
| data | data/dataset.py | modify | medium |
| models | models/cnn_transformer/model.py | modify | high |
| criterion | criterion/dual_loss.py | create | medium |
| training | training/trainer.py | modify | high |
| entry | train.py | modify | medium |

## Task Decomposition

### T01: Dataset返回连续future_ret
- **文件**: `data/dataset.py:368` (modify)
- **描述**: `__getitem__`同步返回`(x[45,60], y_cls long, y_ret float32 clip±0.5)`；`future_ret`取自`groups[code]["future_ret"][label_pos]`，NaN窗口已在`_load_and_prepare`过滤，`__main__`探查打印y_ret分位
- **依赖**: 无
- **预估行数**: +15
- **验收标准**: `x[45,60]`不变；`y_cls==digitize(y_ret_raw)`一致；`|y_ret|<=0.5`；DataLoader默认collate出3张量
- **风险因子**: 改返回元组 arity 会炸 Trainer 解包（T04 同步修）；勿在验证集重fit scaler

### T02: 模型双头fc_cls+fc_reg
- **文件**: `models/cnn_transformer/model.py:86` (modify)
- **描述**: `self.fc`→`self.fc_cls`（同结构LayerNorm+Dropout+Linear256->52），新增`self.fc_reg`(LayerNorm+Dropout+Linear256->1+squeeze)共享`pooled_feat`；`forward`恒返`(logits[B,52], ret_pred[B])`；`__main__`断言双头形状
- **依赖**: 无（可与T01并行）
- **预估行数**: +30
- **验收标准**: `logits[B,52], ret_pred[B]`；`out[0]`即旧pluggable`[B,52]`契约；旧ckpt经键映射可加载cls头
- **风险因子**: `fc.2.*`→`fc_cls.2.*`键迁移；`ret_pred`勿加激活（Huber直接回归）

### T03: DualLoss=EMD+λHuber
- **文件**: `criterion/dual_loss.py` (create)
- **描述**: `DualHeadLoss(emd_cfg, lambda_reg=0.2, huber_delta=1.0, bins=None)`组合`EMDLoss+nn.HuberLoss`；`forward(logits,y_cls,ret_pred,y_ret)`返`(total, emd, huber)`或total；`bins centers`仅用于可选`exp_ret`诊断，不入梯度
- **依赖**: T02（需双头输出签名）
- **预估行数**: +80
- **验收标准**: λ=0退化为纯EMD（数值≈EMDLoss）；`L=EMD+0.2*Huber`手算一致；device随module `.to()`迁移
- **风险因子**:勿改`emd_loss.py`签名；smooth_weights buffer设备一致性沿用EMD实现

### T04: Trainer单/双头兼容
- **文件**: `training/trainer.py:101,141` (modify)
- **描述**: train/val循环`batch`解包兼容2元/3元，`outputs`用isinstance解包：tuple→`(logits,ret_pred)`走DualLoss，Tensor→走EMDLoss；acc仍按`argmax(logits)`；日志打印`emd/huber`分量
- **依赖**: T01, T03
- **预估行数**: +40
- **验收标准**: 旧2元batch+单头ckpt仍可训（回归）；3元batch+双头`loss.backward()`正常；val返回`loss/acc`口径不变
- **风险因子**: `for data,labels`硬解包是必炸点；`labels.size(0)`计数口径勿变

### T05: train.py开关+冒烟对比
- **文件**: `train.py:87,225` (modify)
- **描述**: 加`--dual_head(action store_true,默认关)+--lambda_reg(0.2)+--huber_delta(1.0)`；开时用DualHeadLoss+`EMLossConfig`复用p2/LS0.1，关时纯EMDLoss baseline；`--smoke`跑两遍（baseline vs双头）输出loss/acc对比表
- **依赖**: T04
- **预估行数**: +40
- **验收标准**: 默认`train.py --smoke`行为=baseline不变；`--dual_head --smoke(max_codes20,epoch1)`跑通并输出`train/val loss/acc`对比
- **风险因子**: `LoggerManager config`须可序列化（DualLoss超参进config dict）；`run_log_dir`双跑勿覆盖
