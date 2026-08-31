import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple
from .attention import SelfAttention


class CNN_LSTM_Attention(nn.Module):
    """
    CNN+LSTM+Attention 混合模型
    职责：整合CNN局部特征提取、LSTM时序建模和注意力机制
    
    参数:
        input_dim: 输入特征维度
        seq_len: 序列长度
        num_classes: 分类类别数
        cnn_out_channels: CNN输出通道数
        cnn_kernel_size: CNN卷积核大小
        lstm_hidden_dim: LSTM隐藏层维度
        lstm_num_layers: LSTM层数
        dropout_rate: Dropout比率
    """
    def __init__(self, input_dim: int, seq_len: int, num_classes: int,
                 cnn_out_channels: int = 16, cnn_kernel_size: int = 10,
                 lstm_hidden_dim: int = 64, lstm_num_layers: int = 3,
                 dropout_rate: float = 0.2):
        super(CNN_LSTM_Attention, self).__init__()
        self.input_dim = input_dim
        # self.seq_len = seq_len
        self.lstm_hidden_dim = lstm_hidden_dim

        # CNN模块：局部特征提取
        self.cnn = nn.Sequential(
            nn.Conv1d(in_channels=input_dim, out_channels=cnn_out_channels,
                     kernel_size=cnn_kernel_size, padding=0),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2, stride=2),
            nn.Dropout(dropout_rate)
        )
        
        # LSTM模块：长时序依赖捕捉
        self.lstm = nn.LSTM(
            input_size=cnn_out_channels,
            hidden_size=lstm_hidden_dim,
            num_layers=lstm_num_layers,
            batch_first=True,
            bidirectional=False,
            dropout=dropout_rate if lstm_num_layers > 1 else 0
        )
        
        # 自注意力模块
        self.attention = SelfAttention(hidden_dim=lstm_hidden_dim)
        
        # 全连接分类层
        self.fc = nn.Sequential(
            nn.Dropout(dropout_rate),
            nn.Linear(lstm_hidden_dim, 128),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(128, num_classes)
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        前向传播
        
        参数:
            x: 输入张量 [batch_size, seq_len, input_dim]
        
        返回:
            output: 分类输出 [batch_size, num_classes]
            attention_weights: 注意力权重
        """
        batch_size = x.size(0)
        
        # CNN特征提取
        x_cnn = x
        cnn_out = self.cnn(x_cnn)
        
        # LSTM时序建模
        lstm_in = cnn_out.permute(0, 2, 1)
        lstm_out, _ = self.lstm(lstm_in)
        
        # 自注意力加权
        attention_out, attention_weights = self.attention(lstm_out)
        
        # 时序维度平均池化
        agg_out = torch.mean(attention_out, dim=1)
        
        # 分类输出
        output = self.fc(agg_out)
        return output, attention_weights
