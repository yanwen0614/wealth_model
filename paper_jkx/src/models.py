"""三尺度 2D-CNN,对应论文 Fig.3 + Appendix.

简化说明:首层垂直 stride 按论文取 {5:1, 20:3, 60:3},
dilation 简化为 1(原论文首层 vertical dilation 1/2/3);
其余 block stride=1.padding 保持尺寸,MaxPool 一律 2x1.
FC 输入维用 dummy 前向自动推导,无需手算论文 FC 数.
"""
import torch
from torch import nn

from .imaging import SHAPES

BLOCKS = {5: 2, 20: 3, 30: 3, 60: 4}
CHANNELS = [64, 128, 256, 512]       # 默认(I5/I20/I60 论文复现)
CHANNELS_LITE = [32, 64, 128, 256]   # I30-color 瘦身: 3070 上第 3 块 256ch 太重
FIRST_STRIDE_V = {5: 1, 20: 3, 30: 2, 60: 3}
# 池化核: I30-color 同时降宽(2,2), 其余保持只降高(2,1)
POOL = {5: (2, 1), 20: (2, 1), 30: (2, 2), 60: (2, 1)}


class CNNBlock(nn.Module):
    """Conv5x3 → BN → LeakyReLU → MaxPool2x1."""

    def __init__(self, in_ch, out_ch, stride_v=1, pool=(2, 1)):
        super().__init__()
        self.conv = nn.Conv2d(in_ch, out_ch, kernel_size=(5, 3),
                              stride=(stride_v, 1), padding=(2, 1))
        self.bn = nn.BatchNorm2d(out_ch)
        self.act = nn.LeakyReLU(0.01, inplace=True)
        self.pool = nn.MaxPool2d(kernel_size=pool, stride=pool)

    def forward(self, x):
        return self.pool(self.act(self.bn(self.conv(x))))


class ImageCNN(nn.Module):
    """输入 [B,1,H,W] → 输出 [B,2] 上涨/下跌 logit."""

    def __init__(self, n_days=5, dropout=0.5):
        super().__init__()
        n_block = BLOCKS[n_days]
        h, w, ch = SHAPES[n_days]  # 灰度 C=1, I30-color C=3
        chans = CHANNELS_LITE if n_days == 30 else CHANNELS
        pool = POOL[n_days]
        layers, in_ch = [], ch
        for b in range(n_block):
            sv = FIRST_STRIDE_V[n_days] if b == 0 else 1
            layers.append(CNNBlock(in_ch, chans[b], stride_v=sv, pool=pool))
            in_ch = chans[b]
        self.features = nn.Sequential(*layers)
        self.drop = nn.Dropout(dropout)
        with torch.no_grad():
            dummy = torch.zeros(1, ch, h, w)
            flat = self.features(dummy).numel()
        self.fc = nn.Linear(flat, 2)
        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        z = self.features(x).flatten(1)
        return self.fc(self.drop(z))
