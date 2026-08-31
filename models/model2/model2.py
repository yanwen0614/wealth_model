import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List
from .cnnblock import MultiWindowInceptionCNN
from .config import ModelConfig


class PositionalEncoding(nn.Module):
    """
    正弦余弦位置编码
    参考: https://pytorch.org/tutorials/beginner/transformer_tutorial.html
    """
    def __init__(self, d_model: int, dropout: float = 0.1, max_len: int = 5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        # 计算位置编码矩阵
        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-torch.log(torch.tensor(10000.0)) / d_model))
        
        pe = torch.zeros(max_len, 1, d_model)
        pe[:, 0, 0::2] = torch.sin(position * div_term)
        pe[:, 0, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor, shape [seq_len, batch_size, embedding_dim]
        """
        x = x + self.pe[:x.size(0)]
        return self.dropout(x)


class TransformerEncoder(nn.Module):
    def __init__(
        self,
        config: ModelConfig
    ):
        super().__init__()
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=config.d_model,
            nhead=config.nhead,
            dim_feedforward=config.d_model*4,
            dropout=config.dropout_rate,
            activation="gelu"
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=config.num_encoder_layers)
        
        # 添加位置编码
        self.pos_encoder = PositionalEncoding(
            d_model=config.d_model,
            dropout=config.dropout_rate,
            max_len=config.seq_len  # 使用配置中的序列长度
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [seq_len, batch_size, d_model]
        # 应用位置编码
        x = self.pos_encoder(x)
        # 经过Transformer Encoder
        return self.encoder(x)


class CNNTransformer(nn.Module):
    """多窗口CNN+Transformer时间序列多分类模型"""
    def __init__(
        self,
        config: ModelConfig
    ):
        super().__init__()
        self.config = config
        
        # 1. 多窗口CNN特征提取
        self.multi_window_cnn = MultiWindowInceptionCNN(config)
        
        # 计算CNN输出通道数：最后一个Inception块的输出通道数
        cnn_total_channels = config.cnn_out_channels
        
        # 2. CNN特征映射到Transformer维度
        self.proj = nn.Linear(cnn_total_channels, config.d_model)
        
        # 3. Transformer Encoder（已包含位置编码）
        self.transformer_encoder = TransformerEncoder(config)
        
        # 4. 分类头
        self.fc = nn.Sequential(
            nn.LayerNorm(config.d_model),
            nn.Dropout(config.dropout_rate),
            nn.Linear(config.d_model, config.num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [batch_size, featurenum, seq_len]
        # Step1: 多窗口CNN提取局部特征
        cnn_feat = self.multi_window_cnn(x)  # [batch, cnn_total_channels, seq_len']
        
        # Step2: 调整维度适配Transformer
        cnn_feat = cnn_feat.permute(0, 2, 1)  # [batch, seq_len', cnn_total_channels]
        trans_feat = self.proj(cnn_feat)       # [batch, seq_len', d_model]
        
        # Step3: Transformer输入需要[seq_len, batch, d_model]格式
        trans_feat = trans_feat.permute(1, 0, 2)  # [seq_len', batch, d_model]
        
        # Step4: Transformer提取长程依赖（包含位置编码）
        trans_out = self.transformer_encoder(trans_feat)  # [seq_len', batch, d_model]
        
        # Step5: 全局池化+分类 (在seq_len维度求平均)
        pooled_feat = trans_out.mean(dim=0)  # [batch, d_model]
        logits = self.fc(pooled_feat)        # [batch, num_classes]
        
        return logits


if __name__ == "__main__":
    # python -m models.model2.model2
    # 测试代码
    print("Testing CNNTransformer model with positional encoding...")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")

    config = ModelConfig()
    
    # 实例化模型
    model = CNNTransformer(config).to(device)

    # 打印模型基本信息
    print("=== 模型基本信息 ===")
    # 计算模型参数量
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    non_trainable_params = total_params - trainable_params
    
    print(f"总参数量: {total_params:,}")
    print(f"可训练参数量: {trainable_params:,}")
    print(f"不可训练参数量: {non_trainable_params:,}")
    print(f"可训练参数比例: {100 * trainable_params / total_params:.2f}%")
    
    # 打印位置编码信息
    print(f"\n=== 位置编码信息 ===")
    print(f"位置编码维度: {config.d_model}")
    print(f"最大序列长度: {config.seq_len}")
    
    print(f"\nModel created successfully: {model.__class__.__name__}")
    
    # 生成随机输入数据 [batch_size, featurenum, seq_len]
    batch_size = 8
    x = torch.randn(batch_size, config.featurenum, config.seq_len).to(device)
    print(f"\nInput shape: {x.shape}")
    
    # 前向传播测试
    model.eval()
    with torch.no_grad():
        logits = model(x)
    
    print(f"Output logits shape: {logits.shape}")
    print(f"Output logits: {logits}")
    
    # 测试损失计算
    target = torch.randint(0, config.num_classes, (batch_size,)).to(device)
    loss_fn = nn.CrossEntropyLoss()
    loss = loss_fn(logits, target)
    print(f"\nCrossEntropyLoss: {loss.item()}")
    
    # 测试位置编码单独输出
    print(f"\n=== 测试位置编码 ===")
    pos_encoder = PositionalEncoding(d_model=config.d_model, dropout=0.0).to(device)
    # 创建测试输入 [seq_len, batch_size, d_model]
    test_input = torch.zeros(config.seq_len, batch_size, config.d_model).to(device)
    pos_encoded = pos_encoder(test_input)
    print(f"位置编码输出形状: {pos_encoded.shape}")
    print(f"位置编码示例（第一个位置）: {pos_encoded[0, 0, :10]}")  # 打印前10个维度
    print(f"位置编码示例（中间位置）: {pos_encoded[config.seq_len//2, 0, :10]}")
    print(f"位置编码示例（最后位置）: {pos_encoded[-1, 0, :10]}")
    
    print("\nTest completed successfully!")
