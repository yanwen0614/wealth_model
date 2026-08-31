import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Tuple


class SelfAttention(nn.Module):
    """
    自注意力机制模块
    职责：实现自注意力计算，捕捉序列内部的依赖关系
    
    参数:
        hidden_dim: 隐藏层维度
    """
    def __init__(self, hidden_dim: int):
        super(SelfAttention, self).__init__()
        self.hidden_dim = hidden_dim
        self.query = nn.Linear(hidden_dim, hidden_dim)
        self.key = nn.Linear(hidden_dim, hidden_dim)
        self.value = nn.Linear(hidden_dim, hidden_dim)
        scale = torch.sqrt(torch.tensor(hidden_dim, dtype=torch.float32))
        self.register_buffer('scale', scale)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        前向传播
        
        参数:
            x: 输入张量 [batch_size, seq_len, hidden_dim]
        
        返回:
            attended_output: 注意力加权后的输出 [batch_size, seq_len, hidden_dim]
            attention_weights: 注意力权重 [batch_size, seq_len, seq_len]
        """
        Q = self.query(x)
        K = self.key(x)
        V = self.value(x)
        
        attention_scores = torch.bmm(Q, K.transpose(1, 2)) / self.scale
        attention_weights = F.softmax(attention_scores, dim=-1)
        attended_output = torch.bmm(attention_weights, V)
        return attended_output, attention_weights
