from dataclasses import dataclass, field  # 新增导入field
from typing import List

@dataclass
class ModelConfig:
    featurenum: int = 10          # 输入特征数
    seq_len: int = 20             # 序列长度
    num_classes: int = 5          # 多分类类别数
    cnn_out_channels: int = 60    # CNN输出总通道数
    cnn_kernel_sizes: List[int] = field(default_factory=lambda: [3,5,7])  # 修复：使用default_factory
    d_model: int = 128            # Transformer输入维度
    nhead: int = 8                # 注意力头数（需整除d_model）
    num_encoder_layers: int = 2   # Transformer Encoder层数
    dropout_rate: float = 0.1     # 正则化率

if __name__ == "__main__":
    print(ModelConfig().cnn_kernel_sizes)