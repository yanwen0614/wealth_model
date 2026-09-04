"""Dual-head loss: DualLoss = EMD(cls) + lambda_reg * Huber(ret).

签名兼容说明 (criterion/AGENTS.md):
  - 旧签名: EMDLoss(logits[B,52], labels[B]) -> scalar.
  - 新签名: DualLoss(logits[B,52], ret_pred[B|None], y_cls[B], y_ret[B|None])
      -> (total, emd_part, huber_part) 供 Trainer 日志.
  - 兼容: Trainer 经 `is_dual_head=True` 判别调用 4 参; 缺 ret_pred/y_ret
    时 huber_part=0, total=emd (退化为纯 EMD, 单头模型可用).
  - 遗留 2 参调用 DualLoss(logits, y_cls) 亦兼容 (视作纯 EMD).
"""
import torch
from torch import nn

from .emd_loss import EMDLoss


class DualLoss(nn.Module):
    """EMD 分类头 + Huber 回归头 (ret_pred vs future_ret 连续值)."""

    is_dual_head = True

    def __init__(self, num_classes=52, p=2, label_smoothing=True,
                 smooth_eps=0.1, lambda_reg=0.2, huber_delta=1.0):
        super().__init__()
        self.lambda_reg = lambda_reg
        self.emd = EMDLoss(num_classes=num_classes, p=p,
                           label_smoothing=label_smoothing,
                           smooth_eps=smooth_eps)
        self.huber = nn.HuberLoss(delta=huber_delta, reduction="mean")

    def forward(self, logits, ret_pred=None, targets_cls=None, targets_ret=None):
        # 遗留 2 参兼容: DualLoss(logits, y_cls) -> 纯 EMD
        if targets_cls is None and targets_ret is None and ret_pred is not None:
            targets_cls, ret_pred = ret_pred, None
        emd_part = self.emd(logits, targets_cls)
        if ret_pred is None or targets_ret is None:
            huber_part = torch.zeros((), device=logits.device, dtype=logits.dtype)
            return emd_part, emd_part, huber_part
        ret_pred = ret_pred.reshape(-1).to(logits.dtype)
        targets_ret = targets_ret.reshape(-1).to(logits.device, logits.dtype)
        huber_part = self.huber(ret_pred.to(logits.device), targets_ret)
        total = emd_part + self.lambda_reg * huber_part
        return total, emd_part, huber_part
