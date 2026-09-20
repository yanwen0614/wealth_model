"""散户友好模型：CNN+Transformer 骨架 → 二分类概率 + 预期涨幅回归。

架构（复用 cnn_transformer 模块）：
  Input [B, F=53, T=60]
    → MultiWindowInceptionCNN（5 个 Inception 块，核 [1,3,5,7,10]）
    → Linear 投影（128 → 256）
    → TransformerEncoder（4 层，nhead=8）
    → 时序全局平均池化
    → ┠ fc_bin: LayerNorm → Dropout → Linear(256→1) → Sigmoid  [B]  胜率概率
      └ fc_reg: LayerNorm → Dropout → Linear(256→1)            [B]  预期涨幅

推理决策流程（在回测脚本中实现）：
  1. 模型输出 p_bin（胜率概率）+ ret_pred（预期涨幅）
  2. 封板过滤：排除开盘涨停（T+1 open ≥ 前收盘 × 1.098/1.198）
  3. 综合评分：score = α * p_bin + (1-α) * normalize(ret_pred)
  4. 按 score 降序取前 N 只（N ≤ max_picks_per_day）
  5. 若某日无标的通过阈值 → 跳过（持仓为 0）
"""

import torch
import torch.nn as nn

from models.cnn_transformer.config import ModelConfig as _CNNModelConfig
from models.cnn_transformer.inception_blocks import MultiWindowInceptionCNN
from models.cnn_transformer.model import TransformerEncoder

from .config import RetailModelConfig


class RetailFriendlyModel(nn.Module):
    """CNN+Transformer 骨架 → 二分类概率 + 预期涨幅回归。

    输出:
      p_bin:    [B] 胜率概率（sigmoid），∈(0,1)
      ret_pred: [B] 预期涨幅（未归一化），回归头输出
    """

    def __init__(self, config: RetailModelConfig):
        super().__init__()
        self.config = config

        # ── 桥接配置：复用 CNNTransformer 的 ModelConfig ──
        _cfg = _CNNModelConfig(
            featurenum=config.featurenum,
            seq_len=config.seq_len,
            num_classes=2,  # 占位，本模型不使用
            cnn_out_channels=config.cnn_out_channels,
            cnn_kernel_sizes=list(config.cnn_kernel_sizes),
            d_model=config.d_model,
            nhead=config.nhead,
            num_encoder_layers=config.num_encoder_layers,
            dropout_rate=config.dropout_rate,
        )

        # ── 1. CNN 多尺度特征提取 ──
        self.multi_window_cnn = MultiWindowInceptionCNN(_cfg)
        cnn_total_channels = config.cnn_out_channels  # 128

        # ── 2. CNN → Transformer 投影 ──
        self.proj = nn.Linear(cnn_total_channels, config.d_model)

        # ── 3. Transformer 长程依赖建模（含位置编码） ──
        self.transformer_encoder = TransformerEncoder(_cfg)

        # ── 4. 二分类头（胜率概率） ──
        self.fc_bin = nn.Sequential(
            nn.LayerNorm(config.d_model),
            nn.Dropout(config.dropout_rate),
            nn.Linear(config.d_model, 1),
        )

        # ── 5. 回归头（预期涨幅） ──
        self.fc_reg = nn.Sequential(
            nn.LayerNorm(config.d_model),
            nn.Dropout(config.dropout_rate),
            nn.Linear(config.d_model, 1),
        )

    def forward(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """前向传播。

        Args:
            x: 输入特征 [B, F, T]

        Returns:
            bin_logits: [B] 二分类 logits（pre-sigmoid），用于损失计算
            ret_pred:   [B] 预期涨幅（回归值）
        """
        # CNN
        cnn_feat = self.multi_window_cnn(x)          # [B, 128, T//16]

        # 维度置换适应 Transformer
        cnn_feat = cnn_feat.permute(0, 2, 1)         # [B, T', 128]
        trans_feat = self.proj(cnn_feat)             # [B, T', 256]

        # Transformer 输入格式 [seq, batch, dim]
        trans_feat = trans_feat.permute(1, 0, 2)     # [T', B, 256]
        trans_out = self.transformer_encoder(trans_feat)  # [T', B, 256]

        # 时序全局平均池化
        pooled = trans_out.mean(dim=0)               # [B, 256]

        # 双头输出（bin_logits: pre-sigmoid, ret_pred: 原始回归值）
        bin_logits = self.fc_bin(pooled).squeeze(-1)  # [B]
        ret_pred = self.fc_reg(pooled).squeeze(-1)   # [B]
        return bin_logits, ret_pred

    @torch.no_grad()
    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """推理时输出胜率概率 [B] ∈ (0,1)。"""
        self.eval()
        bin_logits, _ = self.forward(x)
        return torch.sigmoid(bin_logits)

    @torch.no_grad()
    def predict(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """推理辅助：保证 eval 模式返回 (p_bin, ret_pred)。"""
        self.eval()
        return self.forward(x)


# ── 模块自检 ──
if __name__ == "__main__":
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    cfg = RetailModelConfig(featurenum=53, seq_len=60)
    model = RetailFriendlyModel(cfg).to(device)

    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"Total params: {total:,}  |  Trainable: {trainable:,}  |  Ratio: {100 * trainable / total:.1f}%")

    # 前向测试
    B = 16
    x = torch.randn(B, cfg.featurenum, cfg.seq_len).to(device)
    bin_logits, ret_pred = model(x)
    p_bin = torch.sigmoid(bin_logits)
    print(f"\nInput:  {x.shape}")
    print(f"bin_logits:  {bin_logits.shape}  mean={bin_logits.mean().item():.4f}")
    print(f"p_bin(sigmoid):  mean={p_bin.mean().item():.4f}  ∈({p_bin.min().item():.4f},{p_bin.max().item():.4f})")
    print(f"ret_pred: {ret_pred.shape}  mean={ret_pred.mean().item():.4f}")
    assert bin_logits.shape == (B,), f"bin_logits shape mismatch: {bin_logits.shape}"
    assert ret_pred.shape == (B,), f"ret_pred shape mismatch: {ret_pred.shape}"

    print("\n✓ RetailFriendlyModel self-test passed!")
