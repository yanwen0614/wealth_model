"""PureRegLoss: pure regression ablation, Huber(ret_pred, y_ret) only.

签名兼容说明 (对齐 dual_loss.py):
  - 类属性 is_dual_head=True, Trainer 经 getattr 判别走 4 参调用并取 tuple[0].
  - logits 不进任何计算: 分类头无梯度, 参数由 optimizer 自动跳过更新.
  - 缺 ret_pred/targets_ret 时退化返回三元组 zeros, 不炸训练.
"""
import torch
from torch import nn


class PureRegLoss(nn.Module):
    """纯回归消融损失: total = reg_part = Huber(delta)(ret_pred, targets_ret)."""

    is_dual_head = True

    def __init__(self, num_classes=52, huber_delta=1.0):
        super().__init__()
        self.huber = nn.HuberLoss(delta=huber_delta, reduction="mean")

    def forward(self, logits, ret_pred=None, targets_cls=None, targets_ret=None):
        if ret_pred is None or targets_ret is None:
            zero = torch.zeros((), device=logits.device, dtype=logits.dtype)
            return zero, zero, zero
        ret_pred = ret_pred.reshape(-1).to(logits.dtype)
        targets_ret = targets_ret.reshape(-1).to(logits.device, logits.dtype)
        reg_part = self.huber(ret_pred.to(logits.device), targets_ret)
        cls_zero = torch.zeros((), device=logits.device, dtype=logits.dtype)
        return reg_part, reg_part, cls_zero
