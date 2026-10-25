"""交易门头损失（Gate Head）。

仅在 ``GATE_HEAD=True`` 时启用（默认关）。二元分类损失，判断"是否应该交易"。

已知实验结论（handoff Decision 4）：Gate head 在排序任务上训练效果差
（IC -0.0401），不建议默认启用。保留代码供未来实验。

注意：
    - 输入 gate_pred: (batch, 1) logits
    - 输入 gate_labels: (batch,) 0/1 标签
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class GateLoss(nn.Module):
    """交易门头二元分类损失。"""

    def __init__(self, pos_weight: float = 0.5):
        super().__init__()
        self.pos_weight = torch.tensor([pos_weight])

    def forward(self, gate_pred: torch.Tensor, gate_labels: torch.Tensor) -> torch.Tensor:
        """计算 BCE loss。

        Args:
            gate_pred: (batch, 1) logits
            gate_labels: (batch,) 0/1 标签

        Returns:
            标量 loss
        """
        device = gate_pred.device
        pos_weight = self.pos_weight.to(device)
        return F.binary_cross_entropy_with_logits(
            gate_pred.squeeze(-1),
            gate_labels.float(),
            pos_weight=pos_weight,
        )
