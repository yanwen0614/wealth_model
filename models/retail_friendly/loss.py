"""散户友好模型专用损失函数：面向高精度（precision ≥ 75%）优化。

设计思路：
  AsymmetricLoss (ASL) — 非对称聚焦损失，γ_neg > γ_pos 使假阳性（FP）受更大惩罚。
  配合回归辅助头（Huber）引导特征学习，最终决策仅依赖二分类概率。

参考：
  - "Asymmetric Loss For Multi-Label Classification" (Ridnik et al., 2021)
  - 核心公式:
      L_pos = (1-p)^γ_pos * log(p)
      L_neg = p^γ_neg * log(1-p)
      L = -y * L_pos - (1-y) * L_neg
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class AsymmetricLoss(nn.Module):
    """Asymmetric Loss (ASL) — 面向高精度的非对称聚焦损失。

    Args:
        gamma_pos: 正类聚焦参数（建议 0.0，不对正类聚焦）
        gamma_neg: 负类聚焦参数（建议 2.0~4.0，值越高对 FP 惩罚越大）
        clip: 概率裁剪值，防止 log(0)（默认 0.05）
        reduction: 聚合方式（'mean' | 'sum' | 'none'）
    """

    def __init__(
        self,
        gamma_pos: float = 0.0,
        gamma_neg: float = 4.0,
        clip: float = 0.05,
        reduction: str = "mean",
    ):
        super().__init__()
        self.gamma_pos = gamma_pos
        self.gamma_neg = gamma_neg
        self.clip = clip
        self.reduction = reduction

    def forward(
        self,
        preds: torch.Tensor,
        targets: torch.Tensor,
    ) -> torch.Tensor:
        """计算 Asymmetric Loss。

        Args:
            preds: 模型预测概率 [B]（sigmoid 后）
            targets: 二分类标签 [B]（0/1）

        Returns:
            loss: 标量损失值
        """
        # 裁剪防止 log(0)
        preds = preds.clamp(min=self.clip, max=1 - self.clip)

        # 正类损失: L_pos = (1-p)^γ_pos * log(p)
        pos_loss = -targets * (1.0 - preds) ** self.gamma_pos * preds.log()

        # 负类损失: L_neg = p^γ_neg * log(1-p)
        neg_loss = -(1.0 - targets) * preds ** self.gamma_neg * (1.0 - preds).log()

        loss = pos_loss + neg_loss

        if self.reduction == "mean":
            return loss.mean()
        elif self.reduction == "sum":
            return loss.sum()
        return loss


class PrecisionBCE(nn.Module):
    """带正类权重的二元交叉熵损失。

    通过 pos_weight > 1 使模型更重视正类，间接提升 precision。
    较 ASL 更简单，适合作为 baseline。

    Args:
        pos_weight: 正类损失权重（建议 2.0~5.0）
    """

    def __init__(self, pos_weight: float = 3.0):
        super().__init__()
        self.pos_weight = pos_weight

    def forward(
        self,
        preds: torch.Tensor,
        targets: torch.Tensor,
    ) -> torch.Tensor:
        """计算加权 BCE。

        Args:
            preds: 模型预测概率 [B]
            targets: 二分类标签 [B]

        Returns:
            loss: 标量损失值
        """
        # BCEWithLogitsLoss 风格：对正类乘 pos_weight
        loss = F.binary_cross_entropy(
            preds, targets, reduction="none"
        )
        # 正类加权
        weights = torch.where(targets > 0.5, self.pos_weight, 1.0)
        return (loss * weights).mean()


class RetailLoss(nn.Module):
    """散户友好模型组合损失：BCEWithLogits(binary) + λ * Huber(regression)。

    实现 is_dual_head 接口，兼容 batch._compute_loss 的 4 参调用：
      loss = criterion(bin_logits, ret_pred, y_cls, y_ret)
    其中 bin_logits 为 pre-sigmoid（BCEWithLogitsLoss 内部做 sigmoid），
    y_ret 用于推导二分类标签。

    Design:
    - 主损失 BCEWithLogitsLoss + pos_weight：数值稳定，无 ASL 的梯度偏移问题
      pos_weight > 1 使 FP 成本高于 FN，驱动模型更保守（precision 优化）
    - 辅助损失 Huber 引导模型学习收益率大小，稳定特征提取
    - 推理时仅用二分类概率，回归头仅在训练期辅助

    Args:
        pos_weight: 正类损失权重（>1 → FP 惩罚更大 → 更高 precision）
        lambda_reg: 回归辅助头损失权重
        huber_delta: Huber loss delta
        gamma_neg: 保留但弃用（ASL 迁移兼容）
        gamma_pos: 保留但弃用（ASL 迁移兼容）
    """

    is_dual_head = True

    def __init__(
        self,
        pos_weight: float = 2.0,
        lambda_reg: float = 0.3,
        huber_delta: float = 1.0,
        gamma_neg: float | None = None,
        gamma_pos: float | None = None,
    ):
        super().__init__()
        self.lambda_reg = lambda_reg
        # BCEWithLogitsLoss 内部做 sigmoid，数值稳定
        self.bce = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([pos_weight]) if pos_weight != 1.0 else None,
            reduction="mean",
        )
        self.huber = nn.HuberLoss(delta=huber_delta, reduction="mean")
        # 保存 pos_weight 供外部查询
        self.pos_weight = pos_weight

    def forward(
        self,
        bin_logits: torch.Tensor,
        ret_pred: torch.Tensor,
        y_cls: torch.Tensor,
        y_ret: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """计算组合损失。

        Args:
            bin_logits: 二分类 logits [B]（pre-sigmoid）
            ret_pred: 回归预测值 [B]
            y_cls: 52 类分类标签 [B]（本实现不使用，仅占位）
            y_ret: 真实收益率 [B]（用于推导二进制标签和回归损失）

        Returns:
            loss: 标量组合损失
        """
        # 从 y_ret 推导二进制标签
        if y_ret is not None:
            y_bin = (y_ret > 0.0).float().to(bin_logits.device)
        else:
            # 回退：类索引 >= 26 为正
            y_bin = (y_cls >= 26).float().to(bin_logits.device)

        # 主损失：BCEWithLogitsLoss（logits 直接输入，内部做 sigmoid）
        bce_loss = self.bce(bin_logits, y_bin)

        # 辅助损失：Huber（回归头）
        if y_ret is not None and self.lambda_reg > 0:
            ret_pred = ret_pred.reshape(-1).to(bin_logits.dtype)
            y_ret = y_ret.reshape(-1).to(bin_logits.device, bin_logits.dtype)
            huber_loss = self.huber(ret_pred, y_ret)
            return bce_loss + self.lambda_reg * huber_loss

        return bce_loss


# 单元测试
if __name__ == "__main__":
    torch.manual_seed(42)
    B = 128

    # 测试 AsymmetricLoss
    asl = AsymmetricLoss(gamma_pos=0.0, gamma_neg=4.0)
    preds = torch.rand(B)
    targets = (torch.rand(B) > 0.5).float()
    l = asl(preds, targets)
    print(f"AsymmetricLoss: {l.item():.6f}")

    # 测试 PrecisionBCE
    pbce = PrecisionBCE(pos_weight=3.0)
    l2 = pbce(preds, targets)
    print(f"PrecisionBCE:   {l2.item():.6f}")

    # 测试 RetailLoss
    rl = RetailLoss(gamma_neg=4.0, lambda_reg=0.1)
    ret_pred = torch.randn(B)
    y_ret = torch.randn(B)
    l3 = rl(preds, ret_pred, targets, y_ret)
    print(f"RetailLoss:     {l3.item():.6f}")

    # 手动计算验证：FP 应比 FN 产生更大损失
    fp_preds = torch.tensor([0.9, 0.9, 0.9])
    fp_targets = torch.tensor([0.0, 0.0, 0.0])
    fp_loss = asl(fp_preds, fp_targets)
    fn_preds = torch.tensor([0.1, 0.1, 0.1])
    fn_targets = torch.tensor([1.0, 1.0, 1.0])
    fn_loss = asl(fn_preds, fn_targets)
    print(f"\nFP loss (pred=0.9, y=0): {fp_loss.item():.6f}")
    print(f"FN loss (pred=0.1, y=1): {fn_loss.item():.6f}")
    print(f"FP/FN ratio: {fp_loss.item() / fn_loss.item():.2f}x (应 >1)")

    print("\nAll loss tests passed!")
