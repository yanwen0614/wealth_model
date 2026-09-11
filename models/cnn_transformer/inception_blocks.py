
import torch
from torch import nn

from .config import ModelConfig


class LightInceptionBlock1D(nn.Module):
    """
    轻量级Inception块 - ModuleList实现
    
    特性：
    - 使用nn.ModuleList管理所有分支
    - 支持动态kernel_size列表
    - 全部使用深度可分离卷积
    - 自动通道分配
    
    Args:
        in_channels: 输入通道数
        out_channels: 输出通道数
        kernel_sizes: 卷积核尺寸列表，例如 [1, 3, 5, 7]
        expansion_factor: 中间层扩展因子
        channel_ratios: 各分支通道比例，None时自动均分
        use_pool_branch: 是否添加池化分支
        pool_type: 池化类型 'max' 或 'avg'
        dropout: Dropout比例
    """
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_sizes: list[int] | None = None,
        expansion_factor: float = 0.5,
        channel_ratios: list[float] | None = None,
        use_pool_branch: bool = True,
        pool_type: str = "max",
        dropout: float = 0.1
    ):
        super().__init__()

        # 默认多尺度卷积核（None 守卫：避免可变默认参数共享）
        if kernel_sizes is None:
            kernel_sizes = [1, 3, 5, 10, 20]
        # 计算分支数量
        num_conv_branches = len(kernel_sizes)
        num_branches = num_conv_branches + (1 if use_pool_branch else 0)
        
        # 自动计算通道分配
        if channel_ratios is None:
            channel_ratios = [1.0 / num_branches] * num_branches
        else:
            assert len(channel_ratios) == num_branches, \
                f"channel_ratios长度({len(channel_ratios)})必须等于分支数({num_branches})"
            assert abs(sum(channel_ratios) - 1.0) < 1e-6, \
                f"channel_ratios之和必须为1，当前为{sum(channel_ratios)}"
        
        # 计算各分支输出通道数
        branch_channels = []
        for ratio in channel_ratios[:-1]:
            branch_channels.append(int(out_channels * ratio))
        branch_channels.append(out_channels - sum(branch_channels))  # 最后一个分支补齐
        
        # 存储配置
        self.kernel_sizes = kernel_sizes
        self.use_pool_branch = use_pool_branch
        self.mid_channels = int(in_channels * expansion_factor)
        
        # 构建卷积分支列表
        self.conv_branches = nn.ModuleList()
        for i, ks in enumerate(kernel_sizes):
            branch = self._make_conv_branch(
                in_channels=in_channels,
                out_channels=branch_channels[i],
                kernel_size=ks,
                mid_channels=self.mid_channels
            )
            self.conv_branches.append(branch)
        
        # 构建池化分支（如果需要）
        if use_pool_branch:
            pool_branch = self._make_pool_branch(
                in_channels=in_channels,
                out_channels=branch_channels[-1],
                pool_type=pool_type
            )
            self.pool_branch = pool_branch
        
        # Dropout和激活
        self.dropout = nn.Dropout(dropout)
        self.relu = nn.ReLU6(inplace=True)
    
    def _make_conv_branch(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int,
        mid_channels: int
    ) -> nn.Module:
        """
        构建单个卷积分支
        
        结构：
        - kernel_size=1: 直接1x1卷积
        - kernel_size>1: 1x1降维 -> DW卷积 -> 1x1升维
        """
        if kernel_size == 1:
            # 1x1分支：直接卷积
            return nn.Sequential(
                nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=False),
                nn.BatchNorm1d(out_channels),
                nn.ReLU6(inplace=True)
            )
        else:
            # 深度可分离卷积分支
            layers = []
            
            # 1x1降维
            layers.extend([
                nn.Conv1d(in_channels, mid_channels, kernel_size=1, bias=False),
                nn.BatchNorm1d(mid_channels),
                nn.ReLU6(inplace=True)
            ])
            
            layers.extend([
                nn.Conv1d(
                    mid_channels, mid_channels,
                    kernel_size=kernel_size,
                    padding="same",
                    groups=mid_channels,
                    bias=False
                ),
                nn.BatchNorm1d(mid_channels),
                nn.ReLU6(inplace=True)
            ])

            
            # 1x1升维
            layers.extend([
                nn.Conv1d(mid_channels, out_channels, kernel_size=1, bias=False),
                nn.BatchNorm1d(out_channels)
            ])
            
            return nn.Sequential(*layers)
    
    def _make_pool_branch(
        self,
        in_channels: int,
        out_channels: int,
        pool_type: str
    ) -> nn.Module:
        """构建池化分支"""
        if pool_type == "max":
            pool_layer = nn.MaxPool1d(kernel_size=3, stride=1, padding=1)
        elif pool_type == "avg":
            pool_layer = nn.AvgPool1d(kernel_size=3, stride=1, padding=1)
        else:
            raise ValueError(f"不支持的池化类型: {pool_type}")
        
        return nn.Sequential(
            pool_layer,
            nn.Conv1d(in_channels, out_channels, kernel_size=1, bias=False),
            nn.BatchNorm1d(out_channels)
        )
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        Args:
            x: [batch_size, in_channels, seq_len]
        
        Returns:
            out: [batch_size, out_channels, seq_len]
        """
        # 收集所有分支输出
        branch_outputs = []
        
        # 卷积分支
        for conv_branch in self.conv_branches:
            branch_out = conv_branch(x)
            branch_outputs.append(branch_out)
        
        # 池化分支
        if self.use_pool_branch:
            pool_out = self.pool_branch(x)
            branch_outputs.append(pool_out)
        
        # 拼接所有分支
        out = torch.cat(branch_outputs, dim=1)
        
        # Dropout和激活
        out = self.dropout(out)
        out = self.relu(out)
        
        return out

class MultiWindowInceptionCNN(nn.Module):
    """多窗口Inception风格CNN：每层内部多尺度"""
    def __init__(self, config: ModelConfig):
        super().__init__()
        
        # 输入适配层
        self.stem = nn.Sequential(
            nn.Conv1d(config.featurenum, config.cnn_out_channels, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm1d(config.cnn_out_channels),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(kernel_size=3, stride=2, padding=1)
        )
        
        # Inception块堆叠
        self.inception_blocks = nn.Sequential(
            LightInceptionBlock1D(config.cnn_out_channels, config.cnn_out_channels,kernel_sizes=config.cnn_kernel_sizes, dropout=config.dropout_rate),
            LightInceptionBlock1D(config.cnn_out_channels, config.cnn_out_channels * 2,kernel_sizes=config.cnn_kernel_sizes, dropout=config.dropout_rate),
            nn.MaxPool1d(kernel_size=2, stride=2),
            
            LightInceptionBlock1D(config.cnn_out_channels * 2, config.cnn_out_channels * 2,kernel_sizes=config.cnn_kernel_sizes, dropout=config.dropout_rate),
            LightInceptionBlock1D(config.cnn_out_channels * 2, config.cnn_out_channels,kernel_sizes=config.cnn_kernel_sizes, dropout=config.dropout_rate),
            nn.MaxPool1d(kernel_size=2, stride=2)
        )
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [batch_size, featurenum, seq_len]
        x = self.stem(x)  # [batch, cnn_out_channels, seq_len//4]
        x = self.inception_blocks(x)  # [batch, cnn_out_channels*4, seq_len//16]
        return x
